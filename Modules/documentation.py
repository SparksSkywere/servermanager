# Documentation dialogs
import os
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import centre_window, REGISTRY_PATH

def show_help_dialog(parent_window, logger=None):
    # Display help dialog with organised tabs
    try:
        help_dialog = tk.Toplevel(parent_window)
        help_dialog.title("Server Manager Dashboard - Help")
        help_dialog.transient(parent_window)
        help_dialog.grab_set()

        main_frame = ttk.Frame(help_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="Server Manager Dashboard Help",
                              font=("Segoe UI", 16, "bold"))
        title_label.pack(anchor=tk.W, pady=(0, 20))

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        _add_overview_tab(notebook)
        _add_controls_tab(notebook)
        _add_server_management_tab(notebook)
        _add_troubleshooting_tab(notebook)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Close", command=help_dialog.destroy, width=15).pack(side=tk.RIGHT)

        centre_window(help_dialog, 800, 700, parent_window)

    except Exception as e:
        error_msg = f"Help dialog error: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Help failed: {str(e)}")

def _add_overview_tab(notebook):
    # Overview tab content
    overview_frame = ttk.Frame(notebook)
    notebook.add(overview_frame, text="Overview")

    overview_text = scrolledtext.ScrolledText(overview_frame, wrap=tk.WORD,
                                            width=70, height=20, font=("Segoe UI", 10))
    overview_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    overview_content = """Server Manager Dashboard

Overview

Server Manager Dashboard is a comprehensive application designed to simplify the management of game servers on Windows systems. It provides a centralized interface for installing, configuring, and monitoring various types of game servers, including Steam-based servers, Minecraft servers, and custom server applications.

The dashboard offers real-time monitoring of system resources and server performance, ensuring optimal operation and quick identification of issues. Key capabilities include automated server installation, process management, web-based remote access, and configuration management through import/export functionality.

Getting Started

To begin using Server Manager Dashboard:

1. Launch the application and review the main interface components.
2. Add your first server using the Add Server button in the toolbar.
3. Monitor server status and system resources in the main dashboard view.
4. Access additional server management options through the right-click context menu.
5. Enable the web dashboard for remote management if required.

Supported Server Types

Server Manager Dashboard supports the following server types:

- Steam Servers: Automated deployment using SteamCMD for games available on the Steam platform.
- Minecraft Servers: Support for vanilla Minecraft and modded versions using Fabric, Forge, or NeoForge loaders.
- Other Servers: Custom server executables and scripts for games not covered by the above categories."""

    overview_text.insert(tk.END, overview_content)
    overview_text.config(state=tk.DISABLED)

def _add_controls_tab(notebook):
    # Add the Controls & Shortcuts tab to the help notebook
    controls_frame = ttk.Frame(notebook)
    notebook.add(controls_frame, text="Controls & Shortcuts")

    controls_text = scrolledtext.ScrolledText(controls_frame, wrap=tk.WORD,
                                            width=70, height=20, font=("Segoe UI", 10))
    controls_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    controls_content = """Interface Controls and Shortcuts

Main Interface Components

Server List Panel

The server list displays all configured servers with their current status and basic information.

- Left-click: Select a server for operations.
- Right-click: Display the context menu with available actions for the selected server.
- Double-click: Open detailed server information and configuration.

Toolbar Buttons

- Add Server: Opens the server creation wizard to add a new game server.
- Remove Server: Removes the selected server configuration from management.
- Import Server: Imports server configurations from files or existing directories.
- Export Server: Exports the selected server configuration to a file for backup.
- Refresh: Updates all server statuses and refreshes system information.
- Sync All: Synchronizes all server configurations with the database.
- Add Agent: Creates a new monitoring agent for automated tasks.

Context Menu Options

Right-clicking on a server in the list provides the following options:

- Start Server: Launches the selected server process.
- Stop Server: Gracefully shuts down the selected server.
- Restart Server: Stops and then restarts the selected server.
- View Process Details: Displays detailed information about the server process.
- Configure Server: Opens the server configuration dialog for modifications.
- Export Server: Saves the server configuration to a file.
- Open Folder Directory: Opens the server's installation directory in Windows Explorer.
- Remove Server: Deletes the server from the management interface.

System Information Panel

The system information panel displays real-time resource usage:

- CPU: Current processor utilization percentage.
- Memory: RAM usage and total available memory.
- Disk Space: Storage utilization for system drives.
- Network: Network interface activity and throughput.
- GPU: Graphics processing unit information (when available).
- System Uptime: Duration since the last system restart.

Web Server Status Indicator

- Displays the connection status of the web dashboard service.
- Click the indicator to open the web interface in the default browser (when online).
- Use the Offline Mode toggle to disable web features if needed."""

    controls_text.insert(tk.END, controls_content)
    controls_text.config(state=tk.DISABLED)

def _add_server_management_tab(notebook):
    # Add the Server Management tab to the help notebook
    servers_frame = ttk.Frame(notebook)
    notebook.add(servers_frame, text="Server Management")

    servers_text = scrolledtext.ScrolledText(servers_frame, wrap=tk.WORD,
                                           width=70, height=20, font=("Segoe UI", 10))
    servers_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    servers_content = """Server Management

Adding Servers

Steam Servers

To add a Steam-based game server:

1. Click the Add Server button in the toolbar.
2. Select Steam from the server type options.
3. Enter your Steam account credentials when prompted for authentication.
4. Provide the Steam Application ID for the desired game server.
5. Specify the installation directory or accept the default location.
6. Configure any additional startup parameters as required.
7. Click Create Server to begin the automated installation process.

Minecraft Servers

To add a Minecraft server:

1. Click the Add Server button in the toolbar.
2. Select Minecraft from the server type options.
3. Choose the desired Minecraft version from the version dropdown.
4. Select the appropriate mod loader (Vanilla, Fabric, Forge, or NeoForge).
5. Specify the installation directory for the server files.
6. Configure JVM arguments and memory allocation settings.
7. Click Create Server to download and install the server.

Other Server Types

To add a custom server:

1. Click the Add Server button in the toolbar.
2. Select Other from the server type options.
3. Provide the full path to the server executable file.
4. Specify the working directory for the server process.
5. Configure any command-line arguments required for startup.
6. Click Create Server to register the server for management.

Server Status Monitoring

Server status indicators provide real-time information about server state:

- Online: The server is running and responding to queries.
- Offline: The server is not currently active.
- Starting: The server is in the process of initialization.
- Stopping: The server is shutting down gracefully.
- Error: The server has encountered an issue preventing normal operation.

Managing Active Servers

Once servers are running, you can:

- Monitor real-time CPU and memory consumption in the system panel.
- Access detailed process information for troubleshooting.
- Review server uptime and performance metrics.
- Examine log files through the process details dialog.
- Restart unresponsive servers using the context menu.

Configuration Management

The import and export features allow you to:

- Export server configurations to JSON files for backup purposes.
- Import configurations from previously exported files.
- Scan existing server directories to automatically detect and import servers.
- Preserve all settings, file paths, and custom configurations during transfers."""

    servers_text.insert(tk.END, servers_content)
    servers_text.config(state=tk.DISABLED)

def _add_troubleshooting_tab(notebook):
    # Add the Troubleshooting tab to the help notebook
    troubleshooting_frame = ttk.Frame(notebook)
    notebook.add(troubleshooting_frame, text="Troubleshooting")

    troubleshooting_text = scrolledtext.ScrolledText(troubleshooting_frame, wrap=tk.WORD,
                                                   width=70, height=20, font=("Segoe UI", 10))
    troubleshooting_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    troubleshooting_content = """Troubleshooting

Common Issues and Resolutions

Server Startup Failures

If a server fails to start:

- Verify that the executable path specified in the server configuration is correct and the file exists.
- Check that all required startup arguments are properly formatted.
- Ensure the server directory has appropriate read/write permissions.
- Confirm that required network ports are available and not in use by other applications.
- Review the process details dialog for specific error messages or log entries.

Installation Problems

For issues during server installation:

- Verify that an active internet connection is available for downloading required files.
- Check that sufficient disk space is available in the target installation directory.
- Ensure that antivirus software is not blocking the installation process.
- Try running Server Manager Dashboard with administrator privileges.
- Review firewall settings to allow necessary network access.

Performance Issues

If servers or the management interface experience performance problems:

- Monitor CPU and memory usage in the system information panel for resource constraints.
- Close unnecessary applications to free up system resources.
- Verify that the system cooling is adequate to prevent thermal throttling.
- Ensure sufficient RAM is allocated for server requirements.
- Check disk space availability and consider defragmentation if using mechanical drives.

Web Dashboard Access Issues

If the web dashboard is not accessible:

- Check the web server status indicator to confirm the service is running.
- Verify that firewall rules allow traffic on the configured port.
- Disable Offline Mode in the application settings if it is enabled.
- Ensure the configured port is not already in use by another application.

Database Connection Errors

For database-related errors:

- Restart Server Manager Dashboard to refresh database connections.
- Check for database file corruption in the application data directory.
- Verify sufficient disk space for database operations.
- Ensure proper file permissions on database files.

Steam Server Specific Issues

For Steam-based servers:

- Verify that Steam account credentials are correct and have access to the game.
- Ensure SteamCMD is properly installed and accessible.
- Confirm that the provided App ID is valid and corresponds to a dedicated server.
- Update the SteamCMD installation to the latest version.

Minecraft Server Issues

For Minecraft servers:

- Verify that Java is installed and accessible via the system PATH.
- Check that the selected Minecraft version is supported by the application.
- Ensure adequate memory allocation through JVM arguments.
- Verify mod loader compatibility with the selected Minecraft version.

Debug Mode and Logging

To enable detailed troubleshooting:

- Enable debug mode in the application configuration for verbose logging.
- Review log files located in the application directory for error details.
- Use the View Process Details option for real-time monitoring.
- Monitor system resource usage to identify performance bottlenecks.

Additional Support

If issues persist after trying the above solutions:

- Review application logs for detailed error messages and stack traces.
- Restart the application with administrator privileges.
- Verify that all required dependencies and prerequisites are properly installed.
- Contact technical support with specific error messages and system information."""

    troubleshooting_text.insert(tk.END, troubleshooting_content)
    troubleshooting_text.config(state=tk.DISABLED)

def get_version_from_registry():
    # Get the current version from Windows registry
    from Modules.common import get_registry_value
    return get_registry_value(REGISTRY_PATH, "CurrentVersion", "Unknown")

def get_application_info():
    # Get comprehensive application information for display
    return {
        "name": "Server Manager Dashboard",
        "description": "A comprehensive game server management application for Windows systems",
        "version": get_version_from_registry(),
        "author": "Skywere Industries",
        "copyright": "© 2023-2026 Skywere Industries. All rights reserved.",
        "supported_servers": ["Steam Servers", "Minecraft Servers", "Custom Servers"],
        "system_requirements": {
            "os": "Windows 10 or later (64-bit)",
            "cpu": "Dual-core processor or higher",
            "ram": "4 GB minimum, 8 GB recommended",
            "storage": "2 GB available disk space",
            "network": "Broadband internet connection for downloads"
        },
        "features": [
            "Automated server installation and deployment",
            "Real-time system and server monitoring",
            "Process management and control",
            "Web-based remote dashboard interface",
            "Automated agent management",
            "Configuration import and export",
            "Multi-user access control",
            "Comprehensive logging and diagnostics"
        ],
        "contact": "For support and documentation, visit the project repository."
    }

def show_about_dialog(parent_window, logger=None):
    # Display a professional about dialog with comprehensive application information
    try:
        app_info = get_application_info()

        about_dialog = tk.Toplevel(parent_window)
        about_dialog.title("About Server Manager Dashboard")
        about_dialog.transient(parent_window)
        about_dialog.grab_set()
        about_dialog.resizable(False, False)

        # Main frame with padding
        main_frame = ttk.Frame(about_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Application name and version
        ttk.Label(main_frame, text=app_info["name"],
                 font=("Segoe UI", 16, "bold")).pack(pady=(0, 5))
        ttk.Label(main_frame, text=f"Version {app_info['version']}",
                 font=("Segoe UI", 12)).pack(pady=(0, 15))

        # Description
        desc_frame = ttk.LabelFrame(main_frame, text="Description", padding=10)
        desc_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(desc_frame, text=app_info["description"],
                 font=("Segoe UI", 10), wraplength=350).pack(anchor=tk.W)

        # System Requirements
        req_frame = ttk.LabelFrame(main_frame, text="System Requirements", padding=10)
        req_frame.pack(fill=tk.X, pady=(0, 10))
        req_text = f"""Operating System: {app_info['system_requirements']['os']}
Processor: {app_info['system_requirements']['cpu']}
Memory: {app_info['system_requirements']['ram']}
Storage: {app_info['system_requirements']['storage']}
Network: {app_info['system_requirements']['network']}"""
        ttk.Label(req_frame, text=req_text, font=("Segoe UI", 9),
                 justify=tk.LEFT).pack(anchor=tk.W)

        # Supported Server Types
        servers_frame = ttk.LabelFrame(main_frame, text="Supported Server Types", padding=10)
        servers_frame.pack(fill=tk.X, pady=(0, 10))
        servers_text = "\n".join(f"• {server}" for server in app_info["supported_servers"])
        ttk.Label(servers_frame, text=servers_text, font=("Segoe UI", 9),
                 justify=tk.LEFT).pack(anchor=tk.W)

        # Copyright and author
        ttk.Label(main_frame, text=app_info["copyright"],
                 font=("Segoe UI", 9)).pack(pady=(10, 5))
        ttk.Label(main_frame, text=app_info["contact"],
                 font=("Segoe UI", 9)).pack(pady=(0, 15))

        # Close button
        ttk.Button(main_frame, text="Close", command=about_dialog.destroy,
                  width=15).pack()

        # Centre dialog relative to parent
        centre_window(about_dialog, 400, 500, parent_window)

    except Exception as e:
        error_msg = f"Error showing about dialog: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Failed to show about dialog: {str(e)}")

# Test function for standalone testing
def test_documentation():
    # Test function to run the documentation dialogs standalone (DEBUG!)
    root = tk.Tk()
    root.title("Documentation Test")

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Documentation Module Test",
             font=("Segoe UI", 14, "bold")).pack(pady=10)

    ttk.Button(frame, text="Show Help",
              command=lambda: show_help_dialog(root)).pack(pady=5)

    ttk.Button(frame, text="Show About",
              command=lambda: show_about_dialog(root)).pack(pady=5)

    ttk.Button(frame, text="Exit", command=root.destroy).pack(pady=10)

    # Centre the test window
    centre_window(root, 400, 200)

    root.mainloop()

if __name__ == "__main__":
    test_documentation()
