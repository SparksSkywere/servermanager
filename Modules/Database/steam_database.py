# Steam Apps Database Connection Module
# Handles SQLAlchemy connections specifically for Steam application data

from sqlalchemy import text

# Import shared utilities
from .database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type

# Setup standardized logging
from Modules.common import setup_module_logging, setup_module_path
setup_module_path()
logger = setup_module_logging("SteamDatabase")

def get_steam_sql_config_from_registry():
    # Get SQL configuration for Steam apps database from Windows registry
    return get_sql_config_from_registry()

def build_steam_db_url(config):
    # Build SQLAlchemy database URL from config for Steam apps database
    return build_db_url(config)

def get_steam_engine():
    # Get SQLAlchemy engine for Steam apps database
    return get_engine_by_type("steam")

def ensure_steam_tables(engine):
    # Ensure Steam apps tables exist in the Steam database
    try:
        with engine.connect() as conn:
            # Create comprehensive steam_apps table with subscription tracking
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS steam_apps (
                    appid INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT,
                    is_server BOOLEAN DEFAULT 0,
                    is_dedicated_server BOOLEAN DEFAULT 0,
                    requires_subscription BOOLEAN DEFAULT 0,
                    anonymous_install BOOLEAN DEFAULT 1,
                    publisher TEXT,
                    release_date TEXT,
                    description TEXT,
                    tags TEXT,
                    price TEXT,
                    platforms TEXT,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'steamdb'
                )
            """))
            conn.commit()
            logger.info("Ensured steam_apps table exists in Steam database")
            
    except Exception as e:
        logger.error(f"Failed to ensure Steam tables: {e}")
        raise

def initialize_steam_database():
    # Initialize Steam apps database and return engine
    try:
        engine = get_steam_engine()
        ensure_steam_tables(engine)
        logger.info("Steam apps database initialized")
        return engine
    except Exception as e:
        logger.error(f"Failed to initialize Steam database: {e}")
        raise

# Legacy compatibility layer - redirect old function names to Steam-specific versions
def get_engine():
    # Backwards compatibility - redirects to get_steam_engine()
    logger.warning("get_engine() is deprecated, use get_steam_engine() for Steam apps database or get_user_engine() for users")
    return get_steam_engine()

def get_sql_config_from_registry():
    # Backwards compatibility - redirects to get_steam_sql_config_from_registry()
    logger.warning("get_sql_config_from_registry() is deprecated, use get_steam_sql_config_from_registry() or get_user_sql_config_from_registry()")
    return get_steam_sql_config_from_registry()

def build_db_url(config):
    # Backwards compatibility - redirects to build_steam_db_url()
    logger.warning("build_db_url() is deprecated, use build_steam_db_url() or build_user_db_url()")
    return build_steam_db_url(config)