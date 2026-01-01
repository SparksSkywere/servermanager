# Minecraft servers database
from sqlalchemy import text
from .database_utils import get_sql_config_from_registry as db_get_sql_config, build_db_url, get_engine_by_type
from Modules.common import setup_module_logging, setup_module_path

setup_module_path()
logger = setup_module_logging("MinecraftDatabase")

def get_minecraft_sql_config_from_registry():
    # MC DB config from registry
    return db_get_sql_config("minecraft")

def build_minecraft_db_url(config):
    # SQLAlchemy URL for MC DB
    return build_db_url(config)

def get_minecraft_engine():
    # SQLAlchemy engine for MC DB
    return get_engine_by_type("minecraft")

def ensure_minecraft_tables(engine):
    # Create MC tables if missing
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS minecraft_servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id TEXT NOT NULL UNIQUE,
                    version_type TEXT,
                    modloader TEXT,
                    modloader_version TEXT,
                    java_requirement INTEGER,
                    download_url TEXT,
                    installer_url TEXT,
                    release_date TEXT,
                    description TEXT,
                    is_dedicated_server BOOLEAN DEFAULT 1,
                    is_recommended BOOLEAN DEFAULT 0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'mojang'
                )
            """))
            conn.commit()
            logger.info("MC tables ensured")
    except Exception as e:
        logger.error(f"MC tables creation failed: {e}")
        raise

def initialise_minecraft_database():
    # Init MC DB, return engine
    try:
        engine = get_minecraft_engine()
        ensure_minecraft_tables(engine)
        logger.info("MC DB initialised")
        return engine
    except Exception as e:
        logger.error(f"Failed to initialise Minecraft database: {e}")
        raise

# Legacy compatibility layer
def get_engine():
    # Backwards compatibility - redirects to get_minecraft_engine()
    logger.warning("get_engine() is deprecated, use get_minecraft_engine() for Minecraft servers database")
    return get_minecraft_engine()

def get_sql_config_from_registry():
    # Backwards compatibility - redirects to get_minecraft_sql_config_from_registry()
    logger.warning("get_sql_config_from_registry() is deprecated, use get_minecraft_sql_config_from_registry()")
    return get_minecraft_sql_config_from_registry()

def build_db_url(config):
    # Backwards compatibility - redirects to build_minecraft_db_url()
    logger.warning("build_db_url() is deprecated, use build_minecraft_db_url()")
    return build_minecraft_db_url(config)