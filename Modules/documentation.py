"""
Documentation Module for Server Manager Dashboard

This module provides comprehensive help and documentation functionality
for the Server Manager Dashboard application.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import winreg
import os


def show_help_dialog(parent_window, logger=None):
    """
    Show help dialog with program information and controls
    
    Args:
        parent_window: The parent tkinter window to center the dialog on
        logger: Optional logger instance for error logging
    """
    try:
        # Create help dialog
        help_dialog = tk.Toplevel(parent_window)
        help_dialog.title("Server Manager Dashboard - Help")
        help_dialog.geometry("800x700")
        help_dialog.transient(parent_window)
        help_dialog.grab_set()
        
        # Create main frame with padding
        main_frame = ttk.Frame(help_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="Server Manager Dashboard Help", 
                              font=("Segoe UI", 16, "bold"))
        title_label.pack(anchor=tk.W, pady=(0, 20))
        
        # Create notebook for organized help sections
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Add all help tabs
        _add_overview_tab(notebook)
        _add_controls_tab(notebook)
        _add_server_management_tab(notebook)
        _add_troubleshooting_tab(notebook)
        
        # Close button
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(button_frame, text="Close", command=help_dialog.destroy, width=15).pack(side=tk.RIGHT)
        
        # Center dialog on parent window
        help_dialog.update_idletasks()
        x = parent_window.winfo_rootx() + (parent_window.winfo_width() - help_dialog.winfo_width()) // 2
        y = parent_window.winfo_rooty() + (parent_window.winfo_height() - help_dialog.winfo_height()) // 2
        help_dialog.geometry(f"+{x}+{y}")
        
    except Exception as e:
        error_msg = f"Error showing help dialog: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Failed to show help: {str(e)}")


def _add_overview_tab(notebook):
    """Add the Overview tab to the help notebook"""
    overview_frame = ttk.Frame(notebook)
    notebook.add(overview_frame, text="Overview")
    
    overview_text = scrolledtext.ScrolledText(overview_frame, wrap=tk.WORD, 
                                            width=70, height=20, font=("Segoe UI", 10))
    overview_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    overview_content = """Welcome to Server Manager Dashboard!

This application helps you manage game servers including Steam servers, Minecraft servers, and other custom servers.

Key Features:
• Centralized server management and monitoring
• Real-time system resource monitoring
• Server installation and configuration
• Process monitoring and control
• Web-based dashboard interface
• Agent management for automated tasks
• Import/Export server configurations

Getting Started:
1. Use "Add Server" to create new game servers
2. Monitor server status and performance in the main list
3. Use right-click context menu for server actions
4. Check system information panel for resource usage
5. Access web dashboard through the web server status indicator

Server Types Supported:
• Steam Servers: Automated installation via SteamCMD
• Minecraft Servers: Vanilla, Fabric, Forge, and NeoForge
• Other Servers: Custom executables and scripts"""
    
    overview_text.insert(tk.END, overview_content)
    overview_text.config(state=tk.DISABLED)


def _add_controls_tab(notebook):
    """Add the Controls & Shortcuts tab to the help notebook"""
    controls_frame = ttk.Frame(notebook)
    notebook.add(controls_frame, text="Controls & Shortcuts")
    
    controls_text = scrolledtext.ScrolledText(controls_frame, wrap=tk.WORD, 
                                            width=70, height=20, font=("Segoe UI", 10))
    controls_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    controls_content = """Main Interface Controls:

Server List:
• Left Click: Select a server
• Right Click: Open context menu with server actions
• Double Click: View server details

Button Controls:
• Add Server: Create a new game server installation
• Remove Server: Delete selected server configuration
• Import Server: Import server from file or directory
• Export Server: Export selected server configuration
• Refresh: Update all server statuses and system info
• Sync All: Synchronize all server configurations
• Add Agent: Create automated monitoring agents

Context Menu Options:
• Start Server: Launch the selected server
• Stop Server: Gracefully shut down the server
• Restart Server: Stop and start the server
• View Process Details: Show detailed process information
• Configure Server: Modify server settings
• Export Server: Save server configuration to file
• Open Folder Directory: Open server installation folder
• Remove Server: Delete server from management

System Information Panel:
• CPU: Current processor usage
• Memory: RAM usage and availability
• Disk Space: Storage usage on system drives
• Network: Network adapter activity
• GPU: Graphics card information (if available)
• System Uptime: How long the system has been running

Web Server Status:
• Shows connection status to the web dashboard
• Click to access web interface (when available)
• Toggle "Offline Mode" to disable web features"""
    
    controls_text.insert(tk.END, controls_content)
    controls_text.config(state=tk.DISABLED)


def _add_server_management_tab(notebook):
    """Add the Server Management tab to the help notebook"""
    servers_frame = ttk.Frame(notebook)
    notebook.add(servers_frame, text="Server Management")
    
    servers_text = scrolledtext.ScrolledText(servers_frame, wrap=tk.WORD, 
                                           width=70, height=20, font=("Segoe UI", 10))
    servers_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    servers_content = """Server Management Guide:

Adding Steam Servers:
1. Click "Add Server" and select "Steam"
2. Enter your Steam credentials when prompted
3. Provide the Steam App ID for the server
4. Choose installation directory (or use default)
5. Set startup arguments if needed
6. Click "Create Server" to begin installation

Adding Minecraft Servers:
1. Click "Add Server" and select "Minecraft"
2. Choose Minecraft version from the dropdown
3. Select modloader (Vanilla, Fabric, Forge, NeoForge)
4. Set installation directory
5. Configure startup arguments (JVM settings, etc.)
6. Click "Create Server" to download and install

Adding Other Servers:
1. Click "Add Server" and select "Other"
2. Provide the executable path
3. Set installation/working directory
4. Configure startup arguments
5. Click "Create Server" to register

Server Status Indicators:
• Online: Server is running and responding
• Offline: Server is not currently running
• Starting: Server is in the process of starting up
• Stopping: Server is shutting down
• Error: Server encountered an issue

Managing Running Servers:
• Monitor CPU and memory usage in real-time
• View process details for troubleshooting
• Check server uptime and performance
• Access log files through process details
• Restart servers if they become unresponsive

Import/Export Features:
• Export: Save server configurations for backup
• Import from File: Restore from exported configuration
• Import from Directory: Scan existing server folders
• Configurations include all settings and file paths"""
    
    servers_text.insert(tk.END, servers_content)
    servers_text.config(state=tk.DISABLED)


def _add_troubleshooting_tab(notebook):
    """Add the Troubleshooting tab to the help notebook"""
    troubleshooting_frame = ttk.Frame(notebook)
    notebook.add(troubleshooting_frame, text="Troubleshooting")
    
    troubleshooting_text = scrolledtext.ScrolledText(troubleshooting_frame, wrap=tk.WORD, 
                                                   width=70, height=20, font=("Segoe UI", 10))
    troubleshooting_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    troubleshooting_content = """Common Issues and Solutions:

Server Won't Start:
• Check if the executable path is correct
• Verify startup arguments are properly formatted
• Ensure the server directory has proper permissions
• Check if required ports are available
• View process details for error messages

Installation Problems:
• Verify internet connection for downloads
• Check available disk space
• Ensure antivirus isn't blocking files
• Try running as administrator
• Check firewall settings

Performance Issues:
• Monitor CPU and memory usage in system panel
• Close unnecessary programs
• Check for adequate cooling
• Verify adequate RAM for server requirements
• Monitor disk space and fragmentation

Web Dashboard Not Accessible:
• Check if web server is running (status indicator)
• Verify firewall allows the configured port
• Try disabling "Offline Mode"
• Check if port is already in use by another application

Database Connection Errors:
• Restart the application
• Check if database files are corrupted
• Verify disk space for database operations
• Check file permissions in application directory

Steam Server Issues:
• Verify Steam credentials are correct
• Check if SteamCMD is properly installed
• Ensure App ID is valid and accessible
• Try updating SteamCMD installation

Minecraft Server Issues:
• Verify Java is installed and accessible
• Check if the Minecraft version is supported
• Ensure adequate memory allocation (JVM settings)
• Verify modloader compatibility with version

Debug Mode:
• Enable debug mode in configuration for detailed logging
• Check log files in the application directory
• Use "View Process Details" for real-time monitoring
• Monitor resource usage for performance bottlenecks

If problems persist:
• Check the application logs for detailed error messages
• Restart the application with administrator privileges
• Verify all dependencies are properly installed
• Contact support with specific error messages"""
    
    troubleshooting_text.insert(tk.END, troubleshooting_content)
    troubleshooting_text.config(state=tk.DISABLED)


def get_version_from_registry():
    """
    Get the current version from Windows registry
    
    Returns:
        str: Version string from registry or 'Unknown' if not found
    """
    try:
        registry_path = r"Software\SkywereIndustries\Servermanager"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        version = winreg.QueryValueEx(key, "CurrentVersion")[0]
        winreg.CloseKey(key)
        return version
    except Exception:
        return "Unknown"


def get_application_info():
    """
    Get basic application information for display
    
    Returns:
        dict: Dictionary containing application information
    """
    return {
        "name": "Server Manager Dashboard",
        "description": "A comprehensive game server management application",
        "version": get_version_from_registry(),
        "author": "Skywere Industries",
        "supported_servers": ["Steam", "Minecraft", "Other"],
        "features": [
            "Server installation and management",
            "Real-time monitoring",
            "Process control",
            "Web dashboard",
            "Agent automation",
            "Configuration import/export"
        ]
    }


def show_about_dialog(parent_window, logger=None):
    """
    Show a simple about dialog with application information
    
    Args:
        parent_window: The parent tkinter window
        logger: Optional logger instance for error logging
    """
    try:
        app_info = get_application_info()
        
        about_dialog = tk.Toplevel(parent_window)
        about_dialog.title("About Server Manager Dashboard")
        about_dialog.geometry("400x300")
        about_dialog.transient(parent_window)
        about_dialog.grab_set()
        about_dialog.resizable(False, False)
        
        # Main frame
        main_frame = ttk.Frame(about_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Application name
        ttk.Label(main_frame, text=app_info["name"], 
                 font=("Segoe UI", 16, "bold")).pack(pady=(0, 10))
        
        # Version
        ttk.Label(main_frame, text=f"Version {app_info['version']}", 
                 font=("Segoe UI", 12)).pack(pady=(0, 10))
        
        # Description
        ttk.Label(main_frame, text=app_info["description"], 
                 font=("Segoe UI", 10)).pack(pady=(0, 15))
        
        # Author
        ttk.Label(main_frame, text=f"© 2025 {app_info['author']}", 
                 font=("Segoe UI", 10)).pack(pady=(0, 20))
        
        # Close button
        ttk.Button(main_frame, text="Close", command=about_dialog.destroy, 
                  width=15).pack()
        
        # Center dialog
        about_dialog.update_idletasks()
        x = parent_window.winfo_rootx() + (parent_window.winfo_width() - about_dialog.winfo_width()) // 2
        y = parent_window.winfo_rooty() + (parent_window.winfo_height() - about_dialog.winfo_height()) // 2
        about_dialog.geometry(f"+{x}+{y}")
        
    except Exception as e:
        error_msg = f"Error showing about dialog: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Failed to show about dialog: {str(e)}")


# Test function for standalone testing
def test_documentation():
    """Test function to run the documentation dialogs standalone"""
    root = tk.Tk()
    root.title("Documentation Test")
    root.geometry("400x200")
    
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(frame, text="Documentation Module Test", 
             font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    ttk.Button(frame, text="Show Help", 
              command=lambda: show_help_dialog(root)).pack(pady=5)
    
    ttk.Button(frame, text="Show About", 
              command=lambda: show_about_dialog(root)).pack(pady=5)
    
    ttk.Button(frame, text="Exit", command=root.destroy).pack(pady=10)
    
    root.mainloop()


if __name__ == "__main__":
    test_documentation()