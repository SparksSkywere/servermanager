import os
import sys
import logging
import hashlib
import subprocess
import winreg
from datetime import datetime

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Centralized logging / debugging (follows dashboard pattern)
try:  # Prefer centralized log manager
    from Modules.server_logging import get_component_logger, log_security_event, log_user_action, log_exception
    logger = get_component_logger("Authentication")
except Exception:  # Fallback minimal logger
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Authentication")

# Enable debug level if global flag set
if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Authentication module debug mode enabled via environment")

# SQL Authentication support
try:
    from Modules.Database.SQL_Connection import get_engine, initialize_user_manager
    from Modules.user_management import UserManager
    SQL_AVAILABLE = True
    logger.info("SQL authentication support available")
except ImportError as e:
    SQL_AVAILABLE = False
    logger.warning(f"SQL authentication not available: {e}")

# Windows Authentication support
try:
    import win32api
    import win32security
    import win32net
    import win32netcon
    WINDOWS_AUTH_AVAILABLE = True
    logger.info("Windows authentication support available")
except ImportError as e:
    WINDOWS_AUTH_AVAILABLE = False
    logger.warning(f"Windows authentication not available: {e}")

# Centralized logging / debugging (follows dashboard pattern)
try:  # Prefer centralized log manager
    from Modules.server_logging import get_component_logger, log_security_event, log_user_action, log_exception
    logger = get_component_logger("Authentication")
except Exception:  # Fallback minimal logger
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Authentication")

# Enable debug level if global flag set
if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Authentication module debug mode enabled via environment")

# SQL Authentication support
try:
    from Modules.Database.SQL_Connection import get_engine, initialize_user_manager
    from Modules.user_management import UserManager
    SQL_AVAILABLE = True
    logger.info("SQL authentication support available")
except ImportError as e:
    SQL_AVAILABLE = False
    logger.warning(f"SQL authentication not available: {e}")

# Windows Authentication support
try:
    import win32api
    import win32security
    import win32net
    import win32netcon
    WINDOWS_AUTH_AVAILABLE = True
    logger.info("Windows authentication support available")
except ImportError as e:
    WINDOWS_AUTH_AVAILABLE = False
    logger.warning(f"Windows authentication not available: {e}")

# Get the server manager directory from registry
def get_server_manager_dir():
    try:
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Failed to get server manager directory from registry: {e}")
        return None

# Initialize SQL authentication if available
_user_manager = None
def get_user_manager():
    """Get or create UserManager instance"""
    global _user_manager
    if _user_manager is None and SQL_AVAILABLE:
        try:
            engine, user_manager = initialize_user_manager()
            _user_manager = user_manager
            logger.info("SQL UserManager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize SQL UserManager: {e}")
    return _user_manager

def authenticate_user(username, password, auth_type="auto"):
    """
    Authenticate a user with the given credentials
    
    Args:
        username: Username to authenticate
        password: Password for authentication
        auth_type: "auto", "sql", or "windows"
    
    Returns:
        bool: True if authentication successful, False otherwise
    """
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
                    # Hash the provided password and compare
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
                    stored_password = getattr(user, 'password', '')
                    if stored_password == hashed_password:
                        logger.info(f"SQL authentication successful for user: {username}")
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
    """
    Authenticate against Windows using win32 API
    
    Args:
        username: Windows username
        password: Windows password
    
    Returns:
        bool: True if authentication successful
    """
    if not WINDOWS_AUTH_AVAILABLE:
        logger.error("Windows authentication not available")
        return False
    
    try:
        # Try to authenticate against local machine
        domain = "."  # Local machine
        
        # Use LogonUser API to validate credentials
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
    """
    Check if a user has admin privileges
    
    Args:
        username: Username to check
        auth_type: "auto", "sql", or "windows"
    
    Returns:
        bool: True if user is admin
    """
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
    """
    Check if a Windows user is in the local Administrators group
    
    Args:
        username: Windows username to check
    
    Returns:
        bool: True if user is in Administrators group
    """
    if not WINDOWS_AUTH_AVAILABLE:
        return False
    
    try:
        # Simple approach - check if user is in Administrators group
        try:
            # Get user groups
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
    """
    Get a list of all users
    
    Args:
        auth_type: "sql" or "windows" (windows returns local users)
    
    Returns:
        list: List of user dictionaries
    """
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
            # Simplified approach - just return current user for Windows auth
            # Full user enumeration requires elevated privileges
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
    """
    Create a new SQL user (Windows users are managed by the OS)
    
    Args:
        username: Username for new user
        password: Password for new user
        email: Email address (optional)
        is_admin: Whether user should be admin
    
    Returns:
        bool: True if user created successfully
    """
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
    """
    Update a user's password (SQL users only)
    
    Args:
        username: Username to update
        new_password: New password
    
    Returns:
        bool: True if password updated successfully
    """
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
    """
    Delete a SQL user (Windows users are managed by the OS)
    
    Args:
        username: Username to delete
    
    Returns:
        bool: True if user deleted successfully
    """
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
    """
    Set or remove admin status for a SQL user
    
    Args:
        username: Username to update
        is_admin: Whether user should be admin
    
    Returns:
        bool: True if admin status updated successfully
    """
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