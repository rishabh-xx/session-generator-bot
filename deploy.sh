#!/bin/bash
# VPS Deployment Script for Enhanced Session Generator Bot

set -e

echo "🚀 Starting Enhanced Session Generator Bot deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please run this script as a non-root user with sudo privileges"
    exit 1
fi

# Update system packages
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python 3.11 and pip
print_status "Installing Python 3.11 and dependencies..."
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip git redis-server postgresql postgresql-contrib nginx certbot python3-certbot-nginx

# Start and enable services
print_status "Starting system services..."
sudo systemctl start redis-server
sudo systemctl enable redis-server
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create project directory
PROJECT_DIR="/opt/session-bot"
print_status "Creating project directory at $PROJECT_DIR..."
sudo mkdir -p $PROJECT_DIR
sudo chown $USER:$USER $PROJECT_DIR

# Navigate to project directory
cd $PROJECT_DIR

# Create Python virtual environment
print_status "Creating Python virtual environment..."
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
print_status "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements_vps.txt

# Create necessary directories
print_status "Creating directories..."
mkdir -p logs
mkdir -p data

# Create .env file template
print_status "Creating environment configuration..."
if [ ! -f .env ]; then
    cat > .env << EOF
# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here
OWNER_ID=your_telegram_user_id_here

# Redis Configuration
REDIS_URL=redis://localhost:6379

# Rate Limiting
RATE_LIMIT_ENABLED=true
MAX_SESSIONS_PER_HOUR=5

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log

# Optional: Database for session storage
DATABASE_URL=postgresql://session_user:session_pass@localhost/session_bot
EOF
    print_warning ".env file created. Please edit it with your actual credentials."
else
    print_status ".env file already exists, skipping creation."
fi

# Create systemd service file
print_status "Creating systemd service..."
sudo tee /etc/systemd/system/session-bot.service > /dev/null << EOF
[Unit]
Description=Enhanced Session Generator Bot
After=network.target redis.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin
ExecStart=$PROJECT_DIR/venv/bin/python run_bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create nginx configuration
print_status "Creating nginx configuration..."
sudo tee /etc/nginx/sites-available/session-bot > /dev/null << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain

    location /health {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        return 200 "Enhanced Session Generator Bot is running";
        add_header Content-Type text/plain;
    }
}
EOF

# Create health check endpoint
print_status "Creating health check endpoint..."
cat > health_server.py << 'EOF'
#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
import time

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                'status': 'healthy',
                'timestamp': int(time.time()),
                'service': 'session-generator-bot'
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server():
    server = HTTPServer(('127.0.0.1', 8080), HealthHandler)
    server.serve_forever()

if __name__ == '__main__':
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Health server stopped")
EOF

# Create startup script
print_status "Creating startup script..."
cat > start_bot.sh << 'EOF'
#!/bin/bash
cd /opt/session-bot
source venv/bin/activate

# Start health server in background
python health_server.py &
HEALTH_PID=$!

# Start the main bot
python run_bot.py

# Clean up health server on exit
kill $HEALTH_PID 2>/dev/null
EOF

chmod +x start_bot.sh

# Create monitoring script
print_status "Creating monitoring script..."
cat > monitor.sh << 'EOF'
#!/bin/bash
# Monitor script for session bot

LOG_FILE="/opt/session-bot/logs/monitor.log"
SERVICE_NAME="session-bot"

log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOG_FILE
}

check_service() {
    if systemctl is-active --quiet $SERVICE_NAME; then
        return 0
    else
        return 1
    fi
}

# Check if service is running
if ! check_service; then
    log_message "Service $SERVICE_NAME is down, attempting restart..."
    systemctl restart $SERVICE_NAME
    sleep 10
    
    if check_service; then
        log_message "Service $SERVICE_NAME restarted successfully"
    else
        log_message "Failed to restart service $SERVICE_NAME"
    fi
else
    log_message "Service $SERVICE_NAME is running normally"
fi
EOF

chmod +x monitor.sh

# Create log rotation configuration
print_status "Setting up log rotation..."
sudo tee /etc/logrotate.d/session-bot > /dev/null << EOF
$PROJECT_DIR/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 $USER $USER
    postrotate
        systemctl reload session-bot
    endscript
}
EOF

# Set up cron job for monitoring
print_status "Setting up monitoring cron job..."
(crontab -l 2>/dev/null; echo "*/5 * * * * $PROJECT_DIR/monitor.sh") | crontab -

# Reload systemd and enable service
print_status "Enabling systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable session-bot

# Set proper permissions
print_status "Setting permissions..."
chmod +x run_bot.py
chown -R $USER:$USER $PROJECT_DIR

print_status "✅ Deployment completed successfully!"
echo ""
echo "📋 Next steps:"
echo "1. Edit .env file with your bot credentials:"
echo "   nano $PROJECT_DIR/.env"
echo ""
echo "2. Start the bot service:"
echo "   sudo systemctl start session-bot"
echo ""
echo "3. Check service status:"
echo "   sudo systemctl status session-bot"
echo ""
echo "4. View logs:"
echo "   sudo journalctl -u session-bot -f"
echo ""
echo "5. For SSL (optional):"
echo "   sudo certbot --nginx -d your-domain.com"
echo ""
print_warning "Remember to:"
print_warning "- Replace 'your-domain.com' in nginx config with your actual domain"
print_warning "- Configure firewall to allow ports 80 and 443"
print_warning "- Set up proper DNS records for your domain"
