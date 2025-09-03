import os
import sys

# Unified SQL connection interface with backward compatibility layer
# This module provides access to both user and Steam databases while maintaining
# compatibility with legacy code that used the old unified interface

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

# Import specialized database modules with fallback handling
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

# Backward compatibility layer - redirects deprecated functions to new database modules

def get_sql_config_from_registry():
    # DEPRECATED: Use get_user_sql_config_from_registry() or get_steam_sql_config_from_registry()
    # Returns user database config for backward compatibility
    logger.warning("get_sql_config_from_registry() is deprecated. Use get_user_sql_config_from_registry() or get_steam_sql_config_from_registry()")
    return get_user_sql_config_from_registry()

def build_db_url(config):
    # DEPRECATED: Use build_user_db_url() or build_steam_db_url()
    # Uses user database URL builder for backward compatibility
    logger.warning("build_db_url() is deprecated. Use build_user_db_url() or build_steam_db_url()")
    return build_user_db_url(config)

def get_engine():
    # DEPRECATED: Use get_user_engine() or get_steam_engine()
    # Returns user database engine for backward compatibility
    logger.warning("get_engine() is deprecated. Use get_user_engine() or get_steam_engine()")
    return get_user_engine()

# Export interface for backward compatibility and new database separation
__all__ = [
    # User database functions
    'get_user_engine', 'get_user_sql_config_from_registry', 'build_user_db_url', 
    'ensure_root_admin', 'initialize_user_manager', 'sql_login', 'handle_2fa_authentication',
    
    # Steam database functions  
    'get_steam_engine', 'get_steam_sql_config_from_registry', 'build_steam_db_url', 
    'ensure_steam_tables', 'initialize_steam_database',
    
    # Deprecated functions (maintained for backward compatibility)
    'get_engine', 'get_sql_config_from_registry', 'build_db_url'
]
