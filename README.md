# Production Note: This is in active development so all is subject to change! Linux development is a side project, Windows is first.

# Server Manager

A server management system for Steam, Minecraft servers, and other dedicated servers.

## Quick Start

### Installation (Windows)

1. Run the PowerShell installer as Administrator:
   ```powershell
   .\install.ps1
   ```
2. Follow the GUI installation wizard
3. Configure initial settings and create admin account

### Installation (Linux)

1. Run the PowerShell installer as Administrator:
   ```Bash
   sudo sh install.sh
   ```
2. Follow the GUI installation wizard
3. Configure initial settings and create admin account

### Manual Installation

Install Python dependencies:
```bash/powershell
git clone https://github.com/SparksSkywere/servermanager.git
pip install -r requirements.txt
```

### Usage

- **Desktop Mode**: Run `Start-ServerManager.pyw` and right click the icon that appears in the taskbar and click "Open Server Dashboard" to see the local UI
- **Web Interface**: Access at `http://localhost:8080` (Or if on another machine `http://IPADDRESS:8080`)
- **Service Mode**: Start "Server Manager Service" from Windows Services

## Requirements

- Windows 10/11 or Windows Server 2016+
- Python 3.8+
- 4GB RAM (8GB+ recommended)
- Linux users I would suggest Debian based OS's for ease of use, other distro's may work
