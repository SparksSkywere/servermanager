# Server Manager for Steam Game Servers

A comprehensive PowerShell-based management system for Steam game servers, providing automated installation, updating, and monitoring capabilities.

## Features

- Automated server installation and updates via SteamCMD
- Server process monitoring and automatic restart capabilities
- Multi-server management support
- Web-based dashboard for server monitoring
- Configurable update checks
- Automatic server shutdown and restart during updates
- Detailed logging system
- Registry-based configuration storage

## Prerequisites

- Windows Operating System
- PowerShell 5.1 or higher
- Administrator rights for installation
- .NET Framework 4.7.2 or higher
- Internet connection for downloading SteamCMD and server files

## Installation

### Automated Installation

1. Run `install.ps1` with administrator privileges:
   ```powershell
   Right-click install.ps1 -> Run with PowerShell
   ```
2. Follow the installation wizard to:
   - Select SteamCMD installation directory
   - Configure initial settings
   - Set up registry entries

### Manual Installation

1. Set PowerShell execution policy:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned
   ```
2. Create a directory for SteamCMD
3. Download and extract SteamCMD
4. Clone this repository into the 'servermanager' subdirectory

## Configuration

### Server Configuration

1. Edit `auto-app-update.ps1` to add your game servers:
   ```powershell
   $games = @(
       @{ 
           Name = "My Server"; 
           AppID = "123456"; 
           InstallDir = "D:\Servers\MyServer" 
       }
   )
   ```

### Launch Arguments

Configure server-specific launch arguments in the server configuration:
```powershell
$arguments = @"
-console
+map mymap
+maxplayers 32
-tickrate 128
"@
```

## Usage

### Server Management

1. Start Server Manager:
   ```powershell
   .\Start-ServerManager.ps1
   ```

2. Access the web dashboard:
   ```
   http://localhost:10000
   ```

### Common Commands

- Install new server:
  ```powershell
  .\install-server.ps1
  ```

- Create server instance:
  ```powershell
  .\create-server.ps1
  ```

- Remove server:
  ```powershell
  .\destroy-server.ps1
  ```

- Update servers:
  ```powershell
  .\update-server.ps1
  ```

### Automated Updates

Set up a scheduled task to run `auto_app_update.ps1` for automatic updates.

## Logging

Logs are stored in the servermanager directory:
- `log-updateserver.log`: Update operations
- `log-autoupdater.log`: Automatic update checks
- `Install-Log.txt`: Installation logs

## Uninstallation

1. Stop all servers:
   ```powershell
   .\stop-all-servers.ps1
   ```

2. Run the uninstaller:
   ```powershell
   .\uninstaller.ps1
   ```

The uninstaller will:
- Stop all running servers
- Remove registry entries
- Delete installation files (optional)
- Clean up configuration files

## Troubleshooting

1. **Permission Issues**
   - Ensure PowerShell is running as Administrator
   - Check execution policy: `Get-ExecutionPolicy`

2. **Server Won't Start**
   - Check logs for error messages
   - Verify correct AppID and installation path
   - Ensure all prerequisites are installed

3. **Update Issues**
   - Verify internet connectivity
   - Check SteamCMD installation
   - Review update logs for errors

## Contributing

Feel free to submit issues and pull requests to improve the project.

## License

This project is licensed under the MIT License - see the LICENSE file for details.