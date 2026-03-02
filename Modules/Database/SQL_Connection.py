# SQL connection interface
import os
import sys

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_component_logger
logger = get_component_logger("SQL_Connection")

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

# Export interface
__all__ = [
    # User DB functions
    'get_user_engine', 'get_user_sql_config_from_registry', 'build_user_db_url', 
    'ensure_root_admin', 'initialise_user_manager', 
    'sql_login', 'handle_2fa_login',
    
    # Steam DB functions  
    'get_steam_engine', 'get_steam_sql_config_from_registry', 'build_steam_db_url', 
    'ensure_steam_tables', 'initialise_steam_database',
    
    # Shared utilities
    'get_sql_config_from_registry', 'build_db_url', 'get_engine_by_type',
]
