# Enhanced String Session Generator Bot (Telethon + Pyrogram)
# =========================================
# 📌 REQUIREMENTS:
# pip install telethon pyrogram python-telegram-bot python-dotenv redis

import re
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import json

# ⬇️ Config import
from config import BOT_TOKEN, OWNER_ID, REDIS_URL

# Rate limiting storage (use Redis in production)
try:
    import redis
    redis_client = redis.from_url(REDIS_URL) if REDIS_URL else None
except ImportError:
    redis_client = None

# In-memory fallback for rate limiting
rate_limit_storage: Dict[int, Dict[str, Any]] = {}

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        PhoneCodeInvalidError, SessionPasswordNeededError, 
        PhoneCodeExpiredError, PhoneMigrateError, FloodWaitError,
        PhoneNumberInvalidError, ApiIdInvalidError
    )
    from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
    TELETHON_AVAILABLE = True
except ModuleNotFoundError:
    TelegramClient = None
    StringSession = None
    TELETHON_AVAILABLE = False

try:
    from pyrogram import Client as PyroClient
    from pyrogram.errors import SessionPasswordNeeded, PhoneNumberInvalid, ApiIdInvalid
    PYROGRAM_AVAILABLE = True
except ModuleNotFoundError:
    PyroClient = None
    PYROGRAM_AVAILABLE = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        ApplicationBuilder, CommandHandler, MessageHandler, 
        filters, ConversationHandler, ContextTypes, CallbackQueryHandler
    )
    TELEGRAM_BOT_AVAILABLE = True
except ModuleNotFoundError:
    TELEGRAM_BOT_AVAILABLE = False

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🚩 Conversation States
(
    API_ID, API_HASH, TELETHON_PHONE, TELETHON_OTP, TELETHON_2FA,
    PYRO_API_ID, PYRO_API_HASH, PYRO_PHONE, PYRO_OTP, PYRO_2FA,
    REVOKE_CONFIRM, MAIN_MENU
) = range(12)

# Rate limiting constants
RATE_LIMIT_WINDOW = 3600  # 1 hour
MAX_ATTEMPTS_PER_HOUR = 5
FLOOD_WAIT_MULTIPLIER = 2

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

class RateLimiter:
    """Rate limiting utility"""
    
    @staticmethod
    def get_user_attempts(user_id: int) -> int:
        """Get current attempt count for user"""
        if redis_client:
            try:
                key = f"rate_limit:{user_id}"
                attempts = redis_client.get(key)
                return int(attempts) if attempts else 0
            except Exception:
                pass
        
        # Fallback to in-memory storage
        user_data = rate_limit_storage.get(user_id, {})
        if 'reset_time' in user_data and time.time() > user_data['reset_time']:
            rate_limit_storage[user_id] = {'attempts': 0, 'reset_time': time.time() + RATE_LIMIT_WINDOW}
            return 0
        return user_data.get('attempts', 0)
    
    @staticmethod
    def increment_attempts(user_id: int) -> bool:
        """Increment attempt count, return True if under limit"""
        current_attempts = RateLimiter.get_user_attempts(user_id)
        
        if current_attempts >= MAX_ATTEMPTS_PER_HOUR:
            return False
        
        new_attempts = current_attempts + 1
        
        if redis_client:
            try:
                key = f"rate_limit:{user_id}"
                redis_client.setex(key, RATE_LIMIT_WINDOW, new_attempts)
                return True
            except Exception:
                pass
        
        # Fallback to in-memory storage
        if user_id not in rate_limit_storage:
            rate_limit_storage[user_id] = {'reset_time': time.time() + RATE_LIMIT_WINDOW}
        rate_limit_storage[user_id]['attempts'] = new_attempts
        return True

class InputValidator:
    """Input validation utility"""
    
    @staticmethod
    def validate_api_id(api_id_str: str) -> int:
        """Validate and convert API ID"""
        try:
            api_id = int(api_id_str.strip())
            if api_id <= 0 or len(str(api_id)) < 6:
                raise ValidationError("API ID must be a positive number with at least 6 digits")
            return api_id
        except ValueError:
            raise ValidationError("API ID must be a valid number")
    
    @staticmethod
    def validate_api_hash(api_hash: str) -> str:
        """Validate API Hash"""
        api_hash = api_hash.strip()
        if not re.match(r'^[a-f0-9]{32}$', api_hash, re.IGNORECASE):
            raise ValidationError("API Hash must be a 32-character hexadecimal string")
        return api_hash
    
    @staticmethod
    def validate_phone_number(phone: str) -> str:
        """Validate phone number format"""
        phone = re.sub(r'[^\d+]', '', phone.strip())
        if not re.match(r'^\+?[1-9]\d{1,14}$', phone):
            raise ValidationError("Phone number must be in international format (e.g., +1234567890)")
        if not phone.startswith('+'):
            phone = '+' + phone
        return phone
    
    @staticmethod
    def validate_otp(otp: str) -> str:
        """Validate OTP format"""
        otp = re.sub(r'[^\d]', '', otp.strip())
        if not re.match(r'^\d{5}$', otp):
            raise ValidationError("OTP must be a 5-digit code")
        return otp

async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check rate limiting for user"""
    user_id = update.effective_user.id
    
    if not RateLimiter.increment_attempts(user_id):
        await update.message.reply_text(
            "⚠️ Rate limit exceeded. You can only generate 5 sessions per hour.\n"
            "Please try again later."
        )
        return False
    return True

async def safe_disconnect(client, update: Update = None) -> None:
    """Safely disconnect a client with error handling"""
    try:
        if hasattr(client, 'disconnect'):
            await client.disconnect()
        elif hasattr(client, 'stop'):
            await client.stop()
    except Exception as e:
        logger.error(f"Error disconnecting client: {e}")
        if update:
            await update.message.reply_text("⚠️ Warning: Client cleanup encountered an issue.")

# ========== COMMON HANDLERS ========== #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler with main menu"""
    keyboard = [
        [InlineKeyboardButton("🔧 Generate Telethon Session", callback_data="telethon")],
        [InlineKeyboardButton("🚀 Generate Pyrogram Session", callback_data="pyrogram")],
        [InlineKeyboardButton("🗑️ Revoke Sessions", callback_data="revoke")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"🤖 Welcome, {update.effective_user.first_name}!\n\n"
        "This bot helps you generate string sessions for Telegram clients.\n"
        "Please select an option below:"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "telethon":
        if not TELETHON_AVAILABLE:
            await query.edit_message_text("❌ Telethon library is not available.")
            return
        return await start_telethon_flow(query, context)
    
    elif query.data == "pyrogram":
        if not PYROGRAM_AVAILABLE:
            await query.edit_message_text("❌ Pyrogram library is not available.")
            return
        return await start_pyrogram_flow(query, context)
    
    elif query.data == "revoke":
        return await start_revoke_flow(query, context)
    
    elif query.data == "help":
        help_text = (
            "📖 **Help & Information**\n\n"
            "**What are string sessions?**\n"
            "String sessions allow you to run Telegram bots/userbot without re-authenticating each time.\n\n"
            "**Security Notes:**\n"
            "• Never share your string sessions with others\n"
            "• Keep your API credentials secure\n"
            "• Revoke sessions you no longer use\n\n"
            "**Rate Limits:**\n"
            "• Maximum 5 session generations per hour\n"
            "• This prevents abuse and protects your account\n\n"
            "**Need API credentials?**\n"
            "Visit https://my.telegram.org to get your API ID and Hash."
        )
        await query.edit_message_text(help_text, parse_mode='Markdown')

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping command for testing bot responsiveness"""
    start_time = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    latency = (time.time() - start_time) * 1000
    await msg.edit_text(f"🏓 Pong! Latency: {latency:.2f}ms")

# ========== TELETHON FLOW ========== #

async def start_telethon_flow(query, context: ContextTypes.DEFAULT_TYPE):
    """Start Telethon session generation flow"""
    # Create a fake update object for rate limiting
    fake_update = type('obj', (object,), {
        'effective_user': query.from_user,
        'message': type('obj', (object,), {'reply_text': lambda x: query.edit_message_text(x)})()
    })
    
    if not await rate_limit_check(fake_update, context):
        return ConversationHandler.END
    
    await query.edit_message_text("🔧 **Telethon Session Generator**\n\nPlease enter your API ID:")
    return API_ID

async def telethon_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telethon API ID input"""
    try:
        api_id = InputValidator.validate_api_id(update.message.text)
        context.user_data['api_id'] = api_id
        await update.message.reply_text("✅ API ID saved.\n\nNow enter your API Hash:")
        return API_HASH
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid API ID:")
        return API_ID

async def telethon_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telethon API Hash input"""
    try:
        api_hash = InputValidator.validate_api_hash(update.message.text)
        context.user_data['api_hash'] = api_hash
        await update.message.reply_text("✅ API Hash saved.\n\nEnter your phone number (with country code, e.g., +1234567890):")
        return TELETHON_PHONE
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid API Hash:")
        return API_HASH

async def telethon_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telethon phone number input"""
    try:
        phone = InputValidator.validate_phone_number(update.message.text)
        api_id = context.user_data['api_id']
        api_hash = context.user_data['api_hash']
        context.user_data['phone'] = phone
        
        client = TelegramClient(StringSession(), api_id, api_hash)
        context.user_data['client'] = client
        
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
            context.user_data['phone_hash'] = sent.phone_code_hash
            
            await update.message.reply_text(
                "📱 OTP sent to your Telegram account!\n\n"
                "Enter the 5-digit verification code:"
            )
            return TELETHON_OTP
            
        except PhoneNumberInvalidError:
            await safe_disconnect(client, update)
            await update.message.reply_text("❌ Invalid phone number. Please try again with correct format:")
            return TELETHON_PHONE
        except ApiIdInvalidError:
            await safe_disconnect(client, update)
            await update.message.reply_text("❌ Invalid API credentials. Please start over with /start")
            return ConversationHandler.END
        except PhoneMigrateError as e:
            await safe_disconnect(client, update)
            await update.message.reply_text(f"📡 Your account is on DC {e.new_dc}. Please restart the process.")
            return ConversationHandler.END
        except FloodWaitError as e:
            await safe_disconnect(client, update)
            wait_time = e.seconds
            await update.message.reply_text(
                f"⏳ Telegram rate limit hit. Please wait {wait_time} seconds before trying again."
            )
            return ConversationHandler.END
            
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid phone number:")
        return TELETHON_PHONE
    except Exception as e:
        logger.error(f"Unexpected error in telethon_phone: {e}")
        await update.message.reply_text("❌ An unexpected error occurred. Please try again later.")
        return ConversationHandler.END

async def telethon_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telethon OTP input"""
    client = context.user_data.get('client')
    if not client:
        await update.message.reply_text("❌ Session expired. Please start over with /start")
        return ConversationHandler.END
    
    try:
        code = InputValidator.validate_otp(update.message.text)
        
        try:
            await client.sign_in(context.user_data['phone'], code, context.user_data['phone_hash'])
        except SessionPasswordNeededError:
            await update.message.reply_text("🔐 2FA is enabled on your account.\n\nEnter your password:")
            return TELETHON_2FA
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ Invalid OTP code. Please enter the correct 5-digit code:")
            return TELETHON_OTP
        except PhoneCodeExpiredError:
            await safe_disconnect(client, update)
            await update.message.reply_text("⏰ OTP code expired. Please start over with /start")
            return ConversationHandler.END
        
        # Success - generate session
        session = client.session.save()
        await update.message.reply_text(
            f"✅ **Telethon Session Generated Successfully!**\n\n"
            f"`{session}`\n\n"
            "⚠️ **Security Warning:**\n"
            "• Keep this session string private\n"
            "• Don't share it with anyone\n"
            "• Use /start to revoke if compromised",
            parse_mode='Markdown'
        )
        
        await safe_disconnect(client)
        return ConversationHandler.END
        
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter the OTP code:")
        return TELETHON_OTP
    except Exception as e:
        logger.error(f"Unexpected error in telethon_otp: {e}")
        await safe_disconnect(client, update)
        await update.message.reply_text("❌ An unexpected error occurred. Please start over.")
        return ConversationHandler.END

async def telethon_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Telethon 2FA password input"""
    client = context.user_data.get('client')
    if not client:
        await update.message.reply_text("❌ Session expired. Please start over with /start")
        return ConversationHandler.END
    
    try:
        password = update.message.text
        await client.sign_in(password=password)
        
        session = client.session.save()
        await update.message.reply_text(
            f"✅ **Telethon Session Generated Successfully!**\n\n"
            f"`{session}`\n\n"
            "⚠️ **Security Warning:**\n"
            "• Keep this session string private\n"
            "• Don't share it with anyone\n"
            "• Use /start to revoke if compromised",
            parse_mode='Markdown'
        )
        
        await safe_disconnect(client)
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in telethon_2fa: {e}")
        await safe_disconnect(client, update)
        await update.message.reply_text("❌ Incorrect password or authentication failed. Please start over.")
        return ConversationHandler.END

# ========== PYROGRAM FLOW ========== #

async def start_pyrogram_flow(query, context: ContextTypes.DEFAULT_TYPE):
    """Start Pyrogram session generation flow"""
    # Create a fake update object for rate limiting
    fake_update = type('obj', (object,), {
        'effective_user': query.from_user,
        'message': type('obj', (object,), {'reply_text': lambda x: query.edit_message_text(x)})()
    })
    
    if not await rate_limit_check(fake_update, context):
        return ConversationHandler.END
    
    await query.edit_message_text("🚀 **Pyrogram Session Generator**\n\nPlease enter your API ID:")
    return PYRO_API_ID

async def pyro_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Pyrogram API ID input"""
    try:
        api_id = InputValidator.validate_api_id(update.message.text)
        context.user_data['pyro_api_id'] = api_id
        await update.message.reply_text("✅ API ID saved.\n\nNow enter your API Hash:")
        return PYRO_API_HASH
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid API ID:")
        return PYRO_API_ID

async def pyro_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Pyrogram API Hash input"""
    try:
        api_hash = InputValidator.validate_api_hash(update.message.text)
        context.user_data['pyro_api_hash'] = api_hash
        await update.message.reply_text("✅ API Hash saved.\n\nEnter your phone number (with country code, e.g., +1234567890):")
        return PYRO_PHONE
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid API Hash:")
        return PYRO_API_HASH

async def pyro_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Pyrogram phone number input"""
    try:
        phone = InputValidator.validate_phone_number(update.message.text)
        context.user_data['pyro_phone'] = phone
        
        app = PyroClient(
            name="session_gen",
            api_id=context.user_data['pyro_api_id'],
            api_hash=context.user_data['pyro_api_hash'],
            phone_number=phone,
            in_memory=True
        )
        context.user_data['pyro_client'] = app
        
        try:
            await app.connect()
            sent_code = await app.send_code(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            
            await update.message.reply_text(
                "📱 OTP sent to your Telegram account!\n\n"
                "Enter the 5-digit verification code:"
            )
            return PYRO_OTP
            
        except PhoneNumberInvalid:
            await safe_disconnect(app, update)
            await update.message.reply_text("❌ Invalid phone number. Please try again with correct format:")
            return PYRO_PHONE
        except ApiIdInvalid:
            await safe_disconnect(app, update)
            await update.message.reply_text("❌ Invalid API credentials. Please start over with /start")
            return ConversationHandler.END
            
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter a valid phone number:")
        return PYRO_PHONE
    except Exception as e:
        logger.error(f"Unexpected error in pyro_phone: {e}")
        await update.message.reply_text("❌ An unexpected error occurred. Please try again later.")
        return ConversationHandler.END

async def pyro_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Pyrogram OTP input"""
    app = context.user_data.get('pyro_client')
    if not app:
        await update.message.reply_text("❌ Session expired. Please start over with /start")
        return ConversationHandler.END
    
    try:
        code = InputValidator.validate_otp(update.message.text)
        
        try:
            await app.sign_in(
                context.user_data['pyro_phone'],
                context.user_data['phone_code_hash'],
                code
            )
        except SessionPasswordNeeded:
            await update.message.reply_text("🔐 2FA is enabled on your account.\n\nEnter your password:")
            return PYRO_2FA
        
        # Success - generate session
        session = await app.export_session_string()
        await update.message.reply_text(
            f"✅ **Pyrogram Session Generated Successfully!**\n\n"
            f"`{session}`\n\n"
            "⚠️ **Security Warning:**\n"
            "• Keep this session string private\n"
            "• Don't share it with anyone\n"
            "• Use /start to revoke if compromised",
            parse_mode='Markdown'
        )
        
        await safe_disconnect(app)
        return ConversationHandler.END
        
    except ValidationError as e:
        await update.message.reply_text(f"❌ {str(e)}\n\nPlease enter the OTP code:")
        return PYRO_OTP
    except Exception as e:
        logger.error(f"Unexpected error in pyro_otp: {e}")
        await safe_disconnect(app, update)
        await update.message.reply_text("❌ Invalid OTP or authentication failed. Please start over.")
        return ConversationHandler.END

async def pyro_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Pyrogram 2FA password input"""
    app = context.user_data.get('pyro_client')
    if not app:
        await update.message.reply_text("❌ Session expired. Please start over with /start")
        return ConversationHandler.END
    
    try:
        password = update.message.text
        await app.check_password(password)
        
        session = await app.export_session_string()
        await update.message.reply_text(
            f"✅ **Pyrogram Session Generated Successfully!**\n\n"
            f"`{session}`\n\n"
            "⚠️ **Security Warning:**\n"
            "• Keep this session string private\n"
            "• Don't share it with anyone\n"
            "• Use /start to revoke if compromised",
            parse_mode='Markdown'
        )
        
        await safe_disconnect(app)
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in pyro_2fa: {e}")
        await safe_disconnect(app, update)
        await update.message.reply_text("❌ Incorrect password or authentication failed. Please start over.")
        return ConversationHandler.END

# ========== SESSION REVOCATION ========== #

async def start_revoke_flow(query, context: ContextTypes.DEFAULT_TYPE):
    """Start session revocation flow"""
    if not TELETHON_AVAILABLE:
        await query.edit_message_text("❌ Session revocation requires Telethon library.")
        return
    
    revoke_text = (
        "🗑️ **Session Revocation**\n\n"
        "To revoke your active sessions:\n"
        "1. Provide your API credentials\n"
        "2. Sign in to your account\n"
        "3. Select sessions to revoke\n\n"
        "⚠️ This will log out all devices using revoked sessions.\n\n"
        "Enter your API ID to continue:"
    )
    await query.edit_message_text(revoke_text, parse_mode='Markdown')
    return API_ID  # Reuse the same flow initially

async def list_and_revoke_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List active sessions and allow revocation"""
    client = context.user_data.get('client')
    if not client:
        await update.message.reply_text("❌ Session expired. Please start over.")
        return ConversationHandler.END
    
    try:
        # Get active authorizations
        result = await client(GetAuthorizationsRequest())
        
        if not result.authorizations:
            await update.message.reply_text("📱 No active sessions found.")
            await safe_disconnect(client)
            return ConversationHandler.END
        
        session_text = "🔐 **Active Sessions:**\n\n"
        keyboard = []
        
        for i, auth in enumerate(result.authorizations[:10]):  # Limit to 10 sessions
            device_info = f"{auth.device_model} - {auth.platform}"
            if auth.current:
                device_info += " (Current)"
            session_text += f"{i+1}. {device_info}\n"
            
            if not auth.current:  # Don't allow revoking current session
                keyboard.append([InlineKeyboardButton(
                    f"Revoke: {device_info[:30]}...", 
                    callback_data=f"revoke_{auth.hash}"
                )])
        
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_revoke")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(session_text, reply_markup=reply_markup, parse_mode='Markdown')
        return REVOKE_CONFIRM
        
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        await safe_disconnect(client, update)
        await update.message.reply_text("❌ Failed to retrieve session list.")
        return ConversationHandler.END

async def confirm_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle session revocation confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_revoke":
        client = context.user_data.get('client')
        if client:
            await safe_disconnect(client)
        await query.edit_message_text("❌ Session revocation cancelled.")
        return ConversationHandler.END
    
    if query.data.startswith("revoke_"):
        client = context.user_data.get('client')
        if not client:
            await query.edit_message_text("❌ Session expired.")
            return ConversationHandler.END
        
        try:
            session_hash = int(query.data.split("_")[1])
            await client(ResetAuthorizationRequest(hash=session_hash))
            await query.edit_message_text("✅ Session revoked successfully!")
            await safe_disconnect(client)
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error revoking session: {e}")
            await query.edit_message_text("❌ Failed to revoke session.")
            await safe_disconnect(client)
            return ConversationHandler.END

# ========== CONVERSATION HANDLERS ========== #

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current conversation"""
    # Clean up any active clients
    client = context.user_data.get('client')
    pyro_client = context.user_data.get('pyro_client')
    
    if client:
        await safe_disconnect(client)
    if pyro_client:
        await safe_disconnect(pyro_client)
    
    context.user_data.clear()
    await update.message.reply_text("❌ Operation cancelled. Use /start to begin again.")
    return ConversationHandler.END

# ========== MAIN APPLICATION ========== #

def main():
    """Main function to run the bot"""
    if not TELEGRAM_BOT_AVAILABLE:
        print("❌ python-telegram-bot library is not available.")
        return
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found in config.")
        return
    
    # Create application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Telethon conversation handler
    telethon_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_telethon_flow, pattern="^telethon$")],
        states={
            API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_api_id)],
            API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_api_hash)],
            TELETHON_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_phone)],
            TELETHON_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_otp)],
            TELETHON_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_2fa)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Pyrogram conversation handler
    pyrogram_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_pyrogram_flow, pattern="^pyrogram$")],
        states={
            PYRO_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, pyro_api_id)],
            PYRO_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, pyro_api_hash)],
            PYRO_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pyro_phone)],
            PYRO_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, pyro_otp)],
            PYRO_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, pyro_2fa)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Revocation conversation handler
    revoke_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_revoke_flow, pattern="^revoke$")],
        states={
            API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_api_id)],
            API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_api_hash)],
            TELETHON_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, telethon_phone)],
            TELETHON_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, list_and_revoke_sessions)],
            REVOKE_CONFIRM: [CallbackQueryHandler(confirm_revoke)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('ping', ping))
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(telethon_conv)
    app.add_handler(pyrogram_conv)
    app.add_handler(revoke_conv)
    
    print("🤖 Enhanced Session Generator Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
