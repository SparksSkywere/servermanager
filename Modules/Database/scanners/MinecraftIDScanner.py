# Minecraft server scanner
import os
import sys
import logging
import requests
import json
import time
import re
from datetime import datetime, timezone
import argparse

# Pre-compiled version pattern for Fabric version filtering
_MC_VERSION_PATTERN = re.compile(r'^1\.\d+(\.\d+)?$')

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from Modules.core.common import setup_module_path
setup_module_path()

try:
    from Modules.Database.minecraft_database import get_minecraft_engine
    from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("Warning: SQLAlchemy not available, SQLite fallback")

from Modules.core.server_logging import get_component_logger
logger = get_component_logger("MinecraftIDScanner")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("MinecraftIDScanner debug mode")

# DB models
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()  # type: ignore[possibly-unbound]

    class MinecraftServer(Base):  # type: ignore[valid-type, misc]
        __tablename__ = 'minecraft_servers'

        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[possibly-unbound]
        version_id = Column(String(50), nullable=False, unique=True)  # type: ignore[possibly-unbound]
        version_type = Column(String(20))  # type: ignore[possibly-unbound]
        modloader = Column(String(20))  # type: ignore[possibly-unbound]
        modloader_version = Column(String(50))  # type: ignore[possibly-unbound]
        java_requirement = Column(Integer)  # type: ignore[possibly-unbound]
        download_url = Column(Text)  # type: ignore[possibly-unbound]
        installer_url = Column(Text)  # type: ignore[possibly-unbound]
        release_date = Column(String(50))  # type: ignore[possibly-unbound]
        description = Column(Text)  # type: ignore[possibly-unbound]
        is_dedicated_server = Column(Boolean, default=True)  # type: ignore[possibly-unbound]
        is_recommended = Column(Boolean, default=False)  # type: ignore[possibly-unbound]
        last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # type: ignore[possibly-unbound]
        source = Column(String(50), default='mojang')  # type: ignore[possibly-unbound]

class MinecraftIDScanner:
    def __init__(self, use_database=True, debug_mode=False):
        if not use_database:
            raise Exception("Database must be enabled for MinecraftIDScanner - SQLite fallback not supported")

        if not SQLALCHEMY_AVAILABLE:
            raise Exception("SQLAlchemy is required for MinecraftIDScanner - database functionality unavailable")

        self.use_database = True
        self.debug_mode = debug_mode
        self.session_requests = requests.Session()
        self.session_requests.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Rate limiting
        self.request_delay = 0.2  # Reduced from 1.0 for faster scanning
        self.last_request_time = 0
        self.rate_limit_backoff = 1.0  # Reduced from 2.0
        self.max_rate_limit_backoff = 10.0  # Reduced from 30.0

        # Initialise database (NO FALLBACKS)
        self.init_database()

    def init_database(self):
        # Initialise SQLAlchemy database connection (NO FALLBACKS)
        try:
            self.engine = get_minecraft_engine()  # type: ignore[possibly-unbound]
            Base.metadata.create_all(self.engine)  # type: ignore[possibly-unbound]
            Session = sessionmaker(bind=self.engine)  # type: ignore[possibly-unbound]
            self.db_session = Session()
            logger.debug("Connected to Minecraft servers database")
        except Exception as e:
            error_msg = f"Failed to connect to Minecraft database: {e}"
            logger.error(error_msg)
            raise Exception(f"Minecraft database connection failed: {e}")

    def init_sqlite_fallback(self):
        # REMOVED: SQLite fallback no longer supported
        raise Exception("SQLite fallback database is no longer supported - database must be available")

    def save_server_to_database(self, server_data):
        # Save server data to database
        try:
            if self.use_database:
                # Check if server already exists
                existing = self.db_session.query(MinecraftServer).filter(
                    MinecraftServer.version_id == server_data["version_id"]
                ).first()

                if existing:
                    # Update existing server
                    for key, value in server_data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    # Update last_updated timestamp
                    setattr(existing, 'last_updated', datetime.now(timezone.utc))
                    self.db_session.commit()
                    logger.debug(f"Updated existing server: {server_data['version_id']}")
                else:
                    # Create new server entry
                    server = MinecraftServer(
                        version_id=server_data["version_id"],
                        version_type=server_data["version_type"],
                        modloader=server_data["modloader"],
                        modloader_version=server_data["modloader_version"],
                        java_requirement=server_data["java_requirement"],
                        download_url=server_data["download_url"],
                        installer_url=server_data["installer_url"],
                        release_date=server_data["release_time"],
                        is_dedicated_server=True,
                        is_recommended=server_data["is_recommended"],
                        source=server_data["source"]
                    )
                    self.db_session.add(server)
                    self.db_session.commit()
                    logger.debug(f"Added new server: {server_data['version_id']}")

        except Exception as e:
            logger.error(f"Failed to save server {server_data.get('version_id', 'unknown')} to database: {e}")
            raise Exception(f"Database save failed: {e}")

    def rate_limit(self):
        # Implement rate limiting
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.request_delay:
            sleep_time = self.request_delay - time_since_last
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def make_request(self, url, params=None, retries=3):
        # Make HTTP request with retry logic
        for attempt in range(retries):
            try:
                self.rate_limit()
                logger.debug(f"Making request to {url} (attempt {attempt + 1}/{retries})")
                response = self.session_requests.get(url, params=params, timeout=10)
                response.raise_for_status()

                # Special handling for NeoForge API debugging
                if "neoforged.net" in url:
                    logger.debug(f"NeoForge API response status: {response.status_code}")
                    logger.debug(f"NeoForge API response length: {len(response.text)}")

                return response.json()
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP error on attempt {attempt + 1} for {url}: {e}")
                if e.response.status_code == 429:  # Rate limit
                    logger.info("Rate limited, backing off...")
                    time.sleep(self.rate_limit_backoff * (2 ** attempt))
                elif attempt < retries - 1:
                    time.sleep(self.rate_limit_backoff * (2 ** attempt))
                else:
                    logger.error(f"All retry attempts failed for {url}: {e}")
                    return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error on attempt {attempt + 1} for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(self.rate_limit_backoff * (2 ** attempt))
                else:
                    logger.error(f"All retry attempts failed for {url}: {e}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(self.rate_limit_backoff * (2 ** attempt))
                else:
                    logger.error(f"All retry attempts failed for {url} - JSON decode error")
                    return None
            except Exception as e:
                logger.warning(f"Request attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(self.rate_limit_backoff * (2 ** attempt))
                else:
                    logger.error(f"All retry attempts failed for {url}")
                    return None

    def fetch_vanilla_versions(self):
        # Fetch vanilla Minecraft versions from Mojang
        try:
            manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
            manifest = self.make_request(manifest_url)
            if not manifest:
                return []

            versions = []
            for v in manifest.get("versions", []):
                if v["type"] in ("release", "snapshot"):
                    versions.append({
                        "version_id": v["id"],
                        "version_type": v["type"],
                        "modloader": "vanilla",
                        "url": v["url"],
                        "release_time": v["releaseTime"]
                    })
            return versions
        except Exception as e:
            logger.error(f"Failed to fetch vanilla versions: {e}")
            return []

    def fetch_fabric_versions(self):
        # Fetch Fabric versions - get comprehensive but not exhaustive combinations
        try:
            meta_url = "https://meta.fabricmc.net/v2/versions"
            versions_data = self.make_request(meta_url)
            if not versions_data:
                return []

            fabric_versions = []
            game_versions = versions_data.get("game", [])
            loader_versions = versions_data.get("loader", [])

            if game_versions and loader_versions:
                # Strategy: Include only the latest loader for each stable game version
                latest_loader = loader_versions[0]["version"]

                for game_ver in game_versions:
                    # Only include stable releases (filter out snapshots and pre-releases)
                    if not game_ver.get("stable", False):
                        continue

                    version_id = game_ver["version"]

                    # Additional filtering: exclude experimental snapshots, combat snapshots, and weekly snapshots
                    if any(keyword in version_id.lower() for keyword in [
                        'experimental', 'snapshot', 'combat', 'pre', 'rc', 'alpha', 'beta',
                        'w', '_', 'potato', 'or_b'  # Additional snapshot indicators
                    ]):
                        continue

                    # Only include standard version numbers (like 1.20.1, 1.19.2, etc.)
                    if not _MC_VERSION_PATTERN.match(version_id):
                        continue

                    # Only include the latest loader for each game version (no duplicates)
                    fabric_versions.append({
                        "version_id": version_id,
                        "version_type": "release",
                        "modloader": "fabric",
                        "modloader_version": latest_loader,
                        "release_time": game_ver.get("releaseTime", "")
                    })

            logger.info(f"Fetched {len(fabric_versions)} Fabric versions (optimized for usability)")
            return fabric_versions
        except Exception as e:
            logger.error(f"Failed to fetch Fabric versions: {e}")
            return []

    def fetch_forge_versions(self):
        # Fetch Forge versions - get all available versions, not just recommended
        try:
            promotions_url = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
            promotions = self.make_request(promotions_url)
            if not promotions:
                return []

            forge_versions = []
            promos = promotions.get("promos", {})

            # Collect all unique Minecraft versions that have any Forge version
            seen_versions = set()

            for key, version in promos.items():
                # Remove the suffix to get the base Minecraft version
                if "-recommended" in key:
                    mc_version = key.replace("-recommended", "")
                elif "-latest" in key:
                    mc_version = key.replace("-latest", "")
                else:
                    # For keys without suffix, they might be in format "1.20.1-47.2.0"
                    continue

                if mc_version not in seen_versions:
                    seen_versions.add(mc_version)
                    forge_versions.append({
                        "version_id": mc_version,
                        "version_type": "release",
                        "modloader": "forge",
                        "modloader_version": version,
                        "release_time": ""
                    })

            logger.info(f"Fetched {len(forge_versions)} Forge versions")
            return forge_versions
        except Exception as e:
            logger.error(f"Failed to fetch Forge versions: {e}")
            raise Exception(f"Forge version fetch failed: {e}")

    def fetch_neoforge_versions(self):
        # Fetch NeoForge versions using the official API
        try:
            # Use the official NeoForge API to get all versions
            api_url = "https://api.neoforged.net/v1/projects/neoforge/versions"
            logger.debug(f"Fetching NeoForge versions from API: {api_url}")

            versions_data = self.make_request(api_url)
            if not versions_data:
                logger.error("Failed to fetch NeoForge versions from API")
                raise Exception("NeoForge API request failed")

            neoforge_versions = []
            seen_versions = set()

            # Process each version from the API
            for version_info in versions_data:
                # Extract Minecraft version from the version info
                game_versions = version_info.get("game_versions", [])
                neoforge_version = version_info.get("version")

                if game_versions and neoforge_version:
                    for mc_version in game_versions:
                        # Clean up version format (remove extra dots, etc.)
                        clean_mc_version = mc_version.strip()
                        if clean_mc_version and clean_mc_version not in seen_versions:
                            seen_versions.add(clean_mc_version)
                            neoforge_versions.append({
                                "version_id": clean_mc_version,
                                "version_type": "release",
                                "modloader": "neoforge",
                                "modloader_version": neoforge_version,
                                "release_time": ""
                            })
                            logger.debug(f"Added NeoForge version: MC {clean_mc_version}, NeoForge {neoforge_version}")

            if neoforge_versions:
                logger.info(f"Successfully fetched {len(neoforge_versions)} NeoForge versions from API")
                return neoforge_versions
            else:
                logger.error("No NeoForge versions found from API")
                raise Exception("No NeoForge versions available from API")

        except Exception as e:
            logger.error(f"Failed to fetch NeoForge versions from API: {e}")
            if self.debug_mode:
                import traceback
                logger.debug(f"NeoForge API fetch traceback: {traceback.format_exc()}")
            raise Exception(f"NeoForge version fetch failed: {e}")

    def get_java_requirement(self, version_id):
        # Get Java requirement for a Minecraft version
        try:
            if version_id.startswith('1.'):
                version_parts = version_id.split('.')
                if len(version_parts) >= 2:
                    major = int(version_parts[1])
                    if major <= 16:
                        return 8
                    elif major == 17:
                        return 16
                    elif major <= 20:
                        return 17
                    else:
                        return 21

            # Snapshots and future versions
            if 'w' in version_id or version_id.startswith(('2', '3')):
                return 21

            return 17  # Default
        except (ValueError, TypeError, AttributeError):
            return 17

    def _clear_modloader_entries(self, modloader):
        # Clear all entries for a specific modloader to remove outdated versions (NO FALLBACKS)
        try:
            # SQLAlchemy - delete all entries for this modloader
            deleted_count = self.db_session.query(MinecraftServer).filter(MinecraftServer.modloader == modloader).delete()
            self.db_session.commit()
            logger.info(f"Cleared {deleted_count} existing {modloader} entries from database")
        except Exception as e:
            logger.error(f"Failed to clear {modloader} entries: {e}")
            raise Exception(f"Database clear operation failed: {e}")

    def scan_minecraft_servers(self, limit=None):
        # Main scanning function
        logger.info("Starting Minecraft server scan...")

        all_versions = []

        # Fetch versions from all modloaders with error handling
        try:
            logger.info("Fetching vanilla versions...")
            vanilla_versions = self.fetch_vanilla_versions()
            all_versions.extend(vanilla_versions)
            logger.info(f"Fetched {len(vanilla_versions)} vanilla versions")
        except Exception as e:
            logger.error(f"Failed to fetch vanilla versions: {e}")

        try:
            logger.info("Fetching Fabric versions...")
            # Clear existing Fabric entries before scanning to remove old experimental versions
            self._clear_modloader_entries("fabric")
            fabric_versions = self.fetch_fabric_versions()
            all_versions.extend(fabric_versions)
            logger.info(f"Fetched {len(fabric_versions)} Fabric versions")
        except Exception as e:
            logger.error(f"Failed to fetch Fabric versions: {e}")

        try:
            logger.info("Fetching Forge versions...")
            forge_versions = self.fetch_forge_versions()
            all_versions.extend(forge_versions)
            logger.info(f"Fetched {len(forge_versions)} Forge versions")
        except Exception as e:
            logger.error(f"Failed to fetch Forge versions: {e}")

        try:
            logger.info("Fetching NeoForge versions...")
            neoforge_versions = self.fetch_neoforge_versions()
            if neoforge_versions:
                all_versions.extend(neoforge_versions)
                logger.info(f"Fetched {len(neoforge_versions)} NeoForge versions")
            else:
                logger.info("Fetched 0 NeoForge versions")
        except Exception as e:
            logger.error(f"Failed to fetch NeoForge versions: {e}")

        logger.info(f"Total versions fetched: {len(all_versions)}")

        # Process and save versions
        processed = 0
        skipped = 0
        for i, version_data in enumerate(all_versions):
            if limit and processed >= limit:
                break

            try:
                if self.debug_mode and i % 10 == 0:
                    logger.debug(f"Processing version {i+1}/{len(all_versions)}: {version_data.get('modloader', 'unknown')} {version_data.get('version_id', 'unknown')}")

                # Get Java requirement
                java_req = self.get_java_requirement(version_data["version_id"])

                # Get download URLs (skip if this fails to avoid blocking the whole scan)
                urls = {"download_url": "", "installer_url": ""}

                # Prepare server data
                server_data = {
                    "version_id": version_data["version_id"],
                    "version_type": version_data["version_type"],
                    "modloader": version_data["modloader"],
                    "modloader_version": version_data.get("modloader_version", ""),
                    "java_requirement": java_req,
                    "download_url": urls.get("download_url"),
                    "installer_url": urls.get("installer_url"),
                    "release_time": version_data.get("release_time", ""),
                    "is_recommended": version_data["version_type"] == "release",
                    "source": "mojang"
                }

                self.save_server_to_database(server_data)
                processed += 1

            except Exception as e:
                logger.warning(f"Failed to process version {version_data}: {e}")
                skipped += 1
                # Continue processing other versions

        logger.info(f"Scan complete. Processed {processed} Minecraft server versions, skipped {skipped}.")
        return processed

    def get_servers_from_database(self, modloader=None, dedicated_only=True, filter_snapshots=True):
        # Get servers from database
        try:
            if self.use_database:
                query = self.db_session.query(MinecraftServer)
                if modloader:
                    query = query.filter(MinecraftServer.modloader == modloader)
                if dedicated_only:
                    query = query.filter(MinecraftServer.is_dedicated_server == True)

                servers = query.all()
                server_list = [{
                    "id": s.id,
                    "version_id": s.version_id,
                    "version_type": s.version_type,
                    "modloader": s.modloader,
                    "modloader_version": s.modloader_version,
                    "java_requirement": s.java_requirement,
                    "download_url": s.download_url,
                    "installer_url": s.installer_url,
                    "release_date": s.release_date,
                    "is_recommended": s.is_recommended
                } for s in servers]

                # Sort using proper version comparison (newest first)
                sorted_servers = self.sort_versions_desc(server_list)

                # Filter snapshots if requested
                if filter_snapshots:
                    sorted_servers = self.filter_snapshots_by_mainstream(sorted_servers)

                return sorted_servers

        except Exception as e:
            logger.error(f"Failed to get servers from database: {e}")
            raise Exception(f"Database query failed: {e}")

    def get_dedicated_server_versions(self, modloader=None, filter_snapshots=True):
        # Get only versions that support dedicated servers
        return self.get_servers_from_database(modloader=modloader, dedicated_only=True, filter_snapshots=filter_snapshots)

    def parse_version(self, version_id):
        # Parse Minecraft version ID into sortable components
        try:
            # Handle special cases first
            if version_id.startswith('3D Shareware'):
                # Old development version - treat as very old
                return (-999, 0, 0, 0, '', '')

            # Pre-Release versions (e.g., "1.14 Pre-Release 1")
            if 'Pre-Release' in version_id:
                base_version = version_id.split(' Pre-Release')[0]
                pre_num_match = re.search(r'Pre-Release (\d+)', version_id)
                pre_num = int(pre_num_match.group(1)) if pre_num_match else 1

                # Parse base version
                version_parts = base_version.split('.')
                major = int(version_parts[0]) if version_parts[0].isdigit() else 0
                minor = int(version_parts[1]) if len(version_parts) > 1 and version_parts[1].isdigit() else 0
                patch = int(version_parts[2]) if len(version_parts) > 2 and version_parts[2].isdigit() else 0

                return (major, minor, patch, -pre_num, '', 'pre')

            # Weekly snapshots (e.g., "25w37a")
            if 'w' in version_id and version_id[0].isdigit():
                parts = version_id.split('w')
                if len(parts) == 2:
                    year = int(parts[0])
                    week_part = parts[1]
                    # Extract week number and suffix
                    week_match = re.match(r'(\d+)([a-z]*)', week_part)
                    if week_match:
                        week = int(week_match.group(1))
                        suffix = week_match.group(2) or ''
                        return (year, week, 0, 0, suffix, 'weekly')

            # Release candidates and pre-releases (e.g., "1.21.8-rc1", "1.21.6-pre4")
            if '-rc' in version_id or '-pre' in version_id:
                base_version = version_id.split('-')[0]
                suffix_type = 'rc' if '-rc' in version_id else 'pre'
                suffix_num = 0

                # Extract suffix number
                if '-rc' in version_id:
                    rc_match = re.search(r'-rc(\d+)', version_id)
                    if rc_match:
                        suffix_num = int(rc_match.group(1))
                elif '-pre' in version_id:
                    pre_match = re.search(r'-pre(\d+)', version_id)
                    if pre_match:
                        suffix_num = int(pre_match.group(1))

                # Parse base version
                version_parts = base_version.split('.')
                major = int(version_parts[0]) if version_parts[0].isdigit() else 0
                minor = int(version_parts[1]) if len(version_parts) > 1 and version_parts[1].isdigit() else 0
                patch = int(version_parts[2]) if len(version_parts) > 2 and version_parts[2].isdigit() else 0

                return (major, minor, patch, -suffix_num, '', suffix_type)

            # Standard release versions (e.g., "1.21.8", "1.20.6")
            version_parts = version_id.split('.')
            major = int(version_parts[0]) if version_parts[0].isdigit() else 0
            minor = int(version_parts[1]) if len(version_parts) > 1 and version_parts[1].isdigit() else 0
            patch = int(version_parts[2]) if len(version_parts) > 2 and version_parts[2].isdigit() else 0

            return (major, minor, patch, 999, '', 'release')

        except Exception as e:
            # Fallback for unparseable versions
            return (0, 0, 0, 0, version_id, 'unknown')

    def sort_versions_desc(self, servers):
        # Sort servers by version in descending order (newest first)
        def sort_key(server):
            version_id = server['version_id']
            parsed = self.parse_version(version_id)
            # Return negative values for descending sort
            return (-parsed[0], -parsed[1], -parsed[2], -parsed[3], parsed[4], parsed[5])

        return sorted(servers, key=sort_key)

    def filter_snapshots_by_mainstream(self, servers, keep_mainstream_only=True):
        # Filter to keep only mainstream release versions (no snapshots)
        if not keep_mainstream_only:
            return servers

        filtered = []

        for server in servers:
            version_type = server['version_type']

            # Only keep releases, filter out all snapshots
            if version_type == 'release':
                filtered.append(server)

        return filtered

    def search_servers(self, query, modloader=None):
        # Search servers by version or modloader
        try:
            servers = self.get_servers_from_database(modloader=modloader)
            if not servers:
                return []
            if not query:
                return servers

            filtered = []
            query_lower = query.lower()
            for server in servers:
                if (query_lower in server["version_id"].lower() or
                    query_lower in server["modloader"].lower()):
                    filtered.append(server)

            return filtered
        except Exception as e:
            logger.error(f"Failed to search servers: {e}")
            return []

    def get_recommended_servers(self, modloader=None):
        # Get recommended servers
        try:
            if self.use_database:
                query = self.db_session.query(MinecraftServer).filter(MinecraftServer.is_recommended == True)
                if modloader:
                    query = query.filter(MinecraftServer.modloader == modloader)

                servers = query.all()
                return [{
                    "version_id": s.version_id,
                    "modloader": s.modloader,
                    "modloader_version": s.modloader_version,
                    "java_requirement": s.java_requirement
                } for s in servers]

        except Exception as e:
            logger.error(f"Failed to get recommended servers: {e}")
            raise Exception(f"Database query failed: {e}")

    def get_database_stats(self):
        # Get database statistics
        try:
            total = 0
            by_modloader = {}
            if self.use_database:
                total = self.db_session.query(MinecraftServer).count()  # type: ignore[possibly-unbound]
                for modloader in ["vanilla", "fabric", "forge", "neoforge"]:
                    count = self.db_session.query(MinecraftServer).filter(MinecraftServer.modloader == modloader).count()  # type: ignore[possibly-unbound]
                    by_modloader[modloader] = count

            return {
                "total_servers": total,
                "by_modloader": by_modloader,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            raise Exception(f"Database query failed: {e}")

    def close(self):
        # Close database connections
        try:
            if self.use_database and hasattr(self, 'db_session'):
                self.db_session.close()
        except Exception as e:
            logger.warning(f"Error closing database connection: {e}")

def main():
    parser = argparse.ArgumentParser(description='Minecraft Server Scanner')
    parser.add_argument('--limit', type=int, help='Limit number of versions to scan')
    parser.add_argument('--modloader', type=str, choices=['vanilla', 'fabric', 'forge', 'neoforge'],
                       help='Scan only specific modloader')
    parser.add_argument('--search', type=str, help='Search for servers by version')
    parser.add_argument('--list-servers', action='store_true', help='List all server versions')
    parser.add_argument('--recommended', action='store_true', help='Show only recommended versions')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--no-database', action='store_true', help='Use SQLite fallback instead of main database')
    parser.add_argument('--no-filter', action='store_true', help='Show all snapshots (don\'t filter by mainstream versions)')

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Create scanner instance
    scanner = MinecraftIDScanner(use_database=not args.no_database, debug_mode=args.debug)

    try:
        if args.list_servers:
            try:
                servers = scanner.get_dedicated_server_versions(modloader=args.modloader, filter_snapshots=not args.no_filter)
                if not servers:
                    servers = []
                filter_status = "filtered" if not args.no_filter else "unfiltered"
                print(f"\nFound {len(servers)} Minecraft servers ({filter_status}):")
                for server in servers[:50]:  # Limit output
                    print(f"  {server['modloader'].title()} {server['version_id']} (Java {server['java_requirement']})")
                if len(servers) > 50:
                    print(f"  ... and {len(servers) - 50} more")
            except Exception as e:
                print(f"Error retrieving server versions: {e}")

        elif args.recommended:
            try:
                servers = scanner.get_recommended_servers(modloader=args.modloader)
                if not servers:
                    servers = []
                print(f"\nRecommended Minecraft servers:")
                for server in servers:
                    print(f"  {server['modloader'].title()} {server['version_id']} (Java {server['java_requirement']})")
            except Exception as e:
                print(f"Error retrieving recommended servers: {e}")

        elif args.search:
            try:
                servers = scanner.search_servers(args.search, modloader=args.modloader)
                if not servers:
                    servers = []
                print(f"\nSearch results for '{args.search}':")
                for server in servers:
                    print(f"  {server['modloader'].title()} {server['version_id']} (Java {server['java_requirement']})")
            except Exception as e:
                print(f"Error searching servers: {e}")

        elif args.stats:
            try:
                stats = scanner.get_database_stats()
                print(f"\nDatabase Statistics:")
                print(f"  Total servers: {stats['total_servers']}")
                print(f"  By modloader:")
                for modloader, count in stats['by_modloader'].items():
                    print(f"    {modloader.title()}: {count}")
            except Exception as e:
                print(f"Error retrieving database stats: {e}")

        else:
            # Default: scan for new servers
            try:
                processed = scanner.scan_minecraft_servers(limit=args.limit)
                print(f"Scan complete. Processed {processed} server versions.")
            except Exception as e:
                print(f"Error scanning servers: {e}")

    finally:
        scanner.close()

if __name__ == "__main__":
    main()

