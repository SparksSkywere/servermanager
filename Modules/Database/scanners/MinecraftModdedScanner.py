# Minecraft modded pack scanner - ATLauncher, FTB, Technic, CurseForge
import os
import sys
import logging
import requests
import json
import time
import argparse
from datetime import datetime, timezone

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
from Modules.core.common import setup_module_path
setup_module_path()

try:
    from Modules.Database.minecraft_modded_database import get_minecraft_modded_engine
    from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, UniqueConstraint
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("Warning: SQLAlchemy not available for MinecraftModdedScanner")

from Modules.core.server_logging import get_component_logger
logger = get_component_logger("MinecraftModdedScanner")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)

SUPPORTED_LAUNCHERS = ["atlauncher", "ftb", "technic", "modrinth", "curseforge"]

# DB models
if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()  # type: ignore[possibly-unbound]

    class ModdedPack(Base):  # type: ignore[valid-type, misc]
        __tablename__ = 'modded_packs'
        __table_args__ = (UniqueConstraint('pack_id', 'launcher', name='uq_pack_launcher'),)  # type: ignore[possibly-unbound]

        id             = Column(Integer, primary_key=True, autoincrement=True)        # type: ignore[possibly-unbound]
        pack_id        = Column(String(200), nullable=False)                          # type: ignore[possibly-unbound]
        pack_slug      = Column(String(200))                                          # type: ignore[possibly-unbound]
        name           = Column(String(300), nullable=False)                          # type: ignore[possibly-unbound]
        launcher       = Column(String(50), nullable=False)                           # type: ignore[possibly-unbound]
        description    = Column(Text)                                                 # type: ignore[possibly-unbound]
        authors        = Column(String(500))                                          # type: ignore[possibly-unbound]
        mc_version     = Column(String(100))   # latest/representative MC version    # type: ignore[possibly-unbound]
        modloader      = Column(String(50))                                           # type: ignore[possibly-unbound]
        pack_version   = Column(String(100))   # latest pack version string           # type: ignore[possibly-unbound]
        thumbnail_url  = Column(Text)                                                 # type: ignore[possibly-unbound]
        server_url     = Column(Text)          # direct server-pack download URL      # type: ignore[possibly-unbound]
        install_url    = Column(Text)          # API / meta URL for install steps     # type: ignore[possibly-unbound]
        play_count     = Column(Integer, default=0)                                   # type: ignore[possibly-unbound]
        is_server_pack = Column(Boolean, default=True)                               # type: ignore[possibly-unbound]
        last_updated   = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # type: ignore[possibly-unbound]

class MinecraftModdedScanner:
    def __init__(self, curseforge_api_key: str = "", debug_mode: bool = False):
        if not SQLALCHEMY_AVAILABLE:
            raise Exception("SQLAlchemy is required for MinecraftModdedScanner")

        self.debug_mode = debug_mode
        self.curseforge_api_key = curseforge_api_key
        self.session_requests = requests.Session()
        self.session_requests.headers.update({
            'User-Agent': 'ServerManager/1.0 (github.com/SparksSkywere/servermanager)'
        })
        self.request_delay = 0.3
        self.last_request_time = 0.0

        self.engine = get_minecraft_modded_engine()  # type: ignore[possibly-unbound]
        Base.metadata.create_all(self.engine)        # type: ignore[possibly-unbound]
        Session = sessionmaker(bind=self.engine)     # type: ignore[possibly-unbound]
        self.db_session = Session()

    # HTTP helpers
    def _rate_limit(self):
        now = time.time()
        wait = self.request_delay - (now - self.last_request_time)
        if wait > 0:
            time.sleep(wait)
        self.last_request_time = time.time()

    def _get(self, url: str, params=None, headers: dict = None, retries: int = 3):
        for attempt in range(retries):
            try:
                self._rate_limit()
                hdrs = dict(self.session_requests.headers)
                if headers:
                    hdrs.update(headers)
                resp = self.session_requests.get(url, params=params, headers=hdrs, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if code == 429:
                    time.sleep(min(5 * (2 ** attempt), 30))
                elif attempt >= retries - 1:
                    logger.warning(f"HTTP {code} on {url}: {exc}")
                    return None
                else:
                    time.sleep(1 * (2 ** attempt))
            except requests.exceptions.RequestException as exc:
                if attempt >= retries - 1:
                    logger.warning(f"Request failed {url}: {exc}")
                    return None
                time.sleep(1 * (2 ** attempt))
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"JSON decode error for {url}")
                return None
        return None

    # DB helpers
    def _upsert_pack(self, data: dict):
        try:
            existing = (
                self.db_session.query(ModdedPack)  # type: ignore[possibly-unbound]
                .filter_by(pack_id=data['pack_id'], launcher=data['launcher'])
                .first()
            )
            if existing:
                for k, v in data.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
                existing.last_updated = datetime.now(timezone.utc)
            else:
                self.db_session.add(ModdedPack(**data))  # type: ignore[possibly-unbound]
            self.db_session.commit()
        except Exception as exc:
            self.db_session.rollback()
            logger.error(f"DB upsert failed for {data.get('name','?')}: {exc}")

    # ATLauncher
    def fetch_atlauncher_packs(self):
        # Fetch all public packs from the ATLauncher API
        logger.info("Fetching ATLauncher packs...")
        data = self._get("https://api.atlauncher.com/v1/packs/simple")
        if not data:
            logger.error("ATLauncher API returned no data")
            return 0

        packs = data if isinstance(data, list) else data.get("data", [])
        saved = 0
        for pack in packs:
            try:
                if str(pack.get("type", "")).lower() != "public":
                    continue

                name = pack.get("name") or pack.get("safeName") or ""
                if not name:
                    continue

                safe_name = pack.get("safeName", "")
                # Bulk scan uses simple endpoint only to avoid API rate limits.
                pack_version = ""
                mc_version = ""
                loader = "forge"

                self._upsert_pack({
                    "pack_id":       str(safe_name or pack.get("id") or name),
                    "pack_slug":     str(safe_name),
                    "name":          name,
                    "launcher":      "atlauncher",
                    "description":   "",
                    "authors":       "",
                    "mc_version":    mc_version,
                    "modloader":     loader,
                    "pack_version":  pack_version,
                    "thumbnail_url": "",
                    "server_url":    "",
                    "install_url":   str(pack.get("__LINK") or f"https://api.atlauncher.com/v1/pack/{safe_name}"),
                    "play_count":    0,
                    "is_server_pack": True,
                })
                saved += 1
            except Exception as exc:
                logger.debug(f"Skipping ATLauncher pack {pack.get('name','?')}: {exc}")

        logger.info(f"ATLauncher: saved {saved} packs")
        return saved

    # FTB (Feed The Beast)
    def fetch_ftb_packs(self, limit: int = 100):
        # Fetch popular FTB packs via their public API
        logger.info("Fetching FTB packs...")
        limit = max(1, min(int(limit), 250))

        # Get a bounded list of popular pack IDs from the active public endpoint.
        overview = self._get(f"https://api.modpacks.ch/public/modpack/popular/installs/{limit}")
        if not overview:
            logger.error("FTB overview API returned no data")
            return 0

        pack_ids = overview.get("packs", []) if isinstance(overview, dict) else []
        if not pack_ids:
            logger.warning("FTB: no pack IDs found in overview response")
            return 0

        saved = 0
        for pack_id in pack_ids:
            try:
                detail = self._get(f"https://api.modpacks.ch/public/modpack/{pack_id}")
                if not detail or detail.get("status") == "error":
                    continue

                name = detail.get("name", "")
                if not name:
                    continue

                versions = detail.get("versions", []) or []
                latest = versions[-1] if versions else {}

                mc_version = ""
                loader = "forge"
                targets = latest.get("targets", []) or []
                for t in targets:
                    if t.get("type") == "game":
                        mc_version = t.get("version", "")
                    elif t.get("type") in ("forge", "fabric", "neoforge", "quilt"):
                        loader = t.get("type", "forge")

                authors = ", ".join(a.get("name", "") for a in (detail.get("authors") or []))
                thumbnail = ""
                for art in (detail.get("art") or []):
                    if art.get("type") == "square":
                        thumbnail = art.get("url", "")
                        break

                self._upsert_pack({
                    "pack_id":       str(pack_id),
                    "pack_slug":     "",
                    "name":          name,
                    "launcher":      "ftb",
                    "description":   detail.get("description", ""),
                    "authors":       authors,
                    "mc_version":    mc_version,
                    "modloader":     loader,
                    "pack_version":  str(latest.get("id") or latest.get("name", "")),
                    "thumbnail_url": thumbnail,
                    "server_url":    "",
                    "install_url":   f"https://api.modpacks.ch/public/modpack/{pack_id}",
                    "play_count":    int(detail.get("installs", 0) or detail.get("plays", 0) or 0),
                    "is_server_pack": True,
                })
                saved += 1
            except Exception as exc:
                logger.debug(f"Skipping FTB pack {pack_id}: {exc}")

        logger.info(f"FTB: saved {saved} packs")
        return saved

    # Technic
    def fetch_technic_pack(self, slug: str) -> bool:
        # Fetch a single Technic pack by slug. build=unset is required for public access.
        url = f"https://api.technicpack.net/modpack/{slug}"
        data = self._get(url, params={"build": "unset"})
        if not data or data.get("error") or data.get("status") == 401:
            logger.debug(f"Technic: pack '{slug}' not found or returned error")
            return False

        try:
            name = data.get("displayName") or data.get("name") or slug
            pack_version = str(data.get("version", "") or data.get("recommendedBuild", "") or "")
            minecraft_info = data.get("minecraft", "") or ""
            mc_version = minecraft_info if isinstance(minecraft_info, str) else minecraft_info.get("version", "")

            self._upsert_pack({
                "pack_id":       slug,
                "pack_slug":     slug,
                "name":          name,
                "launcher":      "technic",
                "description":   data.get("description", "") or "",
                "authors":       data.get("user", ""),
                "mc_version":    mc_version,
                "modloader":     "forge",
                "pack_version":  pack_version,
                "thumbnail_url": (data.get("logo") or {}).get("url", "") if isinstance(data.get("logo"), dict) else "",
                "server_url":    data.get("serverPackUrl", "") or (data.get("solder") or ""),
                "install_url":   data.get("platformUrl", "") or f"https://api.technicpack.net/modpack/{slug}",
                "play_count":    int(data.get("installs", 0) or data.get("downloads", 0) or 0),
                "is_server_pack": bool(data.get("serverPackUrl")),
            })
            return True
        except Exception as exc:
            logger.debug(f"Technic pack save error ({slug}): {exc}")
            return False

    def _technic_search_slugs(self, terms: list) -> list:
        # Query the Technic search endpoint for each term and collect unique slugs.
        seen = set()
        slugs = []
        for term in terms:
            try:
                data = self._get("https://api.technicpack.net/search",
                                 params={"q": term, "build": "unset"})
                if not data:
                    continue
                for pack in (data.get("modpacks") or []):
                    slug = pack.get("slug", "")
                    if slug and slug not in seen:
                        seen.add(slug)
                        slugs.append(slug)
            except Exception as exc:
                logger.debug(f"Technic search error for '{term}': {exc}")
        return slugs

    def fetch_technic_packs(self, slugs: list = None) -> int:
        # Fetch Technic packs. Discovers slugs via search then supplements with a
        # curated static list so well-known packs are always included.
        static_slugs = [
            "tekkit", "tekkit-classic", "hexxit", "bigdig", "attack-of-the-bteam",
            "blightfall", "tekkitmain", "yogscast-complete-pack", "agrarian-skies",
            "ftb-unleashed", "resonant-rise", "blood-n-bones", "crazy-craft-3",
            "sky-odyssey", "regrowth", "lapito-s-galacticraft-pack",
            "tekkit-legends", "sky-factory-2", "all-the-mods-5", "rlcraft",
            "dungeons-dragons-and-space-shuttles", "sevtech-ages", "the-1-7-10-pack",
        ]

        if slugs:
            all_slugs = list(dict.fromkeys(slugs + static_slugs))
        else:
            logger.info("Technic: discovering packs via search...")
            search_terms = ["skyblock", "adventure", "tech", "magic", "survival",
                            "modpack", "forge", "minecraft", "rpg", "space"]
            discovered = self._technic_search_slugs(search_terms)
            all_slugs = list(dict.fromkeys(static_slugs + discovered))
            logger.info(f"Technic: {len(all_slugs)} slugs to fetch ({len(discovered)} discovered + static list)")

        saved = sum(1 for s in all_slugs if self.fetch_technic_pack(s))
        if saved == 0:
            logger.warning("Technic returned zero packs. The API may be temporarily unavailable.")
        logger.info(f"Technic: saved {saved} packs")
        return saved

    # CurseForge
    def fetch_curseforge_packs(self, page_size: int = 50, max_pages: int = 20) -> int:
        # Fetch modpacks from the CurseForge API. Requires an API key
        api_key = (self.curseforge_api_key or "").strip()
        if not api_key:
            logger.warning("CurseForge API key not set – skipping CurseForge scan")
            return 0

        logger.info("Fetching CurseForge modpacks...")
        headers = {"x-api-key": api_key}
        saved = 0

        # Validate key against a minimal search call to provide a precise error.
        try:
            probe = self.session_requests.get(
                "https://api.curseforge.com/v1/mods/search",
                params={"gameId": 432, "classId": 4471, "pageSize": 1, "index": 0},
                headers={**self.session_requests.headers, **headers},
                timeout=15,
            )
            if probe.status_code == 403:
                logger.warning(
                    "CurseForge key rejected by /mods/search (403). "
                    "Key may be invalid, unapproved for this endpoint, or missing required permissions."
                )
                return 0
        except Exception as exc:
            logger.warning(f"CurseForge key probe failed: {exc}")
            return 0

        # Try to discover the active Modpacks classId dynamically.
        class_ids = []
        categories_resp = self._get(
            "https://api.curseforge.com/v1/categories",
            params={"gameId": 432},
            headers=headers,
        )
        if isinstance(categories_resp, dict):
            for cat in categories_resp.get("data", []) or []:
                name = str(cat.get("name", "")).lower()
                slug = str(cat.get("slug", "")).lower()
                if "modpack" in name or "modpack" in slug:
                    cid = cat.get("id")
                    if cid is not None:
                        class_ids.append(int(cid))

        # Keep legacy value as fallback if category probing changes.
        if 4471 not in class_ids:
            class_ids.append(4471)

        seen_mod_ids = set()

        for class_id in class_ids:
            got_any_for_class = False
            logger.info(f"CurseForge scan using classId={class_id}")
            for page in range(max_pages):
                params = {
                    "gameId": 432,
                    "classId": class_id,
                    "pageSize": page_size,
                    "index": page * page_size,
                    "sortField": 2,
                    "sortOrder": "desc",
                }
                resp = self._get("https://api.curseforge.com/v1/mods/search", params=params, headers=headers)
                if not resp:
                    break

                items = resp.get("data", []) if isinstance(resp, dict) else []
                if not items:
                    break

                got_any_for_class = True

                for mod in items:
                    try:
                        mod_id = mod.get("id")
                        if mod_id in seen_mod_ids:
                            continue
                        seen_mod_ids.add(mod_id)

                        name = mod.get("name", "")
                        if not name:
                            continue

                        # Prefer latest indexed file info if available, then fallback to first latest file.
                        latest_idx = (mod.get("latestFilesIndexes") or [{}])[0]
                        latest_file = (mod.get("latestFiles") or [{}])[0]
                        game_versions = latest_file.get("gameVersions", []) or []

                        mc_version = next((v for v in game_versions if isinstance(v, str) and v.startswith("1.")), "")
                        if not mc_version and latest_idx:
                            mc_version = str(latest_idx.get("gameVersion", ""))

                        loader_tag = next(
                            (v.lower() for v in game_versions
                             if isinstance(v, str) and v.lower() in ("forge", "fabric", "neoforge", "quilt")),
                            "forge"
                        )

                        server_pack_id = latest_file.get("serverPackFileId")
                        server_url = (
                            f"https://api.curseforge.com/v1/mods/{mod_id}/files/{server_pack_id}/download-url"
                            if server_pack_id else ""
                        )

                        authors = ", ".join(a.get("name", "") for a in (mod.get("authors") or []))
                        thumbnail = next(
                            (a.get("thumbnailUrl", "") for a in (mod.get("screenshots") or []) if a.get("thumbnailUrl")),
                            (mod.get("logo") or {}).get("thumbnailUrl", "") if isinstance(mod.get("logo"), dict) else ""
                        )

                        self._upsert_pack({
                            "pack_id":       str(mod_id),
                            "pack_slug":     mod.get("slug", ""),
                            "name":          name,
                            "launcher":      "curseforge",
                            "description":   mod.get("summary", ""),
                            "authors":       authors,
                            "mc_version":    mc_version,
                            "modloader":     loader_tag,
                            "pack_version":  str(latest_file.get("displayName", "") or latest_idx.get("filename", "")),
                            "thumbnail_url": thumbnail,
                            "server_url":    server_url,
                            "install_url":   f"https://api.curseforge.com/v1/mods/{mod_id}",
                            "play_count":    mod.get("downloadCount", 0) or 0,
                            "is_server_pack": bool(server_pack_id),
                        })
                        saved += 1
                    except Exception as exc:
                        logger.debug(f"Skipping CurseForge mod {mod.get('name','?')}: {exc}")

                pagination = resp.get("pagination", {}) if isinstance(resp, dict) else {}
                total = pagination.get("totalCount", 0)
                current_index = pagination.get("index", 0) + len(items)
                if current_index >= total:
                    break

            if got_any_for_class:
                # If this classId works, no need to re-query others.
                break

        if saved == 0:
            logger.warning(
                "CurseForge scan returned zero packs. Check API key validity/permissions and regional access limits."
            )

        logger.info(f"CurseForge: saved {saved} packs")
        return saved

    # Modrinth
    def fetch_modrinth_packs(self, page_size: int = 50, max_pages: int = 20) -> int:
        # Fetch modpacks from Modrinth public API (no API key required)
        logger.info("Fetching Modrinth modpacks...")
        saved = 0

        facets = '[["project_type:modpack"]]'
        page_size = max(1, min(int(page_size), 100))

        for page in range(max_pages):
            params = {
                "facets": facets,
                "index": "downloads",
                "limit": page_size,
                "offset": page * page_size,
            }
            resp = self._get("https://api.modrinth.com/v2/search", params=params)
            if not resp:
                break

            items = resp.get("hits", []) if isinstance(resp, dict) else []
            if not items:
                break

            for mod in items:
                try:
                    name = mod.get("title") or mod.get("name") or ""
                    if not name:
                        continue

                    categories = [str(c).lower() for c in (mod.get("categories") or [])]
                    versions = [str(v) for v in (mod.get("versions") or [])]

                    mc_version = next((v for v in versions if v and v[0].isdigit()), "")
                    loader = next((c for c in categories if c in ("forge", "fabric", "neoforge", "quilt")), "")

                    project_id = str(mod.get("project_id") or "")
                    slug = str(mod.get("slug") or "")
                    latest_version = str(mod.get("latest_version") or "")
                    server_side = str(mod.get("server_side") or "unknown").lower()

                    self._upsert_pack({
                        "pack_id":       project_id or slug,
                        "pack_slug":     slug,
                        "name":          name,
                        "launcher":      "modrinth",
                        "description":   mod.get("description", "") or "",
                        "authors":       str(mod.get("author", "") or ""),
                        "mc_version":    mc_version,
                        "modloader":     loader,
                        "pack_version":  latest_version,
                        "thumbnail_url": mod.get("icon_url", "") or "",
                        "server_url":    "",
                        "install_url":   f"https://modrinth.com/modpack/{slug}" if slug else "",
                        "play_count":    int(mod.get("downloads", 0) or 0),
                        "is_server_pack": server_side != "unsupported",
                    })
                    saved += 1
                except Exception as exc:
                    logger.debug(f"Skipping Modrinth modpack {mod.get('title','?')}: {exc}")

            total_hits = int(resp.get("total_hits", 0) or 0) if isinstance(resp, dict) else 0
            if (page + 1) * page_size >= total_hits:
                break

        logger.info(f"Modrinth: saved {saved} packs")
        return saved

    # Master scan
    def scan_packs(self, launchers: list = None, technic_slugs: list = None) -> dict:
        # Run scanner for the specified launchers. Returns counts per launcher
        if launchers is None:
            launchers = SUPPORTED_LAUNCHERS

        results = {}

        if "atlauncher" in launchers:
            try:
                results["atlauncher"] = self.fetch_atlauncher_packs()
            except Exception as exc:
                logger.error(f"ATLauncher scan failed: {exc}")
                results["atlauncher"] = 0

        if "ftb" in launchers:
            try:
                results["ftb"] = self.fetch_ftb_packs()
            except Exception as exc:
                logger.error(f"FTB scan failed: {exc}")
                results["ftb"] = 0

        if "technic" in launchers:
            try:
                results["technic"] = self.fetch_technic_packs(technic_slugs)
            except Exception as exc:
                logger.error(f"Technic scan failed: {exc}")
                results["technic"] = 0

        if "modrinth" in launchers:
            try:
                results["modrinth"] = self.fetch_modrinth_packs()
            except Exception as exc:
                logger.error(f"Modrinth scan failed: {exc}")
                results["modrinth"] = 0

        if "curseforge" in launchers:
            try:
                results["curseforge"] = self.fetch_curseforge_packs()
            except Exception as exc:
                logger.error(f"CurseForge scan failed: {exc}")
                results["curseforge"] = 0

        total = sum(results.values())
        logger.info(f"Modded pack scan complete. Total saved: {total} | {results}")
        return results

    # Query helpers
    def get_packs_from_database(self, launcher: str = None, search: str = None,
                                 server_packs_only: bool = False) -> list:
        # Return modded packs optionally filtered by launcher and/or name search
        try:
            query = self.db_session.query(ModdedPack)  # type: ignore[possibly-unbound]
            if launcher:
                query = query.filter_by(launcher=launcher)
            if server_packs_only:
                query = query.filter(ModdedPack.is_server_pack == True)  # type: ignore[possibly-unbound]
            if search:
                like = f"%{search}%"
                query = query.filter(ModdedPack.name.ilike(like))  # type: ignore[possibly-unbound]

            rows = query.order_by(ModdedPack.play_count.desc()).all()  # type: ignore[possibly-unbound]
            return [
                {
                    "id":            r.id,
                    "pack_id":       r.pack_id,
                    "pack_slug":     r.pack_slug,
                    "name":          r.name,
                    "launcher":      r.launcher,
                    "description":   r.description or "",
                    "authors":       r.authors or "",
                    "mc_version":    r.mc_version or "",
                    "modloader":     r.modloader or "",
                    "pack_version":  r.pack_version or "",
                    "thumbnail_url": r.thumbnail_url or "",
                    "server_url":    r.server_url or "",
                    "install_url":   r.install_url or "",
                    "play_count":    r.play_count or 0,
                    "is_server_pack": r.is_server_pack,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error(f"get_packs_from_database failed: {exc}")
            return []

    def get_pack_versions(self, pack_id: str, launcher: str) -> list:
        # Return a list of available version strings for a given pack
        # For launchers that expose version lists via their API
        try:
            if launcher == "atlauncher":
                data = self._get(f"https://api.atlauncher.com/v1/pack/{pack_id}")
                if data:
                    payload = data.get("data", {}) if isinstance(data, dict) else {}
                    versions = payload.get("versions", []) if isinstance(payload, dict) else []
                    return [v.get("version", "") for v in versions if v.get("version")]

            elif launcher == "ftb":
                data = self._get(f"https://api.modpacks.ch/public/modpack/{pack_id}")
                if data:
                    versions = data.get("versions", []) or []
                    return [str(v.get("id") or v.get("name", "")) for v in reversed(versions) if v.get("id") or v.get("name")]

            elif launcher == "curseforge":
                if not self.curseforge_api_key:
                    return []
                headers = {"x-api-key": self.curseforge_api_key}
                data = self._get(f"https://api.curseforge.com/v1/mods/{pack_id}/files",
                                 params={"pageSize": 30}, headers=headers)
                if data:
                    files = data.get("data", [])
                    return [f.get("displayName", str(f.get("id", ""))) for f in files]

            elif launcher == "technic":
                data = self._get(f"https://api.technicpack.net/modpack/{pack_id}",
                                 params={"build": "unset"})
                if data:
                    builds = data.get("builds", []) or []
                    return list(reversed(builds))

            elif launcher == "modrinth":
                data = self._get(f"https://api.modrinth.com/v2/project/{pack_id}/version",
                                 params={"featured": False})
                if isinstance(data, list):
                    versions = []
                    for v in data:
                        if not isinstance(v, dict):
                            continue
                        label = v.get("version_number") or v.get("name") or v.get("id")
                        if label:
                            versions.append(str(label))
                    return versions

        except Exception as exc:
            logger.debug(f"get_pack_versions({pack_id}, {launcher}): {exc}")

        return []

    def get_pack_enrichment(self, pack_id: str, launcher: str) -> dict:
        # Fetch mc_version / authors / server_url for packs where fields were absent at bulk-scan time.
        # Updates the DB record in-place so subsequent loads benefit.
        result: dict = {}
        try:
            if launcher == "atlauncher":
                data = self._get(f"https://api.atlauncher.com/v1/pack/{pack_id}")
                if data:
                    payload = data.get("data", {}) if isinstance(data, dict) else {}
                    versions = payload.get("versions", []) if isinstance(payload, dict) else []
                    if versions:
                        mc_ver = str(versions[0].get("minecraft", "") or "")
                        if mc_ver:
                            result["mc_version"] = mc_ver
                    # ATLauncher detail doesn't reliably include authors; skip.

            elif launcher == "modrinth":
                # Fetch latest version to get the primary download URL (.mrpack file)
                data = self._get(f"https://api.modrinth.com/v2/project/{pack_id}/version",
                                 params={"featured": "true"})
                versions = data if isinstance(data, list) else []
                if not versions:
                    # fall back to all versions
                    data = self._get(f"https://api.modrinth.com/v2/project/{pack_id}/version")
                    versions = data if isinstance(data, list) else []
                if versions:
                    latest = versions[0] if isinstance(versions[0], dict) else {}
                    mc_versions = latest.get("game_versions") or []
                    mc_ver = next((v for v in mc_versions if v and v[0].isdigit()), "")
                    if mc_ver:
                        result["mc_version"] = mc_ver
                    # Primary file URL — the .mrpack archive
                    for f in (latest.get("files") or []):
                        if f.get("primary"):
                            result["server_url"] = f.get("url", "")
                            break
                    if not result.get("server_url") and (latest.get("files") or []):
                        result["server_url"] = latest["files"][0].get("url", "")
                    # Author name from project if absent
                    proj = self._get(f"https://api.modrinth.com/v2/project/{pack_id}")
                    if isinstance(proj, dict):
                        members = proj.get("team") or ""
                        if not result.get("authors") and proj.get("team"):
                            # Lightweight: project author string isn't in project endpoint,
                            # but slug is a good install_url.
                            result["install_url"] = (f"https://modrinth.com/modpack/{proj.get('slug', pack_id)}"
                                                     if proj.get("slug") else "")

            elif launcher == "technic":
                data = self._get(f"https://api.technicpack.net/modpack/{pack_id}",
                                 params={"build": "unset"})
                if isinstance(data, dict) and not data.get("error"):
                    srv = data.get("serverPackUrl") or ""
                    if srv:
                        result["server_url"] = srv
                    mc_info = data.get("minecraft", "")
                    mc_ver = mc_info if isinstance(mc_info, str) else (mc_info or {}).get("version", "")
                    if mc_ver:
                        result["mc_version"] = str(mc_ver)

            # Persist any enriched fields to the DB so future loads benefit too.
            if result:
                try:
                    existing = (
                        self.db_session.query(ModdedPack)  # type: ignore[possibly-unbound]
                        .filter_by(pack_id=pack_id, launcher=launcher).first()
                    )
                    if existing:
                        for k, v in result.items():
                            if hasattr(existing, k) and not getattr(existing, k):
                                setattr(existing, k, v)
                        self.db_session.commit()
                except Exception:
                    self.db_session.rollback()

        except Exception as exc:
            logger.debug(f"get_pack_enrichment({pack_id}, {launcher}): {exc}")
        return result
        try:
            total = self.db_session.query(ModdedPack).count()  # type: ignore[possibly-unbound]
            by_launcher = {}
            for lnc in SUPPORTED_LAUNCHERS:
                by_launcher[lnc] = (
                    self.db_session.query(ModdedPack)  # type: ignore[possibly-unbound]
                    .filter_by(launcher=lnc).count()
                )
            return {
                "total_packs": total,
                "by_launcher": by_launcher,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
        except Exception as exc:
            logger.error(f"get_database_stats failed: {exc}")
            return {"total_packs": 0, "by_launcher": {}, "last_updated": ""}

    def close(self):
        try:
            if hasattr(self, 'db_session'):
                self.db_session.close()
        except Exception:
            pass

# CLI entry point
def main():
    parser = argparse.ArgumentParser(description='Minecraft Modded Pack Scanner')
    parser.add_argument('--launchers', nargs='+', choices=SUPPORTED_LAUNCHERS,
                        default=SUPPORTED_LAUNCHERS, help='Launchers to scan')
    parser.add_argument('--curseforge-key', type=str, default='',
                        help='CurseForge API key (required for CurseForge scanning)')
    parser.add_argument('--technic-slugs', nargs='*', default=None,
                        help='Specific Technic pack slugs to fetch')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--list', type=str, choices=SUPPORTED_LAUNCHERS + ['all'],
                        default=None, help='List stored packs for a launcher')
    parser.add_argument('--search', type=str, default='', help='Search pack name')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    scanner = MinecraftModdedScanner(
        curseforge_api_key=args.curseforge_key,
        debug_mode=args.debug
    )
    try:
        if args.stats:
            stats = scanner.get_database_stats()
            print(f"Total packs: {stats['total_packs']}")
            for lnc, cnt in stats['by_launcher'].items():
                print(f"  {lnc}: {cnt}")
            return

        if args.list:
            lnc_filter = None if args.list == 'all' else args.list
            packs = scanner.get_packs_from_database(launcher=lnc_filter, search=args.search)
            for p in packs:
                print(f"[{p['launcher']:12}] {p['name']:<50} MC:{p['mc_version']:<10} {p['modloader']}")
            print(f"\nTotal: {len(packs)}")
            return

        results = scanner.scan_packs(launchers=args.launchers, technic_slugs=args.technic_slugs)
        print("Scan results:")
        for lnc, cnt in results.items():
            print(f"  {lnc}: {cnt} packs saved")
    finally:
        scanner.close()

if __name__ == '__main__':
    main()