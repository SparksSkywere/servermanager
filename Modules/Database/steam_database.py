import os
import sys
import winreg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SteamDatabase")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SteamDatabase")

def get_steam_sql_config_from_registry():
    """Get SQL configuration for Steam apps database from Windows registry"""
    try:
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        
        # Try to get SQL type
        try:
            sql_type = winreg.QueryValueEx(key, "SQLType")[0]
        except:
            sql_type = "SQLite"  # Default to SQLite
        
        # Get database path/connection info based on type
        if sql_type.lower() == "sqlite":
            try:
                db_path = winreg.QueryValueEx(key, "SteamSQLDatabasePath")[0]
            except:
                # Default SQLite path for Steam apps database - using db directory
                try:
                    server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                    db_path = os.path.join(server_manager_dir, "db", "steam_ID.db")
                except:
                    db_path = "steam_ID.db"
            
            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types (MySQL, PostgreSQL, etc.) - use separate Steam database
            try:
                db_name = winreg.QueryValueEx(key, "SteamSQLDatabase")[0]
            except:
                db_name = "steam_apps"
                
            config = {
                "type": sql_type.lower(),
                "host": winreg.QueryValueEx(key, "SQLHost")[0],
                "port": winreg.QueryValueEx(key, "SQLPort")[0],
                "database": db_name,
                "username": winreg.QueryValueEx(key, "SQLUsername")[0],
                "password": winreg.QueryValueEx(key, "SQLPassword")[0]
            }
        
        winreg.CloseKey(key)
        return config
        
    except Exception as e:
        logger.error(f"Failed to read Steam SQL config from registry: {e}")
        # Return default SQLite config
        return {
            "type": "sqlite",
            "db_path": "steam_ID.db"
        }

def build_steam_db_url(config):
    """Build SQLAlchemy database URL from config for Steam apps database"""
    if config["type"] == "sqlite":
        # For SQLite, use absolute path
        db_path = config["db_path"]
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(db_path)
        return f"sqlite:///{db_path}"
    elif config["type"] == "mysql":
        return f"mysql+pymysql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    elif config["type"] == "postgresql":
        return f"postgresql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    else:
        raise ValueError(f"Unsupported database type: {config['type']}")

def get_steam_engine():
    """Get SQLAlchemy engine for Steam apps database"""
    config = get_steam_sql_config_from_registry()
    db_url = build_steam_db_url(config)
    
    # Create engine with appropriate settings
    if config["type"] == "sqlite":
        engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
    else:
        engine = create_engine(db_url, echo=False)
    
    return engine

def ensure_steam_tables(engine):
    """Ensure Steam apps tables exist in the Steam database"""
    try:
        with engine.connect() as conn:
            # Create steam_apps table if it doesn't exist
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
    """Initialize Steam apps database and return engine"""
    try:
        engine = get_steam_engine()
        ensure_steam_tables(engine)
        logger.info("Steam apps database initialized")
        return engine
    except Exception as e:
        logger.error(f"Failed to initialize Steam database: {e}")
        raise

# For backwards compatibility - maintain the old function names but redirect to Steam-specific functions
def get_engine():
    """Backwards compatibility - redirects to get_steam_engine()"""
    logger.warning("get_engine() is deprecated, use get_steam_engine() for Steam apps database or get_user_engine() for users")
    return get_steam_engine()

def get_sql_config_from_registry():
    """Backwards compatibility - redirects to get_steam_sql_config_from_registry()"""
    logger.warning("get_sql_config_from_registry() is deprecated, use get_steam_sql_config_from_registry() or get_user_sql_config_from_registry()")
    return get_steam_sql_config_from_registry()

def build_db_url(config):
    """Backwards compatibility - redirects to build_steam_db_url()"""
    logger.warning("build_db_url() is deprecated, use build_steam_db_url() or build_user_db_url()")
    return build_steam_db_url(config)
