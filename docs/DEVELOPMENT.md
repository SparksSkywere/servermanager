# Development notes

Local data root: `runtime\` under this repository.

Config registry: `HKLM\Software\SkywereIndustries\Servermanager`

Default local ports (override in `runtime\config\appsettings.json` or the installer):

- Web `18080`
- HostRuntime `18091`
- Cluster `15001`

## Checklist

- [ ] AppHost / HostRuntime / Web start cleanly
- [ ] Login works (`admin` / `admin` on fresh DB)
- [ ] Create a test Steam/Minecraft server under `runtime\servers\`
- [ ] Verify start / console / stop / reattach via web UI
- [ ] Optional: import existing `db\` and `ssl\` with `tools\Import-Data.ps1`
