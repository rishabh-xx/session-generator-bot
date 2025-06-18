# Configuration file for Enhanced Session Generator Bot
# ===============================================

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

# Redis Configuration (optional - for production rate limiting)
REDIS_URL = os.getenv('REDIS_URL')

# Validate required configuration
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required. Please set it in your .env file or environment variables.")

if OWNER_ID == 0:
    raise ValueError("OWNER_ID is required. Please set it in your .env file or environment variables.")

# Optional: Database configuration for session storage (future enhancement)
DATABASE_URL = os.getenv('DATABASE_URL')

# Rate limiting configuration
RATE_LIMIT_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
MAX_SESSIONS_PER_HOUR = int(os.getenv('MAX_SESSIONS_PER_HOUR', '5'))

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'bot.log')

print(f"✅ Configuration loaded successfully")
print(f"📊 Rate limiting: {'Enabled' if RATE_LIMIT_ENABLED else 'Disabled'}")
print(f"🔄 Max sessions per hour: {MAX_SESSIONS_PER_HOUR}")
print(f"📝 Log level: {LOG_LEVEL}")
