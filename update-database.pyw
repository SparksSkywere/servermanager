import sys
import os
import traceback

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from Modules.SQL_Connection import get_engine
from sqlalchemy import inspect, text

# Define required columns for the users table
REQUIRED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "username": "VARCHAR(64) UNIQUE NOT NULL",
    "password": "VARCHAR(256) NOT NULL",
    "email": "VARCHAR(128) UNIQUE",
    "is_admin": "BOOLEAN DEFAULT 0",
    "is_active": "BOOLEAN DEFAULT 1",
    "two_factor_enabled": "BOOLEAN DEFAULT 0",
    "two_factor_secret": "VARCHAR(64)"
}

def get_column_type_for_backend(col, backend):
    # Map types for each backend
    if backend == "sqlite":
        mapping = {
            "INTEGER PRIMARY KEY AUTOINCREMENT": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "VARCHAR(64) UNIQUE NOT NULL": "TEXT UNIQUE NOT NULL",
            "VARCHAR(256) NOT NULL": "TEXT NOT NULL",
            "VARCHAR(128) UNIQUE": "TEXT UNIQUE",
            "BOOLEAN DEFAULT 0": "INTEGER DEFAULT 0",
            "BOOLEAN DEFAULT 1": "INTEGER DEFAULT 1",
            "VARCHAR(64)": "TEXT",
        }
    elif backend == "mysql" or backend == "mariadb":
        mapping = {
            "INTEGER PRIMARY KEY AUTOINCREMENT": "INT AUTO_INCREMENT PRIMARY KEY",
            "VARCHAR(64) UNIQUE NOT NULL": "VARCHAR(64) UNIQUE NOT NULL",
            "VARCHAR(256) NOT NULL": "VARCHAR(256) NOT NULL",
            "VARCHAR(128) UNIQUE": "VARCHAR(128) UNIQUE",
            "BOOLEAN DEFAULT 0": "BOOLEAN DEFAULT 0",
            "BOOLEAN DEFAULT 1": "BOOLEAN DEFAULT 1",
            "VARCHAR(64)": "VARCHAR(64)",
        }
    elif backend == "mssql":
        mapping = {
            "INTEGER PRIMARY KEY AUTOINCREMENT": "INT IDENTITY(1,1) PRIMARY KEY",
            "VARCHAR(64) UNIQUE NOT NULL": "NVARCHAR(64) UNIQUE NOT NULL",
            "VARCHAR(256) NOT NULL": "NVARCHAR(256) NOT NULL",
            "VARCHAR(128) UNIQUE": "NVARCHAR(128) UNIQUE",
            "BOOLEAN DEFAULT 0": "BIT DEFAULT 0",
            "BOOLEAN DEFAULT 1": "BIT DEFAULT 1",
            "VARCHAR(64)": "NVARCHAR(64)",
        }
    else:
        mapping = {k: k for k in REQUIRED_COLUMNS.values()}
    return mapping.get(REQUIRED_COLUMNS[col], REQUIRED_COLUMNS[col])

def main():
    print("Checking and updating users table schema...")
    try:
        engine = get_engine()
        inspector = inspect(engine)
        backend = engine.url.get_backend_name()
        # Normalize backend name
        if backend.startswith("mssql"):
            backend = "mssql"
        elif backend.startswith("mysql"):
            backend = "mysql"
        elif backend.startswith("mariadb"):
            backend = "mariadb"
        elif backend.startswith("sqlite"):
            backend = "sqlite"

        # Check if users table exists
        if "users" not in inspector.get_table_names():
            print("Table 'users' does not exist. Creating table...")
            # Compose CREATE TABLE statement
            col_defs = []
            for col, typ in REQUIRED_COLUMNS.items():
                col_defs.append(f"{col} {get_column_type_for_backend(col, backend)}")
            create_sql = f"CREATE TABLE users ({', '.join(col_defs)})"
            with engine.begin() as conn:
                conn.execute(text(create_sql))
            print("Table 'users' created.")
            return

        # Table exists, check columns
        columns = {col["name"] for col in inspector.get_columns("users")}
        missing = [col for col in REQUIRED_COLUMNS if col not in columns]
        if not missing:
            print("All required columns exist. No update needed.")
            return

        print(f"Missing columns: {missing}")
        # Add missing columns
        with engine.begin() as conn:
            for col in missing:
                col_type = get_column_type_for_backend(col, backend)
                try:
                    if backend == "sqlite":
                        sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                    elif backend == "mysql" or backend == "mariadb":
                        sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                    elif backend == "mssql":
                        sql = f"ALTER TABLE users ADD {col} {col_type}"
                    else:
                        sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                    print(f"Executing: {sql}")
                    conn.execute(text(sql))
                except Exception as e:
                    print(f"Failed to add column {col}: {e}")
        print("Database schema updated successfully.")

    except Exception as e:
        print("Error updating database schema:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
