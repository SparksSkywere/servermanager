#!/usr/bin/env python3
import os
import sys
import logging
import sqlite3
import shutil
from datetime import datetime

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("DatabaseMigration")

def get_server_manager_dir():
    """Get Server Manager directory from registry"""
    try:
        import winreg
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Failed to get server manager directory: {e}")
        return None

def backup_old_database(old_db_path):
    """Create a backup of the old database"""
    if not os.path.exists(old_db_path):
        logger.warning(f"Old database not found: {old_db_path}")
        return False
    
    backup_path = f"{old_db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        shutil.copy2(old_db_path, backup_path)
        logger.info(f"Created backup: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return False

def migrate_users_data(old_db_path, new_user_db_path):
    """Migrate user data from old database to new user database"""
    try:
        # Connect to old database
        old_conn = sqlite3.connect(old_db_path)
        old_cursor = old_conn.cursor()
        
        # Check if users table exists in old database
        old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not old_cursor.fetchone():
            logger.info("No users table found in old database, skipping user migration")
            old_conn.close()
            return True
        
        # Connect to new user database
        new_conn = sqlite3.connect(new_user_db_path)
        new_cursor = new_conn.cursor()
        
        # Create users table in new database
        new_cursor.execute("""
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
        """)
        
        # Get all users from old database
        old_cursor.execute("SELECT * FROM users")
        users = old_cursor.fetchall()
        
        # Get column names from old database
        old_cursor.execute("PRAGMA table_info(users)")
        old_columns = [col[1] for col in old_cursor.fetchall()]
        
        logger.info(f"Migrating {len(users)} users...")
        
        for user in users:
            user_dict = dict(zip(old_columns, user))
            
            # Map old columns to new columns
            new_values = {
                'id': user_dict.get('id'),
                'username': user_dict.get('username'),
                'password': user_dict.get('password'),
                'email': user_dict.get('email', ''),
                'first_name': user_dict.get('first_name', ''),
                'last_name': user_dict.get('last_name', ''),
                'display_name': user_dict.get('display_name', ''),
                'account_number': user_dict.get('account_number', ''),
                'is_admin': user_dict.get('is_admin', 0),
                'is_active': user_dict.get('is_active', 1),
                'created_at': user_dict.get('created_at'),
                'last_login': user_dict.get('last_login'),
                'two_factor_enabled': user_dict.get('two_factor_enabled', 0),
                'two_factor_secret': user_dict.get('two_factor_secret', '')
            }
            
            # Insert user into new database
            try:
                placeholders = ', '.join(['?' for _ in new_values])
                columns = ', '.join(new_values.keys())
                new_cursor.execute(f"INSERT OR REPLACE INTO users ({columns}) VALUES ({placeholders})", list(new_values.values()))
            except Exception as e:
                logger.error(f"Failed to migrate user {user_dict.get('username', 'unknown')}: {e}")
        
        new_conn.commit()
        new_conn.close()
        old_conn.close()
        
        logger.info("User data migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to migrate user data: {e}")
        return False

def migrate_steam_data(old_db_path, new_steam_db_path):
    """Migrate Steam apps data from old database to new Steam database"""
    try:
        # Connect to old database
        old_conn = sqlite3.connect(old_db_path)
        old_cursor = old_conn.cursor()
        
        # Check if steam_apps table exists in old database
        old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='steam_apps'")
        if not old_cursor.fetchone():
            logger.info("No steam_apps table found in old database, skipping Steam data migration")
            old_conn.close()
            return True
        
        # Connect to new Steam database
        new_conn = sqlite3.connect(new_steam_db_path)
        new_cursor = new_conn.cursor()
        
        # Create steam_apps table in new database
        new_cursor.execute("""
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
        """)
        
        # Get all Steam apps from old database
        old_cursor.execute("SELECT * FROM steam_apps")
        apps = old_cursor.fetchall()
        
        # Get column names from old database
        old_cursor.execute("PRAGMA table_info(steam_apps)")
        old_columns = [col[1] for col in old_cursor.fetchall()]
        
        logger.info(f"Migrating {len(apps)} Steam apps...")
        
        for app in apps:
            app_dict = dict(zip(old_columns, app))
            
            # Map old columns to new columns (they should be the same, but just in case)
            new_values = {
                'appid': app_dict.get('appid'),
                'name': app_dict.get('name'),
                'type': app_dict.get('type', ''),
                'is_server': app_dict.get('is_server', 0),
                'is_dedicated_server': app_dict.get('is_dedicated_server', 0),
                'requires_subscription': app_dict.get('requires_subscription', 0),
                'anonymous_install': app_dict.get('anonymous_install', 1),
                'publisher': app_dict.get('publisher', ''),
                'release_date': app_dict.get('release_date', ''),
                'description': app_dict.get('description', ''),
                'tags': app_dict.get('tags', ''),
                'price': app_dict.get('price', ''),
                'platforms': app_dict.get('platforms', ''),
                'last_updated': app_dict.get('last_updated'),
                'source': app_dict.get('source', 'steamdb')
            }
            
            # Insert app into new database
            try:
                placeholders = ', '.join(['?' for _ in new_values])
                columns = ', '.join(new_values.keys())
                new_cursor.execute(f"INSERT OR REPLACE INTO steam_apps ({columns}) VALUES ({placeholders})", list(new_values.values()))
            except Exception as e:
                logger.error(f"Failed to migrate app {app_dict.get('appid', 'unknown')}: {e}")
        
        new_conn.commit()
        new_conn.close()
        old_conn.close()
        
        logger.info("Steam data migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to migrate Steam data: {e}")
        return False

def main():
    """Main migration function"""
    logger.info("Starting database migration...")
    
    # Get server manager directory
    server_manager_dir = get_server_manager_dir()
    if not server_manager_dir:
        logger.error("Could not determine server manager directory")
        return False
    
    config_dir = os.path.join(server_manager_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    
    # Define database paths
    old_db_path = os.path.join(config_dir, "servermanager.db")
    new_user_db_path = os.path.join(config_dir, "servermanager_users.db")
    new_steam_db_path = os.path.join(config_dir, "steam_ID.db")
    
    # Check if old database exists
    if not os.path.exists(old_db_path):
        logger.info("No existing database found to migrate")
        return True
    
    # Check if migration has already been done
    if os.path.exists(new_user_db_path) and os.path.exists(new_steam_db_path):
        logger.info("Migration appears to have already been completed")
        response = input("Do you want to re-run the migration? This will overwrite existing separated databases. (y/N): ")
        if response.lower() != 'y':
            return True
    
    # Create backup
    logger.info("Creating backup of existing database...")
    if not backup_old_database(old_db_path):
        logger.error("Failed to create backup. Migration aborted for safety.")
        return False
    
    # Migrate user data
    logger.info("Migrating user data...")
    if not migrate_users_data(old_db_path, new_user_db_path):
        logger.error("User data migration failed")
        return False
    
    # Migrate Steam data
    logger.info("Migrating Steam apps data...")
    if not migrate_steam_data(old_db_path, new_steam_db_path):
        logger.error("Steam data migration failed")
        return False
    
    logger.info("Database migration completed successfully!")
    logger.info(f"User database: {new_user_db_path}")
    logger.info(f"Steam database: {new_steam_db_path}")
    logger.info(f"Original database backed up and can be removed after verification")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\nDatabase migration completed successfully!")
            print("The system will now use separate databases for users and Steam apps.")
            print("Please restart Server Manager to use the new database structure.")
        else:
            print("\nDatabase migration failed. Please check the logs for details.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nMigration cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
