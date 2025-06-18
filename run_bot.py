#!/usr/bin/env python3
"""
Enhanced Session Generator Bot - Main Entry Point
Production-ready Telegram bot for generating Telethon and Pyrogram string sessions
"""

import os
import sys
import signal
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class HealthHandler(BaseHTTPRequestHandler):
    """Health check endpoint handler"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                'status': 'healthy',
                'timestamp': int(time.time()),
                'service': 'enhanced-session-generator-bot'
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress health check logs
        pass

def start_health_server():
    """Start health check server in background"""
    try:
        server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
        logger.info("Health check server started on port 8080")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)

def main():
    """Main function"""
    logger.info("Starting Enhanced Session Generator Bot...")
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start health check server in background
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Import and run the bot
    try:
        from improved_session_bot import main as bot_main
        logger.info("Bot initialized successfully")
        bot_main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    
    main()
