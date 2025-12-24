# Authentication module
# - SQL and Windows auth support
import os
import sys
import logging
import hashlib
import subprocess
import winreg
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from Modules.server_logging import get_component_logger, log_exception
    logger = get_component_logger("Authentication")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Authentication")

# Debug mode via env
if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Auth debug mode enabled")

# SQL auth support
try:
    from Modules.Database.SQL_Connection import get_engine, initialise_user_manager
    from Modules.user_management import UserManager
    SQL_AVAILABLE = True
    logger.info("SQL auth available")
except ImportError as e:
    SQL_AVAILABLE = False
    logger.warning(f"SQL auth not available: {e}")

# Windows auth support
try:
    import win32api
    import win32security
    import win32net
    import win32netcon
    WINDOWS_AUTH_AVAILABLE = True
    logger.info("Windows auth available")
except ImportError as e:
    WINDOWS_AUTH_AVAILABLE = False
    logger.warning(f"Windows auth not available: {e}")

def get_server_manager_dir():
    # SM dir from registry
    try:
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Registry read failed: {e}")
        return None

_user_manager = None
def get_user_manager():
    # Get or create UserManager singleton
    global _user_manager
    if _user_manager is None and SQL_AVAILABLE:
        try:
            engine, user_manager = initialise_user_manager()
            _user_manager = user_manager
            logger.info("SQL UserManager initialised")
        except Exception as e:
            logger.error(f"UserManager init failed: {e}")
    return _user_manager

def authenticate_user(username, password, auth_type="auto"):
    # Authenticate user with credentials - supports SQL and Windows auth
    if not username or not password:
        logger.warning("Username and password are required")
        return False
    
    logger.debug(f"Attempting to authenticate user: {username} with type: {auth_type}")
    
    # Try SQL authentication first (if available and requested)
    if auth_type in ["auto", "sql"] and SQL_AVAILABLE:
        try:
            user_manager = get_user_manager()
            if user_manager:
                user = user_manager.get_user(username)
                if user and getattr(user, 'is_active', True):
                    # Check password - try bcrypt first, then fallback to SHA256 for compatibility
                    stored_password = getattr(user, 'password', '')
                    
                    # Try bcrypt verification first
                    try:
                        import bcrypt
                        if bcrypt.checkpw(password.encode(), stored_password.encode()):
                            logger.info(f"SQL authentication successful for user: {username} (bcrypt)")
                            # Update last login
                            try:
                                user_manager.update_user(username, last_login=datetime.now())
                            except Exception as e:
                                logger.warning(f"Failed to update last login: {e}")
                            return True
                    except Exception as e:
                        logger.debug(f"Bcrypt verification failed, trying SHA256: {e}")
                    
                    # Fallback to SHA256 for backward compatibility
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
                    if stored_password == hashed_password:
                        logger.info(f"SQL authentication successful for user: {username} (SHA256)")
                        # Update last login
                        try:
                            user_manager.update_user(username, last_login=datetime.now())
                        except Exception as e:
                            logger.warning(f"Failed to update last login: {e}")
                        return True
                    else:
                        logger.debug(f"Invalid password for SQL user: {username}")
                else:
                    logger.debug(f"SQL user not found or inactive: {username}")
        except Exception as e:
            logger.error(f"SQL authentication error: {e}")
    
    # Try Windows authentication if available and requested
    if auth_type in ["auto", "windows"] and WINDOWS_AUTH_AVAILABLE:
        try:
            if authenticate_windows_user(username, password):
                logger.info(f"Windows authentication successful for user: {username}")
                return True
        except Exception as e:
            logger.error(f"Windows authentication error: {e}")
    
    logger.warning(f"Authentication failed for user: {username}")
    return False

def authenticate_windows_user(username, password):
    # Authenticate against Windows using win32 API
    if not WINDOWS_AUTH_AVAILABLE:
        logger.error("Windows authentication not available")
        return False
    
    try:
        # Authenticate against local machine using Windows API
        domain = "."  # Local machine
        
        # Use LogonUser API to validate credentials securely
        import win32con
        hToken = win32security.LogonUser(
            username,
            domain,
            password,
            win32con.LOGON32_LOGON_NETWORK,
            win32con.LOGON32_PROVIDER_DEFAULT
        )
        
        if hToken:
            # Close the token handle
            hToken.Close()
            logger.debug(f"Windows authentication successful for: {username}")
            return True
        else:
            logger.debug(f"Windows authentication failed for: {username}")
            return False
            
    except Exception as e:
        logger.debug(f"Windows authentication error for {username}: {e}")
        return False

def is_admin_user(username, auth_type="auto"):
    # Check if user has admin privileges in SQL or Windows
    logger.debug(f"Checking admin status for user: {username} with type: {auth_type}")
    
    # Check SQL user admin status
    if auth_type in ["auto", "sql"] and SQL_AVAILABLE:
        try:
            user_manager = get_user_manager()
            if user_manager:
                user = user_manager.get_user(username)
                if user:
                    is_admin = getattr(user, 'is_admin', False)
                    logger.debug(f"SQL user {username} admin status: {is_admin}")
                    return is_admin
        except Exception as e:
            logger.error(f"Error checking SQL admin status: {e}")
    
    # Check Windows user admin status
    if auth_type in ["auto", "windows"] and WINDOWS_AUTH_AVAILABLE:
        try:
            if is_windows_admin(username):
                logger.debug(f"Windows user {username} is admin")
                return True
        except Exception as e:
            logger.error(f"Error checking Windows admin status: {e}")
    
    logger.debug(f"User {username} is not admin")
    return False

def is_windows_admin(username):
    # Check if Windows user is in local Administrators group
    if not WINDOWS_AUTH_AVAILABLE:
        return False
    
    try:
        # Try primary method - get user's group memberships
        try:
            import socket
            hostname = socket.gethostname()
            groups = win32net.NetUserGetGroups(hostname, username)
            for group in groups[0]:
                if group['name'].lower() in ['administrators', 'admin']:
                    return True
        except Exception:
            # Fallback - try with local groups  
            try:
                import socket
                hostname = socket.gethostname()
                groups = win32net.NetUserGetLocalGroups(hostname, username, 0)
                for group in groups[0]:
                    if group.lower() in ['administrators', 'admin']:
                        return True
            except Exception:
                # Final fallback - assume not admin for safety
                logger.debug(f"Could not determine admin status for {username}, assuming not admin")
                return False
        
        return False
        
    except Exception as e:
        logger.debug(f"Error checking Windows admin status for {username}: {e}")
        return False

def get_all_users(auth_type="sql"):
    # Get list of users from SQL or Windows (returns current user only for Windows)
    users = []
    
    if auth_type == "sql" and SQL_AVAILABLE:
        try:
            user_manager = get_user_manager()
            if user_manager:
                sql_users = user_manager.list_users()
                for user in sql_users:
                    users.append({
                        'Username': user.username,
                        'Email': getattr(user, 'email', ''),
                        'IsAdmin': getattr(user, 'is_admin', False),
                        'IsActive': getattr(user, 'is_active', True),
                        'Created': getattr(user, 'created_at', None),
                        'LastLogin': getattr(user, 'last_login', None),
                        'Type': 'SQL'
                    })
                logger.info(f"Retrieved {len(users)} SQL users")
        except Exception as e:
            logger.error(f"Error getting SQL users: {e}")
    
    elif auth_type == "windows" and WINDOWS_AUTH_AVAILABLE:
        try:
            # Windows user enumeration requires admin privileges, return current user only
            import getpass
            current_user = getpass.getuser()
            users.append({
                'Username': current_user,
                'Email': '',
                'IsAdmin': is_windows_admin(current_user),
                'IsActive': True,
                'Created': None,
                'LastLogin': None,
                'Type': 'Windows'
            })
            logger.info(f"Retrieved 1 Windows user (current user)")
        except Exception as e:
            logger.error(f"Error getting Windows users: {e}")
    
    return users

def create_user(username, password, email="", is_admin=False):
    # Create new SQL user (Windows users managed by OS)
    if not SQL_AVAILABLE:
        logger.error("SQL authentication not available - cannot create users")
        return False
    
    try:
        user_manager = get_user_manager()
        if user_manager:
            result = user_manager.add_user(username, password, email, is_admin)
            if result:
                logger.info(f"Created SQL user: {username}")
            return result
        else:
            logger.error("UserManager not available")
            return False
    except Exception as e:
        logger.error(f"Error creating user {username}: {e}")
        return False

def update_user_password(username, new_password):
    # Update password for SQL user
    if not SQL_AVAILABLE:
        logger.error("SQL authentication not available - cannot update passwords")
        return False
    
    try:
        user_manager = get_user_manager()
        if user_manager:
            result = user_manager.update_user(username, password=new_password)
            if result:
                logger.info(f"Updated password for SQL user: {username}")
            return result
        else:
            logger.error("UserManager not available")
            return False
    except Exception as e:
        logger.error(f"Error updating password for user {username}: {e}")
        return False

def delete_user(username):
    # Delete SQL user (Windows users managed by OS)
    if not SQL_AVAILABLE:
        logger.error("SQL authentication not available - cannot delete users")
        return False
    
    try:
        user_manager = get_user_manager()
        if user_manager:
            result = user_manager.delete_user(username)
            if result:
                logger.info(f"Deleted SQL user: {username}")
            return result
        else:
            logger.error("UserManager not available")
            return False
    except Exception as e:
        logger.error(f"Error deleting user {username}: {e}")
        return False

def set_user_admin_status(username, is_admin):
    # Set or remove admin status for SQL user
    if not SQL_AVAILABLE:
        logger.error("SQL authentication not available - cannot update admin status")
        return False
    
    try:
        user_manager = get_user_manager()
        if user_manager:
            result = user_manager.update_user(username, is_admin=is_admin)
            if result:
                logger.info(f"Updated admin status for SQL user {username} to {is_admin}")
            return result
        else:
            logger.error("UserManager not available")
            return False
    except Exception as e:
        logger.error(f"Error updating admin status for user {username}: {e}")
        return False