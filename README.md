# Server Manager

A comprehensive Windows-based server management system for Steam game servers, Minecraft servers, and other dedicated game servers.

## Features

- **Automated Installation**: Deploy Steam dedicated servers, Minecraft servers (Vanilla, Fabric, Forge, NeoForge), and custom servers
- **Real-time Monitoring**: Process monitoring with automatic restart capabilities
- **Multi-Server Support**: Manage unlimited server instances across multiple game types
- **Multiple Interfaces**: Desktop GUI, web dashboard, and system tray controls
- **Security**: Multi-method authentication, 2FA support, and role-based access control
- **Clustering**: Host-subhost architecture for distributed server management
- **Automation**: Scheduled updates, task scheduling, and resource monitoring

## Quick Start

### Installation

1. Run the PowerShell installer as Administrator:
   ```powershell
   .\install.ps1
   ```
2. Follow the GUI installation wizard
3. Configure initial settings and create admin account

### Manual Installation

Install Python dependencies:
```bash
pip install -r requirements.txt
```

### Usage

- **Desktop Mode**: Run `Start-ServerManager.pyw`
- **Web Interface**: Access at `http://localhost:8080`
- **Service Mode**: Start "Server Manager Service" from Windows Services

## Requirements

- Windows 10 or Windows Server 2016+
- Python 3.8+
- 4GB RAM (8GB+ recommended)
- Administrator privileges for installation

## Configuration

Configure database connections and server settings through the GUI or web interface. Supports SQLite, MySQL, and PostgreSQL.

## License

GNU General Public License v3.0
