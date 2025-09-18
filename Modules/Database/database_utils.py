# Database Utilities Module
# Common database functions shared between user and steam databases

import os
import sys
import winreg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("DatabaseUtils")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("DatabaseUtils")

def get_sql_config_from_registry(db_type="user"):
    # Generic SQL configuration function for both user and steam databases
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
            # Determine database path based on type
            if db_type == "user":
                try:
                    db_path = winreg.QueryValueEx(key, "UsersSQLDatabasePath")[0]
                except:
                    try:
                        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                        db_path = os.path.join(server_manager_dir, "db", "servermanager_users.db")
                    except:
                        db_path = "servermanager_users.db"
            elif db_type == "steam":
                try:
                    db_path = winreg.QueryValueEx(key, "SteamSQLDatabasePath")[0]
                except:
                    try:
                        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                        db_path = os.path.join(server_manager_dir, "db", "steam_ID.db")
                    except:
                        db_path = "steam_ID.db"
            elif db_type == "minecraft":
                try:
                    db_path = winreg.QueryValueEx(key, "MinecraftSQLDatabasePath")[0]
                except:
                    try:
                        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                        db_path = os.path.join(server_manager_dir, "db", "minecraft_ID.db")
                    except:
                        db_path = "minecraft_ID.db"
            else:
                db_path = f"{db_type}.db"

            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types (MySQL, PostgreSQL, etc.)
            if db_type == "user":
                try:
                    db_name = winreg.QueryValueEx(key, "UsersSQLDatabase")[0]
                except:
                    db_name = "servermanager_users"
            elif db_type == "steam":
                try:
                    db_name = winreg.QueryValueEx(key, "SteamSQLDatabase")[0]
                except:
                    db_name = "steam_apps"
            elif db_type == "minecraft":
                try:
                    db_name = winreg.QueryValueEx(key, "MinecraftSQLDatabase")[0]
                except:
                    db_name = "minecraft_servers"
            else:
                db_name = db_type

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
        logger.error(f"Failed to read {db_type} SQL config from registry: {e}")
        # Return default SQLite config
        if db_type == "user":
            default_db = "servermanager_users.db"
        elif db_type == "steam":
            default_db = "steam_ID.db"
        elif db_type == "minecraft":
            default_db = "minecraft_ID.db"
        else:
            default_db = f"{db_type}.db"
        return {
            "type": "sqlite",
            "db_path": default_db
        }

def build_db_url(config):
    # Generic database URL builder for all database types
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

def get_engine(config):
    # Generic SQLAlchemy engine creator
    db_url = build_db_url(config)

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

def get_engine_by_type(db_type="user"):
    # Get engine by database type (for backwards compatibility)
    config = get_sql_config_from_registry(db_type)
    return get_engine(config)