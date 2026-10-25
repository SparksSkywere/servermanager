# Server Manager

Windows-first game server management (web UI, HostRuntime, Windows Service / systemd, tray, HostUI).

## Requirements

- Windows 10/11 (installer) or Linux (script install)
- For building: [.NET SDK](https://dotnet.microsoft.com/download) and [Inno Setup 6](https://jrsoftware.org/isinfo.php)

## Install (release packages)

Build the Windows installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The installer creates **Start Menu** and **Desktop** shortcuts under Skywere Industries (both on by default; you can uncheck them).

Default ports: Web **18080**, HostRuntime **18091**, Cluster **15001**. Login: `admin` / `admin`.

### GUI

1. Launch **Server Manager** from the Start Menu or Desktop
2. Open the local Host Dashboard
3. Add and manage game servers from the web UI

## License
This repository is licensed under the MIT License as provided in the LICENSE file included with the project.
