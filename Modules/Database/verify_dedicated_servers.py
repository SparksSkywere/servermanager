#!/usr/bin/env python3
import os
import sys
import logging
import re
import json
import requests
import time
from datetime import datetime, timezone

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import database connection
try:
    from Modules.Database.steam_database import get_steam_engine
    from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("Warning: SQLAlchemy not available, falling back to SQLite")

import sqlite3

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ServerVerifier")

# Database models (same as AppIDScanner)
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
        tags = Column(Text)
        price = Column(String(20))
        platforms = Column(String(100))
        last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))
        source = Column(String(50), default='steamdb')

class DedicatedServerVerifier:
    def __init__(self, use_database=True, dry_run=False):
        """
        Initialize the verifier
        
        Args:
            use_database: Whether to use the main database or SQLite fallback
            dry_run: If True, only report what would be changed without making changes
        """
        self.use_database = use_database and SQLALCHEMY_AVAILABLE
        self.dry_run = dry_run
        
        # Rate limiting for Steam API calls
        self.request_delay = 2.0
        self.last_request_time = 0
        
        # HTTP session for requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Strict validation criteria
        self.valid_dedicated_keywords = [
            'dedicated server', 'srcds', 'hlds', 'game server tool',
            'server tool', 'server files', 'server software'
        ]
        
        self.valid_dedicated_patterns = [
            r'dedicated\s+server',
            r'server\s+(?:tool|files|software)',
            r'srcds',
            r'hlds',
            r'game\s+server(?:\s+tool)?'
        ]
        
        # DLC and invalid content patterns
        self.invalid_keywords = [
            'dlc', 'downloadable content', 'expansion pack', 'content pack',
            'season pass', 'soundtrack', 'music', 'wallpaper', 'theme',
            'skin pack', 'character pack', 'weapon pack', 'map pack',
            'cosmetic', 'avatar', 'demo', 'beta', 'test', 'trailer',
            'workshop', 'mod', 'editor', 'level editor'
        ]
        
        self.invalid_types = ['dlc', 'music', 'video', 'demo', 'advertising']
        
        # Initialize database connection
        if self.use_database:
            self.init_database()
        else:
            self.init_sqlite_fallback()
    
    def init_database(self):
        """Initialize SQLAlchemy database connection"""
        try:
            self.engine = get_steam_engine()
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
            data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
            db_path = os.path.join(data_dir, 'steam_ID.db')
            self.sqlite_conn = sqlite3.connect(db_path)
            logger.info(f"Connected to SQLite database: {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            raise
    
    def rate_limit(self):
        """Implement rate limiting for API calls"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.request_delay:
            sleep_time = self.request_delay - time_since_last
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def get_app_details(self, appid):
        """Get app details from Steam API with rate limiting"""
        try:
            self.rate_limit()
            url = "https://store.steampowered.com/api/appdetails"
            params = {'appids': appid, 'format': 'json'}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            app_data = data.get(str(appid), {})
            if app_data.get('success') and 'data' in app_data:
                return app_data['data']
            return None
        except Exception as e:
            logger.debug(f"Failed to get details for AppID {appid}: {e}")
            return None
    
    def is_valid_dedicated_server(self, app_name, app_details=None):
        """
        Strict validation to determine if an app is a legitimate dedicated server
        
        Args:
            app_name: Name of the application
            app_details: Detailed app information from Steam API
            
        Returns:
            bool: True if it's a valid dedicated server, False otherwise
        """
        if not app_name:
            return False
        
        app_name_lower = app_name.lower()
        
        # First, check for invalid content (DLC, etc.)
        for invalid_keyword in self.invalid_keywords:
            if invalid_keyword in app_name_lower:
                logger.debug(f"Rejected '{app_name}': contains invalid keyword '{invalid_keyword}'")
                return False
        
        # Check app details if available
        if app_details:
            app_type = app_details.get('type', '').lower()
            
            # Reject invalid types
            if app_type in self.invalid_types:
                logger.debug(f"Rejected '{app_name}': invalid type '{app_type}'")
                return False
            
            # Check if it's marked as DLC
            if app_details.get('is_dlc', False):
                logger.debug(f"Rejected '{app_name}': marked as DLC")
                return False
        
        # Check for valid dedicated server patterns
        has_valid_pattern = False
        
        # Check keywords
        for keyword in self.valid_dedicated_keywords:
            if keyword in app_name_lower:
                has_valid_pattern = True
                break
        
        # Check regex patterns
        if not has_valid_pattern:
            for pattern in self.valid_dedicated_patterns:
                if re.search(pattern, app_name_lower):
                    has_valid_pattern = True
                    break
        
        if not has_valid_pattern:
            logger.debug(f"Rejected '{app_name}': no valid dedicated server patterns found")
            return False
        
        # Additional validation: must contain "server" or be a known server tool
        server_indicators = ['server', 'srcds', 'hlds']
        if not any(indicator in app_name_lower for indicator in server_indicators):
            logger.debug(f"Rejected '{app_name}': no server indicators found")
            return False
        
        # If we have app details, do additional validation
        if app_details:
            # Check if it's a tool type (common for dedicated servers)
            app_type = app_details.get('type', '').lower()
            if app_type not in ['tool', 'game', 'application']:
                logger.debug(f"Rejected '{app_name}': unexpected type '{app_type}'")
                return False
        
        logger.debug(f"Validated '{app_name}': appears to be a legitimate dedicated server")
        return True
    
    def get_all_server_records(self):
        """Get all records marked as dedicated servers from the database"""
        try:
            if self.use_database:
                # Use SQLAlchemy
                apps = self.db_session.query(SteamApp).filter(
                    SteamApp.is_dedicated_server == True
                ).all()
                return [(app.appid, app.name, app.type, app.description) for app in apps]
            else:
                # Use SQLite
                cursor = self.sqlite_conn.execute("""
                    SELECT appid, name, type, description
                    FROM steam_apps 
                    WHERE is_dedicated_server = 1
                    ORDER BY name
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting server records: {e}")
            return []
    
    def remove_invalid_record(self, appid, app_name, reason):
        """Remove an invalid record from the database"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would remove AppID {appid} '{app_name}': {reason}")
                return True
            
            if self.use_database:
                # Use SQLAlchemy
                app = self.db_session.query(SteamApp).filter_by(appid=appid).first()
                if app:
                    self.db_session.delete(app)
                    self.db_session.commit()
                    logger.info(f"Removed AppID {appid} '{app_name}': {reason}")
                    return True
            else:
                # Use SQLite
                self.sqlite_conn.execute("DELETE FROM steam_apps WHERE appid = ?", (appid,))
                self.sqlite_conn.commit()
                logger.info(f"Removed AppID {appid} '{app_name}': {reason}")
                return True
                
        except Exception as e:
            logger.error(f"Error removing AppID {appid}: {e}")
            if self.use_database:
                self.db_session.rollback()
            return False
    
    def update_record_status(self, appid, app_name, is_server, is_dedicated):
        """Update the server status of a record"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would update AppID {appid} '{app_name}': server={is_server}, dedicated={is_dedicated}")
                return True
            
            if self.use_database:
                # Use SQLAlchemy with proper update
                self.db_session.query(SteamApp).filter_by(appid=appid).update({
                    'is_server': is_server,
                    'is_dedicated_server': is_dedicated,
                    'last_updated': datetime.now(timezone.utc)
                })
                self.db_session.commit()
                logger.info(f"Updated AppID {appid} '{app_name}': server={is_server}, dedicated={is_dedicated}")
                return True
            else:
                # Use SQLite
                self.sqlite_conn.execute("""
                    UPDATE steam_apps 
                    SET is_server = ?, is_dedicated_server = ?, last_updated = CURRENT_TIMESTAMP 
                    WHERE appid = ?
                """, (is_server, is_dedicated, appid))
                self.sqlite_conn.commit()
                logger.info(f"Updated AppID {appid} '{app_name}': server={is_server}, dedicated={is_dedicated}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating AppID {appid}: {e}")
            if self.use_database:
                self.db_session.rollback()
            return False
    
    def verify_all_servers(self, fetch_details=True):
        """
        Verify all records marked as dedicated servers
        
        Args:
            fetch_details: Whether to fetch fresh details from Steam API for verification
        """
        logger.info("Starting verification of dedicated server records...")
        
        if self.dry_run:
            logger.info("Running in DRY RUN mode - no changes will be made")
        
        # Get all server records
        records = self.get_all_server_records()
        total_records = len(records)
        
        if total_records == 0:
            logger.info("No dedicated server records found in database")
            return
        
        logger.info(f"Found {total_records} dedicated server records to verify")
        
        removed_count = 0
        updated_count = 0
        valid_count = 0
        error_count = 0
        
        for i, (appid, name, app_type, description) in enumerate(records, 1):
            try:
                logger.info(f"Verifying {i}/{total_records}: AppID {appid} - {name}")
                
                # Get fresh details if requested
                app_details = None
                if fetch_details:
                    app_details = self.get_app_details(appid)
                
                # Perform validation
                is_valid = self.is_valid_dedicated_server(name, app_details)
                
                if not is_valid:
                    # Remove invalid record
                    reason = "Failed dedicated server validation"
                    if self.remove_invalid_record(appid, name, reason):
                        removed_count += 1
                    else:
                        error_count += 1
                else:
                    # Valid dedicated server - ensure it's properly marked
                    if self.update_record_status(appid, name, True, True):
                        if i % 10 == 0:  # Only log every 10th valid update to reduce spam
                            logger.debug(f"Confirmed valid: AppID {appid} - {name}")
                        valid_count += 1
                    else:
                        error_count += 1
                
                # Progress update
                if i % 50 == 0:
                    logger.info(f"Progress: {i}/{total_records} ({i/total_records*100:.1f}%) - "
                              f"Valid: {valid_count}, Removed: {removed_count}, Errors: {error_count}")
                
            except Exception as e:
                logger.error(f"Error processing AppID {appid} '{name}': {e}")
                error_count += 1
                continue
        
        # Final summary
        logger.info("Verification complete!")
        logger.info(f"Total records processed: {total_records}")
        logger.info(f"Valid dedicated servers: {valid_count}")
        logger.info(f"Invalid records removed: {removed_count}")
        logger.info(f"Errors encountered: {error_count}")
        
        if self.dry_run:
            logger.info("This was a DRY RUN - no actual changes were made")
    
    def get_statistics(self):
        """Get current database statistics including subscription information"""
        try:
            if self.use_database:
                total_apps = self.db_session.query(SteamApp).count()
                server_apps = self.db_session.query(SteamApp).filter(SteamApp.is_server == True).count()
                dedicated_apps = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).count()
                try:
                    # Try to get subscription stats - may fail if columns don't exist yet
                    subscription_required = self.db_session.query(SteamApp).filter(
                        SteamApp.is_dedicated_server == True,
                        SteamApp.requires_subscription == True
                    ).count()
                    anonymous_install = self.db_session.query(SteamApp).filter(
                        SteamApp.is_dedicated_server == True,
                        SteamApp.anonymous_install == True
                    ).count()
                except Exception:
                    subscription_required = 0
                    anonymous_install = 0
            else:
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps")
                total_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_server = 1")
                server_apps = cursor.fetchone()[0]
                
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = 1")
                dedicated_apps = cursor.fetchone()[0]
                
                try:
                    # Try to get subscription stats - may fail if columns don't exist yet
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
                except Exception:
                    subscription_required = 0
                    anonymous_install = 0
            
            return {
                'total_apps': total_apps,
                'server_apps': server_apps,
                'dedicated_server_apps': dedicated_apps,
                'subscription_required_servers': subscription_required,
                'anonymous_install_servers': anonymous_install
            }
            
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
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
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify and clean dedicated server records')
    parser.add_argument('--dry-run', action='store_true', help='Only show what would be changed without making changes')
    parser.add_argument('--no-fetch-details', action='store_true', help='Skip fetching fresh details from Steam API')
    parser.add_argument('--no-database', action='store_true', help='Use SQLite fallback instead of main database')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create verifier instance
    verifier = DedicatedServerVerifier(
        use_database=not args.no_database,
        dry_run=args.dry_run
    )
    
    try:
        if args.stats:
            # Show statistics
            stats = verifier.get_statistics()
            print("\nDatabase Statistics:")
            print("-" * 50)
            print(f"Total Applications: {stats['total_apps']:,}")
            print(f"Server Applications: {stats['server_apps']:,}")
            print(f"Dedicated Servers: {stats['dedicated_server_apps']:,}")
            if stats.get('subscription_required_servers', 0) > 0 or stats.get('anonymous_install_servers', 0) > 0:
                print(f"├─ Subscription Required: {stats.get('subscription_required_servers', 0):,}")
                print(f"└─ Anonymous Install: {stats.get('anonymous_install_servers', 0):,}")
        else:
            # Show initial statistics  
            stats = verifier.get_statistics()
            logger.info(f"Initial stats - Total: {stats['total_apps']:,}, "
                       f"Servers: {stats['server_apps']:,}, "
                       f"Dedicated: {stats['dedicated_server_apps']:,}")
            
            # Perform verification
            verifier.verify_all_servers(fetch_details=not args.no_fetch_details)
            
            # Show final statistics
            final_stats = verifier.get_statistics()
            logger.info(f"Final stats - Total: {final_stats['total_apps']:,}, "
                       f"Servers: {final_stats['server_apps']:,}, "
                       f"Dedicated: {final_stats['dedicated_server_apps']:,}")
            if final_stats.get('subscription_required_servers', 0) > 0 or final_stats.get('anonymous_install_servers', 0) > 0:
                logger.info(f"Subscription stats - Required: {final_stats.get('subscription_required_servers', 0):,}, "
                           f"Anonymous: {final_stats.get('anonymous_install_servers', 0):,}")
    
    finally:
        verifier.close()

if __name__ == "__main__":
    main()
