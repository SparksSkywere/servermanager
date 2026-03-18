#!/usr/bin/env python3
# Database verification and integrity tool
import os
import sys
import logging
import argparse
from datetime import datetime, timezone

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path, get_database_connection
setup_module_path()

SQLALCHEMY_AVAILABLE = False
get_steam_engine = None
get_minecraft_engine = None

try:
    from Modules.Database.steam_database import get_steam_engine as _get_steam_engine
    from Modules.Database.minecraft_database import get_minecraft_engine as _get_minecraft_engine
    from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, text, inspect
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
    get_steam_engine = _get_steam_engine
    get_minecraft_engine = _get_minecraft_engine
except ImportError:
    text = lambda x: x  # type: ignore[assignment, misc]
    inspect = None  # type: ignore[assignment]
    sessionmaker = None  # type: ignore[assignment]
    declarative_base = None  # type: ignore[assignment]

import sqlite3

from Modules.core.server_logging import get_component_logger
logger = get_component_logger("DatabaseVerifier")

class DatabaseVerifier:
    # Verify and repair database integrity for Steam and Minecraft databases

    def __init__(self, use_database=True, dry_run=False):
        self.use_database = use_database and SQLALCHEMY_AVAILABLE
        self.dry_run = dry_run
        self.results = {
            'steam': {'status': 'not_checked', 'issues': [], 'stats': {}},
            'minecraft': {'status': 'not_checked', 'issues': [], 'stats': {}}
        }

    # ── Steam database ──────────────────────────────────────────────────

    def _get_steam_session(self):
        # Get a SQLAlchemy session for the Steam database
        engine = get_steam_engine()  # type: ignore[misc]
        Session = sessionmaker(bind=engine)  # type: ignore[possibly-unbound]
        return Session(), engine

    def _get_steam_sqlite(self):
        # Get an SQLite connection for the Steam database
        db_dir = os.path.join(os.path.dirname(__file__), '..', 'db')
        db_path = os.path.join(db_dir, 'steam_ID.db')
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Steam SQLite database not found: {db_path}")
        return sqlite3.connect(db_path)

    def verify_steam_schema(self):
        # Check that the steam_apps table has all required columns
        required_columns = {
            'appid', 'name', 'type', 'is_server', 'is_dedicated_server',
            'requires_subscription', 'anonymous_install', 'publisher',
            'release_date', 'description', 'tags', 'price', 'platforms',
            'last_updated', 'source'
        }

        try:
            if self.use_database:
                session, engine = self._get_steam_session()
                try:
                    insp = inspect(engine)  # type: ignore[possibly-unbound]
                    columns = {col['name'] for col in insp.get_columns('steam_apps')}
                finally:
                    session.close()
            else:
                conn = self._get_steam_sqlite()
                try:
                    cursor = conn.execute("PRAGMA table_info(steam_apps)")
                    columns = {row[1] for row in cursor.fetchall()}
                finally:
                    conn.close()

            missing = required_columns - columns
            extra = columns - required_columns

            if missing:
                self.results['steam']['issues'].append(
                    f"Missing columns: {', '.join(sorted(missing))}"
                )
                # Attempt to add missing columns
                if not self.dry_run:
                    self._add_missing_steam_columns(missing)

            if extra:
                # Informational only – don't treat as an error
                logger.info(f"Steam DB has extra columns (OK): {', '.join(sorted(extra))}")

            return missing

        except Exception as e:
            self.results['steam']['issues'].append(f"Schema check failed: {e}")
            logger.error(f"Steam schema verification failed: {e}")
            return set()

    def _add_missing_steam_columns(self, missing_columns):
        # Add missing columns to the steam_apps table
        column_defaults = {
            'requires_subscription': ('BOOLEAN', 'FALSE', '0'),
            'anonymous_install': ('BOOLEAN', 'TRUE', '1'),
        }

        try:
            if self.use_database:
                session, engine = self._get_steam_session()
                try:
                    for col in missing_columns:
                        if col in column_defaults:
                            sql_type, default_val, _ = column_defaults[col]
                            session.execute(text(
                                f"ALTER TABLE steam_apps ADD COLUMN {col} {sql_type} DEFAULT {default_val}"
                            ))
                            logger.info(f"Added column '{col}' to steam_apps (main DB)")
                    session.commit()
                finally:
                    session.close()
            else:
                conn = self._get_steam_sqlite()
                try:
                    for col in missing_columns:
                        if col in column_defaults:
                            sql_type, _, sqlite_default = column_defaults[col]
                            conn.execute(
                                f"ALTER TABLE steam_apps ADD COLUMN {col} {sql_type} DEFAULT {sqlite_default}"
                            )
                            logger.info(f"Added column '{col}' to steam_apps (SQLite)")
                    conn.commit()
                finally:
                    conn.close()

        except Exception as e:
            logger.error(f"Failed to add missing columns: {e}")
            self.results['steam']['issues'].append(f"Column repair failed: {e}")

    def verify_steam_data(self):
        # Check Steam data integrity - row counts, orphan detection, etc.
        try:
            if self.use_database:
                session, engine = self._get_steam_session()
                try:
                    total = session.execute(text("SELECT COUNT(*) FROM steam_apps")).scalar()
                    servers = session.execute(text(
                        "SELECT COUNT(*) FROM steam_apps WHERE is_server = TRUE"
                    )).scalar()
                    dedicated = session.execute(text(
                        "SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = TRUE"
                    )).scalar()

                    # Check for entries with empty names
                    empty_names = session.execute(text(
                        "SELECT COUNT(*) FROM steam_apps WHERE name IS NULL OR name = ''"
                    )).scalar()

                    # Check for duplicate AppIDs (shouldn't happen with PK but check anyway)
                    dupes = session.execute(text(
                        "SELECT appid, COUNT(*) c FROM steam_apps GROUP BY appid HAVING c > 1"
                    )).fetchall()
                finally:
                    session.close()
            else:
                conn = self._get_steam_sqlite()
                try:
                    total = conn.execute("SELECT COUNT(*) FROM steam_apps").fetchone()[0]
                    servers = conn.execute(
                        "SELECT COUNT(*) FROM steam_apps WHERE is_server = 1"
                    ).fetchone()[0]
                    dedicated = conn.execute(
                        "SELECT COUNT(*) FROM steam_apps WHERE is_dedicated_server = 1"
                    ).fetchone()[0]
                    empty_names = conn.execute(
                        "SELECT COUNT(*) FROM steam_apps WHERE name IS NULL OR name = ''"
                    ).fetchone()[0]
                    dupes = conn.execute(
                        "SELECT appid, COUNT(*) c FROM steam_apps GROUP BY appid HAVING c > 1"
                    ).fetchall()
                finally:
                    conn.close()

            self.results['steam']['stats'] = {
                'total_apps': total,
                'server_apps': servers,
                'dedicated_servers': dedicated,
                'empty_names': empty_names,
                'duplicate_appids': len(dupes)
            }

            if empty_names:
                self.results['steam']['issues'].append(
                    f"{empty_names} entries with empty or NULL names"
                )
            if dupes:
                self.results['steam']['issues'].append(
                    f"{len(dupes)} duplicate AppID entries found"
                )

        except Exception as e:
            self.results['steam']['issues'].append(f"Data check failed: {e}")
            logger.error(f"Steam data verification failed: {e}")

    # ── Minecraft database ──────────────────────────────────────────────

    def _get_minecraft_session(self):
        # Get a SQLAlchemy session for the Minecraft database
        engine = get_minecraft_engine()  # type: ignore[misc]
        Session = sessionmaker(bind=engine)  # type: ignore[possibly-unbound]
        return Session(), engine

    def _get_minecraft_sqlite(self):
        # Get an SQLite connection for the Minecraft database
        db_dir = os.path.join(os.path.dirname(__file__), '..', 'db')
        db_path = os.path.join(db_dir, 'minecraft_servers.db')
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Minecraft SQLite database not found: {db_path}")
        return sqlite3.connect(db_path)

    def verify_minecraft_data(self):
        # Check Minecraft data integrity
        try:
            if self.use_database:
                session, engine = self._get_minecraft_session()
                try:
                    total = session.execute(text(
                        "SELECT COUNT(*) FROM minecraft_servers"
                    )).scalar()

                    # Count by modloader
                    modloaders = session.execute(text(
                        "SELECT modloader, COUNT(*) FROM minecraft_servers GROUP BY modloader"
                    )).fetchall()

                    # Check for entries without version_id
                    no_version = session.execute(text(
                        "SELECT COUNT(*) FROM minecraft_servers WHERE version_id IS NULL OR version_id = ''"
                    )).scalar()
                finally:
                    session.close()
            else:
                conn = self._get_minecraft_sqlite()
                try:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM minecraft_servers"
                    ).fetchone()[0]
                    modloaders = conn.execute(
                        "SELECT modloader, COUNT(*) FROM minecraft_servers GROUP BY modloader"
                    ).fetchall()
                    no_version = conn.execute(
                        "SELECT COUNT(*) FROM minecraft_servers WHERE version_id IS NULL OR version_id = ''"
                    ).fetchone()[0]
                finally:
                    conn.close()

            modloader_counts = {row[0]: row[1] for row in modloaders}

            self.results['minecraft']['stats'] = {
                'total_versions': total,
                'modloaders': modloader_counts,
                'missing_version_id': no_version
            }

            if no_version:
                self.results['minecraft']['issues'].append(
                    f"{no_version} entries with empty or NULL version_id"
                )

            if total == 0:
                self.results['minecraft']['issues'].append(
                    "Minecraft database is empty — run Update Databases first"
                )

        except Exception as e:
            self.results['minecraft']['issues'].append(f"Data check failed: {e}")
            logger.error(f"Minecraft data verification failed: {e}")

    # ── Public API ──────────────────────────────────────────────────────

    def verify_all(self):
        # Run all verification checks and return results
        logger.info("Starting database verification...")

        if self.dry_run:
            logger.info("Running in DRY RUN mode — no changes will be made")

        # Steam checks
        try:
            self.verify_steam_schema()
            self.verify_steam_data()
            self.results['steam']['status'] = (
                'issues_found' if self.results['steam']['issues'] else 'ok'
            )
        except Exception as e:
            self.results['steam']['status'] = 'error'
            self.results['steam']['issues'].append(f"Verification error: {e}")

        # Minecraft checks
        try:
            self.verify_minecraft_data()
            self.results['minecraft']['status'] = (
                'issues_found' if self.results['minecraft']['issues'] else 'ok'
            )
        except Exception as e:
            self.results['minecraft']['status'] = 'error'
            self.results['minecraft']['issues'].append(f"Verification error: {e}")

        logger.info("Database verification complete")
        return self.results

    def get_summary_text(self):
        # Return a human-readable summary of the verification results
        lines = []

        # Steam summary
        lines.append("═" * 55)
        lines.append("  STEAM DATABASE")
        lines.append("═" * 55)
        steam = self.results['steam']
        stats = steam.get('stats', {})
        if stats:
            lines.append(f"  Total Applications:    {stats.get('total_apps', 0):,}")
            lines.append(f"  Server Applications:   {stats.get('server_apps', 0):,}")
            lines.append(f"  Dedicated Servers:     {stats.get('dedicated_servers', 0):,}")
            if stats.get('empty_names'):
                lines.append(f"  Empty Names:           {stats['empty_names']:,}")
            if stats.get('duplicate_appids'):
                lines.append(f"  Duplicate AppIDs:      {stats['duplicate_appids']:,}")

        if steam['issues']:
            lines.append("")
            lines.append("  Issues:")
            for issue in steam['issues']:
                lines.append(f"    • {issue}")
        else:
            lines.append("")
            lines.append("  No issues found")

        lines.append("")

        # Minecraft summary
        lines.append("═" * 55)
        lines.append("  MINECRAFT DATABASE")
        lines.append("═" * 55)
        mc = self.results['minecraft']
        mc_stats = mc.get('stats', {})
        if mc_stats:
            lines.append(f"  Total Versions:        {mc_stats.get('total_versions', 0):,}")
            modloaders = mc_stats.get('modloaders', {})
            for loader, count in sorted(modloaders.items()):
                lines.append(f"    {loader:20s} {count:,}")
            if mc_stats.get('missing_version_id'):
                lines.append(f"  Missing Version IDs:   {mc_stats['missing_version_id']:,}")

        if mc['issues']:
            lines.append("")
            lines.append("  Issues:")
            for issue in mc['issues']:
                lines.append(f"    • {issue}")
        else:
            lines.append("")
            lines.append("  No issues found")

        lines.append("")
        lines.append("═" * 55)

        return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description='Verify database integrity')
    parser.add_argument('--dry-run', action='store_true',
                        help='Only report issues without making changes')
    parser.add_argument('--no-database', action='store_true',
                        help='Use SQLite fallback instead of main database')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    verifier = DatabaseVerifier(
        use_database=not args.no_database,
        dry_run=args.dry_run
    )

    verifier.verify_all()
    print(verifier.get_summary_text())

if __name__ == "__main__":
    main()
