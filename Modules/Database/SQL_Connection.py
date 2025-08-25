import os
import sys

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SQL_Connection")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SQL_Connection")

# Import the new database modules
try:
    from .user_database import (
        get_user_engine, get_user_sql_config_from_registry, build_user_db_url, 
        ensure_root_admin, initialize_user_manager, sql_login, handle_2fa_authentication
    )
    from .steam_database import (
        get_steam_engine, get_steam_sql_config_from_registry, build_steam_db_url, 
        ensure_steam_tables, initialize_steam_database
    )
except ImportError:
    # Fallback for direct imports
    try:
        from user_database import (
            get_user_engine, get_user_sql_config_from_registry, build_user_db_url, 
            ensure_root_admin, initialize_user_manager, sql_login, handle_2fa_authentication
        )
        from steam_database import (
            get_steam_engine, get_steam_sql_config_from_registry, build_steam_db_url, 
            ensure_steam_tables, initialize_steam_database
        )
    except ImportError as e:
        logger.error(f"Failed to import database modules: {e}")
        raise

# Backward compatibility functions - these now redirect to the appropriate database modules

def get_sql_config_from_registry():
    """
    DEPRECATED: This function is deprecated. Use get_user_sql_config_from_registry() for user database
    or get_steam_sql_config_from_registry() for Steam apps database.
    
    For backward compatibility, this returns the user database config.
    """
    logger.warning("get_sql_config_from_registry() is deprecated. Use get_user_sql_config_from_registry() or get_steam_sql_config_from_registry()")
    return get_user_sql_config_from_registry()

def build_db_url(config):
    """
    DEPRECATED: This function is deprecated. Use build_user_db_url() for user database
    or build_steam_db_url() for Steam apps database.
    
    For backward compatibility, this uses the user database URL builder.
    """
    logger.warning("build_db_url() is deprecated. Use build_user_db_url() or build_steam_db_url()")
    return build_user_db_url(config)

def get_engine():
    """
    DEPRECATED: This function is deprecated. Use get_user_engine() for user database
    or get_steam_engine() for Steam apps database.
    
    For backward compatibility, this returns the user database engine.
    """
    logger.warning("get_engine() is deprecated. Use get_user_engine() or get_steam_engine()")
    return get_user_engine()

# Re-export functions from the new database modules for backward compatibility
__all__ = [
    # User database functions
    'get_user_engine', 'get_user_sql_config_from_registry', 'build_user_db_url', 
    'ensure_root_admin', 'initialize_user_manager', 'sql_login', 'handle_2fa_authentication',
    
    # Steam database functions  
    'get_steam_engine', 'get_steam_sql_config_from_registry', 'build_steam_db_url', 
    'ensure_steam_tables', 'initialize_steam_database',
    
    # Deprecated backward compatibility functions
    'get_engine', 'get_sql_config_from_registry', 'build_db_url'
]
