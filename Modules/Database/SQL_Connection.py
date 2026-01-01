# SQL connection interface
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SQL_Connection")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SQL_Connection")

# Import specialised DB modules
try:
    from .user_database import (
        get_user_engine, get_user_sql_config_from_registry, build_user_db_url, 
        ensure_root_admin, initialise_user_manager, sql_login, handle_2fa_login
    )
    from .steam_database import (
        get_steam_engine, get_steam_sql_config_from_registry, build_steam_db_url, 
        ensure_steam_tables, initialise_steam_database
    )
    from .database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type
except ImportError:
    try:
        from user_database import (
            get_user_engine, get_user_sql_config_from_registry, build_user_db_url, 
            ensure_root_admin, initialise_user_manager, sql_login, handle_2fa_login
        )
        from steam_database import (
            get_steam_engine, get_steam_sql_config_from_registry, build_steam_db_url, 
            ensure_steam_tables, initialise_steam_database
        )
        from database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type
    except ImportError as e:
        logger.error(f"DB module import failed: {e}")
        raise

# Backward compat aliases
initialize_user_manager = initialise_user_manager
initialize_steam_database = initialise_steam_database

def get_sql_config_from_registry():
    # DEPRECATED: Use get_user_sql_config_from_registry() or get_steam_sql_config_from_registry()
    logger.warning("get_sql_config_from_registry() deprecated")
    return get_user_sql_config_from_registry()

def build_db_url(config):
    # DEPRECATED: Use build_user_db_url() or build_steam_db_url()
    logger.warning("build_db_url() deprecated")
    return build_user_db_url(config)

def get_engine():
    # DEPRECATED: Use get_user_engine() or get_steam_engine()
    logger.warning("get_engine() deprecated")
    return get_user_engine()

# Export interface
__all__ = [
    # User DB functions
    'get_user_engine', 'get_user_sql_config_from_registry', 'build_user_db_url', 
    'ensure_root_admin', 'initialise_user_manager', 'initialize_user_manager', 
    'sql_login', 'handle_2fa_login',
    
    # Steam DB functions  
    'get_steam_engine', 'get_steam_sql_config_from_registry', 'build_steam_db_url', 
    'ensure_steam_tables', 'initialise_steam_database', 'initialize_steam_database',
    
    # Shared utilities
    'get_sql_config_from_registry', 'build_db_url', 'get_engine_by_type',
    
    # Deprecated (backward compat)
    'get_engine', 'get_sql_config_from_registry', 'build_db_url'
]