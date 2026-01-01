#!/usr/bin/env python3
# Database migration script
import os
import sys
import logging
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from Modules.Database.SQL_Connection import get_engine
    from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    # Provide stub values for type checking when SQLAlchemy is not available
    get_engine = None  # type: ignore[assignment]
    text = lambda x: x  # type: ignore[assignment, misc]
    sessionmaker = None  # type: ignore[assignment]
    declarative_base = None  # type: ignore[assignment]
    print("Warning: SQLAlchemy not available, SQLite only")

import sqlite3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("DatabaseMigration")

# DB models with subscription tracking
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()  # type: ignore[possibly-unbound]

    class SteamApp(Base):  # type: ignore[valid-type, misc]
        __tablename__ = 'steam_apps'

        appid = Column(Integer, primary_key=True)  # type: ignore[possibly-unbound]
        name = Column(String(255), nullable=False)  # type: ignore[possibly-unbound]
        type = Column(String(50))  # type: ignore[possibly-unbound]
        is_server = Column(Boolean, default=False)  # type: ignore[possibly-unbound]
        is_dedicated_server = Column(Boolean, default=False)  # type: ignore[possibly-unbound]
        requires_subscription = Column(Boolean, default=False)  # type: ignore[possibly-unbound]
        anonymous_install = Column(Boolean, default=True)  # type: ignore[possibly-unbound]
        publisher = Column(String(255))  # type: ignore[possibly-unbound]
        release_date = Column(String(50))  # type: ignore[possibly-unbound]
        description = Column(Text)  # type: ignore[possibly-unbound]
        tags = Column(Text)  # type: ignore[possibly-unbound]
        price = Column(String(20))  # type: ignore[possibly-unbound]
        platforms = Column(String(100))  # type: ignore[possibly-unbound]
        last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # type: ignore[possibly-unbound]
        source = Column(String(50), default='steamdb')  # type: ignore[possibly-unbound]

class DatabaseMigrator:
    # - Migrates DB schema
    # - Supports dry-run mode
    def __init__(self, use_database=True, dry_run=False):
        self.use_database = use_database and SQLALCHEMY_AVAILABLE
        self.dry_run = dry_run

        if self.use_database:
            self.init_database()
        else:
            self.init_sqlite_fallback()

    def init_database(self):
        # SQLAlchemy connection
        try:
            self.engine = get_engine()  # type: ignore[misc]
            Session = sessionmaker(bind=self.engine)  # type: ignore[misc]
            self.db_session = Session()
            logger.info("Connected to main database")
        except Exception as e:
            logger.error(f"Failed to connect to main database: {e}")
            logger.info("Falling back to SQLite")
            self.use_database = False
            self.init_sqlite_fallback()

    def init_sqlite_fallback(self):
        # Initialise SQLite fallback database
        try:
            # Use centralised db directory
            db_dir = os.path.join(os.path.dirname(__file__), '..', 'db')
            db_path = os.path.join(db_dir, 'steam_ID.db')

            if not os.path.exists(db_path):
                logger.error(f"SQLite database not found at {db_path}")
                raise FileNotFoundError(f"Database file not found: {db_path}")

            self.sqlite_conn = sqlite3.connect(db_path)
            logger.info(f"Connected to SQLite database: {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialise SQLite database: {e}")
            raise

    def check_current_schema(self):
        # Check the current database schema and return column information
        try:
            if self.use_database:
                # Check columns in main database
                result = self.db_session.execute(text("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'steam_apps'
                    ORDER BY ordinal_position
                """))
                columns = {row[0]: row[1] for row in result}
            else:
                # Check columns in SQLite
                cursor = self.sqlite_conn.execute("PRAGMA table_info(steam_apps)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}

            return columns

        except Exception as e:
            logger.warning(f"Could not check current schema: {e}")
            return {}

    def migrate_schema(self):
        # Perform the schema migration
        logger.info("Starting database schema migration...")

        if self.dry_run:
            logger.info("Running in DRY RUN mode - no changes will be made")

        # Check current schema
        columns = self.check_current_schema()

        if not columns:
            logger.error("Could not determine current schema. Migration aborted.")
            return False

        logger.info(f"Current schema has {len(columns)} columns: {list(columns.keys())}")

        # Check what needs to be migrated
        needs_migration = []

        if 'requires_subscription' not in columns:
            needs_migration.append('requires_subscription')

        if 'anonymous_install' not in columns:
            needs_migration.append('anonymous_install')

        has_developer = 'developer' in columns

        if not needs_migration and not has_developer:
            logger.info("Database schema is already up to date!")
            return True

        logger.info(f"Migration needed for columns: {needs_migration}")
        if has_developer:
            logger.info("Developer column found (will be left for compatibility)")

        # Perform migration
        try:
            if self.use_database:
                self.migrate_main_database(needs_migration, has_developer)
            else:
                self.migrate_sqlite_database(needs_migration, has_developer)

            logger.info("Schema migration completed successfully!")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            if self.use_database:
                self.db_session.rollback()
            return False

    def migrate_main_database(self, needs_migration, has_developer):
        # Migrate the main database schema
        if self.dry_run:
            logger.info("[DRY RUN] Would migrate main database schema")
            return

        # Add new columns
        for column in needs_migration:
            if column == 'requires_subscription':
                logger.info("Adding requires_subscription column to main database")
                self.db_session.execute(text(
                    "ALTER TABLE steam_apps ADD COLUMN requires_subscription BOOLEAN DEFAULT FALSE"
                ))
            elif column == 'anonymous_install':
                logger.info("Adding anonymous_install column to main database")
                self.db_session.execute(text(
                    "ALTER TABLE steam_apps ADD COLUMN anonymous_install BOOLEAN DEFAULT TRUE"
                ))

        # Preserve deprecated developer column for backward compatibility
        if has_developer:
            logger.info("Developer column found - leaving for compatibility (will be ignored)")

        self.db_session.commit()
        logger.info("Main database migration completed")

    def migrate_sqlite_database(self, needs_migration, has_developer):
        # Migrate the SQLite database schema
        if self.dry_run:
            logger.info("[DRY RUN] Would migrate SQLite database schema")
            return

        # Add new columns
        for column in needs_migration:
            if column == 'requires_subscription':
                logger.info("Adding requires_subscription column to SQLite database")
                self.sqlite_conn.execute(
                    "ALTER TABLE steam_apps ADD COLUMN requires_subscription BOOLEAN DEFAULT 0"
                )
            elif column == 'anonymous_install':
                logger.info("Adding anonymous_install column to SQLite database")
                self.sqlite_conn.execute(
                    "ALTER TABLE steam_apps ADD COLUMN anonymous_install BOOLEAN DEFAULT 1"
                )

        if has_developer:
            logger.info("Developer column found - leaving for compatibility (will be ignored)")

        self.sqlite_conn.commit()
        logger.info("SQLite database migration completed")

    def populate_subscription_data(self, limit=None):
        # Populate subscription fields with intelligent defaults based on known free servers
        logger.info("Populating subscription data with intelligent defaults...")

        if self.dry_run:
            logger.info("[DRY RUN] Would populate subscription data")
            return

        updated_count = 0

        try:
            # Curated list of confirmed free dedicated servers that allow anonymous downloads
            free_anonymous_servers = [
                90,      # Counter-Strike Dedicated Server
                232330,  # Counter-Strike: Global Offensive - Dedicated Server
                222860,  # Left 4 Dead 2 Dedicated Server
                232250,  # Team Fortress 2 Dedicated Server
                4020,    # Garry's Mod Dedicated Server
                205,     # Source Dedicated Server
            ]

            if self.use_database:
                # Update well-known free servers
                for appid in free_anonymous_servers:
                    with self.engine.begin() as conn:
                        result = conn.execute(text("""
                            UPDATE steam_apps
                            SET requires_subscription = FALSE, anonymous_install = TRUE
                            WHERE appid = :appid AND is_dedicated_server = TRUE
                        """), {'appid': appid})
                        rows_affected = result.rowcount
                        if rows_affected > 0:
                            updated_count += rows_affected
                            logger.debug(f"Updated AppID {appid} as free/anonymous")

                # Mark servers with non-free pricing as requiring subscription
                with self.engine.begin() as conn:
                    result = conn.execute(text("""
                        UPDATE steam_apps
                        SET requires_subscription = TRUE, anonymous_install = FALSE
                        WHERE is_dedicated_server = TRUE
                        AND price IS NOT NULL
                        AND price != ''
                        AND price != 'Free'
                        AND price NOT LIKE '%free%'
                    """))
                    updated_count += result.rowcount

            else:
                # SQLite version
                for appid in free_anonymous_servers:
                    cursor = self.sqlite_conn.execute("""
                        UPDATE steam_apps
                        SET requires_subscription = 0, anonymous_install = 1
                        WHERE appid = ? AND is_dedicated_server = 1
                    """, (appid,))
                    if cursor.rowcount > 0:
                        updated_count += cursor.rowcount
                        logger.debug(f"Updated AppID {appid} as free/anonymous")

                # Set servers with non-empty price as requiring subscription
                cursor = self.sqlite_conn.execute("""
                    UPDATE steam_apps
                    SET requires_subscription = 1, anonymous_install = 0
                    WHERE is_dedicated_server = 1
                    AND price IS NOT NULL
                    AND price != ''
                    AND price != 'Free'
                    AND price NOT LIKE '%free%'
                """)
                updated_count += cursor.rowcount

                self.sqlite_conn.commit()

            logger.info(f"Updated subscription data for {updated_count} servers")

        except Exception as e:
            logger.error(f"Failed to populate subscription data: {e}")
            if self.use_database:
                self.db_session.rollback()

    def get_migration_stats(self):
        # Get statistics about the migration
        try:
            if self.use_database:
                total = self.db_session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).count()
                subscription_required = self.db_session.query(SteamApp).filter(
                    SteamApp.is_dedicated_server == True,
                    SteamApp.requires_subscription == True
                ).count()
                anonymous_install = self.db_session.query(SteamApp).filter(
                    SteamApp.is_dedicated_server == True,
                    SteamApp.anonymous_install == True
                ).count()
            else:
                cursor = self.sqlite_conn.execute("SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = 1")
                total = cursor.fetchone()[0]

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
                'total_servers': total,
                'subscription_required': subscription_required,
                'anonymous_install': anonymous_install,
                'free_servers': total - subscription_required
            }

        except Exception as e:
            logger.error(f"Error getting migration stats: {e}")
            return None

    def close(self):
        # Close database connections
        try:
            if self.use_database and hasattr(self, 'db_session'):
                self.db_session.close()
            if hasattr(self, 'sqlite_conn'):
                self.sqlite_conn.close()
        except Exception as e:
            logger.error(f"Error closing database connections: {e}")

def main():
    # Command-line interface for database schema migration
    parser = argparse.ArgumentParser(description='Migrate AppID database schema')
    parser.add_argument('--dry-run', action='store_true', help='Only show what would be changed without making changes')
    parser.add_argument('--no-database', action='store_true', help='Use SQLite fallback instead of main database')
    parser.add_argument('--populate-data', action='store_true', help='Populate subscription data with intelligent defaults')
    parser.add_argument('--stats', action='store_true', help='Show migration statistics')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create migrator instance
    migrator = DatabaseMigrator(
        use_database=not args.no_database,
        dry_run=args.dry_run
    )

    try:
        if args.stats:
            # Show migration statistics
            stats = migrator.get_migration_stats()
            if stats:
                print("\nMigration Statistics:")
                print("-" * 40)
                print(f"Total Dedicated Servers: {stats['total_servers']:,}")
                print(f"Subscription Required: {stats['subscription_required']:,}")
                print(f"Anonymous Install: {stats['anonymous_install']:,}")
                print(f"Free Servers: {stats['free_servers']:,}")
            else:
                print("Could not retrieve migration statistics")
        else:
            # Perform migration
            success = migrator.migrate_schema()

            if success and args.populate_data:
                migrator.populate_subscription_data()

                # Show final stats
                stats = migrator.get_migration_stats()
                if stats:
                    print(f"\nMigration completed!")
                    print(f"Total servers: {stats['total_servers']:,}")
                    print(f"Subscription required: {stats['subscription_required']:,}")
                    print(f"Anonymous install: {stats['anonymous_install']:,}")

            if not success:
                sys.exit(1)

    finally:
        migrator.close()

if __name__ == "__main__":
    main()