# -*- coding: utf-8 -*-
# Main dashboard GUI
# - Tkinter-based server management interface
import os
import sys
import datetime as _dt

# Early crash logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.server_logging import early_crash_log

early_crash_log("Dashboard", f"Module loading - Python {sys.version}")

# DPI awareness on Windows BEFORE tkinter import
# Prevents scaling issues with UI elements
if sys.platform == 'win32':
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            early_crash_log("Dashboard", "DPI awareness set to PROCESS_SYSTEM_DPI_AWARE")
        except AttributeError:
            ctypes.windll.user32.SetProcessDPIAware()
            early_crash_log("Dashboard", "DPI awareness set using SetProcessDPIAware")
        except Exception as e:
            early_crash_log("Dashboard", f"DPI awareness failed: {e}")
    except Exception as e:
        early_crash_log("Dashboard", f"DPI setup failed: {e}")

try:
    import argparse
    import subprocess
    import threading
    import json
    import time
    import datetime

    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
    early_crash_log("Dashboard", "Standard library imports successful")

    from Modules.Database.user_database import initialize_user_manager
    early_crash_log("Dashboard", "User database import successful")

    from Modules.server_manager import ServerManager
    from Modules.minecraft import MinecraftServerManager
    early_crash_log("Dashboard", "Server management imports successful")

    from Modules.server_logging import (
        get_dashboard_logger, configure_dashboard_logging,
        log_dashboard_event
    )
    early_crash_log("Dashboard", "All imports successful")

except Exception as e:
    import traceback
    early_crash_log("Dashboard", f"FATAL IMPORT ERROR: {e}")
    early_crash_log("Dashboard", f"Traceback: {traceback.format_exc()}")
    raise

# Import scheduling components
from Modules.scheduler import SchedulerManager

# Import update management
from Modules.server_updates import ServerUpdateManager

# Import documentation dialogs
from Modules.documentation import show_help_dialog, show_about_dialog

# Import core infrastructure
from Modules.common import ServerManagerModule, initialise_registry_values

# Dashboard utility functions
from Host.dashboard_functions import (
    load_dashboard_config, update_webserver_status, update_system_info_threaded, centre_window,
    create_server_type_selection_dialog, load_appid_scanner_list,
    load_minecraft_scanner_list, get_minecraft_versions_from_database,
    get_steam_credentials,perform_server_installation, import_server_from_directory_dialog, import_server_from_export_dialog,
    export_server_dialog, create_progress_dialog_with_console, rename_server_configuration, show_java_configuration_dialog, batch_update_server_types,
    update_server_status_in_treeview, open_directory_in_explorer,
    get_current_server_list, get_current_subhost,
    reattach_to_running_servers, update_server_list_for_subhost,
    refresh_all_subhost_servers, refresh_current_subhost_servers, refresh_subhost_servers,
    create_remote_host_connection_dialog, RemoteHostManager,
    load_categories
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
from Host.admin_dashboard import (admin_login, admin_login_with_root)

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
        
        # Load Minecraft server info from database
        self.minecraft_servers, self.minecraft_metadata = load_minecraft_scanner_list(self.server_manager_dir)

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
            # UI state
            "systemInfoVisible": self.config.get("ui", {}).get("systemInfoVisible", True),
            # Runtime vars
            "formDisplayed": self.config.get("runtime", {}).get("formDisplayed", False),
            "verificationInProgress": self.config.get("runtime", {}).get("verificationInProgress", False),
            "webserverStatus": self.config.get("runtime", {}).get("webserverStatus", "Disconnected"),
        }
        
        # Init paths from registry
        success, self.steam_cmd_path, webserver_port, self.registry_values = initialise_registry_values(self.registry_path)
        if success:
            self.variables["defaultSteamPath"] = self.steam_cmd_path or ""
            self.variables["webserverPort"] = webserver_port
            if self.steam_cmd_path:
                self.variables["defaultSteamInstallDir"] = self.steam_cmd_path
            else:
                self.variables["defaultSteamInstallDir"] = ""
            if self.server_manager_dir:
                self.variables["defaultServerManagerInstallDir"] = os.path.join(self.server_manager_dir, "servers")
            else:
                self.variables["defaultServerManagerInstallDir"] = ""
        else:
            logger.error("Registry init failed")
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
            logger.debug("Server manager initialized")
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
            logger.debug("Server console manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize server console manager: {e}")
            self.console_manager = None
            
        # Configure dashboard logging after paths are initialized
        configure_dashboard_logging(self.debug_mode, self.config)
        
        # Create root window (temporarily hidden for login)
        self.root = tk.Tk()
        self.root.resizable(True, True)
        
        # Calculate DPI scaling factor for proper UI sizing
        self._init_dpi_scaling()
        
        # On Windows, when launched from trayicon (detached process), ensure proper window handling
        if os.name == 'nt' and '--debug' not in sys.argv:
            try:
                # Force the window to be properly initialized
                self.root.update_idletasks()
                # Don't withdraw initially - let the login dialog handle visibility
            except Exception as e:
                logger.warning(f"Window initialization issue (likely from trayicon launch): {e}")
                # Continue anyway
        # Pass our existing root window to avoid multiple Tkinter root windows
        try:            
            # Use the version that accepts existing root to avoid conflicts
            user = admin_login_with_root(self.root, self.user_manager)
                
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
        
        # Set dynamic minimum size based on screen size and DPI scaling
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Calculate DPI-aware minimum sizes
        base_min_width = self.scale_value(800)
        base_min_height = self.scale_value(600)
        
        min_width = min(base_min_width, int(screen_width * 0.6))  # Max 60% of screen width
        min_height = min(base_min_height, int(screen_height * 0.6))  # Max 60% of screen height
        self.root.minsize(min_width, min_height)
        
        # Ensure the main window is properly visible
        self.root.deiconify()
        logger.debug("Dashboard window deiconified")
        
        # Bring window to front and give it focus
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))
        logger.debug("Dashboard window brought to front")
        
        # Centre the main window on screen with adaptive sizing
        # Use 85% of screen on large screens, but ensure minimum usable size
        width = max(min_width, int(screen_width * 0.85))
        height = max(min_height, int(screen_height * 0.85))
        # Cap at 90% to leave some space for taskbar/other UI elements
        width = min(width, int(screen_width * 0.9))
        height = min(height, int(screen_height * 0.9))
        centre_window(self.root, width, height)
        logger.debug("Dashboard window centered")
        
        self.setup_ui()
        
        # Initial server list refresh to populate the UI
        try:
            self.update_server_list(force_refresh=True)
            logger.debug("Initial server list refresh completed")
        except Exception as e:
            logger.error(f"Error during initial server list refresh: {e}")
        
        # Write PID file
        self.write_pid_file("dashboard", os.getpid())
        
        # Initialize timer manager (now using SchedulerManager)
        self.timer_manager = SchedulerManager(self)
        
        # Set agent manager for database syncing
        if hasattr(self, 'agent_manager') and self.agent_manager:
            self.timer_manager.set_agent_manager(self.agent_manager)
        
        # Initialize server update manager
        try:
            self.update_manager = ServerUpdateManager(self.server_manager_dir, self.config)
            self.update_manager.set_server_manager(self.server_manager)
            self.update_manager.set_steam_cmd_path(self.steam_cmd_path)
            self.timer_manager.set_update_manager(self.update_manager)
            logger.debug("Server update manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize server update manager: {str(e)}")
            self.update_manager = None
        
        # Initialize cluster manager
        try:
            # Use database-backed cluster management (no longer using JSON)
            agents_config_path = None  # Migration already done
            self.agent_manager = AgentManager(agents_config_path)
            logger.debug("Cluster manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize cluster manager: {str(e)}")
            self.agent_manager = None
        
        # Initialize system info and timers - defer UI updates until after mainloop starts
        # Note: Heavy operations like server list refresh and system info collection are deferred
        self.timer_manager.start_timers()
        
        # Detect and reattach to running server processes (deferred to avoid blocking)
        # This will be called after mainloop starts
        
        # Get supported server types from server manager
        if self.server_manager:
            self.supported_server_types = self.server_manager.get_supported_server_types()
        else:
            self.supported_server_types = ["Steam", "Minecraft", "Other"]

    def _init_dpi_scaling(self):
        """Initialize DPI scaling factors for proper UI sizing across different displays"""
        try:
            # Get DPI from the root window
            dpi = self.root.winfo_fpixels('1i')  # Pixels per inch
            
            # Standard DPI is 96 on Windows
            self.dpi_scale = dpi / 96.0
            
            # Clamp scaling factor to reasonable range (avoid extreme values)
            self.dpi_scale = max(1.0, min(self.dpi_scale, 3.0))
            
            logger.debug(f"DPI scaling initialized: DPI={dpi}, scale_factor={self.dpi_scale:.2f}")
        except Exception as e:
            logger.warning(f"Could not calculate DPI scaling: {e}")
            self.dpi_scale = 1.0
    
    def scale_value(self, value):
        """Scale a value according to the current DPI scaling factor"""
        return int(value * getattr(self, 'dpi_scale', 1.0))
    
    def _reattach_to_running_servers(self):
        # Detect and reattach to running server processes
        reattach_to_running_servers(self.server_manager, self.console_manager, logger)

    def setup_menu_bar(self):
        # Setup the menu bar
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)
        
        # File Menu
        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings", command=self.show_settings_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        
        # Help Menu
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="Help", command=self.show_help)

    def setup_ui(self):
        # Create and configure the main dashboard user interface
        # Setup the menu bar first
        self.setup_menu_bar()
        
        # Create top frame for action buttons
        self.top_frame = ttk.Frame(self.root)
        self.top_frame.pack(fill=tk.X, padx=10, pady=(8, 5))
        
        # Use DPI-aware button sizing for proper scaling
        button_width = self.scale_value(14)
        button_spacing = self.scale_value(4)
        
        # Action buttons on the left: Add Server, Stop Server, Import Server, Update All, Schedules, Consoles, Cluster
        self.add_server_btn = ttk.Button(self.top_frame, text="Add Server", 
                                        command=self.add_server, width=button_width)
        self.add_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.stop_server_btn = ttk.Button(self.top_frame, text="Stop Server", 
                                         command=self.stop_server, width=button_width)
        self.stop_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.import_server_btn = ttk.Button(self.top_frame, text="Import Server", 
                                           command=self.import_server, width=button_width)
        self.import_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.update_all_button = ttk.Button(self.top_frame, text="Update All", 
                                          command=self.update_all_servers, width=button_width)
        self.update_all_button.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.schedules_button = ttk.Button(self.top_frame, text="Schedules", 
                                         command=self.show_schedule_manager, width=button_width)
        self.schedules_button.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.console_button = ttk.Button(self.top_frame, text="Consoles", 
                                       command=self.show_console_manager, width=button_width)
        self.console_button.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        self.cluster_button = ttk.Button(self.top_frame, text="Cluster", 
                                        command=self.add_agent, width=button_width)
        self.cluster_button.pack(side=tk.LEFT, padx=(0, button_spacing))
        
        # Main container - reduced padding for tighter layout
        self.container_frame = ttk.Frame(self.root, padding=(10, 5, 10, 10))
        self.container_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure container frame for proper resizing with grid
        self.container_frame.columnconfigure(0, weight=1)
        self.container_frame.rowconfigure(0, weight=1)  # Main pane takes all available space
        
        # Main layout - servers list and system info
        self.main_pane = ttk.PanedWindow(self.container_frame, orient=tk.HORIZONTAL)
        self.main_pane.grid(row=0, column=0, sticky="nsew")
        
        # Server tabs frame (left side) - Tabbed interface for subhosts
        self.servers_frame = ttk.LabelFrame(self.main_pane, text="", padding=10)
        
        # Header frame for "Host Servers" title and Remote Host button
        self.servers_header_frame = ttk.Frame(self.servers_frame)
        self.servers_header_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(self.servers_header_frame, text="Host Servers", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        
        # Remote Host button on far right of header
        self.remote_host_button = ttk.Button(self.servers_header_frame, text="Remote Host", 
                                           command=self.connect_remote_host, width=12)
        self.remote_host_button.pack(side=tk.RIGHT)
        
        # Adjust pane weights based on screen size for better responsiveness
        screen_width = self.root.winfo_screenwidth()
        if screen_width < 1366:  # Smaller screens
            server_weight = 75  # Give more space to servers on small screens
            system_weight = 25
        else:  # Larger screens
            server_weight = 70
            system_weight = 30
        
        self.main_pane.add(self.servers_frame, weight=server_weight)
        
        # Configure servers frame for proper resizing
        self.servers_frame.columnconfigure(0, weight=1)
        self.servers_frame.rowconfigure(0, weight=0)
        self.servers_frame.rowconfigure(1, weight=1)
        
        # Create tab navigation frame
        self.tab_nav_frame = ttk.Frame(self.servers_frame)
        self.tab_nav_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Left arrow button for tab navigation
        self.left_arrow = ttk.Button(self.tab_nav_frame, text="◀", width=3, command=self.scroll_tabs_left)
        self.left_arrow.pack(side=tk.LEFT, padx=(0, 2))
        self.left_arrow.config(state=tk.DISABLED)
        
        # Right arrow button for tab navigation
        self.right_arrow = ttk.Button(self.tab_nav_frame, text="▶", width=3, command=self.scroll_tabs_right)
        self.right_arrow.pack(side=tk.RIGHT, padx=(2, 0))
        self.right_arrow.config(state=tk.DISABLED)
        
        # Category control buttons
        self.category_frame = ttk.Frame(self.tab_nav_frame)
        self.category_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.expand_all_btn = ttk.Button(self.category_frame, text="Expand All", width=10, command=self.expand_all_categories)
        self.expand_all_btn.pack(side=tk.LEFT, padx=(0, 2))
        
        self.collapse_all_btn = ttk.Button(self.category_frame, text="Collapse All", width=10, command=self.collapse_all_categories)
        self.collapse_all_btn.pack(side=tk.LEFT)
        
        # Tab notebook
        self.server_notebook = ttk.Notebook(self.servers_frame)
        self.server_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Dictionary to store server lists for each tab
        self.server_lists = {}
        self.tab_frames = {}
        
        # Initialize with local host tab
        self.add_subhost_tab("Local Host", is_local=True)
        
        # Load cluster nodes and create tabs for subhosts
        self.load_subhost_tabs()
        
        # Setup right-click context menu for server lists (will be bound to each tab's treeview)
        self.server_context_menu = tk.Menu(self.root, tearoff=0)
        self.server_context_menu.add_command(label="Add Server", command=self.add_server)
        self.server_context_menu.add_command(label="Refresh", command=self.refresh_all)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Create Category", command=self.create_category)
        self.server_context_menu.add_command(label="Rename Category", command=self.rename_category)
        self.server_context_menu.add_command(label="Delete Category", command=self.delete_category)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Start Server", command=self.start_server)
        self.server_context_menu.add_command(label="Stop Server", command=self.stop_server)
        self.server_context_menu.add_command(label="Kill Process", command=self.kill_server_process)
        self.server_context_menu.add_command(label="Restart Server", command=self.restart_server)
        self.server_context_menu.add_command(label="View Process Details", command=self.view_process_details)
        self.server_context_menu.add_command(label="Show Console", command=self.show_server_console)
        self.server_context_menu.add_command(label="Configure Server", command=self.configure_server)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Check for Updates", command=self.check_server_updates)
        self.server_context_menu.add_command(label="Update Server", command=self.update_server)
        self.server_context_menu.add_command(label="Schedule", command=self.show_server_schedule)
        self.server_context_menu.add_command(label="Console Manager", command=self.show_console_manager)
        self.server_context_menu.add_separator()
        self.server_context_menu.add_command(label="Export Server", command=self.export_server)
        self.server_context_menu.add_command(label="Open Folder Directory", command=self.open_server_directory)
        self.server_context_menu.add_command(label="Remove Server", command=self.remove_server)
        
        # Collapse toggle frame (vertical bar between panes with centered arrow)
        self.system_info_visible = self.variables.get("systemInfoVisible", True)
        self.collapse_frame = ttk.Frame(self.main_pane, width=20)
        self.main_pane.add(self.collapse_frame, weight=0)
        
        # Configure collapse frame to center the button vertically
        self.collapse_frame.columnconfigure(0, weight=1)
        self.collapse_frame.rowconfigure(0, weight=1)
        self.collapse_frame.rowconfigure(1, weight=0)
        self.collapse_frame.rowconfigure(2, weight=1)
        
        # Collapse/Expand toggle button (centered vertically with horizontal arrows)
        self.system_toggle_btn = ttk.Button(
            self.collapse_frame,
            text="◀" if self.system_info_visible else "▶",
            width=2,
            command=self.toggle_system_info
        )
        self.system_toggle_btn.grid(row=1, column=0, pady=5)
        
        # System info frame (right side)
        self.system_frame = ttk.LabelFrame(self.main_pane, text="System Information", padding=10)
        if self.system_info_visible:
            self.main_pane.add(self.system_frame, weight=system_weight)
        
        # Configure system frame for proper resizing
        self.system_frame.columnconfigure(0, weight=1)
        self.system_frame.rowconfigure(0, weight=0)  # Header
        self.system_frame.rowconfigure(1, weight=1)  # Metrics
        
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
        self.metrics_frame = ttk.Frame(self.system_frame, padding=(0, 10, 0, 0))
        self.metrics_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid layout with proper weights for uniform sizing
        for i in range(2):
            self.metrics_frame.columnconfigure(i, weight=1, uniform="metric_col")
        for i in range(3):
            self.metrics_frame.rowconfigure(i, weight=1, uniform="metric_row")
        
        # Create metric panels with uniform sizing
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
            # Create frame with responsive sizing - use DPI-aware padding
            scaled_padding = self.scale_value(8)
            frame = ttk.LabelFrame(self.metrics_frame, text=f"{metric['icon']} {metric['title']}", padding=scaled_padding)
            frame.grid(row=metric["row"], column=metric["col"], padx=3, pady=3, sticky="nsew")
            
            # Let the frame size naturally based on content
            # Don't use fixed heights - this was causing the button bar to be pushed off screen
            # The grid with uniform sizing will handle proportional sizing
            
            # Create value label with DPI-aware wrapping
            # Calculate wrap width based on screen size and DPI
            screen_width = self.root.winfo_screenwidth()
            base_wrap = 150 if metric["name"] == "gpu" else 120
            
            # Scale the wrap width based on screen size ratio and DPI
            screen_scale = screen_width / 1920.0  # Normalize to 1080p base
            wrap_width = int(base_wrap * max(0.7, min(1.5, screen_scale)) * self.dpi_scale)
            
            # Use DPI-aware font size
            font_size = self.scale_value(9)
            value = ttk.Label(frame, text="Loading...", font=("Segoe UI", font_size), wraplength=wrap_width, justify=tk.LEFT)
            value.pack(anchor=tk.W, fill=tk.BOTH, expand=True)
            
            self.metric_labels[metric["name"]] = value
    
    # ===== TAB MANAGEMENT METHODS =====
    
    def add_subhost_tab(self, subhost_name, is_local=False):
        # Add a new tab for a subhost
        # Create tab frame
        tab_frame = ttk.Frame(self.server_notebook)
        self.tab_frames[subhost_name] = tab_frame
        
        # Configure tab frame for proper resizing
        tab_frame.columnconfigure(0, weight=1)
        tab_frame.rowconfigure(0, weight=1)
        
        # Create server list for this tab
        columns = ("name", "status", "pid", "cpu", "memory", "uptime")
        server_list = ttk.Treeview(tab_frame, columns=columns, show="tree headings")
        
        # Column headings
        server_list.heading("#0", text="Categories")
        server_list.heading("name", text="Server Name")
        server_list.heading("status", text="Status")
        server_list.heading("pid", text="PID")
        server_list.heading("cpu", text="CPU Usage")
        server_list.heading("memory", text="Memory Usage")
        server_list.heading("uptime", text="Uptime")

        # Column widths - adjust based on screen size
        screen_width = self.root.winfo_screenwidth()
        if screen_width < 1366:  # Smaller screens
            name_width, name_min = 150, 120
            status_width, status_min = 80, 60
            pid_width, pid_min = 60, 50
            cpu_width, cpu_min = 80, 60
            memory_width, memory_min = 100, 80
            uptime_width, uptime_min = 120, 100
        else:  # Larger screens
            name_width, name_min = 200, 150
            status_width, status_min = 100, 80
            pid_width, pid_min = 80, 60
            cpu_width, cpu_min = 100, 80
            memory_width, memory_min = 120, 100
            uptime_width, uptime_min = 160, 120
        
        server_list.column("#0", width=200, minwidth=150, anchor=tk.W)
        server_list.column("name", width=name_width, minwidth=name_min, anchor=tk.W)
        server_list.column("status", width=status_width, minwidth=status_min, anchor=tk.CENTER)
        server_list.column("pid", width=pid_width, minwidth=pid_min, anchor=tk.CENTER)
        server_list.column("cpu", width=cpu_width, minwidth=cpu_min, anchor=tk.CENTER)
        server_list.column("memory", width=memory_width, minwidth=memory_min, anchor=tk.CENTER)
        server_list.column("uptime", width=uptime_width, minwidth=uptime_min, anchor=tk.CENTER)
        
        # Add scrollbar
        server_scroll = ttk.Scrollbar(tab_frame, orient=tk.VERTICAL, command=server_list.yview)
        server_list.configure(yscrollcommand=server_scroll.set)
        
        server_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        server_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind events
        server_list.bind("<Button-3>", self.show_server_context_menu)
        server_list.bind("<Button-1>", self.on_server_list_click)
        server_list.bind("<Double-1>", self.on_server_double_click)
        
        # Bind drag-and-drop events for category management
        server_list.bind("<ButtonPress-1>", self.on_drag_start)
        server_list.bind("<B1-Motion>", self.on_drag_motion)
        server_list.bind("<ButtonRelease-1>", self.on_drag_release)
        
        # Store reference
        self.server_lists[subhost_name] = server_list
        
        # Add tab to notebook
        display_name = f"🏠 {subhost_name}" if is_local else f"🌐 {subhost_name}"
        self.server_notebook.add(tab_frame, text=display_name)
        
        # Update navigation arrows
        self.update_tab_navigation()
        
        logger.info(f"Added tab for subhost: {subhost_name}")
    
    def remove_subhost_tab(self, subhost_name):
        # Remove a tab for a subhost
        if subhost_name in self.tab_frames:
            # Remove from notebook
            tab_index = self.server_notebook.index(self.tab_frames[subhost_name])
            self.server_notebook.forget(tab_index)
            
            # Clean up references
            del self.server_lists[subhost_name]
            del self.tab_frames[subhost_name]
            
            # Update navigation arrows
            self.update_tab_navigation()
            
            logger.info(f"Removed tab for subhost: {subhost_name}")
    
    def load_subhost_tabs(self):
        # Load tabs for all available subhosts
        try:
            # Import agent manager
            from Modules.agents import AgentManager
            agent_manager = AgentManager()
            
            # Add tabs for each cluster node
            for node_name, node in agent_manager.nodes.items():
                if node_name != "Local Host":  # Skip local host as it's already added
                    self.add_subhost_tab(node_name, is_local=False)
            
            logger.info(f"Loaded {len(agent_manager.nodes)} subhost tabs")
            
        except Exception as e:
            logger.warning(f"Could not load subhost tabs: {e}")
    
    def update_tab_navigation(self):
        # Update the state of navigation arrows based on tab count and visibility
        tab_count = len(self.server_notebook.tabs())
        
        if tab_count <= 5:  # If 5 or fewer tabs, no need for navigation
            self.left_arrow.config(state=tk.DISABLED)
            self.right_arrow.config(state=tk.DISABLED)
        else:
            # Enable navigation arrows
            self.left_arrow.config(state=tk.NORMAL)
            self.right_arrow.config(state=tk.NORMAL)
    
    def scroll_tabs_left(self):
        # Scroll tabs to the left
        current_tab = self.server_notebook.index(self.server_notebook.select())
        if current_tab > 0:
            self.server_notebook.select(current_tab - 1)
    
    def scroll_tabs_right(self):
        # Scroll tabs to the right
        current_tab = self.server_notebook.index(self.server_notebook.select())
        if current_tab < len(self.server_notebook.tabs()) - 1:
            self.server_notebook.select(current_tab + 1)
    
    def expand_all_categories(self):
        # Expand all categories in the current server list
        # Debounce check to prevent rapid clicking issues
        if hasattr(self, '_expanding_categories') and self._expanding_categories:
            return
        self._expanding_categories = True
        
        try:
            current_list = self.get_current_server_list()
            if not current_list:
                return
            
            # Disable button during operation to prevent rapid clicks
            if hasattr(self, 'expand_all_btn'):
                self.expand_all_btn.config(state=tk.DISABLED)
            
            # Find all category items (items with no server name)
            for item in current_list.get_children():
                try:
                    if current_list.exists(item):
                        item_values = current_list.item(item)['values']
                        if item_values and not item_values[1]:  # No server name = category
                            current_list.item(item, open=True)
                except tk.TclError:
                    # Item may have been deleted during iteration
                    continue
                    
        except Exception as e:
            logger.error(f"Error expanding categories: {str(e)}")
        finally:
            self._expanding_categories = False
            # Re-enable button after a short delay
            if hasattr(self, 'expand_all_btn'):
                self.root.after(100, lambda: self.expand_all_btn.config(state=tk.NORMAL))
    
    def collapse_all_categories(self):
        # Collapse all categories in the current server list
        # Debounce check to prevent rapid clicking issues
        if hasattr(self, '_collapsing_categories') and self._collapsing_categories:
            return
        self._collapsing_categories = True
        
        try:
            current_list = self.get_current_server_list()
            if not current_list:
                return
            
            # Disable button during operation to prevent rapid clicks
            if hasattr(self, 'collapse_all_btn'):
                self.collapse_all_btn.config(state=tk.DISABLED)
            
            # Find all category items (items with no server name)
            for item in current_list.get_children():
                try:
                    if current_list.exists(item):
                        item_values = current_list.item(item)['values']
                        if item_values and not item_values[1]:  # No server name = category
                            current_list.item(item, open=False)
                except tk.TclError:
                    # Item may have been deleted during iteration
                    continue
                    
        except Exception as e:
            logger.error(f"Error collapsing categories: {str(e)}")
        finally:
            self._collapsing_categories = False
            # Re-enable button after a short delay
            if hasattr(self, 'collapse_all_btn'):
                self.root.after(100, lambda: self.collapse_all_btn.config(state=tk.NORMAL))
    
    def get_current_server_list(self):
        # Get the server list for the currently active tab
        return get_current_server_list(self)
    
    def get_current_subhost(self):
        # Get the name of the currently active subhost
        return get_current_subhost(self)
    
    def update_server_list_for_subhost(self, subhost_name, servers_data):
        # Update the server list for a specific subhost
        update_server_list_for_subhost(subhost_name, servers_data, self.server_lists, self.server_manager_dir, logger)
    
    def refresh_all_subhost_servers(self):
        # Refresh servers for all subhost tabs
        refresh_all_subhost_servers(self.server_lists, self.server_manager, self.server_manager_dir, logger)
    
    def refresh_current_subhost_servers(self):
        # Refresh servers for the currently active subhost tab
        refresh_current_subhost_servers(self.get_current_subhost, self.server_manager, self.server_lists, self.server_manager_dir, logger)
    
    def refresh_subhost_servers(self, subhost_name):
        # Refresh servers for a specific subhost
        refresh_subhost_servers(subhost_name, self.server_manager, self.server_lists, self.server_manager_dir, logger)

    def show_server_context_menu(self, event):
        # Show context menu on right-click in server list
        current_list = self.get_current_server_list()
        if not current_list:
            return
            
        item = current_list.identify_row(event.y)
        
        if item:
            current_list.selection_set(item)
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
            self.server_context_menu.entryconfigure("Kill Process", state=tk.NORMAL)
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
            self.server_context_menu.entryconfigure("Kill Process", state=tk.DISABLED)
            
        # Show context menu
        self.server_context_menu.tk_popup(event.x_root, event.y_root)

    def on_server_list_click(self, event):
        # Handle left-click on server list - deselect all if clicking on empty space
        current_list = self.get_current_server_list()
        if not current_list:
            return
            
        item = current_list.identify_row(event.y)
        
        if not item:
            # Clicked on empty space - clear all selections (like Windows Explorer)
            # Only clear if there are actually items in the list and not during refresh
            if current_list.get_children() and not getattr(self, '_refreshing_server_list', False):
                current_list.selection_remove(current_list.selection())
                logger.debug("Cleared server list selection due to empty space click")

    def on_server_double_click(self, event):
        # Handle double-click on server list - open configuration dialog
        current_list = self.get_current_server_list()
        if not current_list:
            return
            
        item = current_list.identify_row(event.y)
        
        if item:
            # Double-clicked on a server - open configuration
            current_list.selection_set(item)
            self.configure_server()

    def on_drag_start(self, event):
        # Handle drag start for server/category movement
        current_list = self.get_current_server_list()
        if not current_list:
            return
            
        # Get the region where the click occurred
        region = current_list.identify_region(event.x, event.y)
        
        # Only allow dragging from data cells, not tree column
        if region != "cell":
            return
            
        item = current_list.identify_row(event.y)
        if not item:
            return
        
        # Get item values
        item_values = current_list.item(item)['values']
        
        # Only allow dragging servers, not categories
        if not item_values or not item_values[1]:  # No server name = category
            return
            
        # Store drag information
        self._drag_item = item
        self._drag_start_y = event.y
        self._drag_data = item_values
        self._drag_active = False  # Will be set to True when drag threshold is exceeded
        self._highlighted_category = None
        
        # Highlight the dragged item
        current_list.selection_set(item)
        
    def on_drag_motion(self, event):
        # Handle drag motion - provide visual feedback
        if not hasattr(self, '_drag_item') or not self._drag_item:
            return
            
        current_list = self.get_current_server_list()
        if not current_list:
            return
        
        # Check if we've moved enough to start the drag
        if not getattr(self, '_drag_active', False):
            if abs(event.y - self._drag_start_y) > 5:  # 5 pixel threshold
                self._drag_active = True
                # Create floating drag indicator
                self._create_drag_indicator(current_list, self._drag_data[0] if self._drag_data else "")
            else:
                return
        
        # Update drag indicator position
        if hasattr(self, '_drag_indicator') and self._drag_indicator:
            try:
                # Position indicator near cursor
                x = current_list.winfo_rootx() + event.x + 15
                y = current_list.winfo_rooty() + event.y + 10
                self._drag_indicator.geometry(f"+{x}+{y}")
            except:
                pass
            
        # Get the region where the mouse is
        region = current_list.identify_region(event.x, event.y)
        
        # Clear previous highlight
        self._clear_category_highlight(current_list)
        
        # Only provide feedback for cell regions
        if region != "cell":
            current_list.config(cursor="no")
            self._update_drag_indicator(False, "")
            return
            
        # Get current position
        current_item = current_list.identify_row(event.y)
        
        # Provide visual feedback
        if current_item and current_item != self._drag_item:
            # Check if this is a valid drop target (category or item under category)
            target_values = current_list.item(current_item)['values']
            
            # Find the parent category for the target
            parent = current_list.parent(current_item)
            if not target_values[1]:  # No server name = this IS a category
                category_item = current_item
                category_name = target_values[0]
            elif parent:  # Server under a category
                category_item = parent
                category_name = current_list.item(parent)['values'][0]
            else:
                category_item = None
                category_name = ""
            
            if category_item:
                current_list.config(cursor="hand2")  # Hand cursor for valid drop
                self._highlight_category(current_list, category_item)
                self._update_drag_indicator(True, category_name)
            else:
                current_list.config(cursor="no")  # No cursor for invalid drop
                self._update_drag_indicator(False, "")
        else:
            current_list.config(cursor="")
            self._update_drag_indicator(False, "")
    
    def _create_drag_indicator(self, parent, server_name):
        # Create a floating drag indicator window
        try:
            # Destroy existing indicator if any
            if hasattr(self, '_drag_indicator') and self._drag_indicator:
                try:
                    self._drag_indicator.destroy()
                except:
                    pass
            
            # Create toplevel window for drag indicator
            self._drag_indicator = tk.Toplevel(self.root)
            self._drag_indicator.overrideredirect(True)  # No window decorations
            self._drag_indicator.attributes('-alpha', 0.85)  # Slightly transparent
            self._drag_indicator.attributes('-topmost', True)
            
            # Create frame with border
            frame = tk.Frame(self._drag_indicator, bg='#4a90d9', padx=2, pady=2)
            frame.pack(fill=tk.BOTH, expand=True)
            
            inner_frame = tk.Frame(frame, bg='#f0f0f0', padx=8, pady=4)
            inner_frame.pack(fill=tk.BOTH, expand=True)
            
            # Server name label
            self._drag_label = tk.Label(inner_frame, text=f"📦 {server_name}", 
                                        bg='#f0f0f0', fg='#333333',
                                        font=('Segoe UI', 9, 'bold'))
            self._drag_label.pack(side=tk.LEFT)
            
            # Target category label
            self._drag_target_label = tk.Label(inner_frame, text="", 
                                               bg='#f0f0f0', fg='#666666',
                                               font=('Segoe UI', 8))
            self._drag_target_label.pack(side=tk.LEFT, padx=(10, 0))
            
        except Exception as e:
            logger.debug(f"Error creating drag indicator: {e}")
    
    def _update_drag_indicator(self, valid, category_name):
        # Update the drag indicator to show target status
        try:
            if hasattr(self, '_drag_target_label') and self._drag_target_label:
                if valid and category_name:
                    self._drag_target_label.config(text=f"→ {category_name}", fg='#2e7d32')  # Green
                elif not valid:
                    self._drag_target_label.config(text="✗ Invalid target", fg='#c62828')  # Red
                else:
                    self._drag_target_label.config(text="")
        except:
            pass
    
    def _destroy_drag_indicator(self):
        # Destroy the drag indicator window
        try:
            if hasattr(self, '_drag_indicator') and self._drag_indicator:
                self._drag_indicator.destroy()
                self._drag_indicator = None
        except:
            pass
    
    def _highlight_category(self, treeview, category_item):
        # Highlight a category row to show it's a valid drop target
        try:
            # Store the highlighted category
            self._highlighted_category = category_item
            
            # Add highlight tag
            current_tags = list(treeview.item(category_item, 'tags'))
            if 'drop_target' not in current_tags:
                current_tags.append('drop_target')
                treeview.item(category_item, tags=current_tags)
            
            # Configure the drop_target tag style
            treeview.tag_configure('drop_target', background='#c8e6c9')  # Light green
            
        except Exception as e:
            logger.debug(f"Error highlighting category: {e}")
    
    def _clear_category_highlight(self, treeview):
        # Clear any category highlighting
        try:
            if hasattr(self, '_highlighted_category') and self._highlighted_category:
                try:
                    current_tags = list(treeview.item(self._highlighted_category, 'tags'))
                    if 'drop_target' in current_tags:
                        current_tags.remove('drop_target')
                        treeview.item(self._highlighted_category, tags=current_tags)
                except:
                    pass
            self._highlighted_category = None
        except:
            pass
            
    def on_drag_release(self, event):
        # Handle drag release - move server to new category
        current_list = self.get_current_server_list()
        
        try:
            # Clean up visual elements first
            if current_list:
                current_list.config(cursor="")
                self._clear_category_highlight(current_list)
            self._destroy_drag_indicator()
            
            # Check if we were actually dragging
            if not hasattr(self, '_drag_item') or not self._drag_item:
                return
            
            if not getattr(self, '_drag_active', False):
                # Was just a click, not a drag
                self._drag_item = None
                self._drag_data = None
                self._drag_active = False
                return
                
            if not current_list:
                return
            
            # Check if we're releasing over a valid drop region
            region = current_list.identify_region(event.x, event.y)
            
            # Get drop target
            drop_item = current_list.identify_row(event.y)
            if not drop_item or drop_item == self._drag_item:
                return
            
            # Find the target category
            drop_values = current_list.item(drop_item)['values']
            parent = current_list.parent(drop_item)
            
            if not drop_values[1]:  # No server name = this IS a category
                target_category = drop_values[0]
            elif parent:  # Server under a category - use parent category
                parent_values = current_list.item(parent)['values']
                target_category = parent_values[0]
            else:
                messagebox.showinfo("Invalid Target", "Please drop onto a category.")
                return
                
            # Get source data
            source_values = self._drag_data
            if not source_values or not source_values[1]:  # Not a server
                return
                
            server_name = source_values[0]
            
            # Get current category from parent of dragged item
            drag_parent = current_list.parent(self._drag_item)
            if drag_parent:
                current_category = current_list.item(drag_parent)['values'][0]
            else:
                current_category = "Uncategorized"
            
            # Don't move if already in target category
            if current_category == target_category:
                return
                
            # Move server to new category
            self._move_server_to_category(server_name, target_category)
            
            # Refresh categories immediately for instant visual feedback
            self.refresh_categories()
            
            logger.info(f"Moved server '{server_name}' from '{current_category}' to category '{target_category}'")
                
        except Exception as e:
            logger.error(f"Error during drag-and-drop: {str(e)}")
            messagebox.showerror("Error", f"Failed to move item: {str(e)}")
            
        finally:
            # Always clear drag state
            self._drag_item = None
            self._drag_data = None
            self._drag_active = False
            self._highlighted_category = None

    def _move_server_to_category(self, server_name, new_category):
        # Move a server to a new category by updating its configuration
        try:
            servers_path = self.paths["servers"]
            if not os.path.exists(servers_path):
                return
                
            config_file = os.path.join(servers_path, f"{server_name}.json")
            if not os.path.exists(config_file):
                return
                
            with open(config_file, 'r', encoding='utf-8') as f:
                server_config = json.load(f)
                
            server_config['Category'] = new_category
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(server_config, f, indent=2, ensure_ascii=False)
            
            # Update in-memory cache
            if self.server_manager:
                self.server_manager.reload_server(server_name)
                
            logger.info(f"Updated category for server '{server_name}' to '{new_category}'")
            
        except Exception as e:
            logger.error(f"Error updating server category: {str(e)}")
            raise

    def add_server(self):
        # Add a new game server (Steam, Minecraft, or Other)
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
        dialog_width = min(950, int(self.root.winfo_screenwidth() * 0.9))
        dialog_height = min(700, int(self.root.winfo_screenheight() * 0.8))
        dialog.minsize(dialog_width, dialog_height)
        
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

        # Minecraft-specific fields with two-dropdown interface
        if server_type == "Minecraft":
            try:
                # Load Minecraft versions from database using get_minecraft_versions_from_database
                
                # Get available modloaders
                available_modloaders = ["Vanilla", "Forge", "Fabric", "NeoForge"]
                
                # Modloader selection (positioned above version dropdown)
                ttk.Label(scrollable_frame, text="Modloader:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
                modloader_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['modloader'], 
                                             values=available_modloaders, state="readonly", width=32, font=("Segoe UI", 10))
                modloader_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
                current_row += 1
                
                # Minecraft version dropdown (positioned below modloader)
                ttk.Label(scrollable_frame, text="Minecraft Version:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
                version_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['minecraft_version'], 
                                           values=[], state="readonly", width=32, font=("Segoe UI", 10))
                version_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
                current_row += 1
                
                # Function to update version list based on modloader selection
                def update_version_list(*args):
                    try:
                        selected_modloader = form_vars['modloader'].get().lower()
                        if selected_modloader == "vanilla":
                            selected_modloader = "vanilla"  # Keep as is
                        
                        # Get versions from database for selected modloader
                        versions = get_minecraft_versions_from_database(
                            modloader=selected_modloader
                        )
                        
                        # Create display options and mapping
                        version_options = []
                        version_map = {}
                        
                        for version_data in versions:
                            version_id = version_data.get("version_id", "")
                            display_text = version_id
                            version_options.append(display_text)
                            version_map[display_text] = version_data
                        
                        # Update combobox values
                        version_combo['values'] = version_options
                        
                        # Set default selection to first item if available
                        if version_options:
                            form_vars['minecraft_version'].set(version_options[0])
                        else:
                            form_vars['minecraft_version'].set("")
                        
                        # Store version mapping for later use
                        setattr(dialog, 'version_map', version_map)
                        
                    except Exception as e:
                        logger.error(f"Error updating version list: {e}")
                        version_combo['values'] = []
                        form_vars['minecraft_version'].set("")
                
                # Bind modloader change event
                form_vars['modloader'].trace('w', update_version_list)
                
                # Initialize with default modloader
                update_version_list()
                
            except Exception as e:
                messagebox.showerror("Error", f"Minecraft support not available: {str(e)}")
                dialog.destroy()
                return

        # App ID (Steam only)
        if server_type == "Steam":
            ttk.Label(scrollable_frame, text="App ID:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            app_id_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['app_id'], width=25, font=("Segoe UI", 10))
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
                        error_msg = "Scanner AppID list not available - database must be populated first"
                        logger.error(error_msg)
                        messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
                        return

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
                        if 'T' in last_updated:
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                                formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                                ttk.Label(search_frame, text=f"Data last updated: {formatted_date}",
                                        foreground="gray", font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
                            except:
                                pass

                except Exception as e:
                    error_msg = f"Failed to load AppID scanner data from database: {e}"
                    logger.error(error_msg)
                    messagebox.showerror("Database Error", f"{error_msg}\n\nThe database must be available and populated with AppID scanner data.")
                    return
                
                # Create server list with enhanced columns
                list_frame = ttk.Frame(appid_dialog, padding=10)
                list_frame.pack(fill=tk.BOTH, expand=True)
                
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
                tree_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
                server_tree.configure(yscrollcommand=tree_scrollbar.set)
                
                tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                
                # Populate server list
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
                
                # Search functionality
                def on_search(*args):
                    populate_servers(search_var.get())
                
                search_var.trace('w', on_search)
                
                # Add tooltip functionality for descriptions
                def show_server_info(event):
                    # Show server description tooltip on mouse hover
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
                        item = server_tree.item(selected[0])
                        appid = item['values'][1]
                        form_vars['app_id'].set(appid)
                        appid_dialog.destroy()
                    else:
                        messagebox.showinfo("No Selection", "Please select a server from the list.")
                
                def cancel_selection():
                    appid_dialog.destroy()
                
                ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT, padx=(0, 10))
                ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)
                
                # Centre dialog
                centre_window(appid_dialog, 600, 500, dialog)
            
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
            default_location = self.variables.get("defaultServerManagerInstallDir", "")
            if default_location:
                help_text = f"(Leave blank for default: {default_location}\\ServerName)"
            else:
                help_text = "(Please specify installation directory)"

        # Create a wrapping label for the help text with better wrapping
        help_label = ttk.Label(scrollable_frame, text=help_text, foreground="gray",
                             font=("Segoe UI", 9), wraplength=500, justify=tk.LEFT)
        help_label.grid(row=current_row, column=1, columnspan=2, padx=15, pady=(0, 5), sticky="ew")

        # Ensure the column has proper weight for text wrapping
        scrollable_frame.grid_columnconfigure(1, weight=1)
        current_row += 1

        current_row += 1
        
        # Create button frame in top section (below the scrollable form)
        button_container = ttk.Frame(top_frame)
        button_container.pack(fill=tk.X, pady=(10, 5))
        
        # Create buttons with consistent spacing
        create_button = ttk.Button(button_container, text="Create Server", width=18)
        create_button.pack(side=tk.LEFT, padx=(0, 10))
        
        cancel_button = ttk.Button(button_container, text="Cancel Installation", width=18, state=tk.DISABLED)
        cancel_button.pack(side=tk.LEFT, padx=(0, 10))
        
        close_button = ttk.Button(button_container, text="Close", width=12)
        close_button.pack(side=tk.RIGHT)

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
                    
                # Validate required fields
                server_name = form_vars['name'].get().strip()
                install_dir = form_vars['install_dir'].get().strip()
                
                if not server_name:
                    messagebox.showerror("Validation Error", "Server name is required.")
                    return
                    
                # Set default install directory if not provided
                if not install_dir:
                    if server_type == "Steam":
                        install_dir = self.variables.get("defaultSteamInstallDir", "")
                        if not install_dir:
                            messagebox.showerror("Validation Error", "SteamCMD path not configured. Please set the installation directory manually.")
                            return
                    else:  # Minecraft or Other
                        default_base = self.variables.get("defaultServerManagerInstallDir", "")
                        if default_base:
                            install_dir = os.path.join(default_base, server_name)
                        else:
                            messagebox.showerror("Validation Error", "Default installation directory not configured. Please set the installation directory manually.")
                            return
                
                # Validate server type specific fields
                if server_type == "Steam":
                    app_id = form_vars.get('app_id', tk.StringVar()).get().strip()
                    if not app_id:
                        messagebox.showerror("Validation Error", "Steam App ID is required for Steam servers.")
                        return
                    if not app_id.isdigit():
                        messagebox.showerror("Validation Error", "Steam App ID must be a number.")
                        return
                        
                elif server_type == "Minecraft":
                    minecraft_version = form_vars['minecraft_version'].get().strip()
                    if not minecraft_version:
                        messagebox.showerror("Validation Error", "Minecraft version must be selected.")
                        return
                
                # Check for invalid characters in server name
                invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
                if any(char in server_name for char in invalid_chars):
                    messagebox.showerror("Validation Error", 
                                       "Server name contains invalid characters. Please use only letters, numbers, spaces, and underscores.")
                    return
                
                # Check if server name already exists
                if self.server_manager:
                    existing_config = self.server_manager.get_server_config(server_name)
                    if existing_config:
                        messagebox.showerror("Validation Error", f"A server with the name '{server_name}' already exists.")
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
                
                # Prepare minecraft version data if applicable
                minecraft_version_data = None
                if server_type == "Minecraft":
                    selected_version = form_vars['minecraft_version'].get()
                    version_map = getattr(dialog, 'version_map', {})
                    minecraft_version_data = version_map.get(selected_version)
                
                # Use the existing installation function from dashboard_functions
                success, message = perform_server_installation(
                    server_type=server_type,
                    server_name=server_name,
                    install_dir=install_dir,
                    app_id=form_vars.get('app_id', tk.StringVar()).get() if server_type == "Steam" else None,
                    minecraft_version=minecraft_version_data,
                    credentials=credentials,
                    server_manager=self.server_manager,
                    progress_callback=safe_status_callback,
                    console_callback=safe_console_callback,
                    steam_cmd_path=self.steam_cmd_path
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
                    
                    # Show detailed error dialog for installation failures
                    try:
                        messagebox.showerror("Installation Failed", 
                                           f"Server installation failed:\n\n{message}\n\n"
                                           "Please check the console output for more details.")
                    except tk.TclError:
                        # Dialog might be destroyed
                        pass
                    
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
        
        # Centre dialog relative to parent with proper size for new layout
        centre_window(dialog, dialog_width, dialog_height, self.root)

    def update_server_list(self, force_refresh=False):
        # Update server list from configuration files - thread-safe
        def _update():
            from Host.dashboard_functions import update_server_list_logic
            update_server_list_logic(self, force_refresh)
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def toggle_offline_mode(self):
        # Toggle offline mode
        # Toggle offline mode
        self.variables["offlineMode"] = self.offline_var.get()
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
    def toggle_system_info(self):
        # Toggle visibility of the system information panel
        self.system_info_visible = not self.system_info_visible
        
        if self.system_info_visible:
            # Show the system info panel - add back to pane
            self.main_pane.add(self.system_frame, weight=30)
            self.system_toggle_btn.config(text="◀")
        else:
            # Hide the system info panel - remove from pane
            self.main_pane.forget(self.system_frame)
            self.system_toggle_btn.config(text="▶")
        
        # Save state to database
        self.variables["systemInfoVisible"] = self.system_info_visible
        try:
            from Modules.Database.cluster_database import get_cluster_database
            db = get_cluster_database()
            db.set_dashboard_config("ui.systemInfoVisible", self.system_info_visible, "boolean", "ui")
            logger.debug(f"System info visibility saved: {self.system_info_visible}")
        except Exception as e:
            logger.error(f"Error saving system info visibility state: {e}")
    
    def update_webserver_status(self):
        # Update the web server status display - thread-safe
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
        # Update system information using background threading to prevent UI freezing
        def _update():
            try:
                # Update web server status (this is lightweight)
                self.update_webserver_status()

                # Use the threaded version from dashboard_functions for heavy system monitoring
                update_system_info_threaded(self.metric_labels, self.system_name, self.os_info)

            except Exception as e:
                logger.error(f"Error in update_system_info: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def periodic_server_list_refresh(self):
        # Periodic refresh of server list to clean up orphaned processes and update status
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
        # Run the dashboard application
        logger.info("Starting dashboard run method")

        try:
            # Show the window first
            logger.info("Setting up window protocol and showing window")
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.variables["formDisplayed"] = True

            # Schedule initial updates after mainloop starts
            # This prevents Tkinter widget updates before the event loop is running
            def delayed_initial_update():
                try:
                    logger.info("[SUBPROCESS_TRACE] Starting delayed initial updates - watching for console popup...")
                    # Perform heavy operations that were previously blocking __init__
                    logger.info("[SUBPROCESS_TRACE] Calling update_system_info()...")
                    self.update_system_info()  # Initial system info update (now threaded)
                    logger.info("[SUBPROCESS_TRACE] update_system_info() completed")
                    
                    logger.info("[SUBPROCESS_TRACE] Calling update_server_list()...")
                    self.update_server_list(force_refresh=True)  # Initial server list refresh
                    logger.info("[SUBPROCESS_TRACE] update_server_list() completed")
                    
                    logger.info("[SUBPROCESS_TRACE] Calling _reattach_to_running_servers()...")
                    self._reattach_to_running_servers()  # Reattach to running servers
                    logger.info("[SUBPROCESS_TRACE] _reattach_to_running_servers() completed")
                    
                    logger.info("Delayed initial updates completed")
                except Exception as e:
                    logger.error(f"Error in delayed initial update: {str(e)}")

            logger.info("Scheduling delayed initial update")
            self.root.after(100, delayed_initial_update)  # 100ms delay

            # Start main loop
            logger.info("Starting Tkinter mainloop")
            self.root.mainloop()
            logger.info("Tkinter mainloop exited")
        except Exception as e:
            logger.error(f"Error starting dashboard: {str(e)}")
            # Try to show error and exit gracefully
            try:
                messagebox.showerror("Dashboard Error", f"Failed to start dashboard: {str(e)}")
            except:
                pass  # Messagebox might fail if Tkinter is in bad state
            self.on_close()
    
    def on_close(self):
        # Handle window close event
        logger.info("Dashboard closing")

        # Clean up resources
        try:
            # Save all console states first for crash recovery
            if hasattr(self, 'console_manager') and self.console_manager:
                self.console_manager.save_all_console_states()
                logger.debug("Saved all console states")
            
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
        # Start the selected game server (Steam/Minecraft/Other)
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        # Check if this is a remote host
        if self.is_remote_host(current_subhost):
            self.start_remote_server(server_name, current_subhost)
            return
        
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

    def start_remote_server(self, server_name, subhost_name):
        # Start a server on a remote host
        try:
            host, port = self.get_remote_connection_details(subhost_name)
            if not host or not port or not hasattr(self, 'remote_host_manager'):
                messagebox.showerror("Error", "Remote host connection not available")
                return
            
            # Show starting message
            self.update_server_status(server_name, "Starting...")
            
            def start_remote_in_background():
                try:
                    success, message = self.remote_host_manager.start_server(host, port, server_name)
                    
                    def update_ui():
                        if success:
                            self.update_server_status(server_name, "Running")
                            messagebox.showinfo("Success", f"Server '{server_name}' started successfully on remote host")
                        else:
                            self.update_server_status(server_name, "Failed")
                            messagebox.showerror("Error", f"Failed to start server '{server_name}': {message}")
                        self.update_server_list(force_refresh=True)
                    
                    self.root.after(0, update_ui)
                    
                except Exception as e:
                    logger.error(f"Error starting remote server: {str(e)}")
                    def show_error():
                        self.update_server_status(server_name, "Error")
                        messagebox.showerror("Error", f"Failed to start remote server: {str(e)}")
                        self.update_server_list(force_refresh=True)
                    self.root.after(0, show_error)
            
            # Run in background thread
            start_thread = threading.Thread(target=start_remote_in_background, daemon=True)
            start_thread.start()
            
        except Exception as e:
            logger.error(f"Error starting remote server: {str(e)}")
            messagebox.showerror("Error", f"Failed to start remote server: {str(e)}")

    def stop_remote_server(self, server_name, subhost_name):
        # Stop a server on a remote host
        try:
            host, port = self.get_remote_connection_details(subhost_name)
            if not host or not port or not hasattr(self, 'remote_host_manager'):
                messagebox.showerror("Error", "Remote host connection not available")
                return
            
            # Show stopping message
            self.update_server_status(server_name, "Stopping...")
            
            def stop_remote_in_background():
                try:
                    success, message = self.remote_host_manager.stop_server(host, port, server_name)
                    
                    def update_ui():
                        if success:
                            self.update_server_status(server_name, "Stopped")
                            messagebox.showinfo("Success", f"Server '{server_name}' stopped successfully on remote host")
                        else:
                            self.update_server_status(server_name, "Failed")
                            messagebox.showerror("Error", f"Failed to stop server '{server_name}': {message}")
                        self.update_server_list(force_refresh=True)
                    
                    self.root.after(0, update_ui)
                    
                except Exception as e:
                    logger.error(f"Error stopping remote server: {str(e)}")
                    def show_error():
                        self.update_server_status(server_name, "Error")
                        messagebox.showerror("Error", f"Failed to stop remote server: {str(e)}")
                        self.update_server_list(force_refresh=True)
                    self.root.after(0, show_error)
            
            # Run in background thread
            stop_thread = threading.Thread(target=stop_remote_in_background, daemon=True)
            stop_thread.start()
            
        except Exception as e:
            logger.error(f"Error stopping remote server: {str(e)}")
            messagebox.showerror("Error", f"Failed to stop remote server: {str(e)}")

    def restart_remote_server(self, server_name, subhost_name):
        # Restart a server on a remote host
        try:
            host, port = self.get_remote_connection_details(subhost_name)
            if not host or not port or not hasattr(self, 'remote_host_manager'):
                messagebox.showerror("Error", "Remote host connection not available")
                return
            
            # Show restarting message
            self.update_server_status(server_name, "Restarting...")
            
            def restart_remote_in_background():
                try:
                    success, message = self.remote_host_manager.restart_server(host, port, server_name)
                    
                    def update_ui():
                        if success:
                            self.update_server_status(server_name, "Running")
                            messagebox.showinfo("Success", f"Server '{server_name}' restarted successfully on remote host")
                        else:
                            self.update_server_status(server_name, "Failed")
                            messagebox.showerror("Error", f"Failed to restart server '{server_name}': {message}")
                        self.update_server_list(force_refresh=True)
                    
                    self.root.after(0, update_ui)
                    
                except Exception as e:
                    logger.error(f"Error restarting remote server: {str(e)}")
                    def show_error():
                        self.update_server_status(server_name, "Error")
                        messagebox.showerror("Error", f"Failed to restart remote server: {str(e)}")
                        self.update_server_list(force_refresh=True)
                    self.root.after(0, show_error)
            
            # Run in background thread
            restart_thread = threading.Thread(target=restart_remote_in_background, daemon=True)
            restart_thread.start()
            
        except Exception as e:
            logger.error(f"Error restarting remote server: {str(e)}")
            messagebox.showerror("Error", f"Failed to restart remote server: {str(e)}")

    def stop_server(self):
        # Stop the selected game server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        # Check if this is a remote host
        if self.is_remote_host(current_subhost):
            self.stop_remote_server(server_name, current_subhost)
            return
        
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
                
                # Clean up console state when server is stopped
                # This prevents old PID data from causing issues with reused PIDs
                if success and hasattr(self, 'console_manager') and self.console_manager:
                    try:
                        self.console_manager.cleanup_console_on_stop(server_name)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup console on stop: {e}")
                
                # Update UI on main thread
                def update_ui():
                    if success:
                        # Server stopped successfully - no dialog popup
                        pass
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
        # Restart the selected game server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        # Check if this is a remote host
        if self.is_remote_host(current_subhost):
            # Confirm restart
            confirm = messagebox.askyesno("Confirm Restart", 
                                        f"Are you sure you want to restart the remote server '{server_name}'?",
                                        icon=messagebox.WARNING)
            if confirm:
                self.restart_remote_server(server_name, current_subhost)
            return
        
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
                        # Server restarted successfully - no dialog popup
                        pass
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
        # View detailed process information for a server using debug module
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        
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
            
            ttk.Button(button_frame, text="Refresh", command=refresh_process_info, width=15).pack(side=tk.LEFT, padx=(0, 10))
            
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
            
            ttk.Button(button_frame, text="Monitor (10s)", command=monitor_process, width=15).pack(side=tk.LEFT, padx=(0, 10))
            
            # Stop process button
            def stop_from_details():
                dialog.destroy()
                self.stop_server()
            
            ttk.Button(button_frame, text="Stop Process", command=stop_from_details, width=15).pack(side=tk.RIGHT, padx=(0, 10))
            
            # Close button
            ttk.Button(button_frame, text="Close", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=(0, 10))
            
            # Centre dialog relative to parent
            centre_window(dialog, 700, 600, self.root)
            
        except Exception as e:
            log_exception(e, f"Error viewing process details for {server_name}")
            messagebox.showerror("Error", f"Failed to get process details: {str(e)}")
    
    def show_server_console(self):
        # Show console window for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
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
                server_values = current_list.item(selected_items[0])['values']
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
        # Update the status of a server in the UI - thread-safe
        def _update():
            try:
                current_list = self.get_current_server_list()
                if current_list:
                    update_server_status_in_treeview(current_list, server_name, status)
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
        # Configure server settings including name, type, AppID, and startup configuration
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Get server configuration from server manager
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
            
        install_dir = server_config.get('InstallDir','')
        # REMOVED: Directory existence check - allow configuration even if directory doesn't exist
        # Users can now update the InstallDir in the configuration dialog

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure Server: {server_name}")
        dialog_width = min(900, int(self.root.winfo_screenwidth() * 0.9))
        dialog_height = min(850, int(self.root.winfo_screenheight() * 0.8))
        dialog.geometry(f"{dialog_width}x{dialog_height}")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Create main frame with padding
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create scrollable frame for all content
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
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
                if canvas.winfo_width() > 1:  # Only update if canvas has a valid width
                    canvas.itemconfig(1, width=canvas.winfo_width())  # Item ID 1 is the scrollable_frame
            except:
                pass
        
        canvas.bind("<Configure>", update_canvas_width)

        # Configure scrollable_frame columns
        scrollable_frame.columnconfigure(0, weight=1, minsize=200)
        scrollable_frame.columnconfigure(1, weight=1, minsize=200)
        scrollable_frame.columnconfigure(2, weight=1, minsize=200)
        scrollable_frame.columnconfigure(3, weight=1, minsize=200)

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
            # Open dialog to browse and select Steam dedicated server AppID
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
            
            # Load dedicated servers from scanner's AppID list (NO FALLBACKS)
            try:
                dedicated_servers_data, metadata = load_appid_scanner_list(self.server_manager_dir)

                if not dedicated_servers_data:
                    error_msg = "Scanner AppID list not available - database must be populated first"
                    logger.error(error_msg)
                    messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
                    return

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
                error_msg = f"Failed to load AppID scanner data from database: {e}"
                logger.error(error_msg)
                messagebox.showerror("Database Error", f"{error_msg}\n\nThe database must be available and populated with AppID scanner data.")
                return
            
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
                # Populate the server tree with filtered dedicated server list
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
                # Update server list when search text changes
                populate_servers(search_var.get())
            
            search_var.trace('w', on_search)
            
            # Add tooltip functionality for descriptions
            def show_server_info(event):
                # Show server description tooltip on mouse hover
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
            
            ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)
            
            # Centre dialog
            centre_window(appid_dialog, 600, 500, dialog)
        
        appid_browse_btn = ttk.Button(identity_frame, text="Browse", command=browse_appid, width=10)
        appid_browse_btn.grid(row=2, column=2, padx=5, pady=5)
        
        appid_help = ttk.Label(identity_frame, text="(Steam servers only)", foreground="gray", font=("Segoe UI", 8))
        appid_help.grid(row=2, column=3, padx=5, pady=5, sticky=tk.W)
        
        # Install directory (now editable)
        ttk.Label(identity_frame, text="Install Directory:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        install_dir_var = tk.StringVar(value=install_dir)
        install_dir_entry = ttk.Entry(identity_frame, textvariable=install_dir_var, width=25, font=("Segoe UI", 9))
        install_dir_entry.grid(row=3, column=1, padx=10, pady=5, sticky=tk.EW)
        
        def browse_install_dir():
            current_dir = install_dir_var.get()
            if not os.path.exists(current_dir):
                current_dir = os.path.dirname(current_dir) if current_dir else ""
            
            selected_dir = filedialog.askdirectory(initialdir=current_dir, title="Select Server Installation Directory")
            if selected_dir:
                # Check if directory changed
                old_dir = install_dir_var.get()
                if old_dir != selected_dir:
                    install_dir_var.set(selected_dir)
                    # Update relative paths when install directory changes
                    update_paths_for_new_install_dir(old_dir, selected_dir)
        
        ttk.Button(identity_frame, text="Browse", command=browse_install_dir, width=8).grid(row=3, column=2, padx=5, pady=5)
        
        def test_install_dir_path():
            # Test if the install directory path exists
            dir_path = install_dir_var.get().strip()
            if not dir_path:
                messagebox.showinfo("Test", "No install directory specified.")
                return
            if os.path.exists(dir_path) and os.path.isdir(dir_path):
                messagebox.showinfo("Test OK", f"Directory exists: {dir_path}")
            else:
                messagebox.showwarning("Test Failed", f"Directory not found: {dir_path}")
        
        ttk.Button(identity_frame, text="Test Path", command=test_install_dir_path, width=10).grid(row=3, column=3, padx=5, pady=5)
        
        def update_paths_for_new_install_dir(old_dir, new_dir):
            """Update relative paths when install directory changes"""
            try:
                # Only update if both directories exist and are different
                if not old_dir or not new_dir or old_dir == new_dir:
                    return
                
                # Update executable path if it's relative
                exe_path = exe_var.get().strip()
                if exe_path and not os.path.isabs(exe_path):
                    # Try to find the same relative file in the new directory
                    old_full_path = os.path.join(old_dir, exe_path)
                    if os.path.exists(old_full_path):
                        # File exists in old location, keep relative path
                        pass  # Keep the relative path as is
                    else:
                        # File doesn't exist in old location, try to find it in new directory
                        new_full_path = os.path.join(new_dir, os.path.basename(exe_path))
                        if os.path.exists(new_full_path):
                            exe_var.set(os.path.basename(exe_path))
                
                # Update config file path if it's relative
                config_path = config_file_var.get().strip()
                if config_path and not os.path.isabs(config_path):
                    old_config_full = os.path.join(old_dir, config_path)
                    if os.path.exists(old_config_full):
                        # File exists in old location, keep relative path
                        pass  # Keep the relative path as is
                    else:
                        # Try to find config files in new directory
                        for ext in ['.cfg', '.conf', '.ini', '.json', '.yaml', '.yml', '.properties', '.txt']:
                            potential_config = os.path.join(new_dir, f"server{ext}")
                            if os.path.exists(potential_config):
                                config_file_var.set(f"server{ext}")
                                break
                
                # Update preview
                update_preview()
                
            except Exception as e:
                logger.warning(f"Error updating paths for new install directory: {str(e)}")
        
        # Bind install directory change event
        def on_install_dir_change(*args):
            update_preview()
        
        install_dir_var.trace('w', on_install_dir_change)
        
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
        exe_entry = ttk.Entry(startup_frame, textvariable=exe_var, width=25, font=("Segoe UI", 10))
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
        ttk.Entry(startup_frame, textvariable=stop_var, width=25, font=("Segoe UI", 10)).grid(row=1, column=1, padx=10, pady=5, sticky=tk.EW)
        
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
        args_entry = ttk.Entry(manual_frame, textvariable=args_var, width=35)
        args_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        
        # Config file section
        config_frame = ttk.Frame(args_frame)
        config_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        # Config file path
        ttk.Label(config_frame, text="Config File:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        config_file_var = tk.StringVar(value=server_config.get('ConfigFilePath',''))
        config_file_entry = ttk.Entry(config_frame, textvariable=config_file_var, width=25)
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
        config_arg_entry = ttk.Entry(config_frame, textvariable=config_arg_var, width=15)
        config_arg_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(e.g., --config, -c, +exec)", foreground="gray").grid(row=1, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Additional args for config mode
        ttk.Label(config_frame, text="Additional Args:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        additional_args_var = tk.StringVar(value=server_config.get('AdditionalArgs',''))
        additional_args_entry = ttk.Entry(config_frame, textvariable=additional_args_var, width=25)
        additional_args_entry.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
        ttk.Label(config_frame, text="(optional)", foreground="gray").grid(row=2, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Configure grid weights
        startup_frame.grid_columnconfigure(0, weight=0, minsize=120)
        startup_frame.grid_columnconfigure(1, weight=1, minsize=200)
        startup_frame.grid_columnconfigure(2, weight=0, minsize=80)
        args_frame.grid_columnconfigure(0, weight=1)
        args_frame.grid_columnconfigure(1, weight=1)
        args_frame.grid_columnconfigure(2, weight=0)
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
            java_entry = ttk.Entry(java_info_frame, textvariable=java_path_var, width=30, font=("Segoe UI", 10))
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
            ttk.Entry(java_info_frame, textvariable=jvm_args_var, width=30, font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=10, pady=5)
            
            # Minecraft Version
            ttk.Label(java_info_frame, text="MC Version:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky=tk.W, pady=5, padx=10)
            mc_version_var = tk.StringVar(value=server_config.get("Version", ""))
            ttk.Entry(java_info_frame, textvariable=mc_version_var, width=25, font=("Segoe UI", 10)).grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)
            
            # Configure grid weights
            java_info_frame.grid_columnconfigure(0, weight=0, minsize=100)
            java_info_frame.grid_columnconfigure(1, weight=1, minsize=150)
            java_info_frame.grid_columnconfigure(2, weight=0, minsize=80)
            java_info_frame.grid_columnconfigure(3, weight=0, minsize=100)
        
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
            steam_info_frame.grid_columnconfigure(0, weight=1)
            steam_info_frame.grid_columnconfigure(1, weight=0)
        
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
            ttk.Entry(custom_frame, textvariable=notes_var, width=35, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)
            
            # Configure grid weights
            custom_frame.grid_columnconfigure(0, weight=0, minsize=140)
            custom_frame.grid_columnconfigure(1, weight=1, minsize=200)
        if name_var.get() != server_name or type_var.get() != current_server_type:
            warning_frame = ttk.Frame(scrollable_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))
            
            warning_label = ttk.Label(warning_frame, 
                                    text="⚠ Warning: Changing server name or type will update configuration files. Ensure server is stopped.",
                                    foreground="orange", font=("Segoe UI", 9, "bold"), wraplength=650)
            warning_label.pack()

        # Button frame at bottom of dialog (outside scrollable area)
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=10)
        
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
            # REMOVED: Executable path is no longer required
            # if not exe_path:
            #     errors.append("Executable path is required")
            
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
                exe_abs = exe_path if os.path.isabs(exe_path) else os.path.join(install_dir_var.get(), exe_path)
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
                        config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir_var.get(), config_file_path)
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
                                                                      self.server_manager)
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
                        current_server_name, exe_path, startup_args, stop_cmd, use_config_file=use_config, 
                        config_file_path=config_file_path, config_argument=config_arg, additional_args=additional_args
                    )
                else:
                    success = False
                    message = "Server manager not available"
                
                # Update InstallDir in server configuration if it changed
                if success and install_dir_var.get() != server_config.get('InstallDir'):
                    try:
                        # Read current config file
                        config_file = os.path.join(self.paths["servers"], f"{current_server_name}.json")
                        with open(config_file, 'r', encoding='utf-8') as f:
                            current_config = json.load(f)
                        
                        # Update InstallDir
                        current_config['InstallDir'] = install_dir_var.get()
                        
                        # Save updated config
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump(current_config, f, indent=2, ensure_ascii=False)
                        
                        logger.info(f"Updated InstallDir for server '{current_server_name}' to: {install_dir_var.get()}")
                    except Exception as e:
                        logger.warning(f"Failed to update InstallDir: {str(e)}")
                        # Don't fail the entire operation for this
                
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
        
        # Buttons - Save and Cancel at bottom of dialog
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save Configuration", command=save_configuration).pack(side=tk.RIGHT)

        # Centre dialog relative to parent
        centre_window(dialog, dialog_width, dialog_height, self.root)

    def configure_java(self):
        # Open Java configuration dialog for selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showwarning("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a server to configure Java for.")
            return
        
        # Get selected server name
        item = selected_items[0]
        server_name = current_list.item(item)["values"][0]
        
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
                                               self.server_manager)
        
        # Refresh server list if Java was updated
        if result['success']:
            self.update_server_list(force_refresh=True)
    
    def show_server_type_configuration(self):
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
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 950, 750, self.root)
    
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
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 700, 600, self.root)
    
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
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 600, 500, self.root)

    def open_server_directory(self):
        # Open the server's installation directory in file explorer
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        
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
        # Remove the selected server configuration and optionally files
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = current_list.item(selected_items[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
        
        # Remove server directly without confirmation dialog
        try:
            # Use server manager to remove/uninstall the server (keep files by default)
            if self.server_manager:
                success, message = self.server_manager.uninstall_server(
                    server_name, remove_files=False
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
        # Enhanced import server functionality with support for exported configurations
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
            
            ttk.Button(button_frame, text="Continue", command=proceed_import, width=15).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Cancel", command=cancel_import, width=15).pack(side=tk.LEFT, padx=(0, 10))
            
            # Centre dialog
            centre_window(import_dialog, 400, 300, self.root)
            
        except Exception as e:
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to open import dialog: {str(e)}")

    def import_server_from_directory(self):
        # Import an existing server from a directory (legacy method)
        result = import_server_from_directory_dialog(
            self.root, self.paths, self.server_manager_dir, 
            update_callback=lambda: self.update_server_list(force_refresh=True),
            dashboard_server_manager=self.server_manager
        )

    def import_server_from_export(self):
        # Import server from exported configuration file
        result = import_server_from_export_dialog(
            self.root, self.paths, self.server_manager_dir,
            update_callback=lambda: self.update_server_list(force_refresh=True)
        )

    def export_server(self):
        # Export server configuration for use on other hosts or clusters
        current_list = self.get_current_server_list()
        if current_list:
            result = export_server_dialog(self.root, current_list, self.paths)

    def refresh_all(self):
        # Refresh all dashboard data
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
        # Synchronize all server data with the database
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
            
            # Centre progress dialog relative to parent
            centre_window(progress_dialog, 400, 150, self.root)
            
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

    def connect_remote_host(self):
        # Open the remote host connection dialog
        try:
            create_remote_host_connection_dialog(self.root, self)
        except Exception as e:
            logger.error(f"Error opening remote host connection dialog: {str(e)}")
            messagebox.showerror("Error", f"Failed to open remote host connection dialog: {str(e)}")

    def add_remote_host(self, host, port, username, password, database="", use_ssl=False, timeout=10):
        # Add a remote host to the dashboard with full connection management
        try:
            remote_host_name = f"Remote-{host}"
            
            # Check if tab already exists
            if remote_host_name in self.tab_frames:
                messagebox.showwarning("Warning", f"Remote host '{host}' is already connected")
                return False
            
            # Initialize remote hosts manager if not exists
            if not hasattr(self, 'remote_host_manager'):
                self.remote_host_manager = RemoteHostManager()
            
            # Create connection using RemoteHostManager with SSL and timeout options
            success, message = self.remote_host_manager.connect(host, port, username, password, use_ssl, timeout)
            
            if success:
                # Connection successful, create tab and store connection
                self.add_subhost_tab(remote_host_name, is_local=False)
                
                # Store the connection details for this tab
                if not hasattr(self, 'remote_host_tabs'):
                    self.remote_host_tabs = {}
                
                self.remote_host_tabs[remote_host_name] = {
                    'host': host,
                    'port': port,
                    'username': username,
                    'database': database,
                    'use_ssl': use_ssl,
                    'timeout': timeout
                }
                
                # Load servers for this remote host
                self.load_remote_host_servers(remote_host_name)
                
                logger.info(f"Successfully connected to remote host: {remote_host_name}")
                messagebox.showinfo("Success", f"Successfully connected to remote host '{host}'")
                return True
            else:
                messagebox.showerror("Connection Failed", f"Failed to connect to remote host '{host}': {message}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding remote host: {str(e)}")
            messagebox.showerror("Error", f"Error connecting to remote host: {str(e)}")
            return False

    def load_remote_host_servers(self, remote_host_name):
        # Load servers from a remote host into the dashboard
        try:
            if not hasattr(self, 'remote_host_manager') or remote_host_name not in self.remote_host_tabs:
                return
            
            host = self.remote_host_tabs[remote_host_name]['host']
            port = self.remote_host_tabs[remote_host_name]['port']
            
            # Get servers from remote host
            success, servers_data = self.remote_host_manager.get_servers(host, port)
            
            if success and servers_data and remote_host_name in self.tab_frames:
                # Parse servers data - handle both list and dict responses
                servers = []
                if isinstance(servers_data, list):
                    servers = servers_data
                elif isinstance(servers_data, dict):
                    servers = servers_data.get('servers', [])
                elif isinstance(servers_data, str):
                    try:
                        import json
                        parsed_data = json.loads(servers_data)
                        if isinstance(parsed_data, list):
                            servers = parsed_data
                        elif isinstance(parsed_data, dict):
                            servers = parsed_data.get('servers', [])
                    except:
                        logger.warning(f"Could not parse servers data: {servers_data}")
                        servers = []
                
                # Get the server list widget for this tab
                tab_frame = self.tab_frames[remote_host_name]
                server_list = None
                
                # Find the server list widget in the tab
                for widget in tab_frame.winfo_children():
                    if hasattr(widget, 'winfo_children'):
                        for child in widget.winfo_children():
                            if isinstance(child, ttk.Treeview):
                                server_list = child
                                break
                        if server_list:
                            break
                
                if server_list:
                    # Clear existing items
                    for item in server_list.get_children():
                        server_list.delete(item)
                    
                    # Add remote servers to list
                    for server in servers:
                        server_list.insert('', 'end', values=(
                            server.get('name', 'Unknown'),
                            server.get('status', 'Unknown'),
                            server.get('type', 'Unknown'),
                            server.get('port', 'Unknown'),
                            server.get('players', '0/0')
                        ))
                
                logger.info(f"Loaded {len(servers)} servers for remote host: {remote_host_name}")
            
        except Exception as e:
            logger.error(f"Error loading servers for remote host {remote_host_name}: {str(e)}")

    def disconnect_remote_host(self, remote_host_name):
        # Disconnect from a remote host and remove its tab
        try:
            if hasattr(self, 'remote_host_tabs') and remote_host_name in self.remote_host_tabs:
                host = self.remote_host_tabs[remote_host_name]['host']
                port = self.remote_host_tabs[remote_host_name]['port']
                
                # Disconnect using RemoteHostManager
                if hasattr(self, 'remote_host_manager'):
                    self.remote_host_manager.disconnect(host, port)
                
                # Remove from tracking
                del self.remote_host_tabs[remote_host_name]
                
                # Remove tab if it exists - use the existing pattern from remove_subhost_tab
                if remote_host_name in self.tab_frames:
                    try:
                        tab_index = self.server_notebook.index(self.tab_frames[remote_host_name])
                        self.server_notebook.forget(tab_index)
                    except:
                        # If we can't find the tab index, just remove from dict
                        pass
                    del self.tab_frames[remote_host_name]
                
                logger.info(f"Disconnected from remote host: {remote_host_name}")
                
        except Exception as e:
            logger.error(f"Error disconnecting from remote host {remote_host_name}: {str(e)}")

    def get_remote_connection_details(self, subhost_name):
        # Get the host and port for a remote host
        if self.is_remote_host(subhost_name):
            return (self.remote_host_tabs[subhost_name]['host'], 
                    self.remote_host_tabs[subhost_name]['port'])
        return None, None

    def is_remote_host(self, subhost_name):
        # Check if the given subhost is a remote host
        return hasattr(self, 'remote_host_tabs') and subhost_name in self.remote_host_tabs

    def check_server_updates(self):
        # Check for updates for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
        
        server_name = current_list.item(selected[0])['values'][0]
        
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
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
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
                            # Close progress dialog automatically after user responds
                            progress_dialog.complete("Check completed", auto_close=True)
                            if result:
                                self.update_server_now(server_name, server_config)
                        else:
                            messagebox.showinfo("No Updates", f"{server_name} is up to date.")
                            # Close progress dialog automatically after user clicks OK
                            progress_dialog.complete("Check completed", auto_close=True)
                    
                    self.root.after(0, show_result)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Check Failed", message)
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Check failed", auto_close=True)
                    self.root.after(0, show_error)
                
            except Exception as e:
                error_msg = f"Update check failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Check failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start check in background thread
        import threading
        check_thread = threading.Thread(target=update_check_worker, daemon=True)
        check_thread.start()
    
    def update_server(self):
        # Update the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
        
        server_name = current_list.item(selected[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
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
                        # Use the update_console method which is more robust
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        else:
                            print(message)
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")
                
                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual updates
                    success, message = self.update_manager.update_server(
                        server_name, server_config, progress_callback=progress_callback, scheduled=False
                    )
                else:
                    success, message = False, "Update manager not available"
                
                if success:
                    progress_callback(f"[SUCCESS] {message}")
                    def show_success():
                        messagebox.showinfo("Update Complete", f"{server_name} has been updated successfully!")
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Update completed", auto_close=True)
                        # Refresh server list
                        self.update_server_list()
                    self.root.after(0, show_success)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Failed", message)
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_error)
                
            except Exception as e:
                error_msg = f"Server update failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Update failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start update in background thread
        import threading
        update_thread = threading.Thread(target=update_worker, daemon=True)
        update_thread.start()
    
    def show_schedule_manager(self):
        # Show unified schedule manager
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()
    
    def show_server_schedule(self):
        # Show schedule manager for the selected server
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()
    
    def show_database_sync_manager(self):
        # Show database sync configuration dialog
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        
        if not self.agent_manager:
            messagebox.showerror("Error", "Cluster manager not available. Database syncing requires cluster configuration.")
            return
        
        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Database Sync Manager")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="Database Synchronization", font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Status section
        status_frame = ttk.LabelFrame(main_frame, text="Current Status", padding=10)
        status_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Status variables
        sync_status = self.timer_manager.get_database_sync_status()
        
        status_text = "Enabled" if sync_status['enabled'] else "Disabled"
        status_color = "green" if sync_status['enabled'] else "red"
        
        status_label = ttk.Label(status_frame, text=f"Status: {status_text}", foreground=status_color)
        status_label.pack(anchor=tk.W)
        
        interval_label = ttk.Label(status_frame, text=f"Sync Interval: {sync_status['interval_seconds']} seconds")
        interval_label.pack(anchor=tk.W, pady=(5, 0))
        
        if sync_status['last_sync']:
            last_sync_label = ttk.Label(status_frame, text=f"Last Sync: {sync_status['last_sync']}")
            last_sync_label.pack(anchor=tk.W, pady=(5, 0))
        
        if sync_status['next_sync']:
            next_sync_label = ttk.Label(status_frame, text=f"Next Sync: {sync_status['next_sync']}")
            next_sync_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Configuration section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=10)
        config_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Enable/Disable checkbox
        enabled_var = tk.BooleanVar(value=sync_status['enabled'])
        enabled_cb = ttk.Checkbutton(config_frame, text="Enable database synchronization", 
                                   variable=enabled_var)
        enabled_cb.pack(anchor=tk.W, pady=(0, 10))
        
        # Interval setting
        interval_frame = ttk.Frame(config_frame)
        interval_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(interval_frame, text="Sync interval (seconds):").pack(side=tk.LEFT)
        interval_var = tk.StringVar(value=str(sync_status['interval_seconds']))
        interval_entry = ttk.Entry(interval_frame, textvariable=interval_var, width=10)
        interval_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        # Info text
        info_text = ("Database synchronization will periodically sync server configurations, "
                    "user data, and cluster settings across all online cluster nodes.\n\n"
                    "This ensures consistency across your cluster and prevents configuration drift.")
        
        info_label = ttk.Label(config_frame, text=info_text, wraplength=400, justify=tk.LEFT)
        info_label.pack(anchor=tk.W, pady=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        def apply_settings():
            try:
                interval = int(interval_var.get())
                if interval < 60:
                    messagebox.showerror("Error", "Sync interval must be at least 60 seconds.")
                    return
                
                if enabled_var.get():
                    self.timer_manager.enable_database_sync(interval)
                    messagebox.showinfo("Success", "Database synchronization enabled.")
                else:
                    self.timer_manager.disable_database_sync()
                    messagebox.showinfo("Success", "Database synchronization disabled.")
                
                dialog.destroy()
                
            except ValueError:
                messagebox.showerror("Error", "Invalid interval value. Please enter a number.")
        
        def sync_now():
            if not sync_status['enabled']:
                messagebox.showerror("Error", "Database synchronization is disabled.")
                return
            
            # Run sync immediately
            import threading
            sync_thread = threading.Thread(target=self.timer_manager.sync_cluster_databases, daemon=True)
            sync_thread.start()
            
            messagebox.showinfo("Sync Started", "Database synchronization started in background.")
        
        apply_btn = ttk.Button(button_frame, text="Apply Settings", command=apply_settings)
        apply_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        sync_btn = ttk.Button(button_frame, text="Sync Now", command=sync_now)
        sync_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        cancel_btn = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_btn.pack(side=tk.RIGHT)
        
        # Centre dialog
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
    
    def update_all_servers(self, scheduled=False):
        # Update all Steam servers
        # scheduled: bool - If True, skip confirmation dialogs and close progress dialog automatically
        if not self.update_manager:
            if not scheduled:
                messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Confirm update only for manual updates
        if not scheduled:
            result = messagebox.askyesno("Confirm Update All", 
                "Are you sure you want to update all Steam servers?\n\n"
                "This will stop all running Steam servers during the update process.")
            
            if not result:
                return
        
        # Show progress dialog only for manual updates
        progress_dialog = None
        if not scheduled:
            progress_dialog = create_progress_dialog_with_console(self.root, "Updating All Steam Servers")
        
        def update_all_worker():
            try:
                def progress_callback(message):
                    try:
                        if progress_dialog and hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        elif not scheduled:
                            # For manual updates without progress dialog, print to console
                            print(message)
                        # For scheduled updates, log messages but don't show dialogs
                        if scheduled:
                            logger.info(message)
                    except Exception as e:
                        if not scheduled:
                            print(f"Console callback error: {e}, message: {message}")
                        logger.error(f"Console callback error: {e}, message: {message}")

                if self.update_manager:
                    # Use scheduled parameter to control dialog behavior in update manager
                    results = self.update_manager.update_all_steam_servers(progress_callback=progress_callback, scheduled=scheduled)
                else:
                    results = {"error": (False, "Update manager not available")}
                
                # Count successes and failures
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                
                if progress_callback:
                    progress_callback(f"\n[SUMMARY] Updates complete: {successes} successful, {failures} failed")
                
                # Show detailed results only for manual updates
                def show_results():
                    if not scheduled:
                        # For manual updates, show results dialog
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
                        
                        # Close progress dialog automatically after user clicks OK on results dialog
                        if progress_dialog:
                            progress_dialog.complete("Updates completed", auto_close=True)
                    else:
                        # For scheduled updates, just log the results
                        if failures > 0:
                            failed_servers = [name for name, (success, _) in results.items() if not success]
                            logger.warning(f"Scheduled update completed with failures. Successful: {successes}, Failed: {failures}. Failed servers: {', '.join(failed_servers)}")
                        else:
                            logger.info(f"Scheduled update completed successfully. Updated {successes} servers.")
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch update failed: {str(e)}"
                logger.error(error_msg)
                if not scheduled:
                    def show_exception_error():
                        messagebox.showerror("Error", error_msg)
                        # Close progress dialog automatically after user clicks OK
                        if progress_dialog:
                            progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_exception_error)
        
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
                        # Use the update_console method which is more robust
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        else:
                            print(message)
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")

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
                    
                    # Close progress dialog automatically after user clicks OK on results dialog
                    progress_dialog.complete("Restarts completed", auto_close=True)
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch restart failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Restart failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start restart in background thread
        import threading
        restart_thread = threading.Thread(target=restart_all_worker, daemon=True)
        restart_thread.start()

    def show_console_manager(self):
        # Show console manager dialog with list of active consoles
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
        # Batch update all server types using database-based detection
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
            centre_window(progress_dialog, 400, 150, self.root)
            
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
                    for server in servers[:10]:
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

    def kill_server_process(self):
        # Kill the process for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return
            
        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
        
        server_name = current_list.item(selected[0])['values'][0]
        current_subhost = self.get_current_subhost()
        
        # Confirm action
        if not messagebox.askyesno("Kill Process", 
                                 f"Are you sure you want to forcefully kill the process for '{server_name}'?\n\nThis action cannot be undone and may cause data loss.",
                                 parent=self.root):
            return
        
        # Try to kill via console manager first
        if self.console_manager and hasattr(self.console_manager, 'kill_process'):
            if self.console_manager.kill_process(server_name):
                # Also clean up the server config to remove stale PID
                if self.server_manager:
                    try:
                        server_config = self.server_manager.get_server_config(server_name)
                        if server_config:
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            self.server_manager.save_server_config(server_name, server_config)
                    except Exception as e:
                        logger.warning(f"Failed to clear PID from config after kill: {e}")
                
                messagebox.showinfo("Success", f"Process for '{server_name}' has been killed.", parent=self.root)
                self.update_server_list()
                return
        
        # Fallback: try to find and kill the process directly
        try:
            # Get server configuration
            if self.server_manager:
                server_config = self.server_manager.get_server_config(server_name)
                if server_config:
                    # Try to find process by executable path
                    exe_path = server_config.get('ExecutablePath', '')
                    if exe_path and os.path.exists(exe_path):
                        import psutil
                        exe_name = os.path.basename(exe_path)
                        
                        # Look for processes with matching executable name
                        killed = False
                        for proc in psutil.process_iter(['pid', 'name', 'exe']):
                            try:
                                if proc.info['name'] == exe_name or (proc.info['exe'] and os.path.basename(proc.info['exe']) == exe_name):
                                    logger.info(f"Killing process {proc.info['pid']} for {server_name}")
                                    proc.kill()
                                    killed = True
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                        
                        if killed:
                            # Clear PID from config and console state
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            self.server_manager.save_server_config(server_name, server_config)
                            
                            # Clean up console state
                            if self.console_manager:
                                try:
                                    self.console_manager.cleanup_console_on_stop(server_name)
                                except Exception:
                                    pass
                            
                            messagebox.showinfo("Success", f"Process for '{server_name}' has been killed.", parent=self.root)
                            self.update_server_list()
                            return
            
            messagebox.showerror("Error", f"Could not find or kill process for '{server_name}'.", parent=self.root)
            
        except Exception as e:
            logger.error(f"Error killing process for {server_name}: {e}")
            messagebox.showerror("Error", f"Failed to kill process: {str(e)}", parent=self.root)

    def create_category(self):
        # Create a new server category
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        # Prompt for category name
        category_name = simpledialog.askstring("Create Category", "Enter category name:", parent=self.root)
        if not category_name or not category_name.strip():
            return

        category_name = category_name.strip()

        # Check if category already exists
        categories = load_categories(self.server_manager_dir)
        if category_name in categories:
            messagebox.showerror("Error", f"Category '{category_name}' already exists.")
            return

        # Add category to database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.add_category(category_name):
            # Refresh categories in the UI
            self.refresh_categories()
            logger.info(f"Created category: {category_name}")
        else:
            messagebox.showerror("Error", f"Failed to create category '{category_name}'.")

    def rename_category(self):
        # Rename an existing category
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a category first.")
            return

        item = selected_items[0]
        item_values = current_list.item(item)['values']

        # Check if this is a category (no server name in second column)
        if item_values[1]:  # Has server name, so it's a server
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        current_name = item_values[0]

        # Prompt for new category name
        new_name = simpledialog.askstring("Rename Category", "Enter new category name:", initialvalue=current_name, parent=self.root)
        if not new_name or not new_name.strip() or new_name.strip() == current_name:
            return

        new_name = new_name.strip()

        # Check if new name already exists
        categories = load_categories(self.server_manager_dir)
        if new_name in categories:
            messagebox.showerror("Error", f"Category '{new_name}' already exists.")
            return

        # Rename category in database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.rename_category(current_name, new_name):
            # Update server configurations
            self._update_servers_category(current_name, new_name)

            # Refresh categories in the UI
            self.refresh_categories()

            logger.info(f"Renamed category from '{current_name}' to '{new_name}'")
        else:
            messagebox.showerror("Error", f"Failed to rename category '{current_name}'.")

    def delete_category(self):
        # Delete a category and move all servers to "Uncategorized"
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a category first.")
            return

        item = selected_items[0]
        item_values = current_list.item(item)['values']

        # Check if this is a category (no server name in second column)
        if item_values[1]:  # Has server name, so it's a server
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        category_name = item_values[0]

        # Don't allow deleting "Uncategorized"
        if category_name == "Uncategorized":
            messagebox.showerror("Error", "Cannot delete the 'Uncategorized' category.")
            return

        # Confirm deletion
        if not messagebox.askyesno("Delete Category", 
                                 f"Are you sure you want to delete the category '{category_name}'?\n\nAll servers in this category will be moved to 'Uncategorized'.",
                                 parent=self.root):
            return

        # Delete category from database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.delete_category(category_name):
            # Update server configurations
            self._update_servers_category(category_name, "Uncategorized")

            # Refresh categories in the UI
            self.refresh_categories()

            logger.info(f"Deleted category '{category_name}', moved servers to 'Uncategorized'")
        else:
            messagebox.showerror("Error", f"Failed to delete category '{category_name}'.")

    def _update_servers_category(self, old_category, new_category):
        # Update the category for all servers in the old category to the new category
        try:
            servers_path = self.paths["servers"]
            if not os.path.exists(servers_path):
                return

            updated_count = 0
            for file in os.listdir(servers_path):
                if file.endswith(".json"):
                    try:
                        file_path = os.path.join(servers_path, file)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            server_config = json.load(f)

                        # Update category if it matches the old category
                        if server_config.get('Category') == old_category:
                            server_config['Category'] = new_category

                            # Save updated configuration
                            with open(file_path, 'w', encoding='utf-8') as f:
                                json.dump(server_config, f, indent=2, ensure_ascii=False)

                            updated_count += 1

                    except Exception as e:
                        logger.error(f"Error updating category for server {file}: {str(e)}")

            if updated_count > 0:
                logger.info(f"Updated category from '{old_category}' to '{new_category}' for {updated_count} servers")

        except Exception as e:
            logger.error(f"Error updating server categories: {str(e)}")

    def refresh_categories(self):
        # Refresh only the category structure in the current server list without full server refresh
        current_list = self.get_current_server_list()
        if not current_list:
            logger.warning("refresh_categories: No current server list available")
            return

        logger.debug("refresh_categories: Starting category refresh")

        # Get current servers data (preserve existing data)
        # We need to iterate through category items and their children
        current_servers = {}
        for category_item in current_list.get_children():
            try:
                # Get children (servers) of this category
                for server_item in current_list.get_children(category_item):
                    try:
                        item = current_list.item(server_item)
                        if item and 'values' in item and len(item['values']) >= 1:
                            values = item['values']
                            server_name = values[0]
                            if server_name and len(values) > 1 and values[1]:  # Has server name and status
                                current_servers[server_name] = {
                                    'status': values[1] if len(values) > 1 else 'Unknown',
                                    'pid': values[2] if len(values) > 2 else '',
                                    'cpu': values[3] if len(values) > 3 else '0%',
                                    'memory': values[4] if len(values) > 4 else '0 MB',
                                    'uptime': values[5] if len(values) > 5 else '00:00:00',
                                    'category': 'Uncategorized'  # Will be updated from server config
                                }
                    except Exception as e:
                        logger.debug(f"Error processing server item {server_item}: {e}")
            except Exception as e:
                logger.debug(f"Error processing category item {category_item}: {e}")

        logger.debug(f"refresh_categories: Found {len(current_servers)} servers to reorganize")

        # Get updated categories from database
        from Host.dashboard_functions import load_categories
        all_categories = load_categories(self.server_manager_dir)
        logger.debug(f"refresh_categories: Loaded {len(all_categories)} categories from database")

        # Clear existing items
        for item in current_list.get_children():
            current_list.delete(item)

        # Group servers by category
        categories = {}
        for category in all_categories:
            categories[category] = []

        # Get server categories from their configurations (re-read from disk to get updated values)
        for server_name in current_servers.keys():
            try:
                # Read category directly from server config file for fresh data
                servers_path = self.paths.get("servers", "")
                config_file = os.path.join(servers_path, f"{server_name}.json")
                if os.path.exists(config_file):
                    with open(config_file, 'r', encoding='utf-8') as f:
                        server_config = json.load(f)
                    category = server_config.get('Category', 'Uncategorized')
                else:
                    category = 'Uncategorized'
                current_servers[server_name]['category'] = category
                logger.debug(f"refresh_categories: Server '{server_name}' -> category '{category}'")
            except Exception as e:
                logger.debug(f"Error getting category for {server_name}: {e}")
                current_servers[server_name]['category'] = 'Uncategorized'

        for server_name, server_info in current_servers.items():
            category = server_info.get('category', 'Uncategorized')
            if category not in categories:
                categories[category] = []
            categories[category].append((server_name, server_info))

        # Add categories and servers to Treeview
        for category_name in all_categories:
            servers = categories.get(category_name, [])

            # Insert category as parent (even if empty)
            category_item = current_list.insert("", tk.END, text=category_name,
                                             values=(category_name, "", "", "", "", ""),
                                             open=True, tags=('category',))

            # Add servers under category
            for server_name, server_info in servers:
                try:
                    status = server_info.get('status', 'Unknown')
                    pid = server_info.get('pid', '')
                    cpu = server_info.get('cpu', '0%')
                    memory = server_info.get('memory', '0 MB')
                    uptime = server_info.get('uptime', '00:00:00')

                    current_list.insert(category_item, tk.END, values=(
                        server_name, status, pid, cpu, memory, uptime
                    ), tags=('server',))
                except Exception as e:
                    logger.error(f"Error adding server {server_name} to category refresh: {e}")

        logger.info(f"Categories refreshed successfully - {len(current_servers)} servers in {len(all_categories)} categories")

    def show_help(self):
        # Show help dialog using the documentation module
        show_help_dialog(self.root, logger)

    def show_settings_dialog(self):
        # Show settings dialog for editing configuration
        import tkinter as tk
        from tkinter import ttk, messagebox
        
        # Create settings dialog
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("800x600")
        settings_window.resizable(True, True)
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # Centre the dialog
        settings_window.update_idletasks()
        x = (settings_window.winfo_screenwidth() // 2) - (settings_window.winfo_width() // 2)
        y = (settings_window.winfo_screenheight() // 2) - (settings_window.winfo_height() // 2)
        settings_window.geometry(f"+{x}+{y}")
        
        # Create notebook for different settings categories
        notebook = ttk.Notebook(settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Dashboard Settings Tab
        dashboard_frame = ttk.Frame(notebook)
        notebook.add(dashboard_frame, text="Dashboard")
        
        # Update Settings Tab
        update_frame = ttk.Frame(notebook)
        notebook.add(update_frame, text="Updates")
        
        # System Settings Tab
        system_frame = ttk.Frame(notebook)
        notebook.add(system_frame, text="System")
        
        # Load current configurations
        try:
            from Modules.Database.cluster_database import ClusterDatabase
            db = ClusterDatabase()
            
            dashboard_config = db.get_dashboard_config()
            update_config = db.get_update_config()
            main_config = db.get_main_config()
            
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load settings: {e}")
            settings_window.destroy()
            return
        
        # Dashboard Settings
        self._create_dashboard_settings_tab(dashboard_frame, dashboard_config, db)
        
        # Update Settings
        self._create_update_settings_tab(update_frame, update_config, db)
        
        # System Settings
        self._create_system_settings_tab(system_frame, main_config, db)
        
        # Buttons
        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="Save", command=lambda: self._save_settings(settings_window, db)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel", command=settings_window.destroy).pack(side=tk.RIGHT)
        
        # Store reference to prevent garbage collection
        self.settings_window = settings_window
    
    def _create_dashboard_settings_tab(self, parent, config, db):
        # Create dashboard settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Dashboard settings
        settings = [
            ("Debug Mode", "configuration.debugMode", config.get("configuration.debugMode", False), "boolean"),
            ("Offline Mode", "configuration.offlineMode", config.get("configuration.offlineMode", False), "boolean"),
            ("Hide Server Consoles", "configuration.hideServerConsoles", config.get("configuration.hideServerConsoles", True), "boolean"),
            ("System Refresh Interval", "configuration.systemRefreshInterval", config.get("configuration.systemRefreshInterval", 4), "integer"),
            ("Process Monitoring Interval", "configuration.processMonitoringInterval", config.get("configuration.processMonitoringInterval", 5), "integer"),
            ("Network Update Interval", "configuration.networkUpdateInterval", config.get("configuration.networkUpdateInterval", 5), "integer"),
            ("Server List Update Interval", "configuration.serverListUpdateInterval", config.get("configuration.serverListUpdateInterval", 30), "integer"),
            ("Window Width", "ui.windowWidth", config.get("ui.windowWidth", 1200), "integer"),
            ("Window Height", "ui.windowHeight", config.get("ui.windowHeight", 700), "integer"),
        ]
        
        self._create_settings_controls(scrollable_frame, settings, "dashboard")
    
    def _create_update_settings_tab(self, parent, config, db):
        # Create update settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Update settings - for now just show the raw JSON
        ttk.Label(scrollable_frame, text="Update Configuration (JSON):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))
        
        text_frame = ttk.Frame(scrollable_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        text_widget = tk.Text(text_frame, height=20, wrap=tk.WORD)
        text_scrollbar = ttk.Scrollbar(text_frame, command=text_widget.yview)
        text_widget.configure(yscrollcommand=text_scrollbar.set)
        
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Load current update config
        full_config = config.get("full_config", {})
        if isinstance(full_config, str):
            try:
                import json
                full_config = json.loads(full_config)
            except:
                full_config = {}
        
        import json
        text_widget.insert(tk.END, json.dumps(full_config, indent=2))
        
        # Store reference for saving
        self.update_config_text = text_widget
    
    def _create_system_settings_tab(self, parent, config, db):
        # Create system settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # System settings
        settings = [
            ("Version", "version", config.get("version", "0.1"), "string"),
            ("Web Port", "web_port", config.get("web_port", 8080), "integer"),
            ("Enable Auto Updates", "enable_auto_updates", config.get("enable_auto_updates", True), "boolean"),
            ("Enable Tray Icon", "enable_tray_icon", config.get("enable_tray_icon", True), "boolean"),
            ("Check Updates Interval", "check_updates_interval", config.get("check_updates_interval", 3600), "integer"),
            ("Log Level", "log_level", config.get("log_level", "INFO"), "string"),
            ("Max Log Size", "max_log_size", config.get("max_log_size", 10485760), "integer"),
            ("Max Log Files", "max_log_files", config.get("max_log_files", 10), "integer"),
        ]
        
        self._create_settings_controls(scrollable_frame, settings, "main")
    
    def _create_settings_controls(self, parent, settings, config_type):
        # Create form controls for settings
        self.settings_vars = getattr(self, 'settings_vars', {})
        self.settings_vars[config_type] = {}
        
        for label_text, key, default_value, value_type in settings:
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, padx=10, pady=2)
            
            ttk.Label(frame, text=f"{label_text}:", width=25, anchor=tk.W).pack(side=tk.LEFT)
            
            if value_type == "boolean":
                var = tk.BooleanVar(value=default_value)
                control = ttk.Checkbutton(frame, variable=var)
                control.pack(side=tk.LEFT)
            elif value_type == "integer":
                var = tk.StringVar(value=str(default_value))
                control = ttk.Entry(frame, textvariable=var, width=20)
                control.pack(side=tk.LEFT)
            else:  # string
                var = tk.StringVar(value=str(default_value))
                control = ttk.Entry(frame, textvariable=var, width=30)
                control.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            self.settings_vars[config_type][key] = (var, value_type)
    
    def _save_settings(self, window, db):
        # Save all settings to database
        try:
            # Save dashboard settings
            if "dashboard" in self.settings_vars:
                for key, (var, value_type) in self.settings_vars["dashboard"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    else:
                        value = var.get()
                    
                    db.set_dashboard_config(key, value, value_type, "settings")
            
            # Save update settings
            if hasattr(self, 'update_config_text'):
                import json
                try:
                    config_data = json.loads(self.update_config_text.get(1.0, tk.END))
                    db.set_update_config("full_config", config_data, "json", "settings")
                except json.JSONDecodeError as e:
                    messagebox.showerror("JSON Error", f"Invalid JSON in update config: {e}")
                    return
            
            # Save system settings
            if "main" in self.settings_vars:
                for key, (var, value_type) in self.settings_vars["main"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    else:
                        value = var.get()
                    
                    db.set_main_config(key, value, value_type, "settings")
            
            messagebox.showinfo("Settings Saved", "Settings have been saved successfully!")
            window.destroy()
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save settings: {e}")

    def show_about(self):
        # Show about dialog using the documentation module
        show_about_dialog(self.root, logger)

def main():
    import traceback as tb
    from Modules.server_logging import early_crash_log
    
    early_crash_log("Dashboard", "Startup initiated")
    
    try:
        parser = argparse.ArgumentParser(description='Server Manager Dashboard')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        args = parser.parse_args()

        dashboard = ServerManagerDashboard(debug_mode=args.debug)
        early_crash_log("Dashboard", "Started successfully")
        
        dashboard.run()
        early_crash_log("Dashboard", "Closed normally")
        
    except Exception as e:
        early_crash_log("Dashboard", f"FATAL ERROR: {e}")
        early_crash_log("Dashboard", f"Traceback: {tb.format_exc()}")
        
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Dashboard Startup Error", f"Failed to start dashboard:\n\n{e}\n\nCheck logs/components/Dashboard.log for details.")
            root.destroy()
        except:
            pass
        
        raise

main()
