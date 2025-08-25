# Server Manager

A comprehensive Windows-based server management system for Steam game servers, Minecraft servers, and other dedicated game servers. Provides automated installation, monitoring, updating, and administration capabilities through multiple interfaces.

## Overview

Server Manager is an enterprise-grade game server management platform that combines desktop GUI applications, web interfaces, system services, and clustering capabilities. It's designed to handle everything from single server instances to multi-host distributed server farms.

## Core Features

### Server Management
- **Automated Installation**: Deploy Steam dedicated servers, Minecraft servers (Vanilla, Fabric, Forge, NeoForge), and custom servers
- **Process Monitoring**: Real-time server process monitoring with automatic restart capabilities  
- **Multi-Server Support**: Manage unlimited server instances across multiple game types
- **Server Console Access**: Real-time console interaction and command execution
- **Configuration Management**: Centralized server configuration with validation and templates

### User Interface Options
- **Desktop Dashboard**: Full-featured tkinter GUI with comprehensive server management
- **Web Interface**: Browser-based dashboard with REST API backend
- **System Tray Icon**: Quick access controls and status monitoring
- **Admin Dashboard**: Dedicated user management interface
- **Command Line Tools**: Scriptable automation and batch operations

### Authentication & Security
- **Multi-Method Authentication**: SQL database, Windows authentication, or file-based
- **Two-Factor Authentication (2FA)**: Optional TOTP support for enhanced security
- **Role-Based Access Control**: Admin and standard user permissions
- **Secure Token Management**: JWT-style authentication tokens with expiration
- **Password Security**: bcrypt hashing with configurable complexity

### Automation & Scheduling
- **Automatic Updates**: Scheduled server updates via SteamCMD integration
- **Task Scheduling**: Configurable maintenance windows and automated operations
- **Update Management**: Intelligent update detection with rollback capabilities
- **Resource Monitoring**: CPU, memory, disk, and network usage tracking
- **Alert System**: Configurable notifications for server events

### Clustering & Distribution
- **Host-Subhost Architecture**: Centralized management of distributed servers
- **Remote Agent Support**: Connect and manage servers across multiple machines
- **Load Balancing**: Distribute server load across multiple hosts
- **Cluster Status Monitoring**: Real-time status of all cluster nodes

### Database Integration
- **Multiple Database Support**: SQLite, MySQL, PostgreSQL compatibility
- **Steam App Database**: Comprehensive Steam application metadata
- **User Management Database**: Centralized user accounts and permissions
- **Configuration Storage**: Persistent settings and server configurations
- **Audit Logging**: Complete activity logs and change tracking

### Service Integration
- **Windows Service Mode**: Run as system service for always-on operation
- **Process Management**: Automatic process recovery and health monitoring  
- **PID File Management**: Process tracking and cleanup capabilities
- **Service Installation**: Automated Windows service setup and configuration

## System Requirements

### Minimum Requirements
- **Operating System**: Windows 10 or Windows Server 2016+
- **Python**: 3.8 or higher
- **Memory**: 4GB RAM minimum (8GB+ recommended for multiple servers)
- **Storage**: 10GB free space (additional space required per server)
- **Network**: Internet connection for downloads and updates

### Administrator Privileges
- Required for installation and service management
- Needed for process monitoring and system integration
- Optional for standard server operations after setup

## Installation

### Quick Installation
1. Run the PowerShell installer as Administrator:
   ```powershell
   .\install.ps1
   ```
2. Follow the GUI installation wizard
3. Configure initial settings and database connection
4. Create administrative user account

### Manual Installation
1. Install Python dependencies:
   ```cmd
   pip install -r requirements.txt
   ```
2. Configure registry settings via installer
3. Initialize databases and user accounts
4. Set up service (optional)

## Usage

### Starting the System
- **Desktop Mode**: Run `Start-ServerManager.pyw`
- **Service Mode**: Start "Server Manager Service" from Windows Services
- **Tray Only**: Launch via system tray icon

### Web Interface
Access the web dashboard at `http://localhost:8080` (default port)
- Authentication required
- Real-time server monitoring
- Basic server controls
- User management (admin only)

### Server Operations
- **Add Servers**: Use GUI wizard or web interface to configure new servers
- **Start/Stop/Restart**: Control server processes with one-click operations
- **Console Access**: Interactive console for real-time server interaction
- **Updates**: Manual or automated server updates via Steam or direct download
- **Configuration**: Edit server settings through graphical interface

### Clustering
- **Host Setup**: Configure primary management node
- **Subhost Connection**: Connect additional machines to central host
- **Remote Management**: Control distributed servers from single interface

## Configuration

### Database Configuration
Configure database connection via Windows Registry or installation wizard:
- **SQLite**: Single-file database (default)
- **MySQL**: Network database for multi-host setups  
- **PostgreSQL**: Enterprise database option

### Server Types Supported
- **Steam Dedicated Servers**: Any Steam AppID-based server
- **Minecraft Servers**: Vanilla, Fabric, Forge, NeoForge
- **Custom Servers**: Any executable with configuration support

### Logging
Comprehensive logging system with configurable levels:
- **Component Logs**: Separate logs for each system component
- **Server Logs**: Individual logs per managed server
- **Debug Logs**: Detailed troubleshooting information
- **Audit Logs**: User actions and system changes

## Advanced Features

### API Integration
RESTful API for external integrations:
- Server status and control endpoints
- User management API
- System monitoring data
- Authentication and authorization

### Analytics & Monitoring  
- **Resource Usage**: Historical CPU, memory, disk, network data
- **Performance Metrics**: Server-specific performance tracking
- **SNMP Integration**: Network monitoring system compatibility
- **Grafana Integration**: Advanced dashboard and alerting

### Security Features
- **Encrypted Communication**: Secure API communications
- **Audit Trail**: Complete logging of user actions
- **Access Control**: Granular permission system
- **Secure Storage**: Encrypted password storage

## Troubleshooting

### Common Issues
- **Permission Errors**: Ensure Administrator privileges for installation
- **Database Connection**: Verify database configuration and connectivity
- **Port Conflicts**: Check for conflicting applications on default ports
- **Service Issues**: Use Windows Event Viewer for service-related problems

### Log Locations
- **Main Logs**: `logs/` directory in installation folder
- **Debug Logs**: `logs/debug/` for detailed troubleshooting
- **Server Logs**: Individual server directories

### Support Tools
- **Debug Manager**: Built-in diagnostic and troubleshooting tools
- **Database Update Utility**: Schema migration and repair tools
- **Uninstaller**: Complete system removal with optional data preservation

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
