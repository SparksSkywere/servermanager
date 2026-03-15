# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3]

  Console Stability Fixes:
  - Fixed stale PID console-attach behaviour in `server_console.py`: console now refuses unvalidated PID reattach and clears stale process metadata instead of attaching to a potentially unrelated process
  - Fixed command relay error storm in `command_queue.py`: relay now stops cleanly when target process has exited or stdin is invalid/closed, preventing repeated `[Errno 22] Invalid argument` loops during stop operations
  - Fixed console freeze/false-stop regression for reattached servers in `server_console.py`: stream monitor threads now start only when real stdio streams exist, and missing/invalid stdout no longer marks a still-running process as terminated
  - Fixed duplicate command relay worker issue in `command_queue.py`: server relays are now single-instance per server (existing relay is replaced cleanly), preventing duplicate command consumers and intermittent console non-responsiveness

  Shutdown Reliability Fixes:
  - Improved `stop_servermanager.py` PID-file shutdown coverage to include `dashboard.pid` and `server_automation.pid`
  - Expanded Python process detection for shutdown to include `server_automation.py`, `stdin_relay.py`, and `persistent_stdin.py`
  - Added bounded multi-pass final cleanup in `stop_servermanager.py` so asynchronous stragglers are stopped within a single stop run instead of requiring a second manual stop

  Dead Code / Placeholder Cleanup:
  - Removed dead placeholder `install_server()` and `check_for_updates()` from `server_operations.py` (real implementations exist in `server_manager.py` and `server_updates.py`)
  - Fixed misleading "Additional placeholder functions" comment in `dashboard_functions.py` (functions were fully implemented)
  - Full audit of 42 missing-implementation findings: 18 were TYPE_CHECKING stubs, 4 were string template comments, 2 were type-checker declarations, 6 were informational NOTEs, 8 were intentional fallback patterns, 2 were dead code (removed), 2 had misleading comments (fixed)
  - Removed 70 lines of unreachable 2FA dialog code from `user_database.py` (dead `_show_2fa_setup_dialog` method)

  Code Quality Fixes:
  - Added `encoding='utf-8'` to 29 `open()` calls across 15 files (dashboard.py, cluster_database.py, server_configs_database.py, auto_app_update.py, common.py, launcher.py, minecraft.py, server_logging.py, server_manager.py, stop_servermanager.py, trayicon.py, debug.py, dashboard_tracker.py)
  - Extracted hardcoded Java installation paths in `minecraft.py` to module-level `WINDOWS_JAVA_SEARCH_PATHS` constant
  - Stripped trailing whitespace from 4,759 lines across 55 Python files
  - Added explicit `-> bool` return type annotation to `RegistryModule.initialise_from_registry()` in `common.py` to fix Pylance override type mismatch in subclasses

  Duplication Refactoring:
  - Extracted `RegistryModule` base class into `common.py` — consolidates shared Windows Registry initialisation logic from `security.py` (`SecurityManager`) and `server_operations.py` (`ServerOperations`), eliminating duplicate `registry_path` / `server_manager_dir` / `paths` setup and `initialise_from_registry()` patterns
  - Extracted `make_2fa_callbacks()` factory into `common.py` — consolidates duplicate 2FA setup/verify callback generation from `admin_dashboard.py` and `user_database.py`
  - Extracted `_make_server_op_callback()` in `dashboard_server_ops.py` — consolidates 3 duplicate `on_completion` closures (start/stop/restart) with `error_as_info` parameter
  - Extracted `_make_progress_callback()` staticmethod in `dashboard_server_ops.py` — consolidates 3 duplicate progress callback closures with `scheduled` parameter for logger support
  - Extracted `populate_server_tree()` in `dashboard_functions.py` — consolidates duplicate populate/search/filter logic used by both server browser dialogs; reused in `dashboard_server_config.py` to replace inline duplicate
  - Extracted `make_canvas_width_updater()` in `dashboard_functions.py` — consolidates duplicate scrollable canvas width-binding logic from `dashboard_functions.py` and `dashboard_server_config.py`

  CSS Refactoring:
  - Created `www/css/common.css` — extracted shared layout styles (body reset, page-container, header, nav, content-area, card, responsive grid) from inline `<style>` blocks
  - Migrated `admin.html`, `cluster.html`, `create-server.html`, and `dashboard.html` to use linked `common.css` instead of duplicated inline CSS

  Documentation:
  - Updated WIKI.md: corrected directory layout, removed references to non-existent files (`update-database.pyw`, `migrate_database_schema.py`), updated architecture documentation for `RegistryModule` and shared utility patterns
  - Fixed incorrect `uninstall.sh` references to `uninstaller.sh` in WIKI.md
  - Updated version references from 1.2 to 1.3 in WIKI.md and README.md
  - Added Screenshots!

## [1.2] - 2026-03-01

Maintenance update!

  Bug Fixes:
  - Fix server-type-aware RAM display (JVM heap vs RSS) across Tkinter dashboard, web dashboard, web API, and WIKI
  - Fix Pylance type warnings for psutil in webserver.py
  - Fix 19,000-line log spam caused by reattach loop (added _reattached_servers tracking)
  - Fix dashboard freeze during server stop (added _stopping_servers tracking + 5s lock timeout)
  - Replace batch_update_server_types placeholder with working 3-strategy type detection

  Dead Code Removal:
  - Full codebase audit: verified 143 findings (141 confirmed dead, 2 false positives)
  - Removed 152+ dead functions/classes/variables across 30+ files
  - Removed dead show_java_configuration_dialog (119 lines) from dashboard_functions.py
  - Scanner updated to skip pywin32 service callbacks and __main__ guard references

  Security:
  - Fixed XSS vulnerability in dashboard.html (unescaped API data in innerHTML)
  - Added escapeHtml() utility to create-server.html
  - Updated security scanner to recognise escapeHtml() as XSS mitigation

  Import Cleanup:
  - Removed 61 unused imports across 16+ files (Host, Modules, Database, SMNP, SMTP, services, www/js)

  Comment Style Standardisation:
  - Converted all docstrings to single-line # comments across dashboard_dialogs.py, verify_database.py, console_database.py
  - Simplified 11 verbose multi-line comment blocks across 6 files (web_security, minecraft, server_manager, webserver, stdin_relay, verify_dedicated_servers)
  - Added missing file header to webserver.py
  - Standardised all files to use # comments instead of docstrings

  Compatibility Layer Cleanup:
  - Removed legacy file-based Authentication class from webserver.py (~100 lines)
  - Removed deprecated wrapper functions from minecraft_database.py, steam_database.py, SQL_Connection.py (get_engine, get_sql_config_from_registry, build_db_url)
  - Removed backward-compat spelling aliases (initialize_user_manager, initialize_steam_database, center_window) and updated all callers to use canonical names (initialise_user_manager, centre_window)
  - Removed ServerConsole = RealTimeConsole alias from server_console.py
  - Removed db_manager alias from webserver.py and updated all callers to server_manager
  - Removed analytics backward-compat methods from AnalyticsCollector class, updated webserver to call module-level functions directly
  - Removed deprecated /api/cluster/register endpoint and auto-register from heartbeat (use approval workflow)
  - Removed vestigial "info": {} fields from all cluster API responses
  - Removed unused get_minecraft_sql_config_from_registry and build_minecraft_db_url functions
  - Removed dead SQLAuthentication._check_password method and unused json import
  - Cleaned up all legacy/backward/compat comments across 12+ files

  Section Header Cleanup:
  - Replaced 20 three-line banner blocks (# ====) with single-line # comments across 5 files (common.py, server_console.py, user_management.py, web_security.py, trayicon.py)

  Formatting:
  - Collapsed double blank lines across 53 Python files

  Performance Fixes:
  - Parallelised scheduler cluster node requests with ThreadPoolExecutor
  - Pre-compiled regex patterns in MinecraftIDScanner
  - Tuned performance scanner to reduce false positives (removed open() from expensive-ops, removed list(dict) iterator flagging)

  Duplication Refactoring:
  - Analysed 342 reported duplicate groups: 332 CSS/HTML false positives, 10 Python matches (7 false positives, 3 true duplicates)
  - Extracted send_command_to_server() to common.py shared utility (was duplicated 33 lines x2 in server_automation.py and server_updates.py)
  - Extracted format_speed() to module-level in dashboard_functions.py (was duplicated inline x2)
  - Extracted _flatten_config() to ClusterDatabase static method in cluster_database.py (was duplicated inline x2)
  - Tuned duplication scanner: separate text block threshold (15 lines), Python-only scoring, informational CSS/HTML reporting
  - Added compatibility scanner for deprecated wrapper detection

## [1.1.1] - 2026-02-24

- Updated documentation and HTML changes

## [1.1] - 2026-02-20

- v1.1 overhaul + HTTPS/SSL support + security fix
- Fix critical performance and architecture issues (2026-02-17)

  Performance:
  - Add timeout=30 to Microsoft Graph API requests.post call (mailserver.py)
  - Replace blocking time.sleep() with threading.Event-based waiting in server_automation.py (_stop_event), webserver.py (_shutdown_event), and launcher.py for interruptible/clean shutdown
  - Convert 11 long sleep calls (10-60s) across 4 files to event-based waits

  Architecture:
  - Replace 17 raw winreg.OpenKey/QueryValueEx/SetValueEx/CreateKeyEx call sites with centralised get_registry_value/set_registry_value/ get_registry_values helpers across 7 files:
    - api/cluster.py
    - Host/dashboard.py
    - Modules/cluster_security.py
    - Modules/launcher.py
    - Modules/ssl_utils.py
    - Modules/Database/database_utils.py
    - Modules/Database/server_configs_database.py

- Performance fixes (2026-01-04)
- Comments/IDE error fixes/updated Readme (2026-01-01)

## [1.0.0] - Beta 2026-01-01

- Ready for v1.0.0 release (Par some fixes needed)
- Almost 1.0 ready, just code cleanup and QOL (2025-12-24)
- Updated ready for release v1.0.0 (2025-12-21)
- Large code updates ready for v1.0.0 release (2025-12-21)

## [0.9] - 2025-10-09

- 0.9 Major update - SNMP/SMTP/Templates/Dashboard
- Updated a lot of functions and code + new files (2025-09-27)

## [0.8] - 2025-09-18

- v0.8 update, lots of changes too long for this
- Docstring cleanup + SNMP empty files + name change (2025-09-12)
- Updated comments and cluster fixes (2025-09-12)
- 2FA setup and OAuth email integration + reset 2FA (2025-09-11)
- Updated dashboard UI to remove redundant elements (2025-09-10)

## [0.7] - 2025-09-08

- Console live and history + update to 0.7
- Rewrote readme (2025-09-07)

## [0.2] -> [0.6] - 2025-09-07

- Updated version number to 0.6
- Updated trayicon options
- Fixed dashboard freezing
- Fixed website and cleaned dashboard comments
- Deleted cache (2025-09-04)
- Updated authentication methods and updated install (2025-09-04)
- Comments cleaned up + docstrings removed (2025-09-03)
- Hyper-V Cluster style updates and fixes (2025-08-31)
- Temp update (2025-08-26)
- Working on pycache prevention (2025-08-25)
- Updated readme (2025-08-25)
- Centralised logging with all files now (2025-08-25)
- Modified database functions and updated DB files (2025-08-25)
- Complete refactor of the program (2025-08-25)
- Silent running is fixed (2025-08-22)
- Removed web admin for now (2025-08-22)
- Altered registry path handling in all scripts (2025-08-22)
- Cleaned up comments (2025-08-21)
- Moved the cancel button (2025-08-19)
- Fixed a bug in the server list click behavior (2025-08-19)
- Updated some functions in dashboard, uploaded DB (2025-08-19)
- Fixed some issues with the configuration (2025-08-19)
- Server rename and AppID update functionality (2025-08-19)
- Debug centralised and moved (2025-08-12)
- Deleted unused file (2025-08-11)
- Dashboard optimisations (2025-08-11)
- Working on services (2025-08-06)
- Verification added and some refactoring. (2025-08-06)
- New Feature: server console (2025-08-03)
- Added a scheduler (2025-08-01)
- Updated main dashboard (2025-08-01)
- Dashboard changes (2025-07-28)
- Working on anti-freeze (2025-07-27)
- Updated dashboard (2025-07-27)
- Bunch of changes to the project (2025-07-27)
- Cleanup (2025-07-26)
- Loads of changes to the dashboard (2025-07-26)
- Deleted file gui.py (2025-07-07)
- modified files: dashboard and installer (2025-07-07)
- Changes to database and admin_dashboard (2025-06-30)
- Administration changes (2025-06-26)
- Removed cache and fixed imports (2025-06-17)
- Changing a lot (2025-06-17)
- Moving all files around (2025-05-29)
- Dashboard Tracker Service (2025-05-27)
- Updated todo (2025-05-26)
- Refactoring and new features added (2025-05-26)
- Dashboard fixes (2025-05-25)
- Only one shall exist (2025-05-25)
- Website now working (2025-05-25)
- More updates (2025-05-25)
- Dashboard fully working (2025-05-25)
- Code start (2025-05-24)
- Initial commit (2025-05-24)

## [0.1] - 2024-2025 Alpha (Powershell)

- Created the basic forms and what was needed, originated from my watchdog
- Many of the functions worked but due to performance issues I had to change to Python
- There was many undocumented work during this so much is lost to time!
- This version is now deleted, but was the basic of this