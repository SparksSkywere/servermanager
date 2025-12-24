# Steam apps database
# - SQLAlchemy connections for Steam app data

from sqlalchemy import text

from .database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type

from Modules.common import setup_module_logging, setup_module_path
setup_module_path()
logger = setup_module_logging("SteamDatabase")

def get_steam_sql_config_from_registry():
    # Steam DB config from registry
    return get_sql_config_from_registry()

def build_steam_db_url(config):
    # SQLAlchemy URL for Steam DB
    return build_db_url(config)

def get_steam_engine():
    # SQLAlchemy engine for Steam DB
    return get_engine_by_type("steam")

def ensure_steam_tables(engine):
    # Create Steam apps tables if missing
    try:
        with engine.connect() as conn:
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
            logger.info("Steam apps table ensured")
            
    except Exception as e:
        logger.error(f"Steam tables creation failed: {e}")
        raise

def initialise_steam_database():
    # Init Steam apps DB, return engine
    try:
        engine = get_steam_engine()
        ensure_steam_tables(engine)
        logger.info("Steam DB initialised")
        return engine
    except Exception as e:
        logger.error(f"Steam DB init failed: {e}")
        raise

# Backward compat
initialize_steam_database = initialise_steam_database

def get_engine():
    # DEPRECATED: Use get_steam_engine() or get_user_engine()
    logger.warning("get_engine() deprecated")
    return get_steam_engine()

def get_sql_config_from_registry():
    # DEPRECATED: Use get_steam_sql_config_from_registry() or get_user_sql_config_from_registry()
    logger.warning("get_sql_config_from_registry() deprecated")
    return get_steam_sql_config_from_registry()

def build_db_url(config):
    # DEPRECATED: Use build_steam_db_url()
    logger.warning("build_db_url() is deprecated, use build_steam_db_url() or build_user_db_url()")
    return build_steam_db_url(config)