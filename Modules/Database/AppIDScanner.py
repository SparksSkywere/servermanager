# SteamDB AppID Scanner, used to scan for AppIDs from SteamDB and SteamDB.info
# It is then placed into the database for later use
import os
import sys
import logging
import requests
import json
import time
import re
import sqlite3
import shutil
from datetime import datetime, timezone
import argparse

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import database connection
try:
    from Modules.Database.steam_database import get_steam_engine, initialize_steam_database
    from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("Warning: SQLAlchemy not available, falling back to SQLite")

# Centralized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("AppIDScanner")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("AppIDScanner")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("AppIDScanner debug mode enabled via environment")

# Database models
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()
    
    class SteamApp(Base):
        __tablename__ = 'steam_apps'
        
        appid = Column(Integer, primary_key=True)
        name = Column(String(255), nullable=False)
        type = Column(String(50))
        is_server = Column(Boolean, default=False)
        is_dedicated_server = Column(Boolean, default=False)
        requires_subscription = Column(Boolean, default=False)  # Whether the server requires a paid subscription
        anonymous_install = Column(Boolean, default=True)  # Whether the server can be installed anonymously
        publisher = Column(String(255))
        release_date = Column(String(50))
        description = Column(Text)
        tags = Column(Text)  # JSON string of tags
        price = Column(String(20))
        platforms = Column(String(100))  # JSON string of supported platforms
        last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))
        source = Column(String(50), default='steamdb')

class AppIDScanner:
    def __init__(self, use_database=True, debug_mode=False, migrate_json=True):
        self.use_database = use_database and SQLALCHEMY_AVAILABLE
        self.debug_mode = debug_mode
        self.migrate_json = migrate_json  # Whether to migrate existing JSON data to database
        self.session_requests = requests.Session()
        self.session_requests.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Rate limiting - More conservative settings for Steam API
        self.request_delay = 2.0  # Increased from 1.0 to 2.0 seconds
        self.api_request_delay = 3.0  # Specific delay for Steam Store API calls
        self.last_request_time = 0
        self.last_api_request_time = 0
        self.rate_limit_backoff = 5.0  # Initial backoff for rate limit errors
        self.max_rate_limit_backoff = 60.0  # Maximum backoff time
        
        # Enhanced server-related keywords for better filtering (more restrictive)
        self.server_keywords = [
            'dedicated server', 'srcds', 'game server', 'hlds',
            'multiplayer server', 'server tool', 'server files', 'server software'
        ]
        
        # More specific dedicated server keywords
        self.dedicated_keywords = [
            'dedicated server', 'dedicated', 'srcds', 'hlds', 'game server tool',
            'server tool', 'server files', 'server software'
        ]
        
        # Initialize database
        if self.use_database:
            self.init_database()
        else:
            self.init_sqlite_fallback()
    
    def init_database(self):
        """Initialize SQLAlchemy database connection using Steam database engine"""
        try:
            self.engine = get_steam_engine()
            Base.metadata.create_all(self.engine)
            Session = sessionmaker(bind=self.engine)
            self.db_session = Session()
            logger.info("Connected to Steam apps database")
            
            # Run database migration if needed
            self.migrate_database_schema()
        except Exception as e:
            logger.error(f"Failed to connect to Steam apps database: {e}")
            logger.info("Falling back to SQLite")
            self.use_database = False
            self.init_sqlite_fallback()
    
    def migrate_database_schema(self):
        """Migrate existing database schema to new version with subscription fields"""
        try:
            if self.use_database:
                # Check if migration is needed by looking for the new columns
                from sqlalchemy import text
                
                # Check if the new columns exist
                result = self.db_session.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'steam_apps' AND column_name IN ('requires_subscription', 'anonymous_install')
                """))
                
                existing_columns = [row[0] for row in result]
                
                if 'requires_subscription' not in existing_columns:
                    logger.info("Migrating database: Adding requires_subscription column")
                    self.db_session.execute(text("ALTER TABLE steam_apps ADD COLUMN requires_subscription BOOLEAN DEFAULT FALSE"))
                
                if 'anonymous_install' not in existing_columns:
                    logger.info("Migrating database: Adding anonymous_install column") 
                    self.db_session.execute(text("ALTER TABLE steam_apps ADD COLUMN anonymous_install BOOLEAN DEFAULT TRUE"))
                
                # Check if developer column exists and drop it
                dev_result = self.db_session.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'steam_apps' AND column_name = 'developer'
                """))
                
                if list(dev_result):
                    logger.info("Migrating database: Developer column found (keeping for compatibility)")
                    # Note: Some databases don't support dropping columns easily, so we'll leave it for now
                    # self.db_session.execute(text("ALTER TABLE steam_apps DROP COLUMN developer"))
                
                self.db_session.commit()
                logger.info("Database schema migration completed")
                
            else:
                # SQLite migration  
                cursor = self.sqlite_conn.execute("PRAGMA table_info(steam_apps)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'requires_subscription' not in columns:
                    logger.info("Migrating SQLite: Adding requires_subscription column")
                    self.sqlite_conn.execute("ALTER TABLE steam_apps ADD COLUMN requires_subscription BOOLEAN DEFAULT 0")
                
                if 'anonymous_install' not in columns:
                    logger.info("Migrating SQLite: Adding anonymous_install column")
                    self.sqlite_conn.execute("ALTER TABLE steam_apps ADD COLUMN anonymous_install BOOLEAN DEFAULT 1")
                
                self.sqlite_conn.commit()
                logger.info("SQLite schema migration completed")
                
        except Exception as e:
            logger.warning(f"Database migration failed (this may be normal for new installations): {e}")
    
    def init_sqlite_fallback(self):
        """Initialize SQLite fallback database"""
        try:
            # Create db directory if it doesn't exist - using centralized db directory
            db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'db')
            os.makedirs(db_dir, exist_ok=True)
            
            db_path = os.path.join(db_dir, 'steam_ID.db')
            self.sqlite_conn = sqlite3.connect(db_path)
            self.sqlite_conn.execute('''
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
            ''')
            self.sqlite_conn.commit()
            logger.info(f"Connected to SQLite database: {db_path}")
            
            # Run database migration if needed
            self.migrate_database_schema()
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            raise
    
    def migrate_json_to_database(self):
        """Migrate existing JSON data to database if it doesn't exist in DB yet"""
        try:
            logger.info("Checking for JSON data to migrate to database...")
            
            # Load JSON data
            json_data = self.load_appid_json()
            dedicated_servers = json_data.get('dedicated_servers', [])
            
            if not dedicated_servers:
                logger.info("No JSON data found to migrate")
                return
            
            migrated_count = 0
            skipped_count = 0
            
            for server in dedicated_servers:
                appid = server.get('appid')
                if not appid:
                    continue
                
                # Check if this app already exists in database
                exists = False
                if self.use_database:
                    exists = self.db_session.query(SteamApp).filter(SteamApp.appid == appid).first() is not None
                else:
                    cursor = self.sqlite_conn.execute("SELECT 1 FROM steam_apps WHERE appid = ?", (appid,))
                    exists = cursor.fetchone() is not None
                
                if not exists:
                    # Convert JSON entry to database format
                    app_data = {
                        'appid': appid,
                        'name': server.get('name', ''),
                        'type': server.get('type', 'Dedicated Server'),
                        'is_server': True,
                        'is_dedicated_server': True,
                        'requires_subscription': False,  # Default for migrated data
                        'anonymous_install': True,  # Default for migrated data
                        'publisher': server.get('publisher', ''),
                        'release_date': server.get('release_date', ''),
                        'description': server.get('description', ''),
                        'tags': server.get('tags', '[]'),
                        'price': '',
                        'platforms': server.get('platforms', ''),
                        'source': server.get('source', 'json_migration')
                    }
                    
                    # Save to database
                    self.save_app_to_database(app_data)
                    migrated_count += 1
                else:
                    skipped_count += 1
            
            logger.info(f"Migration complete: {migrated_count} apps migrated, {skipped_count} already existed")
            
            # Optionally create a backup of the JSON file
            if migrated_count > 0:
                logger.info(f"Migration complete: {migrated_count} apps would have been migrated from JSON (feature disabled)")
                    
        except Exception as e:
            logger.error(f"Error during JSON to database migration: {e}")
    
    def get_dedicated_servers_from_database(self):
        """Get all dedicated servers from database (replaces JSON functionality)"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                apps = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).all()
                
                servers = []
                for app in apps:
                    server_entry = {
                        "appid": app.appid,
                        "name": app.name,
                        "type": app.type or "Dedicated Server",
                        "requires_subscription": getattr(app, 'requires_subscription', False),
                        "anonymous_install": getattr(app, 'anonymous_install', True),
                        "publisher": app.publisher or "",
                        "release_date": app.release_date or "",
                        "description": app.description or "",
                        "platforms": app.platforms or "",
                        "source": app.source or "steam_api",
                        "tags": app.tags or "[]"
                    }
                    servers.append(server_entry)
                    
                return sorted(servers, key=lambda x: x['name'])
                
            else:
                # Use SQLite
                cursor = self.sqlite_conn.execute("""
                    SELECT appid, name, type, requires_subscription, anonymous_install, publisher, release_date, 
                           description, platforms, source, tags
                    FROM steam_apps 
                    WHERE is_dedicated_server = 1
                    ORDER BY name
                """)
                
                servers = []
                for row in cursor.fetchall():
                    server_entry = {
                        "appid": row[0],
                        "name": row[1],
                        "type": row[2] or "Dedicated Server",
                        "requires_subscription": bool(row[3]) if row[3] is not None else False,
                        "anonymous_install": bool(row[4]) if row[4] is not None else True,
                        "publisher": row[5] or "",
                        "release_date": row[6] or "",
                        "description": row[7] or "",
                        "platforms": row[8] or "",
                        "source": row[9] or "steam_api",
                        "tags": row[10] or "[]"
                    }
                    servers.append(server_entry)
                    
                return servers
                
        except Exception as e:
            logger.error(f"Error getting dedicated servers from database: {e}")
            return []
    
    def add_server_to_json(self, server_data):
        """Add a single dedicated server to the JSON file (live update)"""
        try:
            # Load existing data
            appid_data = self.load_appid_json()
            
            # Check if server already exists
            existing_appids = {server['appid'] for server in appid_data['dedicated_servers']}
            
            if server_data['appid'] not in existing_appids:
                # Add new server
                appid_data['dedicated_servers'].append(server_data)
                
                # Sort by name
                appid_data['dedicated_servers'].sort(key=lambda x: x['name'])
                
                # Save with pre-check (but force since we know there's a change)
                if self.save_appid_json(appid_data, force_update=True):
                    logger.info(f"Added new dedicated server to JSON: {server_data['name']} (AppID: {server_data['appid']})")
                    return True
            else:
                # Update existing server if data differs
                for i, existing_server in enumerate(appid_data['dedicated_servers']):
                    if existing_server['appid'] == server_data['appid']:
                        if existing_server != server_data:
                            appid_data['dedicated_servers'][i] = server_data
                            
                            # Sort by name
                            appid_data['dedicated_servers'].sort(key=lambda x: x['name'])
                            
                            if self.save_appid_json(appid_data, force_update=True):
                                logger.info(f"Updated dedicated server in JSON: {server_data['name']} (AppID: {server_data['appid']})")
                                return True
                        else:
                            logger.debug(f"Server data unchanged: {server_data['name']} (AppID: {server_data['appid']})")
                        break
            
            return False
            
        except Exception as e:
            logger.error(f"Error adding server to JSON: {e}")
            return False
    
    def get_json_appid_list(self):
        """Get the current list of AppIDs from the JSON file for external use"""
        try:
            appid_data = self.load_appid_json()
            return appid_data.get('dedicated_servers', [])
        except Exception as e:
            logger.error(f"Error loading AppID list: {e}")
            return []

    def load_appid_json(self):
        """JSON functionality disabled - use database instead"""
        logger.warning("JSON functionality has been disabled. Use database methods instead.")
        return {
            "metadata": {
                "last_updated": "",
                "total_dedicated_servers": 0,
                "source": "database_only",
                "version": "3.0",
                "filter_mode": "dedicated_only"
            },
            "dedicated_servers": []
        }
    
    def save_appid_json(self, appid_data, force_update=False):
        """JSON functionality disabled - use database instead"""
        logger.warning("JSON save functionality has been disabled. Use database methods instead.")
        return False
    
    def export_database_to_json(self):
        """JSON export functionality disabled - use database methods instead"""
        logger.info("Exporting database data to JSON file (dedicated servers only)...")
        
        try:
            appid_data = self.load_appid_json()
            
            # Clear existing data
            appid_data["dedicated_servers"] = []
            
            if self.use_database:
                # Export from SQLAlchemy database (dedicated servers only)
                apps = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).all()
                
                for app in apps:
                    server_entry = {
                        "appid": app.appid,
                        "name": app.name,
                        "type": app.type or "Dedicated Server",
                        "requires_subscription": getattr(app, 'requires_subscription', False),
                        "anonymous_install": getattr(app, 'anonymous_install', True),
                        "publisher": app.publisher or "",
                        "release_date": app.release_date or "",
                        "description": app.description or "",
                        "platforms": app.platforms or "",
                        "source": app.source or "steam_api",
                        "tags": app.tags or "[]"
                    }
                    
                    appid_data["dedicated_servers"].append(server_entry)
                    
            else:
                # Export from SQLite database (dedicated servers only)
                cursor = self.sqlite_conn.execute("""
                    SELECT appid, name, type, requires_subscription, anonymous_install, publisher, release_date, 
                           description, platforms, source, tags
                    FROM steam_apps 
                    WHERE is_dedicated_server = 1
                """)
                
                for row in cursor.fetchall():
                    server_entry = {
                        "appid": row[0],
                        "name": row[1],
                        "type": row[2] or "Dedicated Server",
                        "requires_subscription": bool(row[3]) if row[3] is not None else False,
                        "anonymous_install": bool(row[4]) if row[4] is not None else True,
                        "publisher": row[5] or "",
                        "release_date": row[6] or "",
                        "description": row[7] or "",
                        "platforms": row[8] or "",
                        "source": row[9] or "steam_api",
                        "tags": row[10] or "[]"
                    }
                    
                    appid_data["dedicated_servers"].append(server_entry)
            
            # Sort list by name for better organization
            appid_data["dedicated_servers"].sort(key=lambda x: x["name"])
            
            # Save to JSON file
            self.save_appid_json(appid_data)
            
            logger.info("Database export to JSON completed successfully (dedicated servers only)")
            
        except Exception as e:
            logger.error(f"Error exporting database to JSON: {e}")
    
    def rate_limit(self, is_api_call=False):
        """Implement rate limiting to avoid being blocked"""
        current_time = time.time()
        
        if is_api_call:
            # Use more conservative timing for API calls
            time_since_last = current_time - self.last_api_request_time
            delay = self.api_request_delay
            if time_since_last < delay:
                sleep_time = delay - time_since_last
                logger.debug(f"API rate limiting: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
            self.last_api_request_time = time.time()
        else:
            # Regular rate limiting for other requests
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.request_delay:
                sleep_time = self.request_delay - time_since_last
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
            self.last_request_time = time.time()
    
    def make_request(self, url, params=None, retries=3, is_api_call=False):
        """Make a web request with rate limiting and retry logic"""
        self.rate_limit(is_api_call=is_api_call)
        
        current_backoff = self.rate_limit_backoff
        
        for attempt in range(retries):
            try:
                response = self.session_requests.get(url, params=params, timeout=30)
                
                # Handle rate limiting specifically
                if response.status_code == 429:
                    logger.warning(f"Rate limit hit (attempt {attempt + 1}/{retries}). Backing off for {current_backoff:.1f} seconds")
                    time.sleep(current_backoff)
                    
                    # Exponential backoff for rate limits, but cap it
                    current_backoff = min(current_backoff * 2, self.max_rate_limit_backoff)
                    
                    if attempt < retries - 1:
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {retries} attempts for URL: {url}")
                        return None
                
                response.raise_for_status()
                
                # Reset backoff on successful request
                current_backoff = self.rate_limit_backoff
                return response
                
            except requests.RequestException as e:
                if "429" in str(e):
                    # Handle 429 errors that weren't caught by status code check
                    logger.warning(f"Rate limit error (attempt {attempt + 1}/{retries}): {e}")
                    time.sleep(current_backoff)
                    current_backoff = min(current_backoff * 2, self.max_rate_limit_backoff)
                else:
                    logger.warning(f"Request failed (attempt {attempt + 1}/{retries}): {e}")
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff for other errors
                    else:
                        logger.error(f"Request failed after {retries} attempts: {e}")
                        return None
        
        return None
    
    def get_steam_api_applist(self):
        """Get the complete app list from Steam API"""
        logger.info("Fetching Steam app list from API...")
        
        try:
            url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
            response = self.make_request(url, is_api_call=False)  # This API is more lenient
            
            if response is None:
                logger.error("Failed to fetch Steam app list due to request failure")
                return []
            
            data = response.json()
            apps = data.get('applist', {}).get('apps', [])
            logger.info(f"Retrieved {len(apps)} apps from Steam API")
            return apps
        except Exception as e:
            logger.error(f"Failed to fetch Steam app list: {e}")
            return []
    
    def get_app_details_steam_api(self, appid):
        """Get detailed app information from Steam Store API"""
        try:
            url = "https://store.steampowered.com/api/appdetails"
            params = {'appids': appid, 'format': 'json'}
            
            response = self.make_request(url, params, is_api_call=True)  # Use stricter rate limiting
            
            if response is None:
                logger.debug(f"Failed to get details for AppID {appid}: Request failed")
                return None
            
            data = response.json()
            app_data = data.get(str(appid), {})
            if app_data.get('success') and 'data' in app_data:
                return app_data['data']
            return None
        except Exception as e:
            logger.debug(f"Failed to get details for AppID {appid}: {e}")
            return None
    
    def determine_subscription_requirements(self, app_details, appid):
        """
        Determine if a server requires a subscription and supports anonymous install
        
        Returns:
            tuple: (requires_subscription, anonymous_install)
        """
        requires_subscription = False
        anonymous_install = True  # Default to anonymous install support
        
        if app_details:
            # Check if the app has a price (indicating it requires purchase)
            price_overview = app_details.get('price_overview', {})
            if price_overview and price_overview.get('initial_formatted') not in ['', 'Free']:
                requires_subscription = True
                anonymous_install = False  # Paid apps typically require authentication
            
            # Check if the app type indicates it's a tool (most dedicated servers are tools and free)
            app_type = app_details.get('type', '').lower()
            if app_type == 'tool':
                requires_subscription = False
                anonymous_install = True
            
            # Check for specific subscription indicators in the description
            description = (app_details.get('short_description', '') + ' ' + 
                         app_details.get('detailed_description', '')).lower()
            
            subscription_keywords = [
                'requires game', 'requires purchase', 'requires ownership',
                'must own', 'need to own', 'purchase required'
            ]
            
            for keyword in subscription_keywords:
                if keyword in description:
                    requires_subscription = True
                    anonymous_install = False
                    break
            
            # Check if it's marked as free-to-play (usually supports anonymous)
            if app_details.get('is_free', False):
                requires_subscription = False
                anonymous_install = True
        
        # Additional logic based on known patterns for common server AppIDs
        # Many dedicated servers are free tools that support anonymous install
        well_known_free_servers = {
            # Counter-Strike servers
            90: {'requires_subscription': False, 'anonymous_install': True},   # Counter-Strike Dedicated Server
            232330: {'requires_subscription': False, 'anonymous_install': True},  # Counter-Strike: Global Offensive - Dedicated Server
            
            # Left 4 Dead servers  
            222860: {'requires_subscription': False, 'anonymous_install': True},  # Left 4 Dead 2 Dedicated Server
            
            # Team Fortress servers
            232250: {'requires_subscription': False, 'anonymous_install': True},  # Team Fortress 2 Dedicated Server
            
            # Garry's Mod servers
            4020: {'requires_subscription': False, 'anonymous_install': True},   # Garry's Mod Dedicated Server
            
            # Source Engine servers
            205: {'requires_subscription': False, 'anonymous_install': True},    # Source Dedicated Server
        }
        
        if appid in well_known_free_servers:
            server_info = well_known_free_servers[appid]
            requires_subscription = server_info['requires_subscription']
            anonymous_install = server_info['anonymous_install']
        
        return requires_subscription, anonymous_install

    def save_app_to_database(self, app_data):
        """Save app data to database"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                existing_app = self.db_session.query(SteamApp).filter_by(appid=app_data['appid']).first()
                
                if existing_app:
                    # Update existing record
                    for key, value in app_data.items():
                        if key != 'appid':
                            setattr(existing_app, key, value)
                    setattr(existing_app, 'last_updated', datetime.now(timezone.utc))
                else:
                    # Create new record
                    new_app = SteamApp(**app_data)
                    self.db_session.add(new_app)
                
                self.db_session.commit()
            else:
                # Use SQLite
                placeholders = ', '.join(['?' for _ in app_data])
                columns = ', '.join(app_data.keys())
                
                # Check if app exists
                cursor = self.sqlite_conn.execute(
                    "SELECT appid FROM steam_apps WHERE appid = ?", 
                    (app_data['appid'],)
                )
                
                if cursor.fetchone():
                    # Update existing record
                    set_clause = ', '.join([f"{key} = ?" for key in app_data.keys() if key != 'appid'])
                    values = [app_data[key] for key in app_data.keys() if key != 'appid']
                    values.append(app_data['appid'])
                    
                    self.sqlite_conn.execute(
                        f"UPDATE steam_apps SET {set_clause}, last_updated = CURRENT_TIMESTAMP WHERE appid = ?",
                        values
                    )
                else:
                    # Insert new record
                    self.sqlite_conn.execute(
                        f"INSERT INTO steam_apps ({columns}) VALUES ({placeholders})",
                        list(app_data.values())
                    )
                
                self.sqlite_conn.commit()
                
        except Exception as e:
            logger.error(f"Failed to save app {app_data.get('appid', 'unknown')} to database: {e}")
            if self.use_database:
                self.db_session.rollback()
            else:
                # For SQLite, we need to rollback the transaction as well
                self.sqlite_conn.rollback()

    def is_server_application(self, app_name, app_details=None):
        """Determine if an application is a server/dedicated server with enhanced detection and DLC exclusion"""
        if not app_name:
            return False, False
        
        app_name_lower = app_name.lower()
        
        # Exclude DLC and non-server content
        dlc_keywords = [
            'dlc', 'downloadable content', 'expansion pack', 'content pack',
            'season pass', 'soundtrack', 'music', 'wallpaper', 'theme',
            'skin pack', 'character pack', 'weapon pack', 'map pack',
            'cosmetic', 'avatar', 'demo', 'beta', 'test', 'trailer'
        ]
        
        # Check if it's DLC or other non-server content
        for dlc_keyword in dlc_keywords:
            if dlc_keyword in app_name_lower:
                return False, False
        
        # Check app details type for DLC
        if app_details:
            app_type = app_details.get('type', '').lower()
            if app_type in ['dlc', 'music', 'video', 'demo', 'advertising']:
                return False, False
            
            # Check if it's marked as DLC in the data
            if app_details.get('is_dlc', False):
                return False, False
        
        # Check for explicit dedicated server keywords first
        is_dedicated = any(keyword in app_name_lower for keyword in self.dedicated_keywords)
        
        # Check for general server keywords
        is_server = is_dedicated or any(keyword in app_name_lower for keyword in self.server_keywords)
        
        # Enhanced detection patterns for dedicated servers only
        dedicated_patterns = [
            r'dedicated\s+server',
            r'server\s+(?:tool|files|software)',
            r'srcds',
            r'hlds',
            r'\bds\b',
            r'game\s+server'
        ]
        
        # More restrictive server patterns - focus on actual server applications
        server_patterns = [
            r'dedicated\s+server',
            r'server\s+(?:tool|files|software)',
            r'srcds',
            r'hlds',
            r'game\s+server',
            r'multiplayer\s+server'
        ]
        
        # Pattern matching for dedicated servers
        for pattern in dedicated_patterns:
            if re.search(pattern, app_name_lower):
                is_dedicated = True
                is_server = True
                break
        
        # Pattern matching for general servers (if not already dedicated)
        if not is_dedicated:
            for pattern in server_patterns:
                if re.search(pattern, app_name_lower):
                    is_server = True
                    # For these patterns, also mark as dedicated since they're likely actual servers
                    if any(keyword in pattern for keyword in ['dedicated', 'srcds', 'hlds', 'game server']):
                        is_dedicated = True
                    break
        
        # Additional checks using app details
        if app_details:
            app_type = app_details.get('type', '').lower()
            
            # Only consider 'tool' or 'game' types for servers
            if app_type in ['tool', 'game']:
                # Check categories for server-specific content
                categories = app_details.get('categories', [])
                for category in categories:
                    if isinstance(category, dict):
                        desc = category.get('description', '').lower()
                        if any(keyword in desc for keyword in ['dedicated server', 'multiplayer server']):
                            is_server = True
                            is_dedicated = True
                
                # Check genres for server-related content (be more restrictive)
                genres = app_details.get('genres', [])
                for genre in genres:
                    if isinstance(genre, dict):
                        desc = genre.get('description', '').lower()
                        if 'server' in desc and 'dedicated' in desc:
                            is_server = True
                            is_dedicated = True
        
        # Additional validation: must contain "server" to be considered a server
        if is_server and 'server' not in app_name_lower:
            # Double-check with more specific patterns
            if not any(re.search(pattern, app_name_lower) for pattern in [r'srcds', r'hlds', r'\bds\b']):
                is_server = False
                is_dedicated = False
        
        return is_server, is_dedicated
    
    def scan_steam_apps(self, limit=None, dedicated_only=True):
        """Scan Steam applications and save only dedicated server apps to database"""
        logger.info("Starting Steam app scan (saving only dedicated servers to database)...")
        logger.info(f"Rate limiting: {self.request_delay}s general, {self.api_request_delay}s API calls")
        
        # Get app list from Steam API
        apps = self.get_steam_api_applist()
        if not apps:
            logger.error("Failed to retrieve app list")
            return
        
        # Apply limit if specified
        if limit:
            apps = apps[:limit]
            logger.info(f"Limited scan to {limit} apps")
        
        processed = 0
        saved_count = 0
        dedicated_count = 0
        skipped_count = 0
        
        for app in apps:
            try:
                appid = app.get('appid')
                name = app.get('name', '').strip()
                
                if not appid or not name:
                    continue
                
                processed += 1
                
                # Add a progress indicator with timing estimates
                if processed % 50 == 0:
                    logger.info(f"Processed {processed}/{len(apps)} apps ({processed/len(apps)*100:.1f}%), "
                              f"saved {saved_count} dedicated servers, skipped {skipped_count} non-servers")
                
                # Get detailed information with improved error handling
                app_details = self.get_app_details_steam_api(appid)
                
                # Determine if it's a server application
                is_server, is_dedicated = self.is_server_application(name, app_details)
                
                # Only save dedicated servers to reduce database clutter
                if dedicated_only and not is_dedicated:
                    skipped_count += 1
                    continue
                elif not dedicated_only and not is_server:
                    skipped_count += 1
                    continue
                
                # Determine subscription requirements
                requires_subscription, anonymous_install = self.determine_subscription_requirements(app_details, appid)
                
                # Prepare app data for database (only dedicated servers)
                app_data = {
                    'appid': appid,
                    'name': name,
                    'type': app_details.get('type', 'Unknown') if app_details else 'Unknown',
                    'is_server': is_server,
                    'is_dedicated_server': is_dedicated,
                    'requires_subscription': requires_subscription,
                    'anonymous_install': anonymous_install,
                    'source': 'steam_api'
                }
                
                # Add additional details if available
                if app_details:
                    app_data.update({
                        'publisher': ', '.join(app_details.get('publishers', [])),
                        'release_date': app_details.get('release_date', {}).get('date', ''),
                        'description': app_details.get('short_description', ''),
                        'tags': json.dumps([cat.get('description') for cat in app_details.get('categories', [])]),
                        'price': str(app_details.get('price_overview', {}).get('final_formatted', '')),
                        'platforms': json.dumps(app_details.get('platforms', {}))
                    })
                
                # Save to database (only dedicated servers)
                self.save_app_to_database(app_data)
                saved_count += 1
                
                if is_dedicated:
                    dedicated_count += 1
                
                if processed % 100 == 0:
                    logger.info(f"Processed {processed} apps, saved {saved_count} dedicated servers")
                
            except Exception as e:
                logger.error(f"Error processing app {app.get('appid', 'unknown')}: {e}")
                continue
        
        # Final logging and summary
        logger.info(f"Scan complete! Processed {processed} apps, saved {saved_count} dedicated servers to database")
        logger.info(f"Skipped {skipped_count} non-dedicated server applications")
        logger.info("Only dedicated server applications are stored in the database")
    
    def search_apps(self, query, server_only=False):
        """Search for apps in the database"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                query_obj = self.db_session.query(SteamApp).filter(
                    SteamApp.name.ilike(f'%{query}%')
                )
                if server_only:
                    query_obj = query_obj.filter(SteamApp.is_server == True)
                
                results = query_obj.all()
                return [(app.appid, app.name, bool(app.is_server), bool(app.is_dedicated_server)) for app in results]
            else:
                # Use SQLite
                sql = "SELECT appid, name, is_server, is_dedicated_server FROM steam_apps WHERE name LIKE ?"
                params = [f'%{query}%']
                
                if server_only:
                    sql += " AND is_server = 1"
                
                cursor = self.sqlite_conn.execute(sql, params)
                return cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Error searching apps: {e}")
            return []
    
    def get_server_apps(self, dedicated_only=False):
        """Get all server applications from the database"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                query_obj = self.db_session.query(SteamApp)
                if dedicated_only:
                    query_obj = query_obj.filter(SteamApp.is_dedicated_server == True)
                else:
                    query_obj = query_obj.filter(SteamApp.is_server == True)
                
                results = query_obj.all()
                return [(app.appid, app.name, bool(app.is_dedicated_server)) for app in results]
            else:
                # Use SQLite
                if dedicated_only:
                    sql = "SELECT appid, name, is_dedicated_server FROM steam_apps WHERE is_dedicated_server = 1"
                else:
                    sql = "SELECT appid, name, is_dedicated_server FROM steam_apps WHERE is_server = 1"
                
                cursor = self.sqlite_conn.execute(sql)
                return cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Error getting server apps: {e}")
            return []
    
    def get_servers_by_subscription_type(self, requires_subscription=None, anonymous_install=None):
        """Get servers filtered by subscription requirements
        
        Args:
            requires_subscription (bool, optional): Filter by subscription requirement
            anonymous_install (bool, optional): Filter by anonymous install capability
            
        Returns:
            list: List of (appid, name, requires_subscription, anonymous_install) tuples
        """
        try:
            if self.use_database:
                # Use SQLAlchemy
                query_obj = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True)
                
                if requires_subscription is not None:
                    query_obj = query_obj.filter(SteamApp.requires_subscription == requires_subscription)
                
                if anonymous_install is not None:
                    query_obj = query_obj.filter(SteamApp.anonymous_install == anonymous_install)
                
                results = query_obj.all()
                return [(app.appid, app.name, bool(app.requires_subscription), bool(app.anonymous_install)) for app in results]
            else:
                # Use SQLite
                sql = "SELECT appid, name, requires_subscription, anonymous_install FROM steam_apps WHERE is_dedicated_server = 1"
                params = []
                
                if requires_subscription is not None:
                    sql += " AND requires_subscription = ?"
                    params.append(int(requires_subscription))
                
                if anonymous_install is not None:
                    sql += " AND anonymous_install = ?"
                    params.append(int(anonymous_install))
                
                cursor = self.sqlite_conn.execute(sql, params)
                return cursor.fetchall()
                
        except Exception as e:
            logger.error(f"Error getting servers by subscription type: {e}")
            return []
    
    def get_free_anonymous_servers(self):
        """Get all servers that are free and support anonymous installation"""
        return self.get_servers_by_subscription_type(requires_subscription=False, anonymous_install=True)
    
    def get_subscription_servers(self):
        """Get all servers that require a subscription or purchase"""
        return self.get_servers_by_subscription_type(requires_subscription=True)

    def get_database_stats(self):
        """Get statistics about the database including subscription information"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                total_apps = self.db_session.query(SteamApp).count()
                server_apps = self.db_session.query(SteamApp).filter(SteamApp.is_server == True).count()
                dedicated_apps = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).count()
                subscription_required = self.db_session.query(SteamApp).filter(
                    SteamApp.is_dedicated_server == True,
                    SteamApp.requires_subscription == True
                ).count()
                anonymous_install = self.db_session.query(SteamApp).filter(
                    SteamApp.is_dedicated_server == True,
                    SteamApp.anonymous_install == True
                ).count()
            else:
                # Use SQLite
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps")
                total_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_server = 1")
                server_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = 1")
                dedicated_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("""
                    SELECT COUNT(*) FROM steam_apps 
                    WHERE is_dedicated_server = 1 AND requires_subscription = 1
                """)
                subscription_required = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("""
                    SELECT COUNT(*) FROM steam_apps 
                    WHERE is_dedicated_server = 1 AND anonymous_install = 1
                """)
                anonymous_install = cursor.fetchone()[0]
            
            return {
                'total_apps': total_apps,
                'server_apps': server_apps,
                'dedicated_server_apps': dedicated_apps,
                'subscription_required_servers': subscription_required,
                'anonymous_install_servers': anonymous_install
            }
            
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {
                'total_apps': 0, 
                'server_apps': 0, 
                'dedicated_server_apps': 0,
                'subscription_required_servers': 0,
                'anonymous_install_servers': 0
            }
    
    def close(self):
        """Close database connections"""
        try:
            if self.use_database and hasattr(self, 'db_session'):
                self.db_session.close()
            if hasattr(self, 'sqlite_conn'):
                self.sqlite_conn.close()
        except Exception as e:
            logger.error(f"Error closing database connections: {e}")

def main():
    parser = argparse.ArgumentParser(description='Steam AppID Scanner')
    parser.add_argument('--limit', type=int, help='Limit number of apps to scan')
    parser.add_argument('--include-all', action='store_true', help='Include all server types, not just dedicated servers')
    parser.add_argument('--search', type=str, help='Search for apps by name')
    parser.add_argument('--list-servers', action='store_true', help='List all server applications')
    parser.add_argument('--dedicated-only', action='store_true', help='Show only dedicated servers (use with --list-servers)')
    parser.add_argument('--list-free', action='store_true', help='List servers that are free and support anonymous install')
    parser.add_argument('--list-subscription', action='store_true', help='List servers that require a subscription')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--no-database', action='store_true', help='Use SQLite fallback instead of main database')
    parser.add_argument('--export-json', action='store_true', help='Export existing database data to JSON file')
    parser.add_argument('--fast-mode', action='store_true', help='Use faster rate limiting (may trigger rate limits)')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create scanner instance
    scanner = AppIDScanner(use_database=not args.no_database, debug_mode=args.debug)
    
    # Adjust rate limiting based on fast mode
    if args.fast_mode:
        scanner.request_delay = 1.0
        scanner.api_request_delay = 1.5
        logger.info("Fast mode enabled - using aggressive rate limiting (may trigger rate limits)")
    
    try:
        if args.export_json:
            # Export existing database to JSON
            scanner.export_database_to_json()
        
        elif args.search:
            # Search for apps
            results = scanner.search_apps(args.search, server_only=not args.include_all)
            print(f"\nSearch results for '{args.search}':")
            print("-" * 80)
            for appid, name, is_server, is_dedicated in results:
                server_type = "Dedicated Server" if is_dedicated else ("Server" if is_server else "Game")
                print(f"{appid:>8} | {server_type:>15} | {name}")
        
        elif args.list_servers:
            # List server applications
            results = scanner.get_server_apps(dedicated_only=args.dedicated_only)
            server_type = "Dedicated Servers" if args.dedicated_only else "Server Applications"
            print(f"\n{server_type}:")
            print("-" * 80)
            for appid, name, is_dedicated in results:
                marker = "[Dedicated]" if is_dedicated else "[Server]"
                print(f"{appid:>8} | {marker:>12} | {name}")
        
        elif args.list_free:
            # List free servers that support anonymous install
            results = scanner.get_free_anonymous_servers()
            print(f"\nFree Servers (Anonymous Install Supported):")
            print("-" * 80)
            for appid, name, requires_sub, anonymous in results:
                print(f"{appid:>8} | {'[Free/Anonymous]':>17} | {name}")
        
        elif args.list_subscription:
            # List servers that require subscription
            results = scanner.get_subscription_servers()
            print(f"\nSubscription Required Servers:")
            print("-" * 80)
            for appid, name, requires_sub, anonymous in results:
                install_type = "[Auth Required]" if not anonymous else "[Subscription]"
                print(f"{appid:>8} | {install_type:>17} | {name}")
        
        elif args.stats:
            # Show database statistics
            stats = scanner.get_database_stats()
            print("\nDatabase Statistics:")
            print("-" * 50)
            print(f"Total Applications: {stats['total_apps']:,}")
            print(f"Server Applications: {stats['server_apps']:,}")
            print(f"Dedicated Servers: {stats['dedicated_server_apps']:,}")
            print(f"├─ Subscription Required: {stats['subscription_required_servers']:,}")
            print(f"└─ Anonymous Install: {stats['anonymous_install_servers']:,}")
        
        else:
            # Perform scan - now defaults to dedicated_only=True
            dedicated_only = not args.include_all  # If include_all is specified, don't restrict to dedicated only
            scanner.scan_steam_apps(limit=args.limit, dedicated_only=dedicated_only)
            
            # Show final statistics
            stats = scanner.get_database_stats()
            print(f"\nFinal Database Statistics:")
            print("-" * 50)
            print(f"Total Applications: {stats['total_apps']:,}")
            print(f"Server Applications: {stats['server_apps']:,}")
            print(f"Dedicated Servers: {stats['dedicated_server_apps']:,}")
            print(f"├─ Subscription Required: {stats['subscription_required_servers']:,}")
            print(f"└─ Anonymous Install: {stats['anonymous_install_servers']:,}")
    
    finally:
        scanner.close()

if __name__ == "__main__":
    main()