# Production cutover — Master parity checklist

Primary operator UI is **HostUI** (WinForms). Server source of truth is **SQLite** (`runtime\db\servermanager_servers.db`). Export/Import uses portable `.smserver.json` then upserts into SQL.

## Phase 0 — Stabilize (verify)

- [ ] Cold boot: Windows service or `ServerManager.exe` (AppHost) starts Web + HostRuntime.
- [ ] HostUI waits for health, then login works (default admin/admin).
- [ ] `.\build.ps1` produces clean `dist\` (self-contained, **not** single-file).
- [ ] Migration toolkit: SQL-only servers; path-remap advanced-only.

## Phase 1 — Export / Import Server

- [ ] `GET /api/servers/{name}/export` returns `servermanager-server-export` v1 (no PID).
- [ ] `POST /api/servers/import?mode=overwrite|skip|rename` upserts into SQLite.
- [ ] HostUI: **Import Server** toolbar + **Export Server** context menu.
- [ ] Round-trip: create → export → delete → import → fields match.

## Phase 2 — Humanize Tools messaging

- [ ] HostUI Tools dialogs show plain English (`UiMessages`), not raw JSON as primary text.
- [ ] Checkpoint Databases copy clarifies WAL checkpoint ≠ catalog/game update.

## Phase 3 — Dashboard system graphs

- [ ] `GET /api/runtime/metrics/host` (also proxied via Web).
- [ ] HostUI System Information: CPU / Memory / Disk sparklines.
- [ ] www dashboard Chart.js panels poll the same endpoint.

## Phase 4 — Update All

- [ ] **Update All** calls `/api/runtime/servers/update-all` (Steam via SteamCMD).
- [ ] **Reattach All Consoles** remains a separate Tools item (not Update All).

## Phase 5 — Cluster that works

- [ ] `ClusterEnabled` gates mutating cluster APIs.
- [ ] Settings: ClusterEnabled, HostType, HostAddress, ClusterPort, optional ClusterToken.
- [ ] Subhost worker: request-join → poll join-status for token → heartbeat.
- [ ] HostUI ClusterForm: role banner, approve (shows token), remove node, last-seen.
- [ ] Demo: host + subhost join → approve → heartbeat → node list live.

## Phase 6 — www remote parity

- [ ] Server table: kill / configure / export / import / update-all / checkpoint DB.
- [ ] System charts on dashboard.
- [ ] Cluster page uses same APIs with human banner.
- [ ] Tool messages humanized (not JSON-only alerts).

## Phase 7 — Depth features

- [ ] Modded MC pack browser (Modrinth live; CurseForge with API key; Technic/FTB stub messaging).
- [ ] Hardware panel (local metrics + iLO/iDRAC temperature probes).
- [ ] Admin menu from HostUI; theme preference in Settings/profile.
- [ ] Help text covers Export/Import and Cluster.

## Phase 8 — Install / cutover steps

1. Confirm parity on chosen ports (start/stop/console/update/cluster).
2. Stop any previous Server Manager instance.
3. Import data if needed: `tools\Import-Data.ps1 -SourceRoot <previous-install>` or Migrator GUI.
4. Set production ports in `runtime\config\appsettings.json` or via installer (e.g. Web 8080/443, Runtime 8091, Cluster peer port).
5. Install Windows service: `.\dist\install.ps1 -AsService` or run `ServerManager-Setup.exe`.
6. Start the service and verify firewall rules.
7. Confirm operators can use **HostUI** (and optionally www), then retire the previous install when stable.

## Out of scope (do not regress)

- Do not reintroduce single-file publish (breaks SQLite natives).
- Do not replace SQLite.
- Do not edit the legacy Python tree under `D:\SteamCMD\servermanager2` (read-only reference).
