# Web Security Module for Server Manager - Security features including rate limiting, CSRF, input validation, account lockout, and path traversal prevention
import os
import sys
import re
import time
import hashlib
import secrets
import threading
import ipaddress
from collections import defaultdict
from typing import Dict, Optional, Tuple, List, Any, Union
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging, get_allowed_origins
setup_module_path()

logger: logging.Logger = setup_module_logging("WebSecurity")


# =============================================================================
# RATE LIMITING
# =============================================================================

# Thread-safe rate limiter using sliding window algorithm.
# Prevents brute force attacks and DoS attempts.
class RateLimiter:
    
    def __init__(self):
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
        # Cleanup old entries periodically
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
    
    def _cleanup(self):
        # Remove old entries to prevent memory bloat.
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        with self._lock:
            cutoff = now - 3600  # Remove entries older than 1 hour
            for key in list(self._requests.keys()):
                self._requests[key] = [t for t in self._requests[key] if t > cutoff]
                if not self._requests[key]:
                    del self._requests[key]
            self._last_cleanup = now
    
    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        # Check if request is allowed under rate limit.
        # Args:
        #     key: Unique identifier (e.g., IP address, user ID)
        #     max_requests: Maximum requests allowed in window
        #     window_seconds: Time window in seconds
        # Returns:
        #     Tuple of (allowed: bool, retry_after_seconds: int)
        self._cleanup()
        now = time.time()
        cutoff = now - window_seconds
        
        with self._lock:
            # Remove expired timestamps in place for efficiency
            timestamps = self._requests[key]
            i = 0
            while i < len(timestamps):
                if timestamps[i] <= cutoff:
                    del timestamps[i]
                else:
                    i += 1
            
            if len(timestamps) >= max_requests:
                # Calculate retry after
                oldest = min(timestamps)
                retry_after = int(oldest + window_seconds - now) + 1
                return False, max(1, retry_after)
            
            timestamps.append(now)
            return True, 0
    
    def get_remaining(self, key: str, max_requests: int, window_seconds: int) -> int:
        # Get remaining requests in current window.
        now = time.time()
        cutoff = now - window_seconds
        
        with self._lock:
            # Count valid timestamps efficiently
            timestamps = self._requests[key]
            valid_count = sum(1 for t in timestamps if t > cutoff)
            return max(0, max_requests - valid_count)


# Account lockout mechanism to prevent brute force attacks.
# Locks accounts after multiple failed login attempts.
class AccountLockout:
    
    def __init__(self, max_attempts: int = 5, lockout_duration: int = 900):
        # Args:
        #     max_attempts: Max failed attempts before lockout
        #     lockout_duration: Lockout duration in seconds (default 15 minutes)
        self.max_attempts = max_attempts
        self.lockout_duration = lockout_duration
        self._failed_attempts: Dict[str, List[float]] = defaultdict(list)
        self._lockouts: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def record_failed_attempt(self, identifier: str) -> Tuple[bool, int, int]:
        # Record a failed login attempt.
        # Args:
        #     identifier: Username or IP address
        # Returns:
        #     Tuple of (is_locked_out, remaining_attempts, lockout_seconds)
        now = time.time()
        window = 300  # 5 minute window for counting attempts
        
        with self._lock:
            # Check if already locked out
            if identifier in self._lockouts:
                lockout_end = self._lockouts[identifier]
                if now < lockout_end:
                    return True, 0, int(lockout_end - now)
                else:
                    # Lockout expired, clear it
                    del self._lockouts[identifier]
                    self._failed_attempts[identifier] = []
            
            # Add failed attempt
            cutoff = now - window
            self._failed_attempts[identifier] = [
                t for t in self._failed_attempts[identifier] if t > cutoff
            ]
            self._failed_attempts[identifier].append(now)
            
            attempts = len(self._failed_attempts[identifier])
            remaining = max(0, self.max_attempts - attempts)
            
            # Check if should lock out
            if attempts >= self.max_attempts:
                self._lockouts[identifier] = now + self.lockout_duration
                logger.warning(f"Account locked out: {identifier} after {attempts} failed attempts")
                return True, 0, self.lockout_duration
            
            return False, remaining, 0
    
    def is_locked_out(self, identifier: str) -> Tuple[bool, int]:
        # Check if an account/IP is currently locked out.
        # Returns:
        #     Tuple of (is_locked, remaining_seconds)
        now = time.time()
        
        with self._lock:
            if identifier in self._lockouts:
                lockout_end = self._lockouts[identifier]
                if now < lockout_end:
                    return True, int(lockout_end - now)
                else:
                    del self._lockouts[identifier]
                    self._failed_attempts[identifier] = []
            
            return False, 0
    
    def clear_lockout(self, identifier: str):
        # Clear lockout for an identifier (e.g., after successful login).
        with self._lock:
            self._lockouts.pop(identifier, None)
            self._failed_attempts.pop(identifier, None)


# =============================================================================
# CSRF PROTECTION
# =============================================================================

# CSRF (Cross-Site Request Forgery) protection using tokens.
class CSRFProtection:
    
    def __init__(self, token_expiry: int = 3600):
        # Args:
        #     token_expiry: Token validity in seconds (default 1 hour)
        self.token_expiry = token_expiry
        self._tokens: Dict[str, Tuple[str, float]] = {}  # session_id -> (token, expiry)
        self._lock = threading.Lock()
    
    def generate_token(self, session_id: str) -> str:
        # Generate a new CSRF token for a session.
        token = secrets.token_urlsafe(32)
        expiry = time.time() + self.token_expiry
        
        with self._lock:
            self._tokens[session_id] = (token, expiry)
        
        return token
    
    def validate_token(self, session_id: str, token: str) -> bool:
        # Validate a CSRF token for a session.
        now = time.time()
        
        with self._lock:
            if session_id not in self._tokens:
                return False
            
            stored_token, expiry = self._tokens[session_id]
            
            if now > expiry:
                del self._tokens[session_id]
                return False
            
            # Use constant-time comparison to prevent timing attacks
            return secrets.compare_digest(stored_token, token)
    
    def cleanup_expired(self):
        # Remove expired tokens.
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._tokens.items() if now > exp]
            for k in expired:
                del self._tokens[k]


# =============================================================================
# INPUT VALIDATION & SANITIZATION
# =============================================================================

# Input validation and sanitization utilities.
# Prevents SQL injection, XSS, and other injection attacks.
class InputValidator:
    
    # Dangerous patterns that should never appear in input
    SQL_INJECTION_PATTERNS = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|EXEC|EXECUTE)\b)",
        r"(--)|(;)|(/\*)|(\*/)",
        r"(\'|\").*?(OR|AND).*?(\'|\")",
        r"(\bOR\b|\bAND\b)\s+\d+\s*=\s*\d+",
    ]
    
    XSS_PATTERNS = [
        r"<script.*?>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe.*?>",
        r"<object.*?>",
        r"<embed.*?>",
    ]
    
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e/",
        r"%2e%2e\\",
        r"\.\.%2f",
        r"\.\.%5c",
    ]
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000) -> str:
        # Sanitise a string input by removing dangerous characters.
        if not isinstance(value, str):
            return ""
        
        # Truncate to max length
        value = value[:max_length]
        
        # Remove null bytes
        value = value.replace('\x00', '')
        
        # Remove control characters except newlines and tabs
        value = ''.join(c for c in value if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127))
        
        return value.strip()
    
    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        # Validate username format.
        # Returns:
        #     Tuple of (is_valid, error_message)
        if not username or not isinstance(username, str):
            return False, "Username is required"
        
        username = username.strip()
        
        if len(username) < 3:
            return False, "Username must be at least 3 characters"
        
        if len(username) > 50:
            return False, "Username must be 50 characters or less"
        
        # Only allow alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            return False, "Username can only contain letters, numbers, underscores, and hyphens"
        
        return True, ""
    
    @staticmethod
    def validate_password(password: str) -> Tuple[bool, str]:
        # Validate password strength.
        # Returns:
        #     Tuple of (is_valid, error_message)
        if not password or not isinstance(password, str):
            return False, "Password is required"
        
        if len(password) < 8:
            return False, "Password must be at least 8 characters"
        
        if len(password) > 128:
            return False, "Password must be 128 characters or less"
        
        # Require at least one letter and one number
        if not re.search(r'[a-zA-Z]', password):
            return False, "Password must contain at least one letter"
        
        if not re.search(r'\d', password):
            return False, "Password must contain at least one number"
        
        return True, ""
    
    @staticmethod
    def validate_email(email: str) -> Tuple[bool, str]:
        # Validate email format.
        if not email:
            return True, ""  # Email is optional
        
        if not isinstance(email, str):
            return False, "Invalid email format"
        
        email = email.strip()
        
        if len(email) > 254:
            return False, "Email address too long"
        
        # Basic email regex
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False, "Invalid email format"
        
        return True, ""
    
    @classmethod
    def check_sql_injection(cls, value: str) -> bool:
        # Check for SQL injection patterns. Returns True if suspicious.
        if not isinstance(value, str):
            return False
        
        value_upper = value.upper()
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value_upper, re.IGNORECASE):
                logger.warning(f"SQL injection pattern detected: {pattern}")
                return True
        
        return False
    
    @classmethod
    def check_xss(cls, value: str) -> bool:
        # Check for XSS patterns. Returns True if suspicious.
        if not isinstance(value, str):
            return False
        
        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"XSS pattern detected: {pattern}")
                return True
        
        return False
    
    @classmethod
    def check_path_traversal(cls, value: str) -> bool:
        # Check for path traversal patterns. Returns True if suspicious.
        if not isinstance(value, str):
            return False
        
        for pattern in cls.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Path traversal pattern detected: {pattern}")
                return True
        
        return False
    
    @classmethod
    def validate_safe_input(cls, value: str, field_name: str = "input") -> Tuple[bool, str]:
        # Input validation checking for all injection types
        # Returns:
        #     Tuple of (is_safe, error_message)
        if not isinstance(value, str):
            return True, ""
        
        if cls.check_sql_injection(value):
            logger.warning(f"SQL injection attempt in {field_name}")
            return False, f"Invalid characters in {field_name}"
        
        if cls.check_xss(value):
            logger.warning(f"XSS attempt in {field_name}")
            return False, f"Invalid characters in {field_name}"
        
        if cls.check_path_traversal(value):
            logger.warning(f"Path traversal attempt in {field_name}")
            return False, f"Invalid path in {field_name}"
        
        return True, ""


# =============================================================================
# PATH SECURITY
# =============================================================================

# Secure path handling to prevent directory traversal attacks.
class PathSecurity:
    
    def __init__(self, allowed_roots: Optional[List[str]] = None):
        # Args:
        #     allowed_roots: List of allowed root directories
        self.allowed_roots = [os.path.abspath(r) for r in (allowed_roots or [])]
    
    def is_safe_path(self, path: str) -> bool:
        # Check if a path is safe (within allowed roots).
        try:
            # Resolve to absolute path
            abs_path = os.path.abspath(path)
            
            # Check if it's under any allowed root
            for root in self.allowed_roots:
                if abs_path.startswith(root + os.sep) or abs_path == root:
                    return True
            
            return False
        except Exception:
            return False
    
    @staticmethod
    def safe_join(base: str, *paths) -> Optional[str]:
        # Safely join paths, preventing traversal outside base.
        # Returns:
        #     Safe absolute path or None if unsafe
        try:
            # Join paths
            joined = os.path.join(base, *paths)
            
            # Resolve to absolute
            abs_joined = os.path.abspath(joined)
            abs_base = os.path.abspath(base)
            
            # Ensure result is under base
            if abs_joined.startswith(abs_base + os.sep) or abs_joined == abs_base:
                return abs_joined
            
            logger.warning(f"Path traversal blocked: {joined} escapes {base}")
            return None
        except Exception as e:
            logger.error(f"Path join error: {e}")
            return None


# =============================================================================
# IP SECURITY
# =============================================================================

# IP-based security features including allowlist/blocklist.
class IPSecurity:
    
    def __init__(self):
        self._blocklist: set = set()
        self._allowlist: set = set()
        self._allowed_networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
        self._lock = threading.Lock()
        
        # Default private networks
        self._default_allowed = [
            ipaddress.ip_network("127.0.0.0/8"),      # Localhost
            ipaddress.ip_network("10.0.0.0/8"),       # Private Class A
            ipaddress.ip_network("172.16.0.0/12"),    # Private Class B
            ipaddress.ip_network("192.168.0.0/16"),   # Private Class C
        ]
    
    def add_to_blocklist(self, ip: str, reason: str = ""):
        # Add an IP to the blocklist.
        with self._lock:
            self._blocklist.add(ip)
            logger.warning(f"IP blocked: {ip} - {reason}")
    
    def remove_from_blocklist(self, ip: str):
        # Remove an IP from the blocklist.
        with self._lock:
            self._blocklist.discard(ip)
    
    def is_blocked(self, ip: str) -> bool:
        # Check if an IP is blocked.
        with self._lock:
            return ip in self._blocklist
    
    def is_private_ip(self, ip: str) -> bool:
        # Check if an IP is from a private network.
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_private
        except ValueError:
            return False
    
    def add_allowed_network(self, network: str):
        # Add a network to the allowed list.
        try:
            net = ipaddress.ip_network(network, strict=False)
            with self._lock:
                self._allowed_networks.append(net)
            logger.info(f"Added allowed network: {network}")
        except ValueError as e:
            logger.error(f"Invalid network: {network} - {e}")
    
    def is_in_allowed_network(self, ip: str) -> bool:
        # Check if IP is in an allowed network.
        try:
            ip_obj = ipaddress.ip_address(ip)
            
            # Check default allowed
            for net in self._default_allowed:
                if ip_obj in net:
                    return True
            
            # Check custom allowed
            with self._lock:
                for net in self._allowed_networks:
                    if ip_obj in net:
                        return True
            
            return False
        except ValueError:
            return False


# =============================================================================
# SECURITY HEADERS
# =============================================================================

def get_security_headers(ssl_enabled: bool = False, allowed_origins: Optional[List[str]] = None) -> Dict[str, str]:
    # Get recommended security headers for HTTP responses.
    # Args:
    #     ssl_enabled: Whether SSL/HTTPS is enabled
    #     allowed_origins: List of allowed origins for CORS
    headers = {
        # Prevent MIME type sniffing
        'X-Content-Type-Options': 'nosniff',
        
        # Clickjacking protection
        'X-Frame-Options': 'SAMEORIGIN',
        
        # XSS protection (legacy, but still useful)
        'X-XSS-Protection': '1; mode=block',
        
        # Referrer policy
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        
        # Permissions policy (disable dangerous features)
        'Permissions-Policy': 'geolocation=(), microphone=(), camera=(), payment=()',
        
        # Content Security Policy
        'Content-Security-Policy': (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'self';"
        ),
        
        # Cache control for sensitive data
        'Cache-Control': 'no-store, no-cache, must-revalidate, private',
        'Pragma': 'no-cache',
    }
    
    if ssl_enabled:
        # HTTP Strict Transport Security
        headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    
    return headers


# =============================================================================
# REQUEST FINGERPRINTING
# =============================================================================

def get_request_fingerprint(request) -> str:
    # Generate a fingerprint for a request to help identify clients.
    # Uses IP + User-Agent as a basic fingerprint.
    components = [
        request.remote_addr or '',
        request.headers.get('User-Agent', ''),
    ]
    
    fingerprint = hashlib.sha256('|'.join(components).encode()).hexdigest()[:16]
    return fingerprint


def get_client_ip(request) -> str:
    # Get the real client IP, considering proxies.
    # Check for proxy headers (in order of trust)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(',')[0].strip()
    
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()
    
    return request.remote_addr or '0.0.0.0'


# =============================================================================
# GLOBAL SECURITY MANAGER
# =============================================================================

# Central security manager that coordinates all security features.
class WebSecurityManager:
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        
        # Initialise components
        self.rate_limiter = RateLimiter()
        self.account_lockout = AccountLockout(
            max_attempts=config.get('max_login_attempts', 5),
            lockout_duration=config.get('lockout_duration', 900)
        )
        self.csrf = CSRFProtection(
            token_expiry=config.get('csrf_token_expiry', 3600)
        )
        self.input_validator = InputValidator()
        self.ip_security = IPSecurity()
        
        # Rate limit configurations
        self.rate_limits = {
            'login': (5, 60),        # 5 attempts per minute
            'api': (100, 60),        # 100 requests per minute
            'api_write': (30, 60),   # 30 write operations per minute
            'static': (200, 60),     # 200 static file requests per minute
        }
        
        # Allowed origins for CORS
        web_port = config.get('web_port', 8080)
        self.allowed_origins = config.get('allowed_origins', get_allowed_origins(port=web_port))
        
        logger.info("WebSecurityManager initialized")
    
    def check_rate_limit(self, key: str, limit_type: str = 'api') -> Tuple[bool, int]:
        # Check if request is within rate limits.
        # Returns:
        #     Tuple of (allowed, retry_after_seconds)
        max_requests, window = self.rate_limits.get(limit_type, (100, 60))
        return self.rate_limiter.is_allowed(key, max_requests, window)
    
    def validate_login_attempt(self, username: str, ip: str) -> Tuple[bool, str]:
        # Validate a login attempt (check lockouts and rate limits).
        # Returns:
        #     Tuple of (allowed, error_message)
        # Check IP blocklist
        if self.ip_security.is_blocked(ip):
            return False, "Access denied"
        
        # Check rate limit
        allowed, retry_after = self.check_rate_limit(ip, 'login')
        if not allowed:
            return False, f"Too many attempts. Try again in {retry_after} seconds"
        
        # Check account lockout
        locked, remaining = self.account_lockout.is_locked_out(username)
        if locked:
            return False, f"Account temporarily locked. Try again in {remaining} seconds"
        
        # Also check IP-based lockout
        ip_locked, ip_remaining = self.account_lockout.is_locked_out(ip)
        if ip_locked:
            return False, f"Too many failed attempts. Try again in {ip_remaining} seconds"
        
        return True, ""
    
    def record_login_failure(self, username: str, ip: str) -> Tuple[bool, int]:
        # Record a failed login attempt.
        # Returns:
        #     Tuple of (is_locked_out, remaining_attempts)
        # Record for both username and IP
        user_locked, user_remaining, _ = self.account_lockout.record_failed_attempt(username)
        ip_locked, ip_remaining, _ = self.account_lockout.record_failed_attempt(ip)
        
        is_locked = user_locked or ip_locked
        remaining = min(user_remaining, ip_remaining)
        
        return is_locked, remaining
    
    def record_login_success(self, username: str, ip: str):
        # Record a successful login (clears lockouts).
        self.account_lockout.clear_lockout(username)
        self.account_lockout.clear_lockout(ip)
    
    def add_allowed_origin(self, origin: str):
        # Add an allowed CORS origin.
        if origin not in self.allowed_origins:
            self.allowed_origins.append(origin)
            logger.info(f"Added allowed origin: {origin}")


# Global instance
_security_manager: WebSecurityManager = WebSecurityManager(None)


def get_security_manager(config: Optional[Dict[str, Any]] = None) -> WebSecurityManager:
    # Get or create the global security manager.
    if config is not None:
        global _security_manager
        _security_manager = WebSecurityManager(config)
    return _security_manager


def init_security_manager(config: Optional[Dict[str, Any]] = None) -> WebSecurityManager:
    # Initialise a new security manager (replaces existing).
    global _security_manager
    _security_manager = WebSecurityManager(config)
    return _security_manager
