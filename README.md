# Server Manager for Steam Game Servers

A comprehensive Python-based management system for Steam game servers, providing automated installation, updating, and monitoring capabilities.

## Features

- Automated server installation and updates via SteamCMD
- Server process monitoring and automatic restart capabilities
- Multi-server management support
- Web-based dashboard for server monitoring
- Configurable update checks
- Automatic server shutdown and restart during updates
- Detailed logging system
- Configuration storage

## Prerequisites

- Windows Operating System
- Python 3.8 or higher
- Administrator rights for installation
- Internet connection for downloading SteamCMD and server files

## Installation

### Automated Installation

1. Run `install.py` with administrator privileges:
   ```
   Right-click install.py -> Run as Administrator
   ```
2. Follow the installation wizard to:
   - Select SteamCMD installation directory
   - Configure initial settings

### Manual Installation

1. Clone this repository
2. Create a directory for SteamCMD
3. Download and extract SteamCMD
4. Run `python install.py` with appropriate parameters

## Configuration

### Server Configuration

1. Edit server configuration files in the `config` directory:
   ```python
   games = [
       { 
           "name": "My Server", 
           "app_id": "123456", 
           "install_dir": "D:\\Servers\\MyServer" 
       }
   ]
   ```

### Launch Arguments

Configure server-specific launch arguments in the server configuration:
```python
arguments = """
-console
+map mymap
+maxplayers 32
-tickrate 128
"""
```

## Usage

### Server Management

1. Start Server Manager:
   ```
   python start_server_manager.py
   ```

2. Access the web dashboard:
   ```
   http://localhost:10000
   ```

### Common Commands

- Install new server:
  ```
  python install_server.py
  ```

- Create server instance:
  ```
  python create_server.py
  ```

- Remove server:
  ```
  python destroy_server.py
  ```

- Update servers:
  ```
  python update_server.py
  ```

### Automated Updates

Set up a scheduled task to run `auto_app_update.py` for automatic updates.

## Logging

Logs are stored in the servermanager directory:
- `log-updateserver.log`: Update operations
- `log-autoupdater.log`: Automatic update checks
- `install_log.txt`: Installation logs

## Uninstallation

1. Stop all servers:
   ```
   python stop_all_servers.py
   ```

2. Run the uninstaller:
   ```
   python uninstaller.py
   ```

The uninstaller will:
- Stop all running servers
- Remove configuration files
- Delete installation files (optional)
- Clean up configuration files

## Troubleshooting

1. **Permission Issues**
   - Ensure Python is running as Administrator
   - Check user permissions

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

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
