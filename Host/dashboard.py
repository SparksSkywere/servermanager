# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import winreg
import json
import time
import psutil
import platform
import datetime
import socket
import urllib.request

# GUI imports
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import user management system
from Scripts.user_management import UserManager
from Modules.SQL_Connection import get_engine, initialize_user_manager, sql_login
from Modules.server_manager import ServerManager

# Import Minecraft server functions
from Scripts.minecraft import (
    fetch_minecraft_versions, get_minecraft_server_jar_url,
    fetch_fabric_installer_url, fetch_forge_installer_url,
    fetch_neoforge_installer_url, MinecraftServerManager
)

# Import logging functions from the logging module
from Modules.logging import (
    get_dashboard_logger, configure_dashboard_logging,
    log_dashboard_event, log_server_action, log_installation_progress,
    log_process_monitoring, log_security_event, log_user_action
)

# Import timer management
from Modules.timer import TimerManager

# Import documentation module
from Modules.documentation import show_help_dialog, show_about_dialog

# Import common module infrastructure
from Modules.common import ServerManagerModule, initialize_paths_from_registry, initialize_registry_values

# Import dashboard functions (reduced scope)
from Host.dashboard_functions import (
    load_dashboard_config, is_port_open, check_webserver_status, update_webserver_status,
    api_headers, get_steam_credentials, update_system_info, format_uptime_from_start_time,
    get_process_info, export_server_configuration, import_server_configuration,
    export_server_to_file, import_server_from_file, extract_server_files_from_archive,
    generate_unique_server_name, center_window, create_server_type_selection_dialog,
    update_server_status_in_treeview, validate_server_creation_inputs, 
    open_directory_in_explorer, create_confirmation_dialog, show_progress_dialog,
    create_server_installation_dialog, create_server_removal_dialog, perform_server_installation,
    update_server_list_from_files, create_progress_dialog_with_console, load_appid_scanner_list
)

# Import agent management
from Modules.agents import AgentManager, show_agent_management_dialog

# Import debug functions
from Modules.debug import (
    get_detailed_process_info, get_server_process_details, check_port_status,
    is_debug_enabled, log_exception, monitor_process_resources
)

# Get dashboard logger
logger = get_dashboard_logger()

class ServerManagerDashboard(ServerManagerModule):
    def __init__(self, debug_mode=False):
        super().__init__("ServerManagerDashboard")
        
        self.steam_cmd_path = None
        self.servers = []
        self.debug_mode = debug_mode
        self.user_manager = None
        self.current_user = None
        self.install_process = None  # Track installation process
        
        # Load dashboard configuration from JSON file (use inherited config from base class)
        dashboard_config = load_dashboard_config(self.server_manager_dir)
        
        # Update the base config with dashboard-specific settings
        self._config_manager.config.update(dashboard_config)

        # Load AppID/server info from database (not JSON)
        self.dedicated_servers, self.appid_metadata = load_appid_scanner_list(self.server_manager_dir)
        
        # Initialize runtime variables from config
        self.variables = {
            "previousNetworkStats": {},
            "previousNetworkTime": datetime.datetime.now(),
            "lastServerListUpdate": datetime.datetime.min,
            "lastFullUpdate": datetime.datetime.min,
            "networkAdapters": [],
            "lastNetworkStats": {},
            "lastNetworkStatsTime": datetime.datetime.now(),
            "systemInfo": {},
            "diskInfo": [],
            "gpuInfo": None,
            "lastProcessUpdate": datetime.datetime.min,
            "processStatHistory": {},
            "failedProcessRestarts": {},
            # Load configuration values
            "debugMode": self.config.get("configuration", {}).get("debugMode", True),
            "offlineMode": self.config.get("configuration", {}).get("offlineMode", False),
            "systemRefreshInterval": self.config.get("configuration", {}).get("systemRefreshInterval", 4),
            "processMonitoringInterval": self.config.get("configuration", {}).get("processMonitoringInterval", 5),
            "maxProcessHistoryPoints": self.config.get("configuration", {}).get("maxProcessHistoryPoints", 20),
            "networkUpdateInterval": self.config.get("configuration", {}).get("networkUpdateInterval", 5),
            "serverListUpdateInterval": self.config.get("configuration", {}).get("serverListUpdateInterval", 30),
            "systemInfoUpdateInterval": self.config.get("configuration", {}).get("systemInfoUpdateInterval", 5),
            "processMonitorUpdateInterval": self.config.get("configuration", {}).get("processMonitorUpdateInterval", 10),
            "webserverStatusUpdateInterval": self.config.get("configuration", {}).get("webserverStatusUpdateInterval", 15),
            # Runtime variables from config
            "formDisplayed": self.config.get("runtime", {}).get("formDisplayed", False),
            "verificationInProgress": self.config.get("runtime", {}).get("verificationInProgress", False),
            "webserverStatus": self.config.get("runtime", {}).get("webserverStatus", "Disconnected"),
            # Registry-managed variables (will be set from registry)
            "defaultSteamPath": "",
            "webserverPort": 8080
        }
        
        # Initialize paths from registry and setup the application
        success, self.steam_cmd_path, webserver_port, self.registry_values = initialize_registry_values(self.registry_path)
        if success:
            self.variables["defaultSteamPath"] = self.steam_cmd_path or ""
            self.variables["webserverPort"] = webserver_port
            # Set default install directories for different server types
            if self.steam_cmd_path:
                self.variables["defaultSteamInstallDir"] = self.steam_cmd_path
            else:
                self.variables["defaultSteamInstallDir"] = ""
            # Default directory for Minecraft and Other servers (under servermanager)
            if self.server_manager_dir:
                self.variables["defaultServerManagerInstallDir"] = os.path.join(self.server_manager_dir, "servers")
            else:
                self.variables["defaultServerManagerInstallDir"] = ""
        else:
            logger.error("Failed to initialize registry values")
            sys.exit(1)
        
        # Initialize user management system
        try:
            engine, self.user_manager = initialize_user_manager()
        except Exception as e:
            logger.error(f"Failed to initialize user management: {e}")
            messagebox.showerror("Database Error", f"Failed to connect to user database:\n{str(e)}")
            sys.exit(1)
            
        # Initialize server manager
        try:
            self.server_manager = ServerManager()
            logger.info("Server manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize server manager: {e}")
            # Continue without server manager but show warning
            self.server_manager = None
            messagebox.showwarning("Server Manager Warning", 
                                 f"Server manager failed to initialize:\n{str(e)}\n\n"
                                 "Some server operations may not be available.")
            
            
        # Configure dashboard logging after paths are initialized
        configure_dashboard_logging(self.debug_mode, self.config)
        
        # Set up the UI
        self.root = tk.Tk()
        self.root.title("Server Manager Dashboard")
        self.root.minsize(1000, 700)
        
        # Center the main window on screen
        center_window(self.root, 1400, 900)
        
        self.setup_ui()
        
        # Write PID file
        self.write_pid_file("dashboard", os.getpid())
        
        # Initialize timer manager
        self.timer_manager = TimerManager(self)
        
        # Initialize agent manager
        try:
            agents_config_path = os.path.join(self.paths["data"], "agents.json")
            self.agent_manager = AgentManager(agents_config_path)
            logger.info("Agent manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize agent manager: {str(e)}")
            self.agent_manager = None
        
        # Initialize system info and timers
        self.update_system_info()
        self.timer_manager.start_timers()
        
        # Get supported server types from server manager
        if self.server_manager:
            self.supported_server_types = self.server_manager.get_supported_server_types()
        else:
            self.supported_server_types = ["Steam", "Minecraft", "Other"]
        
        # Prompt for login using SQL authentication
        # Exit if login is cancelled
        try:
            success, user = sql_login(self.user_manager, self.root)
            if not success:
                logger.info("Login cancelled, exiting application")
                self.root.destroy()
                sys.exit(0)
            self.current_user = user
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            messagebox.showerror("Login Error", f"Failed to authenticate: {str(e)}\n\nThe application will exit.")
            self.root.destroy()
            sys.exit(1)

    def setup_ui(self):
        """Setup the main UI components"""
        # Create top frame for help and about buttons
        self.top_frame = ttk.Frame(self.root)
        self.top_frame.pack(fill=tk.X, padx=15, pady=(15, 0))
        
        # Add About and Help buttons to top right
        self.help_button = ttk.Button(self.top_frame, text="Help", command=self.show_help, width=10)
        self.help_button.pack(side=tk.RIGHT)
        
        self.about_button = ttk.Button(self.top_frame, text="About", command=self.show_about, width=10)
        self.about_button.pack(side=tk.RIGHT, padx=(0, 5))
        
        # Create main container with more padding
        self.container_frame = ttk.Frame(self.root, padding=(15, 10, 15, 15))
        self.container_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create main layout - servers list and system info
        self.main_pane = ttk.PanedWindow(self.container_frame, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create frame for server list (left side)
        self.servers_frame = ttk.LabelFrame(self.main_pane, text="Game Servers", padding=10)
        self.main_pane.add(self.servers_frame, weight=70)
        
        # Create server list with columns
        columns = ("name", "status", "pid", "cpu", "memory", "uptime")
        self.server_list = ttk.Treeview(self.servers_frame, columns=columns, show="headings")
        
        # Define column headings
        self.server_list.heading("name", text="Server Name")
        self.server_list.heading("status", text="Status")
        self.server_list.heading("pid", text="PID")
        self.server_list.heading("cpu", text="CPU Usage")
        self.server_list.heading("memory", text="Memory Usage")
        self.server_list.heading("uptime", text="Uptime")
        
        # Define column widths with better proportions
        self.server_list.column("name", width=180, minwidth=120)
        self.server_list.column("status", width=100, minwidth=80)
        self.server_list.column("pid", width=80, minwidth=60)
        self.server_list.column("cpu", width=100, minwidth=80)
        self.server_list.column("memory", width=120, minwidth=100)
        self.server_list.column("uptime", width=160, minwidth=120)
        
        # Add scrollbar to server list
        server_scroll = ttk.Scrollbar(self.servers_frame, orient=tk.VERTICAL, command=self.server_list.yview)
        self.server_list.configure(yscrollcommand=server_scroll.set)
        
        # Pack server list components with better spacing
        server_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        self.server_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Setup right-click context menu for server list
        self.server_context_menu = tk.Menu(self.root, tearoff=0)
        self.server_context_menu.add_command(label="Add Server", command=self.add_server)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Start Server", command=self.start_server)
        self.server_context_menu.add_command(label="Stop Server", command=self.stop_server)
        self.server_context_menu.add_command(label="Restart Server", command=self.restart_server)
        self.server_context_menu.add_command(label="View Process Details", command=self.view_process_details)
        self.server_context_menu.add_command(label="Configure Server", command=self.configure_server)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Export Server", command=self.export_server)
        self.server_context_menu.add_command(label="Open Folder Directory", command=self.open_server_directory)
        self.server_context_menu.add_command(label="Remove Server", command=self.remove_server)
        
        # Bind right-click to server list
        self.server_list.bind("<Button-3>", self.show_server_context_menu)
        
        # Create system info frame (right side)
        self.system_frame = ttk.LabelFrame(self.main_pane, text="System Information", padding=10)
        self.main_pane.add(self.system_frame, weight=30)
        
        # System info header
        self.system_header = ttk.Frame(self.system_frame)
        self.system_header.pack(fill=tk.X, pady=(0, 15))
        
        self.system_name = ttk.Label(self.system_header, text="Loading system info...", font=("Segoe UI", 14, "bold"))
        self.system_name.pack(anchor=tk.W, pady=(0, 5))
        
        self.os_info = ttk.Label(self.system_header, text="Loading OS info...", foreground="gray")
        self.os_info.pack(anchor=tk.W, pady=(0, 5))
        
        # Show installation info from registry
        if hasattr(self, 'registry_values'):
            install_info = ttk.Label(self.system_header, 
                text=f"Version: {self.registry_values.get('CurrentVersion', 'Unknown')} | "
                     f"Host Type: {self.registry_values.get('HostType', 'Unknown')}", 
                foreground="gray")
            install_info.pack(anchor=tk.W, pady=(0, 8))
        
        # Web server status
        self.webserver_frame = ttk.Frame(self.system_header)
        self.webserver_frame.pack(anchor=tk.W, pady=(0, 10))
        
        ttk.Label(self.webserver_frame, text="Web Server: ").pack(side=tk.LEFT)
        self.webserver_status = ttk.Label(self.webserver_frame, text="Checking...", foreground="gray")
        self.webserver_status.pack(side=tk.LEFT)
        
        # Offline mode toggle
        self.offline_var = tk.BooleanVar(value=self.variables["offlineMode"])
        self.offline_check = ttk.Checkbutton(
            self.webserver_frame,
            text="Offline Mode",
            variable=self.offline_var,
            command=self.toggle_offline_mode
        )
        self.offline_check.pack(side=tk.LEFT, padx=(15, 0))
        
        # System metrics grid
        self.metrics_frame = ttk.Frame(self.system_frame, padding=(5, 10))
        self.metrics_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid columns and rows with better weight distribution
        for i in range(2):
            self.metrics_frame.columnconfigure(i, weight=1, minsize=150)
        for i in range(3):
            self.metrics_frame.rowconfigure(i, weight=1, minsize=50)
        
        # Create metric panels
        self.metric_labels = {}
        
        metrics = [
            {"row": 0, "col": 0, "title": "CPU", "name": "cpu", "icon": "🖥️"},
            {"row": 0, "col": 1, "title": "Memory", "name": "memory", "icon": "💾"},
            {"row": 1, "col": 0, "title": "Disk Space", "name": "disk", "icon": "💿"},
            {"row": 1, "col": 1, "title": "Network", "name": "network", "icon": "🌐"},
            {"row": 2, "col": 0, "title": "GPU", "name": "gpu", "icon": "🎮"},
            {"row": 2, "col": 1, "title": "System Uptime", "name": "uptime", "icon": "⏱️"}
        ]
        
        for metric in metrics:
            frame = ttk.LabelFrame(self.metrics_frame, text=f"{metric['icon']} {metric['title']}", padding=8)
            frame.grid(row=metric["row"], column=metric["col"], padx=8, pady=8, sticky="nsew")
            
            value = ttk.Label(frame, text="Loading...", font=("Segoe UI", 10))
            value.pack(anchor=tk.W, fill=tk.X)
            
            self.metric_labels[metric["name"]] = value
        
        # Create button bar at bottom with better spacing
        self.button_frame = ttk.Frame(self.container_frame)
        self.button_frame.pack(fill=tk.X, pady=(15, 0))
        
        # Create two rows of buttons for better organization
        self.button_row1 = ttk.Frame(self.button_frame)
        self.button_row1.pack(fill=tk.X, pady=(0, 8))
        
        self.button_row2 = ttk.Frame(self.button_frame)
        self.button_row2.pack(fill=tk.X)
        
        # Add buttons with better organization
        row1_buttons = [
            {"text": "Add Server", "command": self.add_server},
            {"text": "Remove Server", "command": self.remove_server},
            {"text": "Import Server", "command": self.import_server},
            {"text": "Export Server", "command": self.export_server}
        ]
        
        row2_buttons = [
            {"text": "Configure Java", "command": self.configure_java},
            {"text": "Configure Server", "command": self.show_server_type_configuration},
            {"text": "Refresh", "command": self.refresh_all},
            {"text": "Sync All", "command": self.sync_all},
            {"text": "Add Agent", "command": self.add_agent}
        ]
        
        for btn in row1_buttons:
            ttk.Button(self.button_row1, text=btn["text"], command=btn["command"], width=18).pack(side=tk.LEFT, padx=(0, 10))
            
        for btn in row2_buttons:
            ttk.Button(self.button_row2, text=btn["text"], command=btn["command"], width=18).pack(side=tk.LEFT, padx=(0, 10))
    
    def show_server_context_menu(self, event):
        """Show context menu on right-click in server list"""
        # Get item under cursor
        item = self.server_list.identify_row(event.y)
        
        if item:
            # Select the item
            self.server_list.selection_set(item)
            # Enable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Start Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Restart Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("View Process Details", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Configure Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Export Server", state=tk.NORMAL)
        else:
            # Disable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Start Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Restart Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("View Process Details", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Configure Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Export Server", state=tk.DISABLED)
            
        # Show context menu
        self.server_context_menu.tk_popup(event.x_root, event.y_root)

    def add_server(self):
        """Add a new server using database-backed AppID/server info"""
        # Use self.dedicated_servers for AppID/server selection
        # Example: show a dialog to select from self.dedicated_servers
        # ...existing code...
        # When creating a Steam server, use the database info for AppID lookup
        # For example:
        # selected_appid = ... # from user selection
        # server_info = next((s for s in self.dedicated_servers if s["appid"] == selected_appid), None)
        # if server_info:
        #     # Use server_info for server creation
        # ...existing code...
        """Add a new game server (Steam, Minecraft, or Other)"""
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Use the new function to get server type selection
        server_type = create_server_type_selection_dialog(self.root, self.supported_server_types)
        
        # Check if user cancelled
        if not server_type:
            return

        # Get credentials if needed
        credentials = None
        if server_type == "Steam":
            credentials = get_steam_credentials(self.root)
            if not credentials:
                return

        # Create dialog for server details
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Create {server_type} Server")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Create main frame with padding
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Installation control
        self.install_cancelled = tk.BooleanVar(value=False)
        
        # Create a paned window for top-bottom split layout
        paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        
        # Top frame for setup information (50% of space)
        top_frame = ttk.Frame(paned_window)
        paned_window.add(top_frame, weight=1)
        
        # Create scrollable frame for the form inside top_frame
        canvas = tk.Canvas(top_frame)
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack the canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True, padx=(0, 5))
        scrollbar.pack(side="right", fill="y")
        
        # Configure grid weights for scrollable frame
        for i in range(3):
            scrollable_frame.columnconfigure(i, weight=1 if i == 1 else 0)

        # Create form variables
        form_vars = {
            'name': tk.StringVar(),
            'app_id': tk.StringVar(),
            'install_dir': tk.StringVar(),
            'exe_path': tk.StringVar(),
            'startup_args': tk.StringVar(),
            'minecraft_version': tk.StringVar(),
            'modloader': tk.StringVar(value="Vanilla")
        }

        # Server name
        ttk.Label(scrollable_frame, text="Server Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=15, pady=15, sticky=tk.W)
        name_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['name'], width=40, font=("Segoe UI", 10))
        name_entry.grid(row=0, column=1, columnspan=2, padx=15, pady=15, sticky=tk.EW)

        # Server type (readonly)
        ttk.Label(scrollable_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, padx=15, pady=10, sticky=tk.W)
        ttk.Label(scrollable_frame, text=server_type, font=("Segoe UI", 10)).grid(row=1, column=1, padx=15, pady=10, sticky=tk.W)

        current_row = 2

        # Minecraft-specific fields
        if server_type == "Minecraft":
            try:
                mc_versions = self.server_manager.get_minecraft_versions() if self.server_manager else []
                if not mc_versions:
                    messagebox.showerror("Error", "Failed to fetch Minecraft versions.")
                    dialog.destroy()
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Minecraft support not available: {str(e)}")
                dialog.destroy()
                return
                
            # Default to latest release
            latest_release = next((v for v in mc_versions if v["id"] == mc_versions[0]["id"]), mc_versions[0])
            form_vars['minecraft_version'].set(latest_release["id"])
            
            # Minecraft version dropdown
            ttk.Label(scrollable_frame, text="Minecraft Version:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            version_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['minecraft_version'], values=[v["id"] for v in mc_versions], state="readonly", width=37, font=("Segoe UI", 10))
            version_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            current_row += 1
            
            # Modloader selection
            ttk.Label(scrollable_frame, text="Modloader:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            modloader_frame = ttk.Frame(scrollable_frame)
            modloader_frame.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            modloaders = ["Vanilla", "Fabric", "Forge", "NeoForge"]
            for i, modloader in enumerate(modloaders):
                ttk.Radiobutton(modloader_frame, text=modloader, variable=form_vars['modloader'], value=modloader).grid(row=0, column=i, padx=10, pady=5, sticky=tk.W)
            current_row += 1

        # App ID (Steam only)
        if server_type == "Steam":
            ttk.Label(scrollable_frame, text="App ID:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            app_id_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['app_id'], width=30, font=("Segoe UI", 10))
            app_id_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)
            
            def browse_appid():
                # Create AppID selection dialog
                appid_dialog = tk.Toplevel(dialog)
                appid_dialog.title("Select Dedicated Server")
                appid_dialog.transient(dialog)
                appid_dialog.grab_set()
                appid_dialog.geometry("600x500")
                
                # Create search frame
                search_frame = ttk.Frame(appid_dialog, padding=10)
                search_frame.pack(fill=tk.X)
                
                ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
                search_var = tk.StringVar()
                search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
                search_entry.pack(side=tk.LEFT, padx=(5, 10))
                
                # Load dedicated servers from scanner's AppID list
                try:
                    dedicated_servers_data, metadata = load_appid_scanner_list(self.server_manager_dir)
                    
                    if not dedicated_servers_data:
                        # Fallback to hardcoded list if scanner data not available
                        logger.warning("Scanner AppID list not available, using fallback list")
                        dedicated_servers = [
                            {"name": "Counter-Strike 2 Dedicated Server", "appid": "730"},
                            {"name": "Team Fortress 2 Dedicated Server", "appid": "232250"},
                            {"name": "Left 4 Dead 2 Dedicated Server", "appid": "222860"},
                            {"name": "Garry's Mod Dedicated Server", "appid": "4020"},
                            {"name": "ARK: Survival Evolved Dedicated Server", "appid": "376030"},
                            {"name": "Rust Dedicated Server", "appid": "258550"},
                            {"name": "7 Days to Die Dedicated Server", "appid": "294420"},
                            {"name": "Valheim Dedicated Server", "appid": "896660"},
                            {"name": "Source Dedicated Server (Generic)", "appid": "205"}
                        ]
                    else:
                        # Use scanner data - convert to compatible format
                        dedicated_servers = [
                            {
                                "name": server.get("name", "Unknown Server"),
                                "appid": str(server.get("appid", "0")),
                                "developer": server.get("developer", ""),
                                "publisher": server.get("publisher", ""),
                                "description": server.get("description", ""),
                                "type": server.get("type", "Dedicated Server")
                            }
                            for server in dedicated_servers_data
                        ]
                        
                        logger.info(f"Loaded {len(dedicated_servers)} dedicated servers from scanner (last updated: {metadata.get('last_updated', 'Unknown')})")
                        
                        # Add refresh info to dialog
                        if metadata.get('last_updated'):
                            last_updated = metadata['last_updated']
                            if 'T' in last_updated:  # ISO format
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                                    formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                                    ttk.Label(search_frame, text=f"Data last updated: {formatted_date}", 
                                            foreground="gray", font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
                                except:
                                    pass
                        
                except Exception as e:
                    logger.error(f"Error loading scanner AppID list: {e}")
                    # Use fallback list
                    dedicated_servers = [
                        {"name": "Counter-Strike 2 Dedicated Server", "appid": "730"},
                        {"name": "Team Fortress 2 Dedicated Server", "appid": "232250"},
                        {"name": "Left 4 Dead 2 Dedicated Server", "appid": "222860"},
                        {"name": "Garry's Mod Dedicated Server", "appid": "4020"},
                        {"name": "Source Dedicated Server (Generic)", "appid": "205"}
                    ]
                
                # Create server list
                list_frame = ttk.Frame(appid_dialog, padding=10)
                list_frame.pack(fill=tk.BOTH, expand=True)
                
                # Enhanced treeview for server list with additional columns
                columns = ("name", "appid", "developer", "type")
                server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
                server_tree.heading("name", text="Server Name")
                server_tree.heading("appid", text="App ID")
                server_tree.heading("developer", text="Developer")
                server_tree.heading("type", text="Type")
                server_tree.column("name", width=300)
                server_tree.column("appid", width=80)
                server_tree.column("developer", width=150)
                server_tree.column("type", width=120)
                
                # Scrollbar
                scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
                server_tree.configure(yscrollcommand=scrollbar.set)
                
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                
                # Populate server list with enhanced data
                def populate_servers(filter_text=""):
                    server_tree.delete(*server_tree.get_children())
                    for server in dedicated_servers:
                        server_name = server["name"]
                        if not filter_text or filter_text.lower() in server_name.lower():
                            server_tree.insert("", tk.END, values=(
                                server_name, 
                                server["appid"],
                                server.get("developer", "Unknown")[:25] + ("..." if len(server.get("developer", "")) > 25 else ""),
                                server.get("type", "Dedicated Server")
                            ))
                
                populate_servers()
                
                # Enhanced search functionality
                def on_search(*args):
                    populate_servers(search_var.get())
                
                search_var.trace('w', on_search)
                
                # Add tooltip functionality for descriptions
                def show_server_info(event):
                    item = server_tree.selection()
                    if item:
                        selected_server = None
                        item_values = server_tree.item(item[0])['values']
                        for server in dedicated_servers:
                            if server["appid"] == str(item_values[1]):
                                selected_server = server
                                break
                        
                        if selected_server and selected_server.get("description"):
                            # Create a simple tooltip window
                            tooltip = tk.Toplevel(appid_dialog)
                            tooltip.wm_overrideredirect(True)
                            tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")
                            
                            # Limit description length
                            desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")
                            
                            label = tk.Label(tooltip, text=f"{selected_server['name']}\n\n{desc}", 
                                           background="lightyellow", relief="solid", borderwidth=1,
                                           wraplength=300, justify=tk.LEFT, font=("Segoe UI", 9))
                            label.pack()
                            
                            # Auto-hide after 3 seconds
                            tooltip.after(3000, tooltip.destroy)
                
                server_tree.bind('<Double-1>', show_server_info)
                
                # Button frame
                button_frame = ttk.Frame(appid_dialog, padding=10)
                button_frame.pack(fill=tk.X)
                
                def select_server():
                    selected = server_tree.selection()
                    
                    if selected:
                        # Use selected server from list
                        item = server_tree.item(selected[0])
                        appid = item['values'][1]
                        form_vars['app_id'].set(appid)
                        appid_dialog.destroy()
                    else:
                        messagebox.showinfo("No Selection", "Please select a server from the list.")
                
                def cancel_selection():
                    appid_dialog.destroy()
                
                ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT)
                ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)
                
                # Center dialog
                center_window(appid_dialog, 600, 500, dialog)
            
            ttk.Button(scrollable_frame, text="Browse", command=browse_appid, width=12).grid(row=current_row, column=2, padx=15, pady=10)
            current_row += 1
            
            # Help text for App ID
            ttk.Label(scrollable_frame, text="(Enter Steam App ID or use Browse to select from list)", foreground="gray", font=("Segoe UI", 9)).grid(row=current_row, column=1, columnspan=2, padx=15, sticky=tk.W)
            current_row += 1

        # Install directory
        ttk.Label(scrollable_frame, text="Install Directory:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
        install_dir_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['install_dir'], width=30, font=("Segoe UI", 10))
        install_dir_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)
        
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Installation Directory")
            if directory:
                form_vars['install_dir'].set(directory)
        ttk.Button(scrollable_frame, text="Browse", command=browse_directory, width=12).grid(row=current_row, column=2, padx=15, pady=10)
        current_row += 1
        
        # Set default installation directory help text based on server type
        if server_type == "Steam":
            help_text = "(Leave blank for SteamCMD default location)"
        else:  # Minecraft or Other
            default_location = self.variables.get("defaultServerManagerInstallDir", "ServerManager location")
            help_text = f"(Leave blank for default: {default_location}\\[ServerName])"
        
        ttk.Label(scrollable_frame, text=help_text, foreground="gray", font=("Segoe UI", 9)).grid(row=current_row, column=1, columnspan=2, padx=15, sticky=tk.W)
        current_row += 1

        # Executable (Minecraft/Other)
        if server_type in ("Minecraft", "Other"):
            ttk.Label(scrollable_frame, text="Executable Path:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            exe_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['exe_path'], width=30, font=("Segoe UI", 10))
            exe_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)
            
            def browse_exe():
                fp = filedialog.askopenfilename(title="Select Executable",
                    filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd"),("All","*.*")])
                if fp:
                    form_vars['exe_path'].set(fp)
            ttk.Button(scrollable_frame, text="Browse", command=browse_exe, width=12).grid(row=current_row, column=2, padx=15, pady=10)
            current_row += 1

        # Startup Args (all)
        ttk.Label(scrollable_frame, text="Startup Args:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
        args_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['startup_args'], width=40, font=("Segoe UI", 10))
        args_entry.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
        
        # Create button frame in top section (below the scrollable form)
        button_container = ttk.Frame(top_frame)
        button_container.pack(fill=tk.X, pady=(10, 5))
        
        # Create buttons with reshuffled layout
        create_button = ttk.Button(button_container, text="Create Server", width=18)
        create_button.pack(side=tk.LEFT, padx=(5, 10))
        
        cancel_button = ttk.Button(button_container, text="Cancel Installation", width=18, state=tk.DISABLED)
        cancel_button.pack(side=tk.LEFT, padx=(0, 10))
        
        close_button = ttk.Button(button_container, text="Close", width=12)
        close_button.pack(side=tk.RIGHT, padx=(0, 5))

        # Status and progress bar in top section
        status_container = ttk.Frame(top_frame)
        status_container.pack(fill=tk.X, pady=(5, 10))
        
        status_var = tk.StringVar(value="Ready to create server...")
        status_label = ttk.Label(status_container, textvariable=status_var, font=("Segoe UI", 10))
        status_label.pack(anchor=tk.W, pady=(0, 5))
        
        progress = ttk.Progressbar(status_container, mode="indeterminate")
        progress.pack(fill=tk.X)

        # Bottom frame for console log (50% of space)
        bottom_frame = ttk.Frame(paned_window)
        paned_window.add(bottom_frame, weight=1)
        
        # Console output section (bottom half)
        console_container = ttk.LabelFrame(bottom_frame, text="Installation Log", padding=10)
        console_container.pack(fill=tk.BOTH, expand=True)
        
        console_output = scrolledtext.ScrolledText(console_container, width=70, height=12, 
                                                 background="black", foreground="white", 
                                                 font=("Consolas", 9))
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)
        
        # Add initial message to console
        def append_console(text):
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)
        
        append_console(f"[INFO] Ready to create {server_type} server...")
        append_console(f"[INFO] Please fill in the required fields above and click 'Create Server' to begin.")

        def install_server():
            try:
                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                status_var.set("Starting installation...")
                
                # Use the existing installation function from dashboard_functions
                success, message = perform_server_installation(
                    self.server_manager, server_type, form_vars, credentials, self.paths,
                    status_callback=status_var.set,
                    console_callback=append_console,
                    cancel_flag=self.install_cancelled,
                    steam_cmd_path=getattr(self, 'steam_cmd_path', None)
                )

                if success:
                    append_console(f"[SUCCESS] {message}")
                    status_var.set("Installation completed successfully!")
                    self.update_server_list(force_refresh=True)
                    messagebox.showinfo("Success", message)
                    dialog.destroy()
                else:
                    append_console(f"[ERROR] {message}")
                    status_var.set("Installation failed!")
                    create_button.config(state=tk.NORMAL)
                    cancel_button.config(state=tk.DISABLED)
                    
            except Exception as e:
                logger.error(f"Error during server installation: {str(e)}")
                append_console(f"[ERROR] {str(e)}")
                status_var.set("Installation failed!")
                create_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.DISABLED)
            finally:
                progress.stop()
        
        def start_installation():
            installation_thread = threading.Thread(target=install_server)
            installation_thread.daemon = True
            installation_thread.start()
            
        def cancel_installation():
            self.install_cancelled.set(True)
            cancel_button.config(state=tk.DISABLED)
            status_var.set("Cancelling installation...")
            append_console("[INFO] Cancellation requested, stopping installation process...")
            
        def close_dialog():
            dialog.destroy()
            
        # Assign button commands
        create_button.config(command=start_installation)
        cancel_button.config(command=cancel_installation)
        close_button.config(command=close_dialog)
        
        def on_close():
            if cancel_button.instate(['!disabled']):
                result = messagebox.askyesno("Confirm Exit", 
                                           "An installation is in progress. Do you want to cancel it?",
                                           icon=messagebox.QUESTION)
                if result:
                    cancel_installation()
                    dialog.after(1000, dialog.destroy)
                    return
                else:
                    return
            dialog.destroy()
            
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        
        # Center dialog relative to parent with proper size for new layout
        center_window(dialog, 900, 700, self.root)

    def update_server_list(self, force_refresh=False):
        """Update server list from configuration files - thread-safe"""
        def _update():
            try:
                # Skip update if it's been less than configured interval since the last update and force_refresh isn't specified
                update_interval = self.variables.get("serverListUpdateInterval", 30)
                if not force_refresh and \
                   (self.variables["lastServerListUpdate"] != datetime.datetime.min) and \
                   (datetime.datetime.now() - self.variables["lastServerListUpdate"]).total_seconds() < update_interval:
                    log_dashboard_event("SERVER_LIST_UPDATE", f"Skipping update - last update was less than {update_interval} seconds ago", "DEBUG")
                    return
                
                # Use the new function from dashboard_functions
                update_server_list_from_files(
                    self.server_list, self.paths, self.variables, 
                    log_dashboard_event, format_uptime_from_start_time
                )
            except Exception as e:
                logger.error(f"Error in update_server_list: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def toggle_offline_mode(self):
        """Toggle offline mode"""
        self.variables["offlineMode"] = self.offline_var.get()
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
    def update_webserver_status(self):
        """Update the web server status display - thread-safe"""
        def _update():
            try:
                update_webserver_status(self.webserver_status, self.offline_var, self.paths, self.variables)
            except Exception as e:
                logger.error(f"Error in update_webserver_status: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def update_system_info(self):
        """Update system information in the UI - thread-safe"""
        def _update():
            try:
                # Update web server status
                self.update_webserver_status()
                
                # Use the function from dashboard_functions
                update_system_info(self.metric_labels, self.system_name, self.os_info, self.variables)
                
            except Exception as e:
                logger.error(f"Error updating system info: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def run(self):
        """Run the dashboard application"""
        logger.info("Starting dashboard")
        
        # Initial updates
        self.update_server_list(force_refresh=True)
        
        # Show the window
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.variables["formDisplayed"] = True
        
        # Start main loop
        self.root.mainloop()
    
    def on_close(self):
        """Handle window close event"""
        logger.info("Dashboard closing")
        
        # Clean up resources
        try:
            # Stop agent monitoring
            if hasattr(self, 'agent_manager') and self.agent_manager:
                self.agent_manager.stop_monitoring()
                logger.debug("Stopped agent monitoring")
            
            # Remove PID file
            self.remove_pid_file("dashboard")
                
            # Close any open processes
            if hasattr(self, 'install_process') and self.install_process:
                try:
                    self.install_process.terminate()
                    logger.debug("Terminated installation process")
                except:
                    pass
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        
        # Close the window
        self.root.destroy()

    def start_server(self):
        """Start the selected game server (Steam/Minecraft/Other)"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
        
        def start_in_background():
            try:
                # Ensure server_manager is not None before using it
                if self.server_manager is None:
                    def show_error():
                        messagebox.showerror("Error", "Server manager not initialized.")
                    self.root.after(0, show_error)
                    return

                # Use the server manager to start the server
                success, message = self.server_manager.start_server_advanced(
                    server_name, 
                    callback=lambda status: self.update_server_status(server_name, status)
                )
                
                # Update UI on main thread
                def update_ui():
                    if success:
                        messagebox.showinfo("Success", message)
                        self.update_server_list(force_refresh=True)
                    else:
                        messagebox.showerror("Error", message)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error starting server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to start server: {str(e)}")
                self.root.after(0, show_error)
        
        # Show starting message
        messagebox.showinfo("Starting Server", f"Starting server '{server_name}' in background...")
        
        # Run server start in background thread
        start_thread = threading.Thread(target=start_in_background, daemon=True)
        start_thread.start()

    def stop_server(self):
        """Stop the selected game server"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Confirm server stop
        confirm = messagebox.askyesno("Confirm Stop", 
                                    f"Are you sure you want to stop the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        
        if not confirm:
            return
        
        def stop_in_background():
            try:
                # Ensure server_manager is not None before using it
                if self.server_manager is None:
                    def show_error():
                        messagebox.showerror("Error", "Server manager not initialized.")
                    self.root.after(0, show_error)
                    return

                # Use the server manager to stop the server
                success, message = self.server_manager.stop_server_advanced(
                    server_name,
                    callback=lambda status: self.update_server_status(server_name, status)
                )
                
                # Update UI on main thread
                def update_ui():
                    if success:
                        messagebox.showinfo("Success", message)
                        self.update_server_list(force_refresh=True)
                    else:
                        messagebox.showinfo("Info", message)
                        self.update_server_list(force_refresh=True)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error stopping server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to stop server: {str(e)}")
                self.root.after(0, show_error)
        
        # Show stopping message
        messagebox.showinfo("Stopping Server", f"Stopping server '{server_name}' in background...")
        
        # Run server stop in background thread
        stop_thread = threading.Thread(target=stop_in_background, daemon=True)
        stop_thread.start()
    
    def restart_server(self):
        """Restart the selected game server"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
        
        # Confirm restart
        confirm = messagebox.askyesno("Confirm Restart", 
                                    f"Are you sure you want to restart the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        
        if not confirm:
            return
        
        def restart_in_background():
            try:
                # Ensure server_manager is not None before using it
                if self.server_manager is None:
                    def show_error():
                        messagebox.showerror("Error", "Server manager not initialized.")
                    self.root.after(0, show_error)
                    return

                # Use the server manager to restart the server
                success, message = self.server_manager.restart_server_advanced(
                    server_name,
                    callback=lambda status: self.update_server_status(server_name, status)
                )
                
                # Update UI on main thread
                def update_ui():
                    if success:
                        messagebox.showinfo("Success", message)
                        self.update_server_list(force_refresh=True)
                    else:
                        messagebox.showerror("Error", message)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error restarting server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to restart server: {str(e)}")
                self.root.after(0, show_error)
        
        # Show restarting message
        messagebox.showinfo("Restarting Server", f"Restarting server '{server_name}' in background...")
        
        # Run server restart in background thread
        restart_thread = threading.Thread(target=restart_in_background, daemon=True)
        restart_thread.start()
    
    def view_process_details(self):
        """View detailed process information for a server using debug module"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        try:
            # Get server process details from debug module
            process_details = get_server_process_details(server_name)
            
            if "error" in process_details:
                messagebox.showerror("Error", process_details["error"])
                return
            
            # Create detail dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Process Details: {server_name} (PID: {process_details['pid']})")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Create a frame with padding
            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Create notebook for organized tabs
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            
            # Basic Info Tab
            basic_frame = ttk.Frame(notebook)
            notebook.add(basic_frame, text="Basic Info")
            
            # Basic information grid
            info_grid = ttk.Frame(basic_frame)
            info_grid.pack(fill=tk.X, padx=10, pady=10)
            
            # Display basic process information
            info_items = [
                ("PID:", str(process_details["pid"])),
                ("Status:", process_details["status"]),
                ("Name:", process_details["name"]),
                ("Server Uptime:", process_details.get("server_uptime", "Unknown")),
                ("CPU Usage:", f"{process_details['cpu_percent']:.1f}%"),
                ("Memory Usage:", f"{process_details['memory_info']['rss'] / (1024 * 1024):.1f} MB"),
                ("Memory %:", f"{process_details['memory_percent']:.1f}%"),
                ("Threads:", str(process_details["num_threads"]))
            ]
            
            for i, (label, value) in enumerate(info_items):
                row = i // 2
                col = (i % 2) * 2
                ttk.Label(info_grid, text=label, width=15).grid(row=row, column=col, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=value).grid(row=row, column=col+1, sticky=tk.W, padx=5, pady=2)
            
            # Executable path (full width)
            if "exe" in process_details and process_details["exe"] != "Access Denied":
                ttk.Label(info_grid, text="Executable:").grid(row=len(info_items)//2 + 1, column=0, sticky=tk.W, padx=5, pady=2)
                exe_label = ttk.Label(info_grid, text=process_details["exe"])
                exe_label.grid(row=len(info_items)//2 + 1, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)
            
            # Resources Tab
            resources_frame = ttk.Frame(notebook)
            notebook.add(resources_frame, text="Resources")
            
            # Resource details
            resource_text = scrolledtext.ScrolledText(resources_frame, width=80, height=20)
            resource_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            resource_info = f"""Memory Information:
RSS (Resident Set Size): {process_details['memory_info']['rss'] / (1024 * 1024):.2f} MB
VMS (Virtual Memory Size): {process_details['memory_info']['vms'] / (1024 * 1024):.2f} MB
Memory Percentage: {process_details['memory_percent']:.2f}%

Open Files: {process_details.get('open_files_count', 'N/A')}
Network Connections: {process_details.get('connections_count', 'N/A')}

Command Line: {' '.join(process_details.get('cmdline', ['N/A']))}

Working Directory: {process_details.get('cwd', 'N/A')}
"""
            resource_text.insert(tk.END, resource_info)
            resource_text.config(state=tk.DISABLED)
            
            # Children Tab
            if process_details.get("children"):
                children_frame = ttk.Frame(notebook)
                notebook.add(children_frame, text="Child Processes")
                
                # Create child processes list
                child_list = ttk.Treeview(children_frame, columns=("pid", "name", "status", "cpu", "memory"), show="headings")
                child_list.heading("pid", text="PID")
                child_list.heading("name", text="Name")
                child_list.heading("status", text="Status")
                child_list.heading("cpu", text="CPU %")
                child_list.heading("memory", text="Memory MB")
                
                child_list.column("pid", width=60)
                child_list.column("name", width=200)
                child_list.column("status", width=80)
                child_list.column("cpu", width=80)
                child_list.column("memory", width=100)
                
                # Add scrollbar
                child_scroll = ttk.Scrollbar(children_frame, orient=tk.VERTICAL, command=child_list.yview)
                child_list.configure(yscrollcommand=child_scroll.set)
                
                # Pack components
                child_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                child_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                # Populate child list
                for child in process_details["children"]:
                    child_list.insert("", tk.END, values=(
                        child["pid"],
                        child["name"],
                        child["status"],
                        f"{child['cpu_percent']:.1f}",
                        f"{child['memory_mb']:.1f}"
                    ))
            
            # Network Tab
            if process_details.get("connections"):
                network_frame = ttk.Frame(notebook)
                notebook.add(network_frame, text="Network")
                
                # Create network connections list
                conn_list = ttk.Treeview(network_frame, columns=("family", "type", "local", "remote", "status"), show="headings")
                conn_list.heading("family", text="Family")
                conn_list.heading("type", text="Type")
                conn_list.heading("local", text="Local Address")
                conn_list.heading("remote", text="Remote Address")
                conn_list.heading("status", text="Status")
                
                # Add scrollbar
                conn_scroll = ttk.Scrollbar(network_frame, orient=tk.VERTICAL, command=conn_list.yview)
                conn_list.configure(yscrollcommand=conn_scroll.set)
                
                # Pack components
                conn_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                conn_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                # Populate connections list
                for conn in process_details["connections"]:
                    conn_list.insert("", tk.END, values=(
                        conn["family"],
                        conn["type"],
                        conn["local_address"],
                        conn["remote_address"],
                        conn["status"]
                    ))
            
            # Log Files Tab
            server_config = process_details.get("server_config", {})
            if server_config.get("LogStdout") or server_config.get("LogStderr"):
                logs_frame = ttk.Frame(notebook)
                notebook.add(logs_frame, text="Log Files")
                
                log_grid = ttk.Frame(logs_frame)
                log_grid.pack(fill=tk.X, padx=10, pady=10)
                
                row = 0
                if server_config.get("LogStdout"):
                    ttk.Label(log_grid, text="Stdout Log:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
                    ttk.Label(log_grid, text=server_config["LogStdout"]).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)
                    
                    def open_stdout_log():
                        try:
                            if os.path.exists(server_config["LogStdout"]):
                                os.startfile(server_config["LogStdout"])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")
                    
                    ttk.Button(log_grid, text="Open", command=open_stdout_log, width=10).grid(row=row, column=2, padx=5, pady=2)
                    row += 1
                
                if server_config.get("LogStderr"):
                    ttk.Label(log_grid, text="Stderr Log:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
                    ttk.Label(log_grid, text=server_config["LogStderr"]).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)
                    
                    def open_stderr_log():
                        try:
                            if os.path.exists(server_config["LogStderr"]):
                                os.startfile(server_config["LogStderr"])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")
                    
                    ttk.Button(log_grid, text="Open", command=open_stderr_log, width=10).grid(row=row, column=2, padx=5, pady=2)
            
            # Action buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=10)
            
            # Refresh button
            def refresh_process_info():
                dialog.destroy()
                self.view_process_details()
            
            ttk.Button(button_frame, text="Refresh", command=refresh_process_info, width=15).pack(side=tk.LEFT, padx=5)
            
            # Monitor button - shows resource monitoring
            def monitor_process():
                try:
                    monitor_data = monitor_process_resources(process_details["pid"], 10)
                    if "error" not in monitor_data:
                        messagebox.showinfo("Monitoring Complete", 
                                          f"Monitored process for {monitor_data['duration']} seconds.\n"
                                          f"Collected {monitor_data['sample_count']} samples.")
                    else:
                        messagebox.showerror("Error", monitor_data["error"])
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to monitor process: {str(e)}")
            
            ttk.Button(button_frame, text="Monitor (10s)", command=monitor_process, width=15).pack(side=tk.LEFT, padx=5)
            
            # Stop process button
            def stop_from_details():
                dialog.destroy()
                self.stop_server()
            
            ttk.Button(button_frame, text="Stop Process", command=stop_from_details, width=15).pack(side=tk.RIGHT, padx=5)
            
            # Close button
            ttk.Button(button_frame, text="Close", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
            
            # Center dialog relative to parent
            center_window(dialog, 700, 600, self.root)
            
        except Exception as e:
            log_exception(e, f"Error viewing process details for {server_name}")
            messagebox.showerror("Error", f"Failed to get process details: {str(e)}")
    
    def update_server_status(self, server_name, status):
        """Update the status of a server in the UI - thread-safe"""
        def _update():
            try:
                update_server_status_in_treeview(self.server_list, server_name, status)
                # Force UI update
                self.root.update_idletasks()
            except Exception as e:
                logger.error(f"Error updating server status: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def configure_server(self):
        """Configure server executable and startup settings"""
        selected = self.server_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected[0])['values'][0]
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Get server configuration from server manager
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
            
        install_dir = server_config.get('InstallDir','')
        if not install_dir or not os.path.exists(install_dir):
            messagebox.showerror("Error", "Server installation directory not found.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure Server: {server_name}")
        dialog.transient(self.root); dialog.grab_set()
        frm = ttk.Frame(dialog, padding=10); frm.pack(fill=tk.BOTH, expand=True)

        # Info
        info = ttk.LabelFrame(frm, text="Server Information"); info.pack(fill=tk.X,pady=5)
        ttk.Label(info, text=f"Name: {server_name}").pack(anchor=tk.W,padx=10)
        ttk.Label(info, text=f"AppID: {server_config.get('AppID','N/A')}").pack(anchor=tk.W,padx=10)
        ttk.Label(info, text=f"Install Dir: {install_dir}").pack(anchor=tk.W,padx=10)

        # Startup
        start = ttk.LabelFrame(frm, text="Startup Configuration"); start.pack(fill=tk.X,pady=5)
        # Executable
        ttk.Label(start, text="Executable:").grid(row=0,column=0,padx=10,pady=5,sticky=tk.W)
        exe_var = tk.StringVar(value=server_config.get('ExecutablePath',''))
        exe_entry = ttk.Entry(start, textvariable=exe_var, width=40); exe_entry.grid(row=0,column=1,sticky=tk.W)
        def browse_exe():
            fp = filedialog.askopenfilename(initialdir=install_dir,
                filetypes=[("Exec","*.exe;*.bat;*.cmd;*.sh"),("All","*.*")])
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                exe_var.set(rel)
        ttk.Button(start, text="Browse", command=browse_exe).grid(row=0,column=2)

        # Stop command
        ttk.Label(start, text="Stop Command:").grid(row=1,column=0,padx=10,pady=5,sticky=tk.W)
        stop_var = tk.StringVar(value=server_config.get('StopCommand',''))
        ttk.Entry(start, textvariable=stop_var, width=40).grid(row=1,column=1,columnspan=2,sticky=tk.W)
        
        # Startup arguments section with radio button choice
        args_frame = ttk.LabelFrame(start, text="Startup Arguments")
        args_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        # Radio button to choose between manual args or config file
        startup_mode_var = tk.StringVar(value="manual" if not server_config.get('UseConfigFile', False) else "config")
        
        manual_radio = ttk.Radiobutton(args_frame, text="Manual Arguments", variable=startup_mode_var, value="manual")
        manual_radio.grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        
        config_radio = ttk.Radiobutton(args_frame, text="Use Configuration File", variable=startup_mode_var, value="config")
        config_radio.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)
        
        # Manual arguments section
        manual_frame = ttk.Frame(args_frame)
        manual_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        ttk.Label(manual_frame, text="Startup Args:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        args_var = tk.StringVar(value=server_config.get('StartupArgs',''))
        args_entry = ttk.Entry(manual_frame, textvariable=args_var, width=50)
        args_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        
        # Config file section
        config_frame = ttk.Frame(args_frame)
        config_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        # Config file path
        ttk.Label(config_frame, text="Config File:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        config_file_var = tk.StringVar(value=server_config.get('ConfigFilePath',''))
        config_file_entry = ttk.Entry(config_frame, textvariable=config_file_var, width=35)
        config_file_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        
        def browse_config():
            fp = filedialog.askopenfilename(
                initialdir=install_dir,
                title="Select Configuration File",
                filetypes=[
                    ("Config Files", "*.cfg;*.conf;*.ini;*.json;*.xml;*.yaml;*.yml;*.properties;*.txt"),
                    ("All Files", "*.*")
                ]
            )
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                config_file_var.set(rel)
        ttk.Button(config_frame, text="Browse", command=browse_config, width=10).grid(row=0, column=2, padx=5, pady=2)
        
        # Config file argument format
        ttk.Label(config_frame, text="Config Argument:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        config_arg_var = tk.StringVar(value=server_config.get('ConfigArgument', '--config'))
        config_arg_entry = ttk.Entry(config_frame, textvariable=config_arg_var, width=20)
        config_arg_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(e.g., --config, -c, +exec)", foreground="gray").grid(row=1, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Additional args for config mode
        ttk.Label(config_frame, text="Additional Args:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        additional_args_var = tk.StringVar(value=server_config.get('AdditionalArgs',''))
        additional_args_entry = ttk.Entry(config_frame, textvariable=additional_args_var, width=35)
        additional_args_entry.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
        ttk.Label(config_frame, text="(optional)", foreground="gray").grid(row=2, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Configure grid weights
        args_frame.grid_columnconfigure(0, weight=1)
        args_frame.grid_columnconfigure(1, weight=1)
        manual_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(1, weight=1)
        
        # Function to enable/disable widgets based on selection
        def toggle_startup_mode():
            mode = startup_mode_var.get()
            if mode == "manual":
                # Enable manual args, disable config file options
                args_entry.config(state=tk.NORMAL)
                config_file_entry.config(state=tk.DISABLED)
                config_arg_entry.config(state=tk.DISABLED)
                additional_args_entry.config(state=tk.DISABLED)
            else:
                # Disable manual args, enable config file options
                args_entry.config(state=tk.DISABLED)
                config_file_entry.config(state=tk.NORMAL)
                config_arg_entry.config(state=tk.NORMAL)
                additional_args_entry.config(state=tk.NORMAL)
        
        # Bind radio button changes
        startup_mode_var.trace('w', lambda *args: toggle_startup_mode())
        
        # Initial toggle
        toggle_startup_mode()
        
        # Preview command line
        preview_frame = ttk.LabelFrame(frm, text="Command Preview")
        preview_frame.pack(fill=tk.X, pady=5)
        
        preview_text = tk.Text(preview_frame, height=3, wrap=tk.WORD, background="lightgray")
        preview_text.pack(fill=tk.X, padx=10, pady=10)
        
        def update_preview():
            """Update the command preview"""
            try:
                exe = exe_var.get().strip()
                mode = startup_mode_var.get()
                
                # Build command preview
                cmd_parts = []
                if exe:
                    exe_abs = exe if os.path.isabs(exe) else os.path.join(install_dir, exe)
                    cmd_parts.append(f'"{exe_abs}"')
                
                if mode == "manual":
                    # Manual arguments mode
                    args = args_var.get().strip()
                    if args:
                        cmd_parts.append(args)
                else:
                    # Config file mode
                    config_file_path = config_file_var.get().strip()
                    config_arg = config_arg_var.get().strip()
                    additional_args = additional_args_var.get().strip()
                    
                    # Add additional args first (if any)
                    if additional_args:
                        cmd_parts.append(additional_args)
                    
                    # Add config file argument
                    if config_file_path and config_arg:
                        config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                        cmd_parts.append(f'{config_arg} "{config_abs}"')
                
                cmd_preview = ' '.join(cmd_parts) if cmd_parts else "No executable specified"
                
                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, cmd_preview)
            except Exception as e:
                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, f"Error generating preview: {str(e)}")
        
        # Bind update events
        def on_change(*args):
            update_preview()
        
        exe_var.trace('w', on_change)
        args_var.trace('w', on_change)
        startup_mode_var.trace('w', on_change)
        config_file_var.trace('w', on_change)
        config_arg_var.trace('w', on_change)
        additional_args_var.trace('w', on_change)
        
        # Initial preview update
        update_preview()

        # Save/Cancel/Test
        btns = ttk.Frame(frm); btns.pack(fill=tk.X,pady=10)
        def save():
            ep = exe_var.get().strip()
            sc = stop_var.get().strip()
            mode = startup_mode_var.get()
            
            if not ep:
                messagebox.showerror("Validation Error", "Executable path is required.")
                return
            
            # resolve abs paths for validation
            ep_abs = ep if os.path.isabs(ep) else os.path.join(install_dir,ep)
            if not os.path.exists(ep_abs):
                if not messagebox.askyesno("Warning",f"Executable not found: {ep_abs}\nSave anyway?"): return
            
            # Prepare configuration based on mode
            if mode == "manual":
                startup_args = args_var.get().strip()
                use_config = False
                config_file_path = ""
                config_arg = ""
                additional_args = ""
            else:
                startup_args = ""
                use_config = True
                config_file_path = config_file_var.get().strip()
                config_arg = config_arg_var.get().strip()
                additional_args = additional_args_var.get().strip()
                
                # Validate config file if enabled
                if config_file_path:
                    config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                    if not os.path.exists(config_abs):
                        if not messagebox.askyesno("Warning", f"Config file not found: {config_abs}\nSave anyway?"): return
                    if not config_arg:
                        messagebox.showerror("Validation Error", "Config argument is required when using config file."); return
                else:
                    messagebox.showerror("Validation Error", "Config file path is required when using config file mode."); return
            
            # Use server manager to update configuration
            try:
                if self.server_manager:
                    success, message = self.server_manager.update_server_config(
                        server_name, ep, startup_args, sc, use_config, 
                        config_file_path, config_arg, additional_args
                    )
                else:
                    success = False
                    message = "Server manager not initialized"
                
                if success:
                    messagebox.showinfo("Success", "Configuration saved.")
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", message)
                    
            except Exception as e:
                logger.error(f"Error saving configuration: {str(e)}")
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
                
        ttk.Button(btns, text="Save", command=save).pack(side=tk.RIGHT,padx=5)
        ttk.Button(btns, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)

        def test():
            ep = exe_var.get().strip()
            ep_abs = ep if os.path.isabs(ep) else os.path.join(install_dir,ep)
            if os.path.exists(ep_abs):
                messagebox.showinfo("Test OK",f"Found: {ep_abs}")
            else:
                messagebox.showerror("Test Failed",f"Not found: {ep_abs}")
        ttk.Button(btns, text="Test Path", command=test).pack(side=tk.LEFT)

        # Center dialog
        # Center dialog relative to parent
        center_window(dialog, 650, 550, self.root)

    def configure_java(self):
        """Open Java configuration dialog for selected server"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a server to configure Java for.")
            return
        
        # Get selected server name
        item = selected_items[0]
        server_name = self.server_list.item(item)["values"][0]
        
        # Check if it's a Minecraft server
        server_config = None
        if hasattr(self, 'server_manager') and self.server_manager:
            server_config = self.server_manager.get_server_config(server_name)
        
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for '{server_name}'")
            return
        
        if server_config.get("Type") != "Minecraft":
            messagebox.showinfo("Info", f"Java configuration is only available for Minecraft servers.\n'{server_name}' is a {server_config.get('Type', 'Unknown')} server.")
            return
        
        # Open Java configuration dialog
        self.show_java_configuration_dialog(server_name, server_config)
    
    def show_java_configuration_dialog(self, server_name, server_config):
        """Show Java configuration dialog for a specific server"""
        try:
            from Scripts.minecraft import detect_java_installations, check_java_compatibility, get_recommended_java_for_minecraft
            from Host.dashboard_functions import create_java_selection_dialog
            
            # Create dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Java Configuration - {server_name}")
            dialog.geometry("700x600")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Main frame
            main_frame = ttk.Frame(dialog, padding=15)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Title
            title_label = ttk.Label(main_frame, text=f"Java Configuration for {server_name}", 
                                   font=("Segoe UI", 14, "bold"))
            title_label.pack(pady=(0, 20))
            
            # Server info frame
            info_frame = ttk.LabelFrame(main_frame, text="Server Information", padding=10)
            info_frame.pack(fill=tk.X, pady=(0, 15))
            
            version = server_config.get("Version", "Unknown")
            current_java = server_config.get("JavaPath", "java (system default)")
            
            ttk.Label(info_frame, text=f"Minecraft Version: {version}", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=2)
            ttk.Label(info_frame, text=f"Current Java: {current_java}", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=2)
            
            # Check current compatibility
            if version != "Unknown":
                is_compatible, java_version, required_version, message = check_java_compatibility(version, current_java)
                compatibility_color = "green" if is_compatible else "red"
                compatibility_text = "✓ Compatible" if is_compatible else "✗ Incompatible"
                
                ttk.Label(info_frame, text=f"Compatibility: {compatibility_text}", 
                         foreground=compatibility_color, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=2)
                
                if not is_compatible:
                    ttk.Label(info_frame, text=f"Required: Java {required_version}+", 
                             foreground="red", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=2)
            
            # Java selection frame
            selection_frame = ttk.LabelFrame(main_frame, text="Available Java Installations", padding=10)
            selection_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
            
            # Create treeview for Java installations
            columns = ("name", "path", "compatibility")
            java_tree = ttk.Treeview(selection_frame, columns=columns, show="headings", height=8)
            
            java_tree.heading("name", text="Java Version")
            java_tree.heading("path", text="Path")
            java_tree.heading("compatibility", text="Compatibility")
            
            java_tree.column("name", width=180, minwidth=150)
            java_tree.column("path", width=300, minwidth=200)
            java_tree.column("compatibility", width=120, minwidth=100)
            
            # Add scrollbar
            scroll = ttk.Scrollbar(selection_frame, orient=tk.VERTICAL, command=java_tree.yview)
            java_tree.configure(yscrollcommand=scroll.set)
            
            java_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            
            # Populate Java installations
            installations = detect_java_installations()
            selected_java = None
            
            for installation in installations:
                if version != "Unknown":
                    is_compatible, _, _, _ = check_java_compatibility(version, installation["path"])
                    compatibility_text = "✓ Compatible" if is_compatible else "✗ Incompatible"
                    tags = ("compatible",) if is_compatible else ("incompatible",)
                else:
                    compatibility_text = "N/A"
                    tags = ()
                
                item_id = java_tree.insert("", tk.END, 
                                         values=(installation["display_name"], 
                                               installation["path"], 
                                               compatibility_text),
                                         tags=tags)
                
                # Select current Java if it matches
                if installation["path"] == current_java:
                    java_tree.selection_set(item_id)
                    java_tree.focus(item_id)
                    selected_java = installation
            
            # Configure tag colors
            java_tree.tag_configure("compatible", foreground="green")
            java_tree.tag_configure("incompatible", foreground="red")
            
            # Custom Java path frame
            custom_frame = ttk.LabelFrame(main_frame, text="Custom Java Path", padding=10)
            custom_frame.pack(fill=tk.X, pady=(0, 15))
            
            custom_path_var = tk.StringVar()
            custom_entry = ttk.Entry(custom_frame, textvariable=custom_path_var, width=50)
            custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            
            def browse_java():
                if os.name == 'nt':
                    file_types = [("Java Executable", "java.exe"), ("All Files", "*.*")]
                else:
                    file_types = [("All Files", "*")]
                
                java_path = filedialog.askopenfilename(
                    title="Select Java Executable",
                    filetypes=file_types
                )
                if java_path:
                    custom_path_var.set(java_path)
            
            ttk.Button(custom_frame, text="Browse", command=browse_java).pack(side=tk.RIGHT)
            
            # Action buttons frame
            action_frame = ttk.Frame(main_frame)
            action_frame.pack(fill=tk.X, pady=(0, 15))
            
            def auto_select_java():
                if version != "Unknown":
                    recommended = get_recommended_java_for_minecraft(version)
                    if recommended:
                        # Select the recommended Java in the tree
                        for child in java_tree.get_children():
                            if java_tree.item(child)["values"][1] == recommended["path"]:
                                java_tree.selection_set(child)
                                java_tree.focus(child)
                                java_tree.see(child)
                                break
                        messagebox.showinfo("Auto-Select", f"Selected: {recommended['display_name']}")
                    else:
                        messagebox.showwarning("No Suitable Java", 
                                             "No suitable Java installation found for this Minecraft version.")
                else:
                    messagebox.showwarning("Unknown Version", "Cannot auto-select Java for unknown Minecraft version.")
            
            ttk.Button(action_frame, text="Auto-Select Best Java", command=auto_select_java).pack(side=tk.LEFT, padx=(0, 10))
            
            def refresh_java_list():
                # Clear existing items
                for item in java_tree.get_children():
                    java_tree.delete(item)
                
                # Repopulate
                installations = detect_java_installations()
                for installation in installations:
                    if version != "Unknown":
                        is_compatible, _, _, _ = check_java_compatibility(version, installation["path"])
                        compatibility_text = "✓ Compatible" if is_compatible else "✗ Incompatible"
                        tags = ("compatible",) if is_compatible else ("incompatible",)
                    else:
                        compatibility_text = "N/A"
                        tags = ()
                    
                    java_tree.insert("", tk.END, 
                                   values=(installation["display_name"], 
                                         installation["path"], 
                                         compatibility_text),
                                   tags=tags)
            
            ttk.Button(action_frame, text="Refresh List", command=refresh_java_list).pack(side=tk.LEFT)
            
            # Button frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X)
            
            def on_apply():
                # Get selected Java
                custom_path = custom_path_var.get().strip()
                selected_java_path = None
                
                if custom_path:
                    # Use custom path
                    from Scripts.minecraft import get_java_version
                    major, version_str = get_java_version(custom_path)
                    if major is not None:
                        selected_java_path = custom_path
                    else:
                        messagebox.showerror("Error", f"Invalid Java executable: {custom_path}")
                        return
                else:
                    # Use selected from tree
                    selection = java_tree.selection()
                    if selection:
                        item = selection[0]
                        selected_java_path = java_tree.item(item)["values"][1]
                    else:
                        messagebox.showwarning("No Selection", "Please select a Java installation or provide a custom path.")
                        return
                
                # Update server configuration
                try:
                    server_config["JavaPath"] = selected_java_path
                    server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                    
                    # Save configuration
                    if self.server_manager:
                        self.server_manager.save_server_config(server_name, server_config)
                    
                    # Update launch script
                    from Scripts.minecraft import MinecraftServerManager
                    manager = MinecraftServerManager(self.server_manager_dir, self.config)
                    
                    install_dir = server_config.get("InstallDir", "")
                    if install_dir and os.path.exists(install_dir):
                        executable_path = server_config.get("ExecutablePath", "")
                        jar_file = os.path.basename(executable_path) if executable_path else "server.jar"
                        
                        script_path = manager.create_launch_script(install_dir, jar_file, 1024, "", selected_java_path)
                        
                    messagebox.showinfo("Success", f"Java configuration updated for '{server_name}'!\nUsing: {selected_java_path}")
                    dialog.destroy()
                    
                    # Refresh server list to show updated info
                    self.update_server_list(force_refresh=True)
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to update configuration: {str(e)}")
            
            def on_cancel():
                dialog.destroy()
            
            ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
            ttk.Button(button_frame, text="Apply", command=on_apply, width=12).pack(side=tk.RIGHT)
            
            # Center dialog
            from Host.dashboard_functions import center_window
            center_window(dialog, 700, 600, self.root)
            
            # Auto-select recommended Java if none selected
            if not java_tree.selection() and version != "Unknown":
                auto_select_java()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open Java configuration dialog: {str(e)}")
    
    def show_server_type_configuration(self):
        """Show server configuration dialog based on server type"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a server to configure.")
            return
        
        # Get selected server name
        item = selected_items[0]
        server_name = self.server_list.item(item)["values"][0]
        
        # Get server configuration
        server_config = None
        if hasattr(self, 'server_manager') and self.server_manager:
            server_config = self.server_manager.get_server_config(server_name)
        
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for '{server_name}'")
            return
        
        server_type = server_config.get("Type", "Other")
        
        # Show appropriate configuration dialog based on type
        if server_type == "Minecraft":
            self.show_minecraft_server_config(server_name, server_config)
        elif server_type == "Steam":
            self.show_steam_server_config(server_name, server_config)
        else:
            self.show_other_server_config(server_name, server_config)
    
    def show_minecraft_server_config(self, server_name, server_config):
        """Show Minecraft-specific configuration dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Minecraft Server Configuration - {server_name}")
        dialog.geometry("800x700")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Minecraft Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Basic Configuration Tab
        basic_frame = ttk.Frame(notebook, padding=10)
        notebook.add(basic_frame, text="Basic Settings")
        
        # Server Information
        info_frame = ttk.LabelFrame(basic_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Version
        ttk.Label(info_frame, text="Minecraft Version:").grid(row=1, column=0, sticky=tk.W, pady=5)
        version_var = tk.StringVar(value=server_config.get("Version", ""))
        ttk.Entry(info_frame, textvariable=version_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server JAR file
        ttk.Label(info_frame, text="Server JAR:").grid(row=3, column=0, sticky=tk.W, pady=5)
        jar_var = tk.StringVar(value=os.path.basename(server_config.get("ExecutablePath", "")))
        ttk.Entry(info_frame, textvariable=jar_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Java Configuration Tab
        java_frame = ttk.Frame(notebook, padding=10)
        notebook.add(java_frame, text="Java Settings")
        
        # Java Path
        java_info_frame = ttk.LabelFrame(java_frame, text="Java Configuration", padding=10)
        java_info_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(java_info_frame, text="Java Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        java_path_var = tk.StringVar(value=server_config.get("JavaPath", "java"))
        java_entry = ttk.Entry(java_info_frame, textvariable=java_path_var, width=50)
        java_entry.grid(row=0, column=1, sticky=tk.W, padx=(10, 5), pady=5)
        
        def browse_java():
            file_types = [("Java Executable", "java.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            java_path = filedialog.askopenfilename(title="Select Java Executable", filetypes=file_types)
            if java_path:
                java_path_var.set(java_path)
        
        ttk.Button(java_info_frame, text="Browse", command=browse_java).grid(row=0, column=2, padx=(5, 0), pady=5)
        
        def auto_detect_java():
            try:
                from Scripts.minecraft import get_recommended_java_for_minecraft
                version = version_var.get()
                if version:
                    recommended = get_recommended_java_for_minecraft(version)
                    if recommended:
                        java_path_var.set(recommended["path"])
                        messagebox.showinfo("Auto-Detect", f"Found: {recommended['display_name']}")
                    else:
                        messagebox.showwarning("No Java Found", "No compatible Java installation found.")
                else:
                    messagebox.showwarning("No Version", "Please enter Minecraft version first.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to detect Java: {str(e)}")
        
        ttk.Button(java_info_frame, text="Auto-Detect", command=auto_detect_java).grid(row=0, column=3, padx=(5, 0), pady=5)
        
        # Memory Settings
        memory_frame = ttk.LabelFrame(java_frame, text="Memory Settings", padding=10)
        memory_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(memory_frame, text="RAM Allocation (MB):").grid(row=0, column=0, sticky=tk.W, pady=5)
        ram_var = tk.StringVar(value=str(server_config.get("RAM", 1024)))
        ttk.Entry(memory_frame, textvariable=ram_var, width=20).grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # JVM Arguments
        ttk.Label(memory_frame, text="JVM Arguments:").grid(row=1, column=0, sticky=tk.W, pady=5)
        jvm_args_var = tk.StringVar(value=server_config.get("JVMArgs", ""))
        ttk.Entry(memory_frame, textvariable=jvm_args_var, width=50).grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Advanced Tab
        advanced_frame = ttk.Frame(notebook, padding=10)
        notebook.add(advanced_frame, text="Advanced")
        
        # Server Properties
        props_frame = ttk.LabelFrame(advanced_frame, text="Server Properties", padding=10)
        props_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Add a text widget for server.properties editing
        props_text = tk.Text(props_frame, height=20, width=70)
        props_scroll = ttk.Scrollbar(props_frame, orient=tk.VERTICAL, command=props_text.yview)
        props_text.configure(yscrollcommand=props_scroll.set)
        
        props_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        props_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Load server.properties if it exists
        install_dir = server_config.get("InstallDir", "")
        props_file = os.path.join(install_dir, "server.properties")
        if os.path.exists(props_file):
            try:
                with open(props_file, 'r', encoding='utf-8') as f:
                    props_text.insert(tk.END, f.read())
            except Exception as e:
                props_text.insert(tk.END, f"# Error reading server.properties: {str(e)}\n")
        else:
            props_text.insert(tk.END, "# server.properties file not found\n# Create server first or manually add properties here\n")
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["Version"] = version_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = os.path.join(install_dir_var.get(), jar_var.get())
                server_config["JavaPath"] = java_path_var.get()
                server_config["RAM"] = int(ram_var.get()) if ram_var.get().isdigit() else 1024
                server_config["JVMArgs"] = jvm_args_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.save_server_config(server_name, server_config)
                
                # Save server.properties
                install_dir = install_dir_var.get()
                if install_dir and os.path.exists(install_dir):
                    props_file = os.path.join(install_dir, "server.properties")
                    try:
                        with open(props_file, 'w', encoding='utf-8') as f:
                            f.write(props_text.get(1.0, tk.END))
                    except Exception as e:
                        messagebox.showwarning("Properties Save Failed", f"Failed to save server.properties: {str(e)}")
                
                # Update launch script
                try:
                    from Scripts.minecraft import MinecraftServerManager
                    manager = MinecraftServerManager(self.server_manager_dir, self.config)
                    script_path = manager.create_launch_script(
                        install_dir_var.get(),
                        jar_var.get(),
                        int(ram_var.get()) if ram_var.get().isdigit() else 1024,
                        jvm_args_var.get(),
                        java_path_var.get()
                    )
                except Exception as e:
                    messagebox.showwarning("Script Update Failed", f"Failed to update launch script: {str(e)}")
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Center dialog
        from Host.dashboard_functions import center_window
        center_window(dialog, 800, 700, self.root)
    
    def show_steam_server_config(self, server_name, server_config):
        """Show Steam-specific configuration dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Steam Server Configuration - {server_name}")
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Steam Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Basic Configuration Tab
        basic_frame = ttk.Frame(notebook, padding=10)
        notebook.add(basic_frame, text="Basic Settings")
        
        # Server Information
        info_frame = ttk.LabelFrame(basic_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # App ID
        ttk.Label(info_frame, text="Steam App ID:").grid(row=1, column=0, sticky=tk.W, pady=5)
        app_id_var = tk.StringVar(value=server_config.get("AppID", ""))
        ttk.Entry(info_frame, textvariable=app_id_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Executable
        ttk.Label(info_frame, text="Server Executable:").grid(row=3, column=0, sticky=tk.W, pady=5)
        exe_var = tk.StringVar(value=os.path.basename(server_config.get("ExecutablePath", "")))
        ttk.Entry(info_frame, textvariable=exe_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Launch Parameters Tab
        launch_frame = ttk.Frame(notebook, padding=10)
        notebook.add(launch_frame, text="Launch Parameters")
        
        # Launch Arguments
        args_frame = ttk.LabelFrame(launch_frame, text="Launch Arguments", padding=10)
        args_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(args_frame, text="Command Line Arguments:").pack(anchor=tk.W, pady=(0, 5))
        args_var = tk.StringVar(value=server_config.get("LaunchArgs", ""))
        args_text = tk.Text(args_frame, height=5, width=70)
        args_text.insert(1.0, args_var.get())
        args_text.pack(fill=tk.X, pady=(0, 10))
        
        # Common Steam Server Settings
        steam_frame = ttk.LabelFrame(launch_frame, text="Common Steam Settings", padding=10)
        steam_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Port
        ttk.Label(steam_frame, text="Server Port:").grid(row=0, column=0, sticky=tk.W, pady=5)
        port_var = tk.StringVar(value=str(server_config.get("Port", 27015)))
        ttk.Entry(steam_frame, textvariable=port_var, width=20).grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Max Players
        ttk.Label(steam_frame, text="Max Players:").grid(row=1, column=0, sticky=tk.W, pady=5)
        maxplayers_var = tk.StringVar(value=str(server_config.get("MaxPlayers", 16)))
        ttk.Entry(steam_frame, textvariable=maxplayers_var, width=20).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server Name (in-game)
        ttk.Label(steam_frame, text="Server Name (in-game):").grid(row=2, column=0, sticky=tk.W, pady=5)
        servername_var = tk.StringVar(value=server_config.get("ServerName", ""))
        ttk.Entry(steam_frame, textvariable=servername_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Map
        ttk.Label(steam_frame, text="Map:").grid(row=3, column=0, sticky=tk.W, pady=5)
        map_var = tk.StringVar(value=server_config.get("Map", ""))
        ttk.Entry(steam_frame, textvariable=map_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Advanced Tab
        advanced_frame = ttk.Frame(notebook, padding=10)
        notebook.add(advanced_frame, text="Advanced")
        
        # SteamCMD Settings
        steamcmd_frame = ttk.LabelFrame(advanced_frame, text="SteamCMD Configuration", padding=10)
        steamcmd_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(steamcmd_frame, text="SteamCMD Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        steamcmd_var = tk.StringVar(value=server_config.get("SteamCMDPath", ""))
        ttk.Entry(steamcmd_frame, textvariable=steamcmd_var, width=50).grid(row=0, column=1, sticky=tk.W, padx=(10, 5), pady=5)
        
        def browse_steamcmd():
            file_types = [("SteamCMD", "steamcmd.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            steamcmd_path = filedialog.askopenfilename(title="Select SteamCMD Executable", filetypes=file_types)
            if steamcmd_path:
                steamcmd_var.set(steamcmd_path)
        
        ttk.Button(steamcmd_frame, text="Browse", command=browse_steamcmd).grid(row=0, column=2, padx=(5, 0), pady=5)
        
        # Auto-update settings
        auto_update_var = tk.BooleanVar(value=server_config.get("AutoUpdate", False))
        ttk.Checkbutton(steamcmd_frame, text="Enable automatic updates", variable=auto_update_var).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["AppID"] = app_id_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = os.path.join(install_dir_var.get(), exe_var.get())
                server_config["LaunchArgs"] = args_text.get(1.0, tk.END).strip()
                server_config["Port"] = int(port_var.get()) if port_var.get().isdigit() else 27015
                server_config["MaxPlayers"] = int(maxplayers_var.get()) if maxplayers_var.get().isdigit() else 16
                server_config["ServerName"] = servername_var.get()
                server_config["Map"] = map_var.get()
                server_config["SteamCMDPath"] = steamcmd_var.get()
                server_config["AutoUpdate"] = auto_update_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.save_server_config(server_name, server_config)
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Center dialog
        from Host.dashboard_functions import center_window
        center_window(dialog, 700, 600, self.root)
    
    def show_other_server_config(self, server_name, server_config):
        """Show generic server configuration dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Server Configuration - {server_name}")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Server Information
        info_frame = ttk.LabelFrame(main_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server Type
        ttk.Label(info_frame, text="Server Type:").grid(row=1, column=0, sticky=tk.W, pady=5)
        type_var = tk.StringVar(value=server_config.get("Type", "Other"))
        ttk.Entry(info_frame, textvariable=type_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Executable
        ttk.Label(info_frame, text="Server Executable:").grid(row=3, column=0, sticky=tk.W, pady=5)
        exe_var = tk.StringVar(value=server_config.get("ExecutablePath", ""))
        ttk.Entry(info_frame, textvariable=exe_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        def browse_executable():
            file_types = [("Executable Files", "*.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            exe_path = filedialog.askopenfilename(title="Select Server Executable", filetypes=file_types)
            if exe_path:
                exe_var.set(exe_path)
        
        ttk.Button(info_frame, text="Browse", command=browse_executable).grid(row=3, column=2, padx=(5, 0), pady=5)
        
        # Launch Configuration
        launch_frame = ttk.LabelFrame(main_frame, text="Launch Configuration", padding=10)
        launch_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Launch Arguments
        ttk.Label(launch_frame, text="Command Line Arguments:").pack(anchor=tk.W, pady=(0, 5))
        args_var = tk.StringVar(value=server_config.get("LaunchArgs", ""))
        args_text = tk.Text(launch_frame, height=8, width=70)
        args_text.insert(1.0, args_var.get())
        args_scroll = ttk.Scrollbar(launch_frame, orient=tk.VERTICAL, command=args_text.yview)
        args_text.configure(yscrollcommand=args_scroll.set)
        
        args_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        args_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Working Directory
        work_dir_frame = ttk.Frame(main_frame)
        work_dir_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(work_dir_frame, text="Working Directory:").pack(side=tk.LEFT)
        work_dir_var = tk.StringVar(value=server_config.get("WorkingDir", ""))
        ttk.Entry(work_dir_frame, textvariable=work_dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 5))
        
        def browse_work_dir():
            work_dir = filedialog.askdirectory(title="Select Working Directory")
            if work_dir:
                work_dir_var.set(work_dir)
        
        ttk.Button(work_dir_frame, text="Browse", command=browse_work_dir).pack(side=tk.RIGHT)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["Type"] = type_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = exe_var.get()
                server_config["LaunchArgs"] = args_text.get(1.0, tk.END).strip()
                server_config["WorkingDir"] = work_dir_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.save_server_config(server_name, server_config)
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Center dialog
        from Host.dashboard_functions import center_window
        center_window(dialog, 600, 500, self.root)

    def open_server_directory(self):
        """Open the server's installation directory in file explorer"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                messagebox.showerror("Error", f"Server configuration file not found: {config_file}")
                return
                
            # Read server configuration
            with open(config_file, 'r', encoding='utf-8') as f:
                server_config = json.load(f)
                
            install_dir = server_config.get('InstallDir', '')
            
            if not install_dir:
                messagebox.showerror("Error", "Server installation directory not configured.")
                return
                
            # Use the imported function to open directory
            success, message = open_directory_in_explorer(install_dir)
            if success:
                logger.info(f"Opened directory for server '{server_name}': {install_dir}")
            else:
                messagebox.showerror("Error", message)
                
        except Exception as e:
            logger.error(f"Error opening server directory: {str(e)}")
            messagebox.showerror("Error", f"Failed to open server directory: {str(e)}")

    def remove_server(self):
        """Remove the selected server configuration and optionally files"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
        
        # Use the new removal dialog function
        result = create_server_removal_dialog(self.root, server_name, self.server_manager)
        
        if result["confirmed"]:
            try:
                remove_files = result["remove_files"]
                
                # Use server manager to remove/uninstall the server
                if self.server_manager:
                    success, message = self.server_manager.uninstall_server(
                        server_name, remove_files=remove_files
                    )
                else:
                    success = False
                    message = "Server manager not initialized"
                
                if success:
                    # Update server list
                    self.update_server_list(force_refresh=True)
                    messagebox.showinfo("Success", message)
                else:
                    messagebox.showerror("Error", message)
                    
            except Exception as e:
                logger.error(f"Error removing server: {str(e)}")
                messagebox.showerror("Error", f"Failed to remove server: {str(e)}")

    def import_server(self):
        """Enhanced import server functionality with support for exported configurations"""
        try:
            # Choose import type
            import_dialog = tk.Toplevel(self.root)
            import_dialog.title("Import Server")
            import_dialog.transient(self.root)
            import_dialog.grab_set()
            
            main_frame = ttk.Frame(import_dialog, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(main_frame, text="Select Import Method:", font=("Segoe UI", 12, "bold")).pack(pady=10)
            
            import_type = tk.StringVar(value="directory")
            
            ttk.Radiobutton(main_frame, text="Import from existing directory", 
                          variable=import_type, value="directory").pack(anchor=tk.W, pady=5)
            
            ttk.Radiobutton(main_frame, text="Import from exported configuration file", 
                          variable=import_type, value="exported").pack(anchor=tk.W, pady=5)
            
            # Button frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(pady=20)
            
            def proceed_import():
                import_dialog.destroy()
                if import_type.get() == "directory":
                    self.import_server_from_directory()
                else:
                    self.import_server_from_export()
            
            def cancel_import():
                import_dialog.destroy()
            
            ttk.Button(button_frame, text="Continue", command=proceed_import, width=15).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=cancel_import, width=15).pack(side=tk.LEFT, padx=5)
            
            # Center dialog
            # Center dialog relative to parent
            center_window(import_dialog, 400, 300, self.root)
            
        except Exception as e:
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to open import dialog: {str(e)}")

    def import_server_from_directory(self):
        """Import an existing server from a directory (legacy method)"""
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        try:
            # Ask user to select a directory
            install_dir = filedialog.askdirectory(
                title="Select Server Installation Directory",
                initialdir=self.server_manager_dir
            )
            
            if not install_dir:
                return
                
            # Create import dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Import Server from Directory")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Main frame
            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Server name
            ttk.Label(main_frame, text="Server Name:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
            name_var = tk.StringVar(value=os.path.basename(install_dir))
            name_entry = ttk.Entry(main_frame, textvariable=name_var, width=35)
            name_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)

            # Server type
            ttk.Label(main_frame, text="Server Type:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
            type_var = tk.StringVar(value="Other")
            type_combo = ttk.Combobox(main_frame, textvariable=type_var, values=self.supported_server_types, width=32)
            type_combo.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            
            # Installation directory (readonly)
            ttk.Label(main_frame, text="Install Directory:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
            ttk.Label(main_frame, text=install_dir, wraplength=300).grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            
            # Executable path
            ttk.Label(main_frame, text="Executable:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
            exe_var = tk.StringVar()
            exe_entry = ttk.Entry(main_frame, textvariable=exe_var, width=25)
            exe_entry.grid(row=3, column=1, padx=10, pady=10, sticky=tk.W)
            
            def browse_exe():
                fp = filedialog.askopenfilename(
                    title="Select Server Executable",
                    initialdir=install_dir,
                    filetypes=[("Executables", "*.exe;*.jar;*.bat;*.cmd;*.sh"), ("All files", "*.*")]
                )
                if fp:
                    # Store relative path if possible
                    try:
                        rel_path = os.path.relpath(fp, install_dir)
                        exe_var.set(rel_path)
                    except:
                        exe_var.set(fp)
            
            ttk.Button(main_frame, text="Browse", command=browse_exe, width=10).grid(row=3, column=2, padx=5, pady=10)
            
            # Startup arguments
            ttk.Label(main_frame, text="Startup Args:").grid(row=4, column=0, padx=10, pady=10, sticky=tk.W)
            args_var = tk.StringVar()
            args_entry = ttk.Entry(main_frame, textvariable=args_var, width=35)
            args_entry.grid(row=4, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            
            # Auto-detect common server files
            def auto_detect():
                try:
                    if self.server_manager:
                        found_files = self.server_manager.auto_detect_server_executable(install_dir)
                    else:
                        messagebox.showerror("Error", "Server manager not initialized.")
                        return
                    
                    if found_files:
                        # Show selection dialog if multiple found
                        if len(found_files) == 1:
                            exe_var.set(found_files[0])
                        else:
                            # Create selection dialog
                            selection_dialog = tk.Toplevel(dialog)
                            selection_dialog.title("Select Executable")
                            selection_dialog.geometry("400x300")
                            selection_dialog.transient(dialog)
                            selection_dialog.grab_set()
                            
                            ttk.Label(selection_dialog, text="Multiple executables found. Select one:").pack(pady=10)
                            
                            listbox = tk.Listbox(selection_dialog)
                            listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
                            
                            for file in found_files:
                                listbox.insert(tk.END, file)
                            
                            def select_file():
                                selection = listbox.curselection()
                                if selection:
                                    exe_var.set(found_files[selection[0]])
                                selection_dialog.destroy()
                            
                            ttk.Button(selection_dialog, text="Select", command=select_file).pack(pady=10)
                    else:
                        messagebox.showinfo("Auto-detect", "No common server executables found. Please select manually.")
                        
                except Exception as e:
                    logger.error(f"Error during auto-detect: {str(e)}")
                    messagebox.showerror("Error", f"Auto-detection failed: {str(e)}")
            
            ttk.Button(main_frame, text="Auto-detect", command=auto_detect, width=15).grid(row=5, column=1, pady=10)
            
            # Buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.grid(row=6, column=0, columnspan=3, pady=20)
            
            def import_config():
                try:
                    server_name = name_var.get().strip()
                    server_type = type_var.get()
                    executable_path = exe_var.get().strip()
                    startup_args = args_var.get().strip()
                    
                    if not server_name:
                        messagebox.showerror("Validation Error", "Server name is required.")
                        return
                        
                    if not executable_path:
                        messagebox.showerror("Validation Error", "Executable path is required.")
                        return
                    
                    # Use server manager to import the server
                    if self.server_manager:
                        success, message = self.server_manager.import_server_config(
                            server_name, server_type, install_dir, executable_path, startup_args
                        )
                    else:
                        success = False
                        message = "Server manager not initialized"
                    
                    if success:
                        # Update server list
                        self.update_server_list(force_refresh=True)
                        messagebox.showinfo("Success", message)
                        dialog.destroy()
                    else:
                        messagebox.showerror("Error", message)
                    
                except Exception as e:
                    logger.error(f"Error importing server: {str(e)}")
                    messagebox.showerror("Error", f"Failed to import server: {str(e)}")

            ttk.Button(button_frame, text="Import", command=import_config, width=15).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
            
            # Center dialog relative to parent
            center_window(dialog, 500, 400, self.root)
            
        except Exception as e:
            logger.error(f"Error during directory import: {str(e)}")
            messagebox.showerror("Error", f"Failed to import server from directory: {str(e)}")

    def import_server_from_export(self):
        """Import server from exported configuration file"""
        try:
            # Ask user to select export file
            file_path = filedialog.askopenfilename(
                title="Select Server Export File",
                filetypes=[
                    ("Server Export Files", "*.json;*.zip"),
                    ("JSON Files", "*.json"),
                    ("ZIP Files", "*.zip"),
                    ("All Files", "*.*")
                ]
            )
            
            if not file_path:
                return
            
            # Import server data from file
            success, export_data, has_files = import_server_from_file(file_path)
            
            if not success or not export_data:
                messagebox.showerror("Import Error", "Failed to read export file. File may be corrupted or invalid.")
                return
            
            # Create import configuration dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Import Server Configuration")
            dialog.transient(self.root)
            dialog.grab_set()
            
            main_frame = ttk.Frame(dialog, padding=15)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Display export information
            export_info_frame = ttk.LabelFrame(main_frame, text="Export Information", padding=10)
            export_info_frame.pack(fill=tk.X, pady=(0, 10))
            
            export_metadata = export_data.get("export_metadata", {})
            server_config = export_data.get("server_configuration", {})
            dependencies = export_data.get("dependencies", {})
            
            info_text = f"""Exported: {export_metadata.get('exported_at', 'Unknown')}
From Host: {export_metadata.get('source_host', 'Unknown')}
Server Type: {server_config.get('Type', 'Unknown')}
Original Name: {server_config.get('Name', 'Unknown')}
Includes Files: {'Yes' if has_files else 'No'}"""
            
            if server_config.get('Type') == 'Steam' and server_config.get('AppId'):
                info_text += f"\nSteam App ID: {server_config['AppId']}"
                
            ttk.Label(export_info_frame, text=info_text, justify=tk.LEFT).pack(anchor=tk.W)
            
            # Import configuration frame
            config_frame = ttk.LabelFrame(main_frame, text="Import Configuration", padding=10)
            config_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Server name (with unique name generation)
            ttk.Label(config_frame, text="Server Name:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
            original_name = server_config.get("Name", "Imported Server")
            unique_name = generate_unique_server_name(original_name, self.paths)
            name_var = tk.StringVar(value=unique_name)
            name_entry = ttk.Entry(config_frame, textvariable=name_var, width=40)
            name_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W)
            
            # Installation directory
            ttk.Label(config_frame, text="Install Directory:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
            default_install_dir = ""
            if has_files and self.server_manager_dir:
                default_install_dir = os.path.join(self.server_manager_dir, "servers", unique_name.replace(" ", "_"))
            
            install_dir_var = tk.StringVar(value=default_install_dir)
            install_dir_entry = ttk.Entry(config_frame, textvariable=install_dir_var, width=30)
            install_dir_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
            
            def browse_install_dir():
                dir_path = filedialog.askdirectory(title="Select Installation Directory")
                if dir_path:
                    install_dir_var.set(dir_path)
            
            ttk.Button(config_frame, text="Browse", command=browse_install_dir, width=10).grid(row=1, column=2, padx=5, pady=5)
            
            # Steam installation option (if Steam server)
            auto_install_var = tk.BooleanVar(value=False)
            if server_config.get('Type') == 'Steam' and server_config.get('AppId'):
                install_check = ttk.Checkbutton(
                    config_frame,
                    text=f"Automatically install Steam App ID {server_config['AppId']} (requires SteamCMD)",
                    variable=auto_install_var
                )
                install_check.grid(row=2, column=0, columnspan=3, padx=5, pady=10, sticky=tk.W)
            
            # File extraction option (if files are included)
            extract_files_var = tk.BooleanVar(value=has_files)
            if has_files:
                extract_check = ttk.Checkbutton(
                    config_frame,
                    text="Extract server files from archive",
                    variable=extract_files_var
                )
                extract_check.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)
            
            # Progress frame
            progress_frame = ttk.Frame(main_frame)
            progress_frame.pack(fill=tk.X, pady=(10, 0))
            
            status_var = tk.StringVar(value="Ready to import")
            status_label = ttk.Label(progress_frame, textvariable=status_var)
            status_label.pack(anchor=tk.W, pady=2)
            
            progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
            progress_bar.pack(fill=tk.X, pady=2)
            
            # Buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            def perform_import():
                try:
                    server_name = name_var.get().strip()
                    install_dir = install_dir_var.get().strip()
                    
                    if not server_name:
                        messagebox.showerror("Validation Error", "Server name is required.")
                        return
                    
                    # Start import process
                    status_var.set("Importing server configuration...")
                    progress_bar.config(value=10)
                    dialog.update()
                    
                    # Import server configuration
                    success, message, imported_config = import_server_configuration(
                        export_data, self.paths, install_dir, auto_install_var.get()
                    )
                    
                    if not success:
                        messagebox.showerror("Import Error", message)
                        return
                    
                    progress_bar.config(value=50)
                    status_var.set("Server configuration imported successfully")
                    dialog.update()
                    
                    # Extract files if requested
                    if has_files and extract_files_var.get() and install_dir:
                        status_var.set("Extracting server files...")
                        progress_bar.config(value=70)
                        dialog.update()
                        
                        extract_success, extract_message = extract_server_files_from_archive(file_path, install_dir)
                        
                        if not extract_success:
                            logger.warning(f"File extraction failed: {extract_message}")
                            messagebox.showwarning("Extraction Warning", 
                                                 f"Server imported but file extraction failed:\n{extract_message}")
                        else:
                            status_var.set("Files extracted successfully")
                    
                    progress_bar.config(value=100)
                    status_var.set("Import completed successfully")
                    dialog.update()
                    
                    # Update server list
                    self.update_server_list(force_refresh=True)
                    
                    # Show completion message
                    completion_msg = f"Server '{server_name}' imported successfully!"
                    if auto_install_var.get():
                        completion_msg += "\n\nNote: Steam installation will be performed when the server is first started."
                    
                    messagebox.showinfo("Import Complete", completion_msg)
                    dialog.destroy()
                    
                except Exception as e:
                    logger.error(f"Error during import: {str(e)}")
                    status_var.set(f"Import failed: {str(e)}")
                    messagebox.showerror("Import Error", f"Failed to import server: {str(e)}")
            
            def cancel_import():
                dialog.destroy()
            
            ttk.Button(button_frame, text="Import", command=perform_import, width=15).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=cancel_import, width=15).pack(side=tk.RIGHT, padx=5)
            
            # Center dialog relative to parent
            center_window(dialog, 600, 550, self.root)
            
        except Exception as e:
            logger.error(f"Error importing from export: {str(e)}")
            messagebox.showerror("Error", f"Failed to import server from export: {str(e)}")

    def export_server(self):
        """Export server configuration for use on other hosts or clusters"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server to export first.")
            return
        
        try:
            server_name = self.server_list.item(selected_items[0])['values'][0]
            
            # Create export options dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Export Server: {server_name}")
            dialog.transient(self.root)
            dialog.grab_set()
            
            main_frame = ttk.Frame(dialog, padding=15)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Export options frame
            options_frame = ttk.LabelFrame(main_frame, text="Export Options", padding=10)
            options_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Include files option
            include_files_var = tk.BooleanVar(value=False)
            include_files_check = ttk.Checkbutton(
                options_frame,
                text="Include server files in export (creates larger archive)",
                variable=include_files_var
            )
            include_files_check.pack(anchor=tk.W, pady=5)
            
            # Warning about file inclusion
            warning_label = ttk.Label(
                options_frame,
                text="⚠️ Including files will create a zip archive. Large server installations may take time to export.",
                foreground="orange",
                wraplength=450
            )
            warning_label.pack(anchor=tk.W, pady=5)
            
            # Export location frame
            location_frame = ttk.LabelFrame(main_frame, text="Export Location", padding=10)
            location_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(location_frame, text="Export to:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
            
            # Default filename
            safe_name = "".join(c for c in server_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            default_filename = f"{safe_name.replace(' ', '_')}_export.json"
            
            export_path_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Desktop", default_filename))
            export_path_entry = ttk.Entry(location_frame, textvariable=export_path_var, width=40)
            export_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
            
            def browse_export_location():
                if include_files_var.get():
                    file_path = filedialog.asksaveasfilename(
                        title="Save Server Export",
                        defaultextension=".zip",
                        filetypes=[("ZIP Archives", "*.zip"), ("All Files", "*.*")]
                    )
                else:
                    file_path = filedialog.asksaveasfilename(
                        title="Save Server Export",
                        defaultextension=".json",
                        filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
                    )
                
                if file_path:
                    export_path_var.set(file_path)
            
            def update_filename():
                # Update file extension based on include files option
                current_path = export_path_var.get()
                if include_files_var.get():
                    if current_path.endswith('.json'):
                        export_path_var.set(current_path[:-5] + '.zip')
                else:
                    if current_path.endswith('.zip'):
                        export_path_var.set(current_path[:-4] + '.json')
            
            include_files_check.configure(command=update_filename)
            
            ttk.Button(location_frame, text="Browse", command=browse_export_location, width=10).grid(row=0, column=2, padx=5, pady=5)
            
            # Progress frame
            progress_frame = ttk.Frame(main_frame)
            progress_frame.pack(fill=tk.X, pady=(10, 0))
            
            status_var = tk.StringVar(value="Ready to export")
            status_label = ttk.Label(progress_frame, textvariable=status_var)
            status_label.pack(anchor=tk.W, pady=2)
            
            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=2)
            
            # Buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            def perform_export():
                try:
                    export_path = export_path_var.get().strip()
                    include_files = include_files_var.get()
                    
                    if not export_path:
                        messagebox.showerror("Validation Error", "Export path is required.")
                        return
                    
                    # Start export process
                    status_var.set("Generating export configuration...")
                    progress_bar.start()
                    dialog.update()
                    
                    # Export server configuration
                    export_data = export_server_configuration(server_name, self.paths, include_files)
                    
                    status_var.set("Saving export file...")
                    dialog.update()
                    
                    # Save to file
                    success, message = export_server_to_file(export_data, export_path, include_files)
                    
                    progress_bar.stop()
                    
                    if success:
                        status_var.set("Export completed successfully")
                        
                        # Show completion dialog
                        completion_msg = f"Server '{server_name}' exported successfully!\n\n{message}"
                        
                        # Add usage instructions
                        completion_msg += "\n\nUsage Instructions:"
                        completion_msg += "\n• Use 'Import Server' > 'Import from exported configuration file' on target host"
                        completion_msg += "\n• Configuration includes all startup parameters and settings"
                        
                        if include_files:
                            completion_msg += "\n• Archive includes server files for complete migration"
                        else:
                            completion_msg += "\n• Only configuration exported - server files must be installed separately"
                        
                        if export_data.get("server_configuration", {}).get("Type") == "Steam":
                            completion_msg += "\n• Steam servers can be auto-installed on import if SteamCMD is available"
                        
                        messagebox.showinfo("Export Complete", completion_msg)
                        dialog.destroy()
                    else:
                        status_var.set(f"Export failed: {message}")
                        messagebox.showerror("Export Error", message)
                    
                except Exception as e:
                    logger.error(f"Error during export: {str(e)}")
                    progress_bar.stop()
                    status_var.set(f"Export failed: {str(e)}")
                    messagebox.showerror("Export Error", f"Failed to export server: {str(e)}")
            
            def cancel_export():
                dialog.destroy()
            
            ttk.Button(button_frame, text="Export", command=perform_export, width=15).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=cancel_export, width=15).pack(side=tk.RIGHT, padx=5)
            
            # Center dialog relative to parent
            center_window(dialog, 500, 400, self.root)
            
        except Exception as e:
            logger.error(f"Error in export server: {str(e)}")
            messagebox.showerror("Error", f"Failed to export server: {str(e)}")

    def refresh_all(self):
        """Refresh all dashboard data"""
        try:
            logger.info("Refreshing all dashboard data")
            
            # Update system information
            self.update_system_info()
            
            # Update server list
            self.update_server_list(force_refresh=True)
            
            # Update web server status
            self.update_webserver_status()
            
            # Monitor processes
            self.timer_manager.monitor_processes()
            
            messagebox.showinfo("Refresh Complete", "All dashboard data has been refreshed.")
            
        except Exception as e:
            logger.error(f"Error refreshing dashboard: {str(e)}")
            messagebox.showerror("Error", f"Failed to refresh dashboard: {str(e)}")

    def sync_all(self):
        """Synchronize all server data with the database"""
        try:
            if self.variables["offlineMode"]:
                messagebox.showinfo("Offline Mode", "Cannot sync while in offline mode.")
                return
                
            if not self.current_user:
                messagebox.showinfo("Authentication Required", "Please log in to synchronize data.")
                return
                
            # Create progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Synchronizing Data")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            
            progress_frame = ttk.Frame(progress_dialog, padding=20)
            progress_frame.pack(fill=tk.BOTH, expand=True)
            
            status_label = ttk.Label(progress_frame, text="Starting synchronization...")
            status_label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=10)
            progress_bar.start()
            
            def sync_data():
                try:
                    status_label.config(text="Syncing server configurations...")
                    
                    # Get all local server configurations
                    servers_path = self.paths["servers"]
                    synced_count = 0
                    
                    if os.path.exists(servers_path):
                        for file in os.listdir(servers_path):
                            if file.endswith(".json"):
                                try:
                                    with open(os.path.join(servers_path, file), 'r') as f:
                                        server_config = json.load(f)
                                    
                                    # Update local configuration timestamp
                                    server_config['LastSync'] = datetime.datetime.now().isoformat()
                                    if self.current_user and hasattr(self.current_user, 'username'):
                                        server_config['SyncedBy'] = self.current_user.username
                                    else:
                                        server_config['SyncedBy'] = "Unknown"
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                                    
                                    synced_count += 1
                                        
                                except Exception as e:
                                    logger.error(f"Error syncing server {file}: {str(e)}")
                    
                    status_label.config(text=f"Synchronization complete. Synced {synced_count} servers.")
                    progress_bar.stop()
                    
                    # Auto-close after 2 seconds
                    progress_dialog.after(2000, progress_dialog.destroy)
                    
                    logger.info(f"Sync completed. {synced_count} servers synchronized.")
                    
                except Exception as e:
                    logger.error(f"Error during sync: {str(e)}")
                    status_label.config(text=f"Sync failed: {str(e)}")
                    progress_bar.stop()
                    
                    # Show error and close after 3 seconds
                    progress_dialog.after(3000, progress_dialog.destroy)
            
            # Start sync in a separate thread
            sync_thread = threading.Thread(target=sync_data, daemon=True)
            sync_thread.start()
            
            # Center progress dialog relative to parent
            center_window(progress_dialog, 400, 150, self.root)
            
        except Exception as e:
            logger.error(f"Error in sync all: {str(e)}")
            messagebox.showerror("Error", f"Failed to synchronize data: {str(e)}")

    def add_agent(self):
        """Add a remote agent connection"""
        try:
            if self.agent_manager is None:
                logger.error("Agent manager not initialized")
                messagebox.showerror("Error", "Agent manager not initialized. Cannot add agents.")
                return
            
            # Show the agent management dialog
            show_agent_management_dialog(self.root, self.agent_manager)
            
        except Exception as e:
            logger.error(f"Error in add agent: {str(e)}")
            messagebox.showerror("Error", f"Failed to add agent: {str(e)}")

    def show_help(self):
        """Show help dialog using the documentation module"""
        show_help_dialog(self.root, logger)

    def show_about(self):
        """Show about dialog using the documentation module"""
        show_about_dialog(self.root, logger)

def main():
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(description='Server Manager Dashboard')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    # Create and run dashboard
    dashboard = ServerManagerDashboard(debug_mode=args.debug)
    dashboard.run()

main()
