import os
import sys
import logging
import winreg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("SQL_Connection")

def get_sql_config_from_registry():
    """Get SQL configuration from Windows registry"""
    try:
        registry_path = r"Software\SkywereIndustries\Servermanager"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        
        # Try to get SQL type
        try:
            sql_type = winreg.QueryValueEx(key, "SQLType")[0]
        except:
            sql_type = "SQLite"  # Default to SQLite
        
        # Get database path/connection info based on type
        if sql_type.lower() == "sqlite":
            try:
                db_path = winreg.QueryValueEx(key, "SQLDatabasePath")[0]
            except:
                # Default SQLite path
                try:
                    server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                    db_path = os.path.join(server_manager_dir, "config", "servermanager.db")
                except:
                    db_path = "servermanager.db"
            
            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types (MySQL, PostgreSQL, etc.)
            config = {
                "type": sql_type.lower(),
                "host": winreg.QueryValueEx(key, "SQLHost")[0],
                "port": winreg.QueryValueEx(key, "SQLPort")[0],
                "database": winreg.QueryValueEx(key, "SQLDatabase")[0],
                "username": winreg.QueryValueEx(key, "SQLUsername")[0],
                "password": winreg.QueryValueEx(key, "SQLPassword")[0]
            }
        
        winreg.CloseKey(key)
        return config
        
    except Exception as e:
        logger.error(f"Failed to read SQL config from registry: {e}")
        # Return default SQLite config
        return {
            "type": "sqlite",
            "db_path": "servermanager.db"
        }

def build_db_url(config):
    """Build SQLAlchemy database URL from config"""
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

def get_engine():
    """Get SQLAlchemy engine"""
    config = get_sql_config_from_registry()
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

def ensure_root_admin(engine):
    """Ensure root admin user exists in database"""
    try:
        # This is a placeholder - implement based on your user table structure
        with engine.connect() as conn:
            # Check if users table exists and create if needed with all columns
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    display_name TEXT,
                    account_number TEXT UNIQUE,
                    is_admin BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME,
                    last_login DATETIME,
                    two_factor_enabled BOOLEAN DEFAULT 0,
                    two_factor_secret TEXT
                )
            """))
            
            # Check if admin user exists
            result = conn.execute(text("SELECT COUNT(*) FROM users WHERE username = 'admin'"))
            count = result.scalar()
            
            if count == 0:
                # Create admin user with default password
                import hashlib
                from datetime import datetime
                import uuid
                admin_password = hashlib.sha256("admin".encode()).hexdigest()
                account_number = str(uuid.uuid4())[:8].upper()
                conn.execute(text("""
                    INSERT INTO users (username, password, is_admin, is_active, created_at, email, first_name, last_name, display_name, account_number) 
                    VALUES ('admin', :password, 1, 1, :created_at, 'admin@localhost', 'System', 'Administrator', 'Admin', :account_number)
                """), {
                    "password": admin_password,
                    "created_at": datetime.utcnow(),
                    "account_number": account_number
                })
                conn.commit()
                logger.info("Created default admin user")
            
    except Exception as e:
        logger.error(f"Failed to ensure root admin: {e}")
        raise
