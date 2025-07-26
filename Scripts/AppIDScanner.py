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
from datetime import datetime, UTC
import argparse

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import database connection
try:
    from Modules.SQL_Connection import get_engine
    from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("Warning: SQLAlchemy not available, falling back to SQLite")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("AppIDScanner")

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
        developer = Column(String(255))
        publisher = Column(String(255))
        release_date = Column(String(50))
        description = Column(Text)
        tags = Column(Text)  # JSON string of tags
        price = Column(String(20))
        platforms = Column(String(100))  # JSON string of supported platforms
        last_updated = Column(DateTime, default=datetime.utcnow)
        source = Column(String(50), default='steamdb')

class AppIDScanner:
    def __init__(self, use_database=True, debug_mode=False):
        self.use_database = use_database and SQLALCHEMY_AVAILABLE
        self.debug_mode = debug_mode
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
        
        # Enhanced server-related keywords for better filtering
        self.server_keywords = [
            'dedicated server', 'server', 'dedicated', 'srcds', 'game server',
            'multiplayer server', 'listen server', 'host', 'hosting', 'ds'
        ]
        
        # More specific dedicated server keywords
        self.dedicated_keywords = [
            'dedicated server', 'dedicated', 'srcds', 'hlds', 'game server tool',
            'server tool', 'ds', 'server files', 'server software'
        ]
        
        # JSON file path for AppID list
        self.json_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'AppIDList.json')
        
        # Initialize database
        if self.use_database:
            self.init_database()
        else:
            self.init_sqlite_fallback()
    
    def init_database(self):
        """Initialize SQLAlchemy database connection"""
        try:
            self.engine = get_engine()
            Base.metadata.create_all(self.engine)
            Session = sessionmaker(bind=self.engine)
            self.db_session = Session()
            logger.info("Connected to main database")
        except Exception as e:
            logger.error(f"Failed to connect to main database: {e}")
            logger.info("Falling back to SQLite")
            self.use_database = False
            self.init_sqlite_fallback()
    
    def init_sqlite_fallback(self):
        """Initialize SQLite fallback database"""
        try:
            # Create data directory if it doesn't exist
            data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
            os.makedirs(data_dir, exist_ok=True)
            
            db_path = os.path.join(data_dir, 'steam_apps.db')
            self.sqlite_conn = sqlite3.connect(db_path)
            self.sqlite_conn.execute('''
                CREATE TABLE IF NOT EXISTS steam_apps (
                    appid INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT,
                    is_server BOOLEAN DEFAULT 0,
                    is_dedicated_server BOOLEAN DEFAULT 0,
                    developer TEXT,
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
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            raise
    
    def load_appid_json(self):
        """Load existing AppID list from JSON file"""
        try:
            if os.path.exists(self.json_file_path):
                with open(self.json_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"Loaded existing AppID list with {len(data.get('dedicated_servers', []))} dedicated servers")
                return data
            else:
                logger.info("No existing AppID JSON file found, creating new structure")
                return {
                    "metadata": {
                        "last_updated": "",
                        "total_dedicated_servers": 0,
                        "source": "steam_api",
                        "version": "2.0",
                        "filter_mode": "dedicated_only"
                    },
                    "dedicated_servers": []
                }
        except Exception as e:
            logger.error(f"Error loading AppID JSON file: {e}")
            return {
                "metadata": {
                    "last_updated": "",
                    "total_dedicated_servers": 0,
                    "source": "steam_api",
                    "version": "2.0",
                    "filter_mode": "dedicated_only"
                },
                "dedicated_servers": []
            }
    
    def save_appid_json(self, appid_data):
        """Save AppID list to JSON file"""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.json_file_path), exist_ok=True)
            
            # Update metadata
            appid_data["metadata"]["last_updated"] = datetime.now().isoformat()
            appid_data["metadata"]["total_dedicated_servers"] = len(appid_data["dedicated_servers"])
            
            # Write to file with proper formatting
            with open(self.json_file_path, 'w', encoding='utf-8') as f:
                json.dump(appid_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved AppID list to {self.json_file_path}")
            logger.info(f"Total dedicated servers: {appid_data['metadata']['total_dedicated_servers']}")
        except Exception as e:
            logger.error(f"Error saving AppID JSON file: {e}")
    
    def export_database_to_json(self):
        """Export existing database data to JSON file (dedicated servers only)"""
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
                        "developer": app.developer or "",
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
                    SELECT appid, name, type, developer, publisher, release_date, 
                           description, platforms, source, tags
                    FROM steam_apps 
                    WHERE is_dedicated_server = 1
                """)
                
                for row in cursor.fetchall():
                    server_entry = {
                        "appid": row[0],
                        "name": row[1],
                        "type": row[2] or "Dedicated Server",
                        "developer": row[3] or "",
                        "publisher": row[4] or "",
                        "release_date": row[5] or "",
                        "description": row[6] or "",
                        "platforms": row[7] or "",
                        "source": row[8] or "steam_api",
                        "tags": row[9] or "[]"
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
                    setattr(existing_app, 'last_updated', datetime.now(UTC))
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

    def is_server_application(self, app_name, app_details=None):
        """Determine if an application is a server/dedicated server with enhanced detection"""
        if not app_name:
            return False, False
        
        app_name_lower = app_name.lower()
        
        # Check for explicit dedicated server keywords first
        is_dedicated = any(keyword in app_name_lower for keyword in self.dedicated_keywords)
        
        # Check for general server keywords
        is_server = is_dedicated or any(keyword in app_name_lower for keyword in self.server_keywords)
        
        # Enhanced detection patterns
        dedicated_patterns = [
            r'dedicated\s+server',
            r'server\s+(?:tool|files|software)',
            r'srcds',
            r'hlds',
            r'\bds\b',
            r'game\s+server'
        ]
        
        server_patterns = [
            r'server',
            r'multiplayer\s+(?:tool|host)',
            r'hosting\s+tool'
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
                    break
        
        # Additional checks using app details
        if app_details:
            app_type = app_details.get('type', '').lower()
            
            # Check app type
            if 'tool' in app_type or 'server' in app_type:
                is_server = True
                if 'dedicated' in app_type or 'server' in app_type:
                    is_dedicated = True
            
            # Check categories
            categories = app_details.get('categories', [])
            for category in categories:
                if isinstance(category, dict):
                    desc = category.get('description', '').lower()
                    if any(keyword in desc for keyword in ['dedicated server', 'multiplayer server', 'server tool']):
                        is_server = True
                        is_dedicated = True
            
            # Check genres for server-related content
            genres = app_details.get('genres', [])
            for genre in genres:
                if isinstance(genre, dict):
                    desc = genre.get('description', '').lower()
                    if 'server' in desc or 'multiplayer' in desc:
                        is_server = True
        
        return is_server, is_dedicated
    
    def scan_steam_apps(self, limit=None, server_only=True):
        """Scan Steam applications and save dedicated servers to JSON file"""
        logger.info("Starting Steam app scan (dedicated servers only for JSON)...")
        logger.info(f"Rate limiting: {self.request_delay}s general, {self.api_request_delay}s API calls")
        
        # Load existing JSON data
        appid_data = self.load_appid_json()
        
        # Create lookup sets for existing data to avoid duplicates
        existing_appids = {server["appid"] for server in appid_data["dedicated_servers"]}
        
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
        json_updates = 0
        
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
                              f"saved {saved_count} to DB, {json_updates} dedicated servers in JSON, "
                              f"found {dedicated_count} dedicated servers")
                
                # Get detailed information with improved error handling
                app_details = self.get_app_details_steam_api(appid)
                
                # Determine if it's a server application
                is_server, is_dedicated = self.is_server_application(name, app_details)
                
                # Skip non-server apps if server_only is True (default)
                if server_only and not is_server:
                    continue
                
                # Prepare app data for database (save all server apps to database)
                app_data = {
                    'appid': appid,
                    'name': name,
                    'type': app_details.get('type', 'Unknown') if app_details else 'Unknown',
                    'is_server': is_server,
                    'is_dedicated_server': is_dedicated,
                    'source': 'steam_api'
                }
                
                # Add additional details if available
                if app_details:
                    app_data.update({
                        'developer': ', '.join(app_details.get('developers', [])),
                        'publisher': ', '.join(app_details.get('publishers', [])),
                        'release_date': app_details.get('release_date', {}).get('date', ''),
                        'description': app_details.get('short_description', ''),
                        'tags': json.dumps([cat.get('description') for cat in app_details.get('categories', [])]),
                        'price': str(app_details.get('price_overview', {}).get('final_formatted', '')),
                        'platforms': json.dumps(app_details.get('platforms', {}))
                    })
                
                # Save to database (all server apps)
                self.save_app_to_database(app_data)
                saved_count += 1
                
                # Only add DEDICATED servers to JSON file
                if is_dedicated and appid not in existing_appids:
                    json_server_entry = {
                        "appid": appid,
                        "name": name,
                        "type": app_data.get('type', 'Dedicated Server'),
                        "developer": app_data.get('developer', ''),
                        "publisher": app_data.get('publisher', ''),
                        "release_date": app_data.get('release_date', ''),
                        "description": app_data.get('description', ''),
                        "platforms": app_data.get('platforms', ''),
                        "source": app_data.get('source', 'steam_api'),
                        "tags": app_data.get('tags', '[]')
                    }
                    
                    appid_data["dedicated_servers"].append(json_server_entry)
                    existing_appids.add(appid)
                    json_updates += 1
                
                if is_dedicated:
                    dedicated_count += 1
                
                if processed % 100 == 0:
                    logger.info(f"Processed {processed} apps, saved {saved_count} to DB, updated {json_updates} dedicated servers in JSON, found {dedicated_count} dedicated servers")
                
            except Exception as e:
                logger.error(f"Error processing app {app.get('appid', 'unknown')}: {e}")
                continue
        
        # Sort and save JSON data
        appid_data["dedicated_servers"].sort(key=lambda x: x["name"])
        
        self.save_appid_json(appid_data)
        
        logger.info(f"Scan complete! Processed {processed} apps, saved {saved_count} to database, updated {json_updates} dedicated servers in JSON, found {dedicated_count} total dedicated servers")
    
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
    
    def get_database_stats(self):
        """Get statistics about the database"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                total_apps = self.db_session.query(SteamApp).count()
                server_apps = self.db_session.query(SteamApp).filter(SteamApp.is_server == True).count()
                dedicated_apps = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).count()
            else:
                # Use SQLite
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps")
                total_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_server = 1")
                server_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = 1")
                dedicated_apps = cursor.fetchone()[0]
            
            return {
                'total_apps': total_apps,
                'server_apps': server_apps,
                'dedicated_server_apps': dedicated_apps
            }
            
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {'total_apps': 0, 'server_apps': 0, 'dedicated_server_apps': 0}
    
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
    parser.add_argument('--server-only', action='store_true', default=True, help='Only save server applications (default: True)')
    parser.add_argument('--include-all', action='store_true', help='Include all apps, not just servers')
    parser.add_argument('--search', type=str, help='Search for apps by name')
    parser.add_argument('--list-servers', action='store_true', help='List all server applications')
    parser.add_argument('--dedicated-only', action='store_true', help='Show only dedicated servers (use with --list-servers)')
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
            results = scanner.search_apps(args.search, server_only=args.server_only and not args.include_all)
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
        
        elif args.stats:
            # Show database statistics
            stats = scanner.get_database_stats()
            print("\nDatabase Statistics:")
            print("-" * 30)
            print(f"Total Applications: {stats['total_apps']:,}")
            print(f"Server Applications: {stats['server_apps']:,}")
            print(f"Dedicated Servers: {stats['dedicated_server_apps']:,}")
        
        else:
            # Perform scan
            scanner.scan_steam_apps(limit=args.limit, server_only=args.server_only and not args.include_all)
            
            # Show final statistics
            stats = scanner.get_database_stats()
            print(f"\nFinal Database Statistics:")
            print(f"Total Applications: {stats['total_apps']:,}")
            print(f"Server Applications: {stats['server_apps']:,}")
            print(f"Dedicated Servers: {stats['dedicated_server_apps']:,}")
    
    finally:
        scanner.close()

if __name__ == "__main__":
    main()