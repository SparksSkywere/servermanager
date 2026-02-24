# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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