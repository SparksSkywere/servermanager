# Server Manager migration toolkit

Standalone helpers to copy **legacy** Server Manager SQLite data, SSL files, and settings into a **new** runtime root. This folder is **not** part of the installed product; operators run it once during cutover.

## Server configs = SQLite only

All server definitions are stored in `db\servermanager_servers.db`. The .NET product does **not** use `servers\*.json` as a source of truth.

If a legacy install still has `servers\*.json` (or `data\servers\` / `config\servers\`), migration **imports those into SQL** by default so nothing is left as JSON-only files.

| Input | How it is resolved |
|-------|--------------------|
| Source | `-SourceRoot` / `--source`, or registry under `Software\SkywereIndustries\Servermanager` |
| Dest | `-DestRoot` / `--dest`, or sibling `..\runtime`, or `{InstallPath}\runtime` |
| Path remap | **Optional** `--path-remap` JSON — only rewrites *install folder path prefixes* when games moved drives. **Not** a server config file. |

## Requirements

- .NET 8 SDK (to build `ServerManager.Migrator`), or a pre-built `dist\ServerManager.Migrator.exe`
- Read access to the legacy install (`db\`, optional `ssl\` / `servers\`)
- Write access to the destination runtime root

Do **not** commit real server names, drive letters, or credentials into examples.

## Quick start

### GUI (recommended)

```powershell
cd <this-migration-folder>
.\Launch-MigrationGui.cmd
# or
.\Migrate-ServerManager.ps1 -Gui
```

Pick legacy source (folder with `db\`) and destination runtime. Prefer dry-run first, then run for real.

### Command line

```powershell
cd <this-migration-folder>

# Preview
.\Migrate-ServerManager.ps1 -SourceRoot '<legacy-root>' -DestRoot '<runtime-root>' -DryRun

# Migrate (SQL DBs + optional JSON→SQL import)
.\Migrate-ServerManager.ps1 -SourceRoot '<legacy-root>' -DestRoot '<runtime-root>'

# Only if game install folders moved between machines
.\Migrate-ServerManager.ps1 -SourceRoot '<legacy-root>' -DestRoot '<runtime-root>' -PathRemapFile .\path-remap.json
```

Direct CLI:

```powershell
dotnet run --project .\ServerManager.Migrator -- --source '<legacy-root>' --dest '<runtime-root>' --dry-run
```

Skip leftover JSON import (rarely needed): `--skip-json-servers` / `-SkipJsonServers`.

## What is migrated

| Source | Destination | Notes |
|--------|-------------|--------|
| `db\servermanager_servers.db` | same name | Column rename (`executable_path`→`Executable`, …); permissions by server **name** |
| `servers\*.json` (if present) | **into** `servermanager_servers.db` | Imported into SQL; not copied as JSON files |
| `db\servermanager_users.db` | same name | `password` → `PasswordHash` (hash as-is; bcrypt compatible) |
| `db\servermanager.db` | same name | `main_config`, cluster; path-like keys remapped only if `--path-remap` set |
| Catalog DBs | file copy | `steam_ID.db`, `minecraft_ID.db`, … |
| `ssl\` | `ssl\` | Certificates when present |

**Not migrated:** live process IDs. Re-enter Steam password in settings if protectors differ.

## Path remap file (optional)

Only for rewriting **install directory prefixes** after a drive/folder move. Copy `path-remap.example.json`:

```json
{
  "pathRemap": {
    "D:\\OldGames": "E:\\Games"
  }
}
```

This file is **not** where server configs live.

## Safety

- Prefer `--dry-run` first.
- Use `--clear-dest-db` only when replacing destination DBs.
- Stop HostRuntime / Web before writing to a live `runtime\db`.
