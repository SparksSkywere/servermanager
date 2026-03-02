# Steam apps database
import os
import sys
from sqlalchemy import text
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path, setup_module_logging
setup_module_path()

from .database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type

logger: logging.Logger = setup_module_logging("SteamDatabase")

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
            
            # Console states table for storing server console output
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS console_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    process_id INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    output_buffer TEXT,  -- JSON array of console output entries
                    command_history TEXT, -- JSON array of command history
                    UNIQUE(server_name)
                )
            """))
            
            conn.commit()
            logger.info("Steam apps and console states tables ensured")
            
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
