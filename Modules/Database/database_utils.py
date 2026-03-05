# Database utilities
import os
import sys
from sqlalchemy import create_engine
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_component_logger

logger: logging.Logger = get_component_logger("DatabaseUtils")

def get_sql_config_from_registry(db_type="user"):
    # SQL config from registry for user/steam/minecraft databases
    try:
        from Modules.common import REGISTRY_PATH, get_server_manager_dir, get_registry_value, get_registry_values

        sql_type = get_registry_value(REGISTRY_PATH, "SQLType", "SQLite")

        # Database path based on type
        if sql_type.lower() == "sqlite":
            if db_type == "user":
                db_path = get_registry_value(REGISTRY_PATH, "UsersSQLDatabasePath", None)
                if not db_path:
                    try:
                        server_manager_dir = get_server_manager_dir()
                        db_path = os.path.join(server_manager_dir, "db", "servermanager_users.db")
                    except Exception:
                        db_path = "servermanager_users.db"
            elif db_type == "steam":
                db_path = get_registry_value(REGISTRY_PATH, "SteamSQLDatabasePath", None)
                if not db_path:
                    try:
                        server_manager_dir = get_server_manager_dir()
                        db_path = os.path.join(server_manager_dir, "db", "steam_ID.db")
                    except Exception:
                        db_path = "steam_ID.db"
            elif db_type == "minecraft":
                db_path = get_registry_value(REGISTRY_PATH, "MinecraftSQLDatabasePath", None)
                if not db_path:
                    try:
                        server_manager_dir = get_server_manager_dir()
                        db_path = os.path.join(server_manager_dir, "db", "minecraft_ID.db")
                    except Exception:
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
                db_name = get_registry_value(REGISTRY_PATH, "UsersSQLDatabase", "servermanager_users")
            elif db_type == "steam":
                db_name = get_registry_value(REGISTRY_PATH, "SteamSQLDatabase", "steam_apps")
            elif db_type == "minecraft":
                db_name = get_registry_value(REGISTRY_PATH, "MinecraftSQLDatabase", "minecraft_servers")
            else:
                db_name = db_type

            sql_conn = get_registry_values(REGISTRY_PATH, ["SQLHost", "SQLPort", "SQLUsername", "SQLPassword"])
            config = {
                "type": sql_type.lower(),
                "host": sql_conn["SQLHost"],
                "port": sql_conn["SQLPort"],
                "database": db_name,
                "username": sql_conn["SQLUsername"],
                "password": sql_conn["SQLPassword"]
            }

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
    # Get engine by database type
    config = get_sql_config_from_registry(db_type)
    return get_engine(config)