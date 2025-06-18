# Utility functions for Enhanced Session Generator Bot
# ===============================================

import re
import time
import hashlib
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

class SecurityUtils:
    """Security-related utility functions"""
    
    @staticmethod
    def generate_secure_session_id() -> str:
        """Generate a secure session ID for tracking"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def hash_phone_number(phone: str) -> str:
        """Hash phone number for privacy in logs"""
        return hashlib.sha256(phone.encode()).hexdigest()[:16]
    
    @staticmethod
    def sanitize_for_logs(text: str) -> str:
        """Sanitize sensitive data for logging"""
        # Remove potential API hashes and session strings
        text = re.sub(r'[a-f0-9]{32}', '[API_HASH]', text, flags=re.IGNORECASE)
        text = re.sub(r'\+\d{10,15}', '[PHONE]', text)
        text = re.sub(r'\d{5}', '[OTP]', text)
        return text

class FormatUtils:
    """Text formatting utilities"""
    
    @staticmethod
    def format_session_preview(session: str, length: int = 20) -> str:
        """Format session string for safe preview"""
        if len(session) <= length:
            return session
        return f"{session[:length//2]}...{session[-length//2:]}"
    
    @staticmethod
    def format_duration(seconds: int) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds//60}m {seconds%60}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    
    @staticmethod
    def mask_api_credentials(api_id: str, api_hash: str) -> Dict[str, str]:
        """Mask API credentials for display"""
        return {
            'api_id': f"{api_id[:3]}***{api_id[-3:]}",
            'api_hash': f"{api_hash[:8]}***{api_hash[-8:]}"
        }

class ValidationUtils:
    """Extended validation utilities"""
    
    @staticmethod
    def is_valid_telegram_username(username: str) -> bool:
        """Validate Telegram username format"""
        return bool(re.match(r'^@?[a-zA-Z][a-zA-Z0-9_]{4,31}$', username))
    
    @staticmethod
    def normalize_phone_number(phone: str) -> str:
        """Normalize phone number to standard format"""
        # Remove all non-digit characters except +
        phone = re.sub(r'[^\d+]', '', phone.strip())
        
        # Add + if not present
        if not phone.startswith('+'):
            phone = '+' + phone
        
        return phone
    
    @staticmethod
    def estimate_country_from_phone(phone: str) -> Optional[str]:
        """Estimate country from phone number prefix"""
        country_codes = {
            '+1': 'US/CA',
            '+7': 'RU/KZ',
            '+44': 'UK',
            '+49': 'DE',
            '+33': 'FR',
            '+39': 'IT',
            '+34': 'ES',
            '+91': 'IN',
            '+86': 'CN',
            '+81': 'JP',
            '+82': 'KR',
            '+55': 'BR',
            '+52': 'MX',
            '+61': 'AU',
            '+90': 'TR',
            '+98': 'IR',
            '+966': 'SA',
            '+971': 'AE',
            '+20': 'EG',
            '+27': 'ZA'
        }
        
        for code, country in country_codes.items():
            if phone.startswith(code):
                return country
        return None

class MetricsUtils:
    """Metrics and analytics utilities"""
    
    def __init__(self):
        self.session_counts = {'telethon': 0, 'pyrogram': 0}
        self.error_counts = {}
        self.start_time = time.time()
    
    def increment_session_count(self, session_type: str):
        """Increment session generation count"""
        if session_type in self.session_counts:
            self.session_counts[session_type] += 1
    
    def increment_error_count(self, error_type: str):
        """Increment error count"""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current bot statistics"""
        uptime = time.time() - self.start_time
        return {
            'uptime': FormatUtils.format_duration(int(uptime)),
            'sessions_generated': self.session_counts,
            'total_sessions': sum(self.session_counts.values()),
            'error_counts': self.error_counts,
            'total_errors': sum(self.error_counts.values())
        }

class CacheUtils:
    """Simple caching utilities"""
    
    def __init__(self):
        self.cache = {}
        self.expiry = {}
    
    def set(self, key: str, value: Any, ttl: int = 300):
        """Set cache value with TTL in seconds"""
        self.cache[key] = value
        self.expiry[key] = time.time() + ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Get cache value if not expired"""
        if key not in self.cache:
            return None
        
        if time.time() > self.expiry.get(key, 0):
            self.delete(key)
            return None
        
        return self.cache[key]
    
    def delete(self, key: str):
        """Delete cache entry"""
        self.cache.pop(key, None)
        self.expiry.pop(key, None)
    
    def clear_expired(self):
        """Clear all expired cache entries"""
        current_time = time.time()
        expired_keys = [
            key for key, exp_time in self.expiry.items() 
            if current_time > exp_time
        ]
        for key in expired_keys:
            self.delete(key)

# Global instances
metrics = MetricsUtils()
cache = CacheUtils()

def get_user_friendly_error(error_type: str, context: str = "") -> str:
    """Convert technical errors to user-friendly messages"""
    error_messages = {
        'PhoneCodeInvalidError': 'The verification code you entered is incorrect. Please check and try again.',
        'PhoneCodeExpiredError': 'The verification code has expired. Please request a new one.',
        'SessionPasswordNeededError': 'Two-factor authentication is enabled on your account.',
        'PhoneMigrateError': 'Your account has been moved to a different data center.',
        'FloodWaitError': 'Too many requests. Please wait before trying again.',
        'PhoneNumberInvalidError': 'The phone number format is invalid.',
        'ApiIdInvalidError': 'Invalid API credentials. Please check your API ID and Hash.',
        'ConnectionError': 'Unable to connect to Telegram servers. Please check your internet connection.',
        'TimeoutError': 'Connection timed out. Please try again.',
        'ValidationError': 'Input validation failed. Please check your input format.'
    }
    
    base_message = error_messages.get(error_type, 'An unexpected error occurred.')
    if context:
        return f"{base_message} Context: {context}"
    return base_message

def log_user_action(user_id: int, action: str, success: bool = True, error: str = None):
    """Log user actions for monitoring"""
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'user_id': SecurityUtils.hash_phone_number(str(user_id)),  # Hash for privacy
        'action': action,
        'success': success,
        'error': SecurityUtils.sanitize_for_logs(error) if error else None
    }
    
    # In production, this would go to a proper logging system
    print(f"[{timestamp}] User Action: {log_entry}")
    
    # Update metrics
    if success:
        if 'telethon' in action.lower():
            metrics.increment_session_count('telethon')
        elif 'pyrogram' in action.lower():
            metrics.increment_session_count('pyrogram')
    else:
        metrics.increment_error_count(error or 'unknown_error')
