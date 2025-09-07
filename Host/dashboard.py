# -*- coding: utf-8 -*-
import argparse
import os
import sys
import subprocess
import threading
import json
import time
import datetime

# GUI imports
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import user management system
from Modules.Database.user_database import initialize_user_manager

# Import server management components
from Modules.server_manager import ServerManager
from Modules.minecraft import MinecraftServerManager

# Import logging components
from Modules.server_logging import (
    get_dashboard_logger, configure_dashboard_logging,
    log_dashboard_event
)

# Import scheduling components
from Modules.scheduler import SchedulerManager

# Import update management
from Modules.server_updates import ServerUpdateManager

# Import documentation dialogs
from Modules.documentation import show_help_dialog, show_about_dialog

# Import core infrastructure
from Modules.common import ServerManagerModule, initialize_registry_values

# Import dashboard utility functions
from Host.dashboard_functions import (
    load_dashboard_config, update_webserver_status, update_system_info, center_window,
    create_server_type_selection_dialog, load_appid_scanner_list, show_java_configuration_dialog,
    update_server_list_from_files, get_steam_credentials, open_directory_in_explorer,
    create_server_removal_dialog, export_server_dialog, perform_server_installation,
    format_uptime_from_start_time, update_server_status_in_treeview,
    import_server_from_directory_dialog, import_server_from_export_dialog,
    create_progress_dialog_with_console, rename_server_configuration,
    check_appid_in_database, detect_server_type_from_appid, detect_server_type_from_directory,
    batch_update_server_types, update_server_configuration_with_detection
)

# Import cluster management
from Modules.agents import AgentManager, show_agent_management_dialog

# Import debugging utilities
from debug.debug import (
    get_server_process_details, log_exception, monitor_process_resources
)

# Import console management
from Modules.server_console import ConsoleManager

# Import authentication
from Host.admin_dashboard import admin_login

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
        self.install_process = None
        self._refreshing_server_list = False
        
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
            "updateCheckInterval": self.config.get("configuration", {}).get("updateCheckInterval", 300),
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
        
        # Initialize server console manager
        try:
            self.console_manager = ConsoleManager(self.server_manager)
            logger.info("Server console manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize server console manager: {e}")
            self.console_manager = None
            
        # Configure dashboard logging after paths are initialized
        configure_dashboard_logging(self.debug_mode, self.config)
        
        # Create root window (temporarily hidden for login)
        self.root = tk.Tk()
        self.root.withdraw()
        
        # Prompt for login using admin authentication dialog (using admin_dashboard)
        try:
            user = admin_login(self.user_manager)
            if not user:
                logger.info("Login cancelled or failed, exiting application")
                self.root.destroy()
                sys.exit(0)
            self.current_user = user
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            messagebox.showerror("Login Error", f"Failed to authenticate: {str(e)}\n\nThe application will exit.")
            self.root.destroy()
            sys.exit(1)
        
        # Now configure the UI with user information
        username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
        self.root.title(f"Server Manager Dashboard (Logged in as: {username})")
        self.root.minsize(1000, 700)
        self.root.deiconify()
        
        # Center the main window on screen
        center_window(self.root, 1400, 900)
        
        self.setup_ui()
        
        # Write PID file
        self.write_pid_file("dashboard", os.getpid())
        
        # Initialize timer manager (now using SchedulerManager)
        self.timer_manager = SchedulerManager(self)
        
        # Initialize server update manager
        try:
            self.update_manager = ServerUpdateManager(self.server_manager_dir, self.config)
            self.update_manager.set_server_manager(self.server_manager)
            self.update_manager.set_steam_cmd_path(self.steam_cmd_path)
            self.timer_manager.set_update_manager(self.update_manager)
            logger.info("Server update manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize server update manager: {str(e)}")
            self.update_manager = None
        
        # Initialize cluster manager
        try:
            # Use database-backed cluster management (no longer using JSON)
            agents_config_path = os.path.join(self.paths["data"], "cluster_nodes.json")  # For migration only
            self.agent_manager = AgentManager(agents_config_path)
            logger.info("Cluster manager initialized successfully with database backend")
        except Exception as e:
            logger.error(f"Failed to initialize cluster manager: {str(e)}")
            self.agent_manager = None
        
        # Initialize system info and timers
        self.update_system_info()
        self.timer_manager.start_timers()
        
        # Get supported server types from server manager
        if self.server_manager:
            self.supported_server_types = self.server_manager.get_supported_server_types()
        else:
            self.supported_server_types = ["Steam", "Minecraft", "Other"]

    def setup_menu_bar(self):
        """Setup the menu bar with update options"""
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)
        
        # File Menu
        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Add Server", command=self.add_server)
        file_menu.add_command(label="Import Server", command=self.import_server)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        
        # Updates Menu
        updates_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Updates", menu=updates_menu)
        updates_menu.add_command(label="Update All Steam Servers", command=self.update_all_servers)
        updates_menu.add_separator()
        updates_menu.add_command(label="Schedule Manager", command=self.show_schedule_manager)
        
        # Tools Menu
        tools_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Refresh All", command=self.refresh_all)
        tools_menu.add_command(label="Sync All", command=self.sync_all)
        tools_menu.add_separator()
        tools_menu.add_command(label="Update Server Types", command=self.batch_update_server_types)
        tools_menu.add_separator()
        tools_menu.add_command(label="Cluster", command=self.add_agent)
        
        # Help Menu
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Help", command=self.show_help)
        help_menu.add_command(label="About", command=self.show_about)

    def setup_ui(self):
        """Create and configure the main dashboard user interface"""
        # Create top frame for help and about buttons
        self.top_frame = ttk.Frame(self.root)
        self.top_frame.pack(fill=tk.X, padx=15, pady=(15, 0))
        
        # Add About and Help buttons to top right
        self.help_button = ttk.Button(self.top_frame, text="Help", command=self.show_help, width=10)
        self.help_button.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.about_button = ttk.Button(self.top_frame, text="About", command=self.show_about, width=10)
        self.about_button.pack(side=tk.RIGHT, padx=(5, 5))
        
        # Add quick update buttons to top left
        self.update_all_button = ttk.Button(self.top_frame, text="Update All", 
                                          command=self.update_all_servers, width=12)
        self.update_all_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.schedules_button = ttk.Button(self.top_frame, text="Schedules", 
                                         command=self.show_schedule_manager, width=12)
        self.schedules_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Add console management button
        self.console_button = ttk.Button(self.top_frame, text="Consoles", 
                                       command=self.show_console_manager, width=12)
        self.console_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Main container
        self.container_frame = ttk.Frame(self.root, padding=(15, 10, 15, 15))
        self.container_frame.pack(fill=tk.BOTH, expand=True)
        
        # Main layout - servers list and system info
        self.main_pane = ttk.PanedWindow(self.container_frame, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Server list frame (left side)
        self.servers_frame = ttk.LabelFrame(self.main_pane, text="Game Servers", padding=10)
        self.main_pane.add(self.servers_frame, weight=70)
        
        # Server list with columns
        columns = ("name", "status", "pid", "cpu", "memory", "uptime")
        self.server_list = ttk.Treeview(self.servers_frame, columns=columns, show="headings")
        
        # Column headings
        self.server_list.heading("name", text="Server Name")
        self.server_list.heading("status", text="Status")
        self.server_list.heading("pid", text="PID")
        self.server_list.heading("cpu", text="CPU Usage")
        self.server_list.heading("memory", text="Memory Usage")
        self.server_list.heading("uptime", text="Uptime")

        # Column widths - improved for better readability and consistent spacing
        self.server_list.column("name", width=200, minwidth=150, anchor=tk.W)
        self.server_list.column("status", width=100, minwidth=80, anchor=tk.CENTER)
        self.server_list.column("pid", width=80, minwidth=60, anchor=tk.CENTER)
        self.server_list.column("cpu", width=100, minwidth=80, anchor=tk.CENTER)
        self.server_list.column("memory", width=120, minwidth=100, anchor=tk.CENTER)
        self.server_list.column("uptime", width=160, minwidth=120, anchor=tk.CENTER)
        
        # Add scrollbar to server list
        server_scroll = ttk.Scrollbar(self.servers_frame, orient=tk.VERTICAL, command=self.server_list.yview)
        self.server_list.configure(yscrollcommand=server_scroll.set)
        
        server_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        self.server_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Setup right-click context menu for server list
        self.server_context_menu = tk.Menu(self.root, tearoff=0)
        self.server_context_menu.add_command(label="Add Server", command=self.add_server)
        self.server_context_menu.add_command(label="Refresh", command=self.refresh_all)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Start Server", command=self.start_server)
        self.server_context_menu.add_command(label="Stop Server", command=self.stop_server)
        self.server_context_menu.add_command(label="Restart Server", command=self.restart_server)
        self.server_context_menu.add_command(label="View Process Details", command=self.view_process_details)
        self.server_context_menu.add_command(label="Show Console", command=self.show_server_console)
        self.server_context_menu.add_command(label="Configure Server", command=self.configure_server)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Check for Updates", command=self.check_server_updates)
        self.server_context_menu.add_command(label="Update Server", command=self.update_server)
        self.server_context_menu.add_command(label="Schedule", command=self.show_server_schedule)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Export Server", command=self.export_server)
        self.server_context_menu.add_command(label="Open Folder Directory", command=self.open_server_directory)
        self.server_context_menu.add_command(label="Remove Server", command=self.remove_server)
        
        # Bind right-click to server list
        self.server_list.bind("<Button-3>", self.show_server_context_menu)
        
        # Bind left-click to handle deselection on empty space (like Windows Explorer)
        self.server_list.bind("<Button-1>", self.on_server_list_click)
        
        # Bind double-click to configure server
        self.server_list.bind("<Double-1>", self.on_server_double_click)
        
        # System info frame (right side)
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
        
        # Configure grid layout
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
        
        # Button bar at bottom
        self.button_frame = ttk.Frame(self.container_frame)
        self.button_frame.pack(fill=tk.X, pady=(15, 0))
        
        # Two rows of buttons for better organization
        self.button_row1 = ttk.Frame(self.button_frame)
        self.button_row1.pack(fill=tk.X, pady=(0, 8))
        
        self.button_row2 = ttk.Frame(self.button_frame)
        self.button_row2.pack(fill=tk.X)
        
        # Add buttons with consistent sizing and spacing
        row1_buttons = [
            {"text": "Add Server", "command": self.add_server, "width": 15},
            {"text": "Import Server", "command": self.import_server, "width": 15},
            {"text": "Sync All", "command": self.sync_all, "width": 15}
        ]
        
        row2_buttons = [
            {"text": "Cluster", "command": self.add_agent, "width": 15}
        ]
        
        for btn in row1_buttons:
            ttk.Button(self.button_row1, text=btn["text"], command=btn["command"], 
                      width=btn["width"]).pack(side=tk.LEFT, padx=(0, 8))
            
        for btn in row2_buttons:
            ttk.Button(self.button_row2, text=btn["text"], command=btn["command"], 
                      width=btn["width"]).pack(side=tk.LEFT, padx=(0, 8))
    
    def show_server_context_menu(self, event):
        """Show context menu on right-click in server list"""
        item = self.server_list.identify_row(event.y)
        
        if item:
            self.server_list.selection_set(item)
            # Enable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Start Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Restart Server", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("View Process Details", state=tk.NORMAL)
            self.server_context_menu.entryconfigure("Show Console", state=tk.NORMAL)
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
            self.server_context_menu.entryconfigure("Show Console", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Configure Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Export Server", state=tk.DISABLED)
            
        # Show context menu
        self.server_context_menu.tk_popup(event.x_root, event.y_root)

    def on_server_list_click(self, event):
        """Handle left-click on server list - deselect all if clicking on empty space"""
        item = self.server_list.identify_row(event.y)
        
        if not item:
            # Clicked on empty space - clear all selections (like Windows Explorer)
            self.server_list.selection_remove(self.server_list.selection())
            logger.debug("Cleared server list selection due to empty space click")

    def on_server_double_click(self, event):
        """Handle double-click on server list - open configuration dialog"""
        item = self.server_list.identify_row(event.y)
        
        if item:
            # Double-clicked on a server - open configuration
            self.server_list.selection_set(item)
            self.configure_server()

    def add_server(self):
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

        # Server details dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Create {server_type} Server")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Installation control
        self.install_cancelled = tk.BooleanVar(value=False)
        
        # Paned window for top-bottom split layout
        paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        
        # Top frame for setup information
        top_frame = ttk.Frame(paned_window)
        paned_window.add(top_frame, weight=1)
        
        # Scrollable form
        canvas = tk.Canvas(top_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrollbar first, then canvas
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # Update canvas window width when the canvas changes size
        def update_canvas_width(event=None):
            try:
                if canvas.winfo_width() > 1:
                    canvas.itemconfig(1, width=canvas.winfo_width())
            except:
                pass
        
        canvas.bind("<Configure>", update_canvas_width)
        
        # Configure scrollable frame grid with proper column weights
        scrollable_frame.columnconfigure(0, weight=0, minsize=150)
        scrollable_frame.columnconfigure(1, weight=1, minsize=200)
        scrollable_frame.columnconfigure(2, weight=0, minsize=100)

        # Form variables
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
        name_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['name'], width=35, font=("Segoe UI", 10))
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
            version_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['minecraft_version'], values=[v["id"] for v in mc_versions], state="readonly", width=32, font=("Segoe UI", 10))
            version_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            current_row += 1
            
            # Modloader selection
            ttk.Label(scrollable_frame, text="Modloader:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            modloader_frame = ttk.Frame(scrollable_frame)
            modloader_frame.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            for i in range(4):
                modloader_frame.columnconfigure(i, weight=1)
            
            modloaders = ["Vanilla", "Fabric", "Forge", "NeoForge"]
            for i, modloader in enumerate(modloaders):
                ttk.Radiobutton(modloader_frame, text=modloader, variable=form_vars['modloader'], value=modloader).grid(row=0, column=i, padx=8, pady=5, sticky=tk.W)
            current_row += 1

        # App ID (Steam only)
        if server_type == "Steam":
            ttk.Label(scrollable_frame, text="App ID:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            app_id_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['app_id'], width=25, font=("Segoe UI", 10))
            app_id_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)
            
            def browse_appid():
                """Open dialog to browse and select Steam dedicated server AppID"""
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
                    """Populate the server tree with filtered dedicated server list"""
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
                    """Update server list when search text changes"""
                    populate_servers(search_var.get())
                
                search_var.trace('w', on_search)
                
                # Add tooltip functionality for descriptions
                def show_server_info(event):
                    """Show server description tooltip on mouse hover"""
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
        install_dir_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['install_dir'], width=25, font=("Segoe UI", 10))
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
            exe_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['exe_path'], width=25, font=("Segoe UI", 10))
            exe_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)
            
            def browse_exe():
                fp = filedialog.askopenfilename(title="Select Executable",
                    filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd;*.ps1"),("All","*.*")])
                if fp:
                    form_vars['exe_path'].set(fp)
            ttk.Button(scrollable_frame, text="Browse", command=browse_exe, width=12).grid(row=current_row, column=2, padx=15, pady=10)
            current_row += 1

        # Startup Args (all)
        ttk.Label(scrollable_frame, text="Startup Args:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
        args_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['startup_args'], width=35, font=("Segoe UI", 10))
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
        
        console_output = scrolledtext.ScrolledText(console_container, width=60, height=12, 
                                                 background="black", foreground="white", 
                                                 font=("Consolas", 9))
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)
        
        # Add initial message to console
        def append_console(text):
            try:
                if not dialog.winfo_exists():
                    return
                console_output.config(state=tk.NORMAL)
                console_output.insert(tk.END, text + "\n")
                console_output.see(tk.END)
                console_output.config(state=tk.DISABLED)
            except (tk.TclError, AttributeError):
                # Widget was destroyed, ignore
                pass
        
        append_console(f"[INFO] Ready to create {server_type} server...")
        append_console(f"[INFO] Please fill in the required fields above and click 'Create Server' to begin.")

        def install_server():
            try:
                # Check if dialog still exists before accessing widgets
                if not dialog.winfo_exists():
                    return
                    
                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                status_var.set("Starting installation...")
                
                # Define safe callback functions
                def safe_status_callback(msg):
                    try:
                        if dialog.winfo_exists():
                            status_var.set(msg)
                    except (tk.TclError, AttributeError):
                        pass
                
                def safe_console_callback(msg):
                    try:
                        if dialog.winfo_exists():
                            append_console(msg)
                    except (tk.TclError, AttributeError):
                        pass
                
                # Use the existing installation function from dashboard_functions
                success, message = perform_server_installation(
                    self.server_manager, server_type, form_vars, credentials, self.paths,
                    status_callback=safe_status_callback,
                    console_callback=safe_console_callback,
                    cancel_flag=self.install_cancelled,
                    steam_cmd_path=getattr(self, 'steam_cmd_path', None)
                )

                # Check if dialog still exists before updating UI
                if not dialog.winfo_exists():
                    return

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
                    
            except tk.TclError:
                # Dialog was destroyed while thread was running - this is normal
                logger.info("Installation dialog was closed while installation was in progress")
                return
            except Exception as e:
                logger.error(f"Error during server installation: {str(e)}")
                if dialog.winfo_exists():
                    append_console(f"[ERROR] {str(e)}")
                    status_var.set("Installation failed!")
                    create_button.config(state=tk.NORMAL)
                    cancel_button.config(state=tk.DISABLED)
            finally:
                # Safely stop progress bar only if dialog still exists
                try:
                    if dialog.winfo_exists():
                        progress.stop()
                except (tk.TclError, AttributeError):
                    # Widget was destroyed, ignore
                    pass
        
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
            # Cancel any running installation
            if hasattr(self, 'install_cancelled'):
                self.install_cancelled.set(True)
            dialog.destroy()
            
        # Assign button commands
        create_button.config(command=start_installation)
        cancel_button.config(command=cancel_installation)
        close_button.config(command=close_dialog)
        
        def on_close():
            # Handle window close (X button) - check if installation is running
            if hasattr(self, 'install_cancelled') and hasattr(cancel_button, 'instate'):
                try:
                    if cancel_button.instate(['!disabled']):
                        result = messagebox.askyesno("Confirm Exit", 
                                                   "An installation is in progress. Do you want to cancel it?",
                                                   icon=messagebox.QUESTION)
                        if result:
                            self.install_cancelled.set(True)
                            dialog.destroy()
                        # If they chose not to cancel, don't close the dialog
                        return
                except tk.TclError:
                    # Widget was destroyed, just close
                    pass
            
            # Cancel any running installation and close
            if hasattr(self, 'install_cancelled'):
                self.install_cancelled.set(True)
            dialog.destroy()
            
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        
        # Center dialog relative to parent with proper size for new layout
        center_window(dialog, 950, 700, self.root)

    def update_server_list(self, force_refresh=False):
        """Update server list from configuration files - thread-safe"""
        def _update():
            try:
                # Skip update if already refreshing
                if hasattr(self, '_refreshing_server_list') and self._refreshing_server_list:
                    log_dashboard_event("SERVER_LIST_UPDATE", "Skipping update - refresh already in progress", "DEBUG")
                    return
                
                # Skip update if it's been less than configured interval since the last update and force_refresh isn't specified
                update_interval = self.variables.get("serverListUpdateInterval", 30)
                if not force_refresh and \
                   (self.variables["lastServerListUpdate"] != datetime.datetime.min) and \
                   (datetime.datetime.now() - self.variables["lastServerListUpdate"]).total_seconds() < update_interval:
                    log_dashboard_event("SERVER_LIST_UPDATE", f"Skipping update - last update was less than {update_interval} seconds ago", "DEBUG")
                    return
                
                # Set refreshing flag
                self._refreshing_server_list = True
                
                try:
                    # Use the new function from dashboard_functions
                    update_server_list_from_files(
                        self.server_list, self.paths, self.variables, 
                        log_dashboard_event, format_uptime_from_start_time
                    )
                finally:
                    # Always clear the refreshing flag
                    self._refreshing_server_list = False
                    
            except Exception as e:
                logger.error(f"Error in update_server_list: {str(e)}")
                self._refreshing_server_list = False
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def toggle_offline_mode(self):
        """Toggle offline mode"""
        # Toggle offline mode
        self.variables["offlineMode"] = self.offline_var.get()
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
    def update_webserver_status(self):
        """Update the web server status display - thread-safe"""
        def _update():
            try:
                # Use the imported function from dashboard_functions
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

                # Use the imported function from dashboard_functions
                update_system_info(self.metric_labels, self.system_name, self.os_info, self.variables)

            except Exception as e:
                logger.error(f"Error updating system info: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def periodic_server_list_refresh(self):
        """Periodic refresh of server list to clean up orphaned processes and update status"""
        def _refresh():
            try:
                # Only refresh if not already refreshing and enough time has passed
                if not hasattr(self, '_refreshing_server_list') or not self._refreshing_server_list:
                    # Use the main update method which now has its own protection
                    self.update_server_list(force_refresh=True)
                else:
                    log_dashboard_event("PERIODIC_REFRESH", "Skipping periodic refresh - update already in progress", "DEBUG")
            except Exception as e:
                logger.error(f"Error in periodic server list refresh: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _refresh()
        else:
            self.root.after(0, _refresh)
    
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
            # Close all console windows
            if hasattr(self, 'console_manager') and self.console_manager:
                self.console_manager.cleanup_all_consoles()
                logger.debug("Closed all console windows")

            # Cluster management cleanup (no specific cleanup needed)
            if hasattr(self, 'agent_manager') and self.agent_manager:
                logger.debug("Cluster manager cleanup completed")

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
                success, result = self.server_manager.start_server_advanced(
                    server_name, 
                    callback=lambda status: self.update_server_status(server_name, status)
                )
                
                # If successful and we got a process object, start console
                if success and hasattr(result, 'pid'):
                    # Start console for real-time monitoring
                    if self.console_manager:
                        self.console_manager.attach_console_to_process(server_name, result)
                    message = f"Server '{server_name}' started successfully with PID {result.pid}."
                else:
                    message = result if isinstance(result, str) else "Server started successfully"
                
                # Update UI on main thread
                def update_ui():
                    if success:
                        # Add a debug if required (removed for now)
                        pass
                    else:
                        messagebox.showerror("Error", message)
                    # Always refresh the server list to show current status
                    self.update_server_list(force_refresh=True)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error starting server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to start server: {str(e)}")
                    # Refresh list even on error to show current status
                    self.update_server_list(force_refresh=True)
                self.root.after(0, show_error)
        
        # Show starting message
        self.update_server_status(server_name, "Starting...")

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
                    else:
                        messagebox.showinfo("Info", message)
                    # Always refresh the server list to show current status
                    self.update_server_list(force_refresh=True)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error stopping server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to stop server: {str(e)}")
                    # Refresh list even on error to show current status
                    self.update_server_list(force_refresh=True)
                self.root.after(0, show_error)
        
        # Show stopping message
        self.update_server_status(server_name, "Stopping...")

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
                    else:
                        messagebox.showerror("Error", message)
                    # Always refresh the server list to show current status
                    self.update_server_list(force_refresh=True)
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                logger.error(f"Error restarting server: {str(e)}")
                def show_error():
                    messagebox.showerror("Error", f"Failed to restart server: {str(e)}")
                    # Refresh list even on error to show current status
                    self.update_server_list(force_refresh=True)
                self.root.after(0, show_error)
        
        # Show restarting message
        self.update_server_status(server_name, "Restarting...")

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
    
    def show_server_console(self):
        """Show console window for the selected server"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        try:
            if not self.console_manager:
                messagebox.showerror("Console Error", "Console manager not available.")
                return
            
            # Get server config from server manager
            server_config = None
            if self.server_manager:
                try:
                    server_config = self.server_manager.get_server_config(server_name)
                except Exception as e:
                    logger.warning(f"Could not get server config for {server_name}: {e}")
            
            # If we can't get config from server manager, create a basic one
            if not server_config:
                server_values = self.server_list.item(selected_items[0])['values']
                server_config = {
                    'name': server_name,
                    'type': 'Unknown',
                    'pid': server_values[2] if len(server_values) > 2 else None
                }
            
            # Show the console window
            success = self.console_manager.show_console(server_name, self.root)
            
            if success:
                username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                logger.info(f"USER_ACTION: {username} opened console for server: {server_name}")
            else:
                messagebox.showerror("Console Error", f"Failed to open console for {server_name}")
            
        except Exception as e:
            log_exception(e, f"Error showing console for {server_name}")
            messagebox.showerror("Console Error", f"Failed to open console:\n{str(e)}")
    
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
        """Configure server settings including name, type, AppID, and startup configuration"""
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
            messagebox.showerror("Server Installation Directory Missing", 
                               f"Server installation directory is missing or invalid.\n\n"
                               f"Server: {server_name}\n"
                               f"Expected Directory: {install_dir or '(not set)'}\n\n"
                               f"The server installation may have been incomplete or the files were moved.\n"
                               f"Please reinstall the server to resolve this issue.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure Server: {server_name}")
        dialog.geometry("900x850")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Create main frame with padding
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create scrollable frame for all content
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
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

        # Server Identity Section
        identity_frame = ttk.LabelFrame(scrollable_frame, text="Server Identity", padding=10)
        identity_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server name
        ttk.Label(identity_frame, text="Server Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        name_var = tk.StringVar(value=server_name)
        name_entry = ttk.Entry(identity_frame, textvariable=name_var, width=30, font=("Segoe UI", 10))
        name_entry.grid(row=0, column=1, padx=10, pady=5, sticky=tk.EW)
        
        # Server type
        ttk.Label(identity_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        current_server_type = server_config.get('Type', 'Other')
        type_var = tk.StringVar(value=current_server_type)
        type_combo = ttk.Combobox(identity_frame, textvariable=type_var, values=["Steam", "Minecraft", "Other"], 
                                 state="readonly", width=27, font=("Segoe UI", 10))
        type_combo.grid(row=1, column=1, padx=10, pady=5, sticky=tk.W)
        
        # AppID (conditionally shown for Steam servers)
        ttk.Label(identity_frame, text="AppID:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        appid_var = tk.StringVar(value=str(server_config.get('appid', server_config.get('AppID', ''))))
        appid_entry = ttk.Entry(identity_frame, textvariable=appid_var, width=15, font=("Segoe UI", 10))
        appid_entry.grid(row=2, column=1, padx=10, pady=5, sticky=tk.W)
        
        def browse_appid():
            """Open dialog to browse and select Steam dedicated server AppID"""
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
                """Populate the server tree with filtered dedicated server list"""
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
                """Update server list when search text changes"""
                populate_servers(search_var.get())
            
            search_var.trace('w', on_search)
            
            # Add tooltip functionality for descriptions
            def show_server_info(event):
                """Show server description tooltip on mouse hover"""
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
                    appid_var.set(appid)
                    appid_dialog.destroy()
                else:
                    messagebox.showinfo("No Selection", "Please select a server from the list.")
            
            def cancel_selection():
                appid_dialog.destroy()
            
            ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT)
            ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)
            
            # Center dialog
            center_window(appid_dialog, 600, 500, dialog)
        
        appid_browse_btn = ttk.Button(identity_frame, text="Browse", command=browse_appid, width=10)
        appid_browse_btn.grid(row=2, column=2, padx=5, pady=5)
        
        appid_help = ttk.Label(identity_frame, text="(Steam servers only)", foreground="gray", font=("Segoe UI", 8))
        appid_help.grid(row=2, column=3, padx=5, pady=5, sticky=tk.W)
        
        # Install directory (read-only display)
        ttk.Label(identity_frame, text="Install Directory:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        dir_label = ttk.Label(identity_frame, text=install_dir, font=("Segoe UI", 9), foreground="gray")
        dir_label.grid(row=3, column=1, columnspan=2, padx=10, pady=5, sticky=tk.W)
        
        # Configure grid
        identity_frame.grid_columnconfigure(1, weight=1)
        identity_frame.grid_columnconfigure(2, weight=0)
        identity_frame.grid_columnconfigure(3, weight=0)
        
        def toggle_appid_field():
            # Enable/disable AppID field based on server type
            if type_var.get() == "Steam":
                appid_entry.config(state=tk.NORMAL)
                appid_browse_btn.config(state=tk.NORMAL)
                appid_help.config(text="(Required for Steam servers)")
            else:
                appid_entry.config(state=tk.DISABLED)
                appid_browse_btn.config(state=tk.DISABLED)
                appid_help.config(text="(Steam servers only)")
        
        # Bind type change event
        type_var.trace('w', lambda *args: toggle_appid_field())
        toggle_appid_field()  # Initial state
        
        # Startup Configuration Section
        startup_frame = ttk.LabelFrame(scrollable_frame, text="Startup Configuration", padding=10)
        startup_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Executable
        ttk.Label(startup_frame, text="Executable:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        exe_var = tk.StringVar(value=server_config.get('ExecutablePath',''))
        exe_entry = ttk.Entry(startup_frame, textvariable=exe_var, width=35, font=("Segoe UI", 10))
        exe_entry.grid(row=0, column=1, padx=10, pady=5, sticky=tk.EW)
        
        def browse_exe():
            fp = filedialog.askopenfilename(initialdir=install_dir,
                filetypes=[("Executables","*.exe;*.bat;*.cmd;*.ps1;*.sh"),("All Files","*.*")])
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                exe_var.set(rel)
        ttk.Button(startup_frame, text="Browse", command=browse_exe).grid(row=0, column=2, padx=10, pady=5)

        # Stop command
        ttk.Label(startup_frame, text="Stop Command:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        stop_var = tk.StringVar(value=server_config.get('StopCommand',''))
        ttk.Entry(startup_frame, textvariable=stop_var, width=35, font=("Segoe UI", 10)).grid(row=1, column=1, padx=10, pady=5, sticky=tk.EW)
        
        # Startup arguments section with radio button choice
        args_frame = ttk.LabelFrame(startup_frame, text="Startup Arguments", padding=5)
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
        startup_frame.grid_columnconfigure(1, weight=1)
        args_frame.grid_columnconfigure(0, weight=1)
        args_frame.grid_columnconfigure(1, weight=1)
        manual_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(2, weight=0)
        
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
        toggle_startup_mode()  # Initial toggle
        
        # Preview command line
        preview_frame = ttk.LabelFrame(scrollable_frame, text="Command Preview", padding=10)
        preview_frame.pack(fill=tk.X, pady=(0, 15))
        
        preview_text = tk.Text(preview_frame, height=3, wrap=tk.WORD, background="lightgray", font=("Consolas", 9))
        preview_text.pack(fill=tk.X, padx=5, pady=5)
        
        def update_preview():
            # Update the command preview
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

        # Server Type-Specific Configuration Sections
        server_type = server_config.get('Type', 'Other')
        
        # Initialize server-type-specific variables
        java_path_var = ram_var = jvm_args_var = mc_version_var = None
        auto_update_var = validate_files_var = None
        notes_var = None
        
        # Minecraft-specific configuration section
        if server_type == "Minecraft":
            minecraft_section = ttk.LabelFrame(scrollable_frame, text="🎮 Minecraft Settings", padding=10)
            minecraft_section.pack(fill=tk.X, pady=(15, 0))
            
            # Java Configuration
            java_info_frame = ttk.LabelFrame(minecraft_section, text="Java Configuration", padding=10)
            java_info_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(java_info_frame, text="Java Path:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            java_path_var = tk.StringVar(value=server_config.get("JavaPath", "java"))
            java_entry = ttk.Entry(java_info_frame, textvariable=java_path_var, width=50, font=("Segoe UI", 10))
            java_entry.grid(row=0, column=1, sticky=tk.EW, padx=10, pady=5)
            
            def browse_java():
                file_types = [("Java Executable", "java.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
                java_path = filedialog.askopenfilename(title="Select Java Executable", filetypes=file_types)
                if java_path:
                    java_path_var.set(java_path)
            
            ttk.Button(java_info_frame, text="Browse", command=browse_java).grid(row=0, column=2, padx=5, pady=5)
            
            def auto_detect_java():
                try:
                    from Modules.minecraft import get_recommended_java_for_minecraft
                    version = server_config.get("Version", "")
                    if version:
                        recommended = get_recommended_java_for_minecraft(version)
                        if recommended:
                            java_path_var.set(recommended["path"])
                            messagebox.showinfo("Auto-Detect", f"Found: {recommended['display_name']}")
                        else:
                            messagebox.showwarning("No Java Found", "No compatible Java installation found.")
                    else:
                        messagebox.showwarning("No Version", "Minecraft version not specified in server config.")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to detect Java: {str(e)}")
            
            ttk.Button(java_info_frame, text="Auto-Detect", command=auto_detect_java).grid(row=0, column=3, padx=5, pady=5)
            
            # Memory Settings in same row
            ttk.Label(java_info_frame, text="RAM (MB):", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            ram_var = tk.StringVar(value=str(server_config.get("RAM", 1024)))
            ttk.Entry(java_info_frame, textvariable=ram_var, width=15, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
            
            ttk.Label(java_info_frame, text="JVM Args:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky=tk.W, pady=5, padx=10)
            jvm_args_var = tk.StringVar(value=server_config.get("JVMArgs", ""))
            ttk.Entry(java_info_frame, textvariable=jvm_args_var, width=50, font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=10, pady=5)
            
            # Minecraft Version
            ttk.Label(java_info_frame, text="MC Version:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky=tk.W, pady=5, padx=10)
            mc_version_var = tk.StringVar(value=server_config.get("Version", ""))
            ttk.Entry(java_info_frame, textvariable=mc_version_var, width=30, font=("Segoe UI", 10)).grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)
            
            # Configure grid weights
            java_info_frame.grid_columnconfigure(1, weight=1)
            java_info_frame.grid_columnconfigure(2, weight=0)
            java_info_frame.grid_columnconfigure(3, weight=0)
        
        # Steam-specific configuration section
        elif server_type == "Steam":
            steam_section = ttk.LabelFrame(scrollable_frame, text="🚂 Steam Settings", padding=10)
            steam_section.pack(fill=tk.X, pady=(15, 0))
            
            # Steam Information
            steam_info_frame = ttk.LabelFrame(steam_section, text="Steam Configuration", padding=10)
            steam_info_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Update Settings
            auto_update_var = tk.BooleanVar(value=server_config.get("AutoUpdate", False))
            ttk.Checkbutton(steam_info_frame, text="Enable automatic updates", variable=auto_update_var).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            
            validate_files_var = tk.BooleanVar(value=server_config.get("ValidateFiles", False))
            ttk.Checkbutton(steam_info_frame, text="Validate files on update", variable=validate_files_var).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            
            # Configure grid weights
            steam_info_frame.grid_columnconfigure(1, weight=1)
        
        # Other server type configuration section
        elif server_type == "Other":
            other_section = ttk.LabelFrame(scrollable_frame, text="🔧 Custom Server Settings", padding=10)
            other_section.pack(fill=tk.X, pady=(15, 0))
            
            # Custom Settings
            custom_frame = ttk.LabelFrame(other_section, text="Custom Configuration", padding=10)
            custom_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(custom_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            ttk.Label(custom_frame, text="Other/Custom", font=("Segoe UI", 10)).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
            
            ttk.Label(custom_frame, text="Configuration Notes:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            notes_var = tk.StringVar(value=server_config.get("Notes", ""))
            ttk.Entry(custom_frame, textvariable=notes_var, width=50, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)
            
            # Configure grid weights
            custom_frame.grid_columnconfigure(1, weight=1)        # Allow notes entry to expand
        if name_var.get() != server_name or type_var.get() != current_server_type:
            warning_frame = ttk.Frame(scrollable_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))
            
            warning_label = ttk.Label(warning_frame, 
                                    text="⚠ Warning: Changing server name or type will update configuration files. Ensure server is stopped.",
                                    foreground="orange", font=("Segoe UI", 9, "bold"), wraplength=650)
            warning_label.pack()

        # Button frame at bottom of main dialog
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        def validate_inputs():
            # Validate all input fields
            errors = []
            
            new_name = name_var.get().strip()
            new_type = type_var.get()
            new_appid = appid_var.get().strip()
            exe_path = exe_var.get().strip()
            
            # Validate server name
            if not new_name:
                errors.append("Server name cannot be empty")
            elif new_name != server_name and self.server_manager:
                # Check if new name already exists
                try:
                    existing_config = self.server_manager.get_server_config(new_name)
                    if existing_config:
                        errors.append(f"Server name '{new_name}' already exists")
                except:
                    pass  # Server doesn't exist, which is good
            
            # Validate AppID for Steam servers
            if new_type == 'Steam':
                if not new_appid:
                    errors.append("AppID is required for Steam servers")
                elif not new_appid.isdigit():
                    errors.append("AppID must contain only numbers")
            
            # Validate executable
            if not exe_path:
                errors.append("Executable path is required")
            
            return errors
        
        def save_configuration():
            # Save the server configuration
            errors = validate_inputs()
            if errors:
                messagebox.showerror("Validation Error", "\n".join(errors))
                return
            
            new_name = name_var.get().strip()
            new_type = type_var.get()
            new_appid = appid_var.get().strip()
            exe_path = exe_var.get().strip()
            stop_cmd = stop_var.get().strip()
            mode = startup_mode_var.get()
            
            try:
                # Validate executable path
                exe_abs = exe_path if os.path.isabs(exe_path) else os.path.join(install_dir, exe_path)
                if not os.path.exists(exe_abs):
                    if not messagebox.askyesno("Warning", f"Executable not found: {exe_abs}\nSave anyway?"):
                        return
                
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
                            if not messagebox.askyesno("Warning", f"Config file not found: {config_abs}\nSave anyway?"):
                                return
                        if not config_arg:
                            messagebox.showerror("Validation Error", "Config argument is required when using config file.")
                            return
                    else:
                        messagebox.showerror("Validation Error", "Config file path is required when using config file mode.")
                        return
                
                # Handle name/type/AppID changes first
                name_changed = new_name != server_name
                type_changed = new_type != current_server_type
                current_appid_str = str(server_config.get('appid', server_config.get('AppID', ''))) if server_config else ''
                appid_changed = new_type == 'Steam' and new_appid != current_appid_str
                
                if name_changed or type_changed or appid_changed:
                    # Create updated server config
                    if server_config:
                        updated_config = server_config.copy()
                        updated_config['type'] = new_type
                        if new_type == 'Steam' and new_appid:
                            updated_config['appid'] = int(new_appid)
                            updated_config['AppID'] = int(new_appid)  # Legacy support
                    
                    # Use the rename function if name changed
                    if name_changed:
                        success, message = rename_server_configuration(server_name, new_name, 
                                                                      int(new_appid) if new_type == 'Steam' and new_appid else None, 
                                                                      self.server_manager, self.paths)
                        if not success:
                            messagebox.showerror("Error", f"Failed to rename server: {message}")
                            return
                        
                        # Update server_name for subsequent operations
                        current_server_name = new_name
                    else:
                        # Just update the type/AppID without renaming
                        try:
                            # Read current config file
                            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
                            with open(config_file, 'r', encoding='utf-8') as f:
                                current_config = json.load(f)
                            
                            # Update the config
                            current_config['type'] = new_type
                            if new_type == 'Steam' and new_appid:
                                current_config['appid'] = int(new_appid)
                                current_config['AppID'] = int(new_appid)  # Legacy support
                            
                            # Save updated config
                            with open(config_file, 'w', encoding='utf-8') as f:
                                json.dump(current_config, f, indent=2, ensure_ascii=False)
                            
                            logger.info(f"Updated server type/AppID for '{server_name}'")
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to update server configuration: {str(e)}")
                            return
                        
                        current_server_name = server_name
                else:
                    current_server_name = server_name
                
                # Update startup configuration
                if self.server_manager:
                    success, message = self.server_manager.update_server_config(
                        current_server_name, exe_path, startup_args, stop_cmd, use_config, 
                        config_file_path, config_arg, additional_args
                    )
                else:
                    success = False
                    message = "Server manager not available"
                
                # Handle server-type-specific configurations
                if success and new_type:
                    try:
                        # Read the updated configuration
                        config_file = os.path.join(self.paths["servers"], f"{current_server_name}.json")
                        with open(config_file, 'r', encoding='utf-8') as f:
                            updated_config = json.load(f)
                        
                        # Update server-type-specific settings
                        if new_type == "Minecraft":
                            # Update Minecraft-specific settings if they exist
                            if java_path_var is not None:
                                updated_config['JavaPath'] = java_path_var.get()
                            if ram_var is not None:
                                try:
                                    updated_config['RAM'] = int(ram_var.get())
                                except ValueError:
                                    pass  # Keep existing value if invalid
                            if jvm_args_var is not None:
                                updated_config['JVMArgs'] = jvm_args_var.get()
                            if mc_version_var is not None:
                                updated_config['Version'] = mc_version_var.get()
                        
                        elif new_type == "Steam":
                            # Update Steam-specific settings if they exist
                            # Note: AppID is handled in the main identity section above
                            if auto_update_var is not None:
                                updated_config['AutoUpdate'] = auto_update_var.get()
                            if validate_files_var is not None:
                                updated_config['ValidateFiles'] = validate_files_var.get()
                        
                        elif new_type == "Other":
                            # Update Other server-specific settings if they exist
                            if notes_var is not None:
                                updated_config['Notes'] = notes_var.get()
                        
                        # Save the updated configuration with server-specific settings
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump(updated_config, f, indent=2, ensure_ascii=False)
                        
                        logger.info(f"Updated {new_type}-specific configuration for server '{current_server_name}'")
                    
                    except Exception as e:
                        logger.warning(f"Failed to update server-type-specific settings: {str(e)}")
                        # Don't fail the entire operation for this
                
                if success:
                    # Log the actions
                    actions = []
                    if name_changed:
                        actions.append(f"renamed to '{new_name}'")
                    if type_changed:
                        actions.append(f"changed type to '{new_type}'")
                    if appid_changed:
                        actions.append(f"updated AppID to {new_appid}")
                    
                    if actions:
                        username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                        logger.info(f"USER_ACTION: {username} - Server '{server_name}' {', '.join(actions)}")
                    
                    username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                    logger.info(f"USER_ACTION: {username} updated startup configuration for server '{current_server_name}'")
                    
                    messagebox.showinfo("Success", "Server configuration saved successfully.")
                    dialog.destroy()
                    
                    # Refresh server list to show changes
                    self.update_server_list(force_refresh=True)
                else:
                    messagebox.showerror("Error", f"Failed to save startup configuration: {message}")
                    
            except Exception as e:
                logger.error(f"Error saving server configuration: {str(e)}")
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def test_executable():
            # Test if the executable path exists
            exe_path = exe_var.get().strip()
            if not exe_path:
                messagebox.showwarning("Test", "Please specify an executable path first.")
                return
                
            exe_abs = exe_path if os.path.isabs(exe_path) else os.path.join(install_dir, exe_path)
            if os.path.exists(exe_abs):
                messagebox.showinfo("Test OK", f"Executable found: {exe_abs}")
            else:
                messagebox.showerror("Test Failed", f"Executable not found: {exe_abs}")
        
        # Buttons
        ttk.Button(button_frame, text="Test Path", command=test_executable).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save Configuration", command=save_configuration).pack(side=tk.RIGHT, padx=5)

        # Center dialog relative to parent
        center_window(dialog, 900, 850, self.root)

    def configure_java(self):
        # Open Java configuration dialog for selected server
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
        result = show_java_configuration_dialog(self.root, server_name, server_config, 
                                               self.server_manager, self.server_manager_dir, self.config)
        
        # Refresh server list if Java was updated
        if result['success']:
            self.update_server_list(force_refresh=True)
    
    def show_server_type_configuration(self):
        # Show server configuration dialog based on server type - redirects to unified configure_server
        # Redirect to unified configure_server method
        self.configure_server()
    
    def show_minecraft_server_config(self, server_name, server_config):
        # Show Minecraft-specific configuration dialog
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
                from Modules.minecraft import get_recommended_java_for_minecraft
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
                    from Modules.minecraft import MinecraftServerManager
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
        center_window(dialog, 800, 700, self.root)
    
    def show_steam_server_config(self, server_name, server_config):
        # Show Steam-specific configuration dialog
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
        center_window(dialog, 700, 600, self.root)
    
    def show_other_server_config(self, server_name, server_config):
        # Show generic server configuration dialog
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
            file_types = [("Executable Files", "*.exe;*.bat;*.cmd;*.ps1;*.sh;*.jar"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
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
            center_window(import_dialog, 400, 300, self.root)
            
        except Exception as e:
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to open import dialog: {str(e)}")

    def import_server_from_directory(self):
        # Import an existing server from a directory (legacy method)
        result = import_server_from_directory_dialog(
            self.root, self.server_manager, self.server_manager_dir, 
            self.supported_server_types, 
            update_callback=lambda: self.update_server_list(force_refresh=True)
        )

    def import_server_from_export(self):
        # Import server from exported configuration file
        result = import_server_from_export_dialog(
            self.root, self.paths, self.server_manager_dir,
            update_callback=lambda: self.update_server_list(force_refresh=True)
        )

    def export_server(self):
        # Export server configuration for use on other hosts or clusters
        result = export_server_dialog(self.root, self.server_list, self.paths)

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

            # Silently complete the refresh without showing a dialog

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
                                        server_config['SyncedBy'] = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
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
        try:
            if self.agent_manager is None:
                logger.error("Cluster manager not initialized")
                messagebox.showerror("Error", "Cluster manager not initialized. Cannot access cluster management.")
                return

            # Show the cluster management dialog
            show_agent_management_dialog(self.root, self.agent_manager)

        except Exception as e:
            logger.error(f"Error in cluster management: {str(e)}")
            messagebox.showerror("Error", f"Failed to open cluster management: {str(e)}")

    def check_server_updates(self):
        """Check for updates for the selected server"""
        selected = self.server_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
        
        server_name = self.server_list.item(selected[0])['values'][0]
        
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return
        
        if not self.server_manager:
            messagebox.showerror("Error", "Server manager not available.")
            return
        
        # Get server configuration
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
        
        # Check if it's a Steam server
        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Update checking is only available for Steam servers.")
            return
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, f"Checking Updates - {server_name}")
        
        def update_check_worker():
            try:
                def progress_callback(message):
                    try:
                        if 'console_text' in progress_dialog:
                            progress_dialog['console_text'].insert(tk.END, message + "\n")
                            progress_dialog['console_text'].see(tk.END)
                            progress_dialog['console_text'].update()
                        else:
                            print(message)
                    except:
                        print(message)
                
                if self.update_manager:
                    success, message, has_updates = self.update_manager.check_for_updates(
                        server_name, server_config['AppID'], progress_callback=progress_callback
                    )
                else:
                    success, message, has_updates = False, "Update manager not available", False
                
                if success:
                    status = "Updates available!" if has_updates else "Server is up to date"
                    progress_callback(f"[RESULT] {status}")
                    
                    # Show result in main thread
                    def show_result():
                        if has_updates:
                            result = messagebox.askyesno("Updates Available", 
                                f"Updates are available for {server_name}.\n\nWould you like to update now?")
                            if result:
                                self.update_server_now(server_name, server_config)
                        else:
                            messagebox.showinfo("No Updates", f"{server_name} is up to date.")
                    
                    self.root.after(0, show_result)
                else:
                    progress_callback(f"[ERROR] {message}")
                    self.root.after(0, lambda: messagebox.showerror("Update Check Failed", message))
                
            except Exception as e:
                error_msg = f"Update check failed: {str(e)}"
                logger.error(error_msg)
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        # Start check in background thread
        import threading
        check_thread = threading.Thread(target=update_check_worker, daemon=True)
        check_thread.start()
    
    def update_server(self):
        """Update the selected server"""
        selected = self.server_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
        
        server_name = self.server_list.item(selected[0])['values'][0]
        
        if not self.server_manager:
            messagebox.showerror("Error", "Server manager not available.")
            return
        
        # Get server configuration
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
        
        # Check if it's a Steam server
        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Updates are only available for Steam servers.")
            return
        
        # Confirm update
        result = messagebox.askyesno("Confirm Update", 
            f"Are you sure you want to update {server_name}?\n\n"
            "The server will be stopped during the update process if it's currently running.")
        
        if result:
            self.update_server_now(server_name, server_config)
    
    def update_server_now(self, server_name, server_config):
        # Perform server update with progress dialog
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, f"Updating Server - {server_name}")
        
        def update_worker():
            try:
                def progress_callback(message):
                    try:
                        # Use the console callback function which is more robust
                        if 'console_callback' in progress_dialog:
                            progress_dialog['console_callback'](message)
                        elif 'console_text' in progress_dialog:
                            progress_dialog['console_text'].config(state=tk.NORMAL)
                            progress_dialog['console_text'].insert(tk.END, message + "\n")
                            progress_dialog['console_text'].see(tk.END)
                            progress_dialog['console_text'].config(state=tk.DISABLED)
                            progress_dialog['console_text'].update()
                        else:
                            print(message)  # Fallback
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")  # Fallback with error info
                
                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual updates
                    success, message = self.update_manager.update_server(
                        server_name, server_config, progress_callback=progress_callback, scheduled=False
                    )
                else:
                    success, message = False, "Update manager not available"
                
                if success:
                    progress_callback(f"[SUCCESS] {message}")
                    self.root.after(0, lambda: messagebox.showinfo("Update Complete", 
                        f"{server_name} has been updated successfully!"))
                    # Refresh server list
                    self.root.after(0, self.update_server_list)
                else:
                    progress_callback(f"[ERROR] {message}")
                    self.root.after(0, lambda: messagebox.showerror("Update Failed", message))
                
            except Exception as e:
                error_msg = f"Server update failed: {str(e)}"
                logger.error(error_msg)
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        # Start update in background thread
        import threading
        update_thread = threading.Thread(target=update_worker, daemon=True)
        update_thread.start()
    
    def show_schedule_manager(self):
        """Show unified schedule manager"""
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()
    
    def show_server_schedule(self):
        """Show schedule manager for the selected server"""
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()
    
    def update_all_servers(self):
        """Update all Steam servers"""
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Confirm update
        result = messagebox.askyesno("Confirm Update All", 
            "Are you sure you want to update all Steam servers?\n\n"
            "This will stop all running Steam servers during the update process.")
        
        if not result:
            return
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, "Updating All Steam Servers")
        
        def update_all_worker():
            try:
                def progress_callback(message):
                    try:
                        # Use the console callback function which is more robust
                        if 'console_callback' in progress_dialog:
                            progress_dialog['console_callback'](message)
                        elif 'console_text' in progress_dialog:
                            progress_dialog['console_text'].config(state=tk.NORMAL)
                            progress_dialog['console_text'].insert(tk.END, message + "\n")
                            progress_dialog['console_text'].see(tk.END)
                            progress_dialog['console_text'].config(state=tk.DISABLED)
                            progress_dialog['console_text'].update()
                        else:
                            print(message)  # Fallback
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")  # Fallback with error info
                
                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual batch updates
                    results = self.update_manager.update_all_steam_servers(progress_callback=progress_callback, scheduled=False)
                else:
                    results = {"error": (False, "Update manager not available")}
                
                # Count successes and failures
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                
                progress_callback(f"\n[SUMMARY] Updates complete: {successes} successful, {failures} failed")
                
                # Show detailed results
                def show_results():
                    if failures > 0:
                        failed_servers = [name for name, (success, _) in results.items() if not success]
                        messagebox.showwarning("Some Updates Failed", 
                            f"Update completed with some failures.\n\n"
                            f"Successful: {successes}\nFailed: {failures}\n\n"
                            f"Failed servers: {', '.join(failed_servers)}")
                    else:
                        messagebox.showinfo("Updates Complete", 
                            f"All Steam servers updated successfully!\n\n"
                            f"Updated {successes} servers.")
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch update failed: {str(e)}"
                logger.error(error_msg)
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        # Start update in background thread
        import threading
        update_thread = threading.Thread(target=update_all_worker, daemon=True)
        update_thread.start()

    def restart_all_servers(self):
        # Restart all servers
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Get list of all servers
        all_servers = []
        if self.server_manager:
            servers = self.server_manager.get_all_servers()
            all_servers = list(servers.keys())
        
        if not all_servers:
            messagebox.showinfo("No Servers", "No servers found to restart.")
            return
        
        # Confirm action
        result = messagebox.askyesno("Confirm Batch Restart", 
            f"Restart all {len(all_servers)} servers?\n\n"
            f"Servers to restart: {', '.join(all_servers)}")
        
        if not result:
            return
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, "Restarting All Servers")
        
        def restart_all_worker():
            try:
                def progress_callback(message):
                    try:
                        # Use the console callback function which is more robust
                        if 'console_callback' in progress_dialog:
                            progress_dialog['console_callback'](message)
                        elif 'console_text' in progress_dialog:
                            progress_dialog['console_text'].config(state=tk.NORMAL)
                            progress_dialog['console_text'].insert(tk.END, message + "\n")
                            progress_dialog['console_text'].see(tk.END)
                            progress_dialog['console_text'].config(state=tk.DISABLED)
                            progress_dialog['console_text'].update()
                        else:
                            print(message)  # Fallback
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")  # Fallback with error info
                
                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual batch restarts
                    results = self.update_manager.restart_all_servers(progress_callback=progress_callback, scheduled=False)
                else:
                    results = {"error": (False, "Update manager not available")}
                
                # Count successes and failures
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                
                progress_callback(f"\n[SUMMARY] Restarts complete: {successes} successful, {failures} failed")
                
                # Show detailed results
                def show_results():
                    if failures > 0:
                        failed_servers = [name for name, (success, _) in results.items() if not success]
                        messagebox.showwarning("Some Restarts Failed", 
                            f"Restart completed with some failures.\n\n"
                            f"Successful: {successes}\nFailed: {failures}\n\n"
                            f"Failed servers: {', '.join(failed_servers)}")
                    else:
                        messagebox.showinfo("Restarts Complete", 
                            f"All servers restarted successfully!\n\n"
                            f"Restarted {successes} servers.")
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch restart failed: {str(e)}"
                logger.error(error_msg)
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        # Start restart in background thread
        import threading
        restart_thread = threading.Thread(target=restart_all_worker, daemon=True)
        restart_thread.start()

    def show_console_manager(self):
        """Show console manager dialog with list of active consoles"""
        try:
            if not self.console_manager:
                messagebox.showinfo("Console Manager", "Console manager not available.")
                return

            # Use the built-in console management window
            self.console_manager.show_console_manager_window(self.root)

        except Exception as e:
            log_exception(e, "Error showing console manager")
            messagebox.showerror("Console Manager Error", f"Failed to show console manager:\n{str(e)}")

    def batch_update_server_types(self):
        """Batch update all server types using database-based detection"""
        try:
            # Show confirmation dialog first
            response = messagebox.askyesno(
                "Update Server Types",
                "This will analyze all server configurations and update their types based on:\n"
                "• Steam AppIDs in the database\n"
                "• Directory contents and files\n"
                "• Executable paths\n\n"
                "This operation is safe and will backup the original type information.\n\n"
                "Do you want to continue?"
            )
            
            if not response:
                return
            
            # Show progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Updating Server Types")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            center_window(progress_dialog, 400, 150, self.root)
            
            # Progress frame
            progress_frame = ttk.Frame(progress_dialog, padding=20)
            progress_frame.pack(fill=tk.BOTH, expand=True)
            
            status_var = tk.StringVar(value="Analyzing server configurations...")
            status_label = ttk.Label(progress_frame, textvariable=status_var)
            status_label.pack(pady=(0, 10))
            
            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=(0, 20))
            progress_bar.start(10)
            
            # Run the update in a separate thread to avoid freezing UI
            def run_update():
                try:
                    # Perform batch update
                    updated_count, updated_servers = batch_update_server_types(self.paths)
                    
                    # Update UI in main thread
                    self.root.after(0, update_complete, updated_count, updated_servers)
                    
                except Exception as e:
                    # Handle error in main thread
                    self.root.after(0, update_error, str(e))
            
            def update_complete(count, servers):
                progress_bar.stop()
                progress_dialog.destroy()
                
                if count == 0:
                    messagebox.showinfo(
                        "Update Complete",
                        "No server type updates were needed. All servers are already correctly classified."
                    )
                else:
                    # Show results dialog
                    result_msg = f"Successfully updated {count} server(s):\n\n"
                    for server in servers[:10]:  # Show first 10 servers
                        result_msg += f"• {server['name']}: {server['old_type']} → {server['new_type']}\n"
                    
                    if len(servers) > 10:
                        result_msg += f"... and {len(servers) - 10} more\n"
                    
                    result_msg += f"\nPlease refresh the server list to see the changes."
                    
                    messagebox.showinfo("Update Complete", result_msg)
                
                # Refresh the server list
                self.update_server_list(force_refresh=True)
            
            def update_error(error_msg):
                progress_bar.stop()
                progress_dialog.destroy()
                messagebox.showerror("Update Error", f"Failed to update server types:\n{error_msg}")
            
            # Start the update thread
            import threading
            update_thread = threading.Thread(target=run_update, daemon=True)
            update_thread.start()
            
        except Exception as e:
            log_exception(e, "Error in batch update server types")
            messagebox.showerror("Update Error", f"Failed to update server types:\n{str(e)}")

    def show_help(self):
        """Show help dialog using the documentation module"""
        show_help_dialog(self.root, logger)

    def show_about(self):
        """Show about dialog using the documentation module"""
        show_about_dialog(self.root, logger)

def main():
    """Parse command line arguments and create/run dashboard"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Server Manager Dashboard')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    # Create and run dashboard
    dashboard = ServerManagerDashboard(debug_mode=args.debug)
    dashboard.run()

main()
