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
    get_dashboard_logger, configure_dashboard_logging, write_pid_file,
    log_dashboard_event, log_server_action, log_installation_progress,
    log_process_monitoring, log_security_event, log_user_action
)

# Import timer management
from Modules.timer import TimerManager

# Get dashboard logger
logger = get_dashboard_logger()

class ServerManagerDashboard:
    def __init__(self, debug_mode=False):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.steam_cmd_path = None
        self.paths = {}
        self.servers = []
        self.debug_mode = debug_mode
        self.user_manager = None
        self.current_user = None
        self.config = {}
        self.install_process = None  # Track installation process
        
        # Initialize configuration and registry first
        if not self.initialize():
            logger.error("Failed to initialize dashboard")
            sys.exit(1)
        
        # Load dashboard configuration from JSON file
        self.load_dashboard_config()
        
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
        if not self.initialize_registry_values():
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
        except Exception as e:
            logger.error(f"Failed to initialize server manager: {e}")
            # Continue without server manager but log the error
            self.server_manager = None
            
        # Configure dashboard logging after paths are initialized
        configure_dashboard_logging(self.debug_mode, self.config)
        
        # Set up the UI
        self.root = tk.Tk()
        self.root.title("Server Manager Dashboard")
        self.root.geometry("1200x700")
        self.root.minsize(800, 600)
        
        self.setup_ui()
        
        # Write PID file
        write_pid_file("dashboard", os.getpid(), self.paths["temp"])
        
        # Initialize timer manager
        self.timer_manager = TimerManager(self)
        
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
        success, user = sql_login(self.user_manager, self.root)
        if not success:
            logger.info("Login cancelled, exiting application")
            self.root.destroy()
            sys.exit(0)
        self.current_user = user

    def load_dashboard_config(self):
        """Load dashboard configuration from JSON file"""
        try:
            if not self.server_manager_dir:
                logger.warning("Server manager directory not initialized, using default config")
                self.config = {}
                return
                
            config_file = os.path.join(self.server_manager_dir, "data", "dashboard.json")
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    self.config = json.load(f)
                logger.info(f"Loaded dashboard configuration from: {config_file}")
            else:
                logger.warning(f"Dashboard config file not found: {config_file}, using defaults")
                self.config = {}
        except Exception as e:
            logger.error(f"Failed to load dashboard configuration: {str(e)}")
            self.config = {}

    def initialize(self):
        """Initialize basic paths from registry"""
        try:
            # Read registry for basic paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Clean up path
            self.server_manager_dir = self.server_manager_dir.strip('"').strip()
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "modules": os.path.join(self.server_manager_dir, "modules"),
                "data": os.path.join(self.server_manager_dir, "data")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
            logger.info(f"Basic initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Basic initialization failed: {str(e)}")
            return False

    def initialize_registry_values(self):
        """Initialize registry-managed values"""
        try:
            # Read registry for all installation-managed values
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            
            # Try to get SteamCmd path
            try:
                self.steam_cmd_path = winreg.QueryValueEx(key, "SteamCmdPath")[0]
                self.variables["defaultSteamPath"] = self.steam_cmd_path
            except:
                self.steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
                self.variables["defaultSteamPath"] = self.steam_cmd_path
                logger.warning(f"SteamCmd path not found in registry, using default: {self.steam_cmd_path}")
                
            # Try to get WebPort from registry
            try:
                self.variables["webserverPort"] = int(winreg.QueryValueEx(key, "WebPort")[0])
            except:
                self.variables["webserverPort"] = 8080
                logger.warning(f"WebPort not found in registry, using default: 8080")
            
            # Read other registry values for reference (not stored in variables to avoid duplication)
            try:
                self.registry_values = {
                    "CurrentVersion": winreg.QueryValueEx(key, "CurrentVersion")[0],
                    "UserWorkspace": winreg.QueryValueEx(key, "UserWorkspace")[0],
                    "InstallDate": winreg.QueryValueEx(key, "InstallDate")[0],
                    "LastUpdate": winreg.QueryValueEx(key, "LastUpdate")[0],
                    "ModulePath": winreg.QueryValueEx(key, "ModulePath")[0],
                    "LogPath": winreg.QueryValueEx(key, "LogPath")[0],
                    "HostType": winreg.QueryValueEx(key, "HostType")[0]
                }
                
                # Try to get HostAddress if it exists (for subhost installations)
                try:
                    self.registry_values["HostAddress"] = winreg.QueryValueEx(key, "HostAddress")[0]
                except:
                    pass  # HostAddress only exists for subhost installations
                    
                logger.info("Registry values loaded successfully")
            except Exception as e:
                logger.warning(f"Some registry values could not be read: {str(e)}")
                self.registry_values = {}
                
            winreg.CloseKey(key)
            
            # Set default install directory
            self.variables["defaultInstallDir"] = os.path.join(self.steam_cmd_path, "steamapps", "common")
            
            logger.info(f"Registry initialization complete")
            return True
            
        except Exception as e:
            logger.error(f"Registry initialization failed: {str(e)}")
            return False
    
    def setup_ui(self):
        """Setup the main UI components"""
        # Create main container
        self.container_frame = ttk.Frame(self.root, padding=10)
        self.container_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create main layout - servers list and system info
        self.main_pane = ttk.PanedWindow(self.container_frame, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Create frame for server list (left side)
        self.servers_frame = ttk.LabelFrame(self.main_pane, text="Game Servers")
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
        
        # Define column widths
        self.server_list.column("name", width=150)
        self.server_list.column("status", width=80)
        self.server_list.column("pid", width=60)
        self.server_list.column("cpu", width=80)
        self.server_list.column("memory", width=100)
        self.server_list.column("uptime", width=150)
        
        # Add scrollbar to server list
        server_scroll = ttk.Scrollbar(self.servers_frame, orient=tk.VERTICAL, command=self.server_list.yview)
        self.server_list.configure(yscrollcommand=server_scroll.set)
        
        # Pack server list components
        server_scroll.pack(side=tk.RIGHT, fill=tk.Y)
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
        self.server_context_menu.add_command(label="Open Folder Directory", command=self.open_server_directory)
        self.server_context_menu.add_command(label="Remove Server", command=self.remove_server)
        
        # Bind right-click to server list
        self.server_list.bind("<Button-3>", self.show_server_context_menu)
        
        # Create system info frame (right side)
        self.system_frame = ttk.LabelFrame(self.main_pane, text="System Information")
        self.main_pane.add(self.system_frame, weight=30)
        
        # System info header
        self.system_header = ttk.Frame(self.system_frame)
        self.system_header.pack(fill=tk.X, padx=10, pady=10)
        
        self.system_name = ttk.Label(self.system_header, text="Loading system info...", font=("Segoe UI", 14, "bold"))
        self.system_name.pack(anchor=tk.W)
        
        self.os_info = ttk.Label(self.system_header, text="Loading OS info...", foreground="gray")
        self.os_info.pack(anchor=tk.W)
        
        # Show installation info from registry
        if hasattr(self, 'registry_values'):
            install_info = ttk.Label(self.system_header, 
                text=f"Version: {self.registry_values.get('CurrentVersion', 'Unknown')} | "
                     f"Host Type: {self.registry_values.get('HostType', 'Unknown')}", 
                foreground="gray")
            install_info.pack(anchor=tk.W)
        
        # Web server status
        self.webserver_frame = ttk.Frame(self.system_header)
        self.webserver_frame.pack(anchor=tk.W, pady=5)
        
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
        self.offline_check.pack(side=tk.LEFT, padx=10)
        
        # System metrics grid
        self.metrics_frame = ttk.Frame(self.system_frame, padding=(10, 5))
        self.metrics_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Configure grid columns and rows
        for i in range(2):
            self.metrics_frame.columnconfigure(i, weight=1)
        for i in range(3):
            self.metrics_frame.rowconfigure(i, weight=1)
        
        # Create metric panels
        self.metric_labels = {}
        
        metrics = [
            {"row": 0, "col": 0, "title": "CPU", "name": "cpu", "icon": "(CPU)"},
            {"row": 0, "col": 1, "title": "Memory", "name": "memory", "icon": "(MEM)"},
            {"row": 1, "col": 0, "title": "Disk Space", "name": "disk", "icon": "(DSK)"},
            {"row": 1, "col": 1, "title": "Network", "name": "network", "icon": "(NET)"},
            {"row": 2, "col": 0, "title": "GPU", "name": "gpu", "icon": "(GPU)"},
            {"row": 2, "col": 1, "title": "System Uptime", "name": "uptime", "icon": "(UP)"}
        ]
        
        for metric in metrics:
            frame = ttk.LabelFrame(self.metrics_frame, text=f"{metric['icon']} {metric['title']}")
            frame.grid(row=metric["row"], column=metric["col"], padx=5, pady=5, sticky="nsew")
            
            value = ttk.Label(frame, text="Loading...", font=("Segoe UI", 11))
            value.pack(anchor=tk.W, padx=5, pady=5)
            
            self.metric_labels[metric["name"]] = value
        
        # Create button bar at bottom
        self.button_frame = ttk.Frame(self.container_frame)
        self.button_frame.pack(fill=tk.X, pady=10)
        
        # Add buttons
        buttons = [
            {"text": "Add Server", "command": self.add_server},
            {"text": "Remove Server", "command": self.remove_server},
            {"text": "Import Server", "command": self.import_server},
            {"text": "Refresh", "command": self.refresh_all},
            {"text": "Sync All", "command": self.sync_all},
            {"text": "Add Agent", "command": self.add_agent}
        ]
        
        for btn in buttons:
            ttk.Button(self.button_frame, text=btn["text"], command=btn["command"], width=15).pack(side=tk.LEFT, padx=5)
    
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
        else:
            # Disable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Start Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Restart Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("View Process Details", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Configure Server", state=tk.DISABLED)
            
        # Show context menu
        self.server_context_menu.tk_popup(event.x_root, event.y_root)
    
    def get_steam_credentials(self):
        """Open a dialog to get Steam credentials"""
        credentials = {"anonymous": False, "username": "", "password": ""}
        
        # Create dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title("Steam Login")
        dialog.geometry("300x250")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Username field
        ttk.Label(dialog, text="Username:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        username_var = tk.StringVar()
        username_entry = ttk.Entry(dialog, textvariable=username_var, width=25)
        username_entry.grid(row=0, column=1, padx=10, pady=10)
        
        # Password field
        ttk.Label(dialog, text="Password:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        password_var = tk.StringVar()
        password_entry = ttk.Entry(dialog, textvariable=password_var, width=25, show="*")
        password_entry.grid(row=1, column=1, padx=10, pady=10)
        
        # Result variable
        result = {"success": False}
        
        # Button actions
        def on_login():
            credentials["username"] = username_var.get()
            credentials["password"] = password_var.get()
            credentials["anonymous"] = False
            result["success"] = True
            dialog.destroy()
            
        def on_anonymous():
            credentials["anonymous"] = True
            result["success"] = True
            dialog.destroy()
            
        def on_cancel():
            dialog.destroy()
        
        # Buttons
        ttk.Button(dialog, text="Login", command=on_login).grid(row=3, column=0, columnspan=2, padx=10, pady=10)
        ttk.Button(dialog, text="Anonymous", command=on_anonymous).grid(row=4, column=0, columnspan=2, padx=10, pady=5)
        ttk.Button(dialog, text="Cancel", command=on_cancel).grid(row=5, column=0, columnspan=2, padx=10, pady=5)
        
        # Center dialog on parent window
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Wait for dialog to close
        self.root.wait_window(dialog)
        
        # Return credentials if successful, None otherwise
        return credentials if result["success"] else None
        exe_row = install_dir_row + 2
        if server_type in ("Minecraft", "Other"):
            ttk.Label(dialog, text="Executable Path:").grid(row=exe_row, column=0, padx=10, pady=10, sticky=tk.W)
            exe_var = tk.StringVar()
            exe_entry = ttk.Entry(dialog, textvariable=exe_var, width=35)
            exe_entry.grid(row=exe_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            def browse_exe():
                fp = filedialog.askopenfilename(title="Select Executable",
                    filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd"),("All","*.*")])
                if fp:
                    exe_var.set(fp)
            ttk.Button(dialog, text="Browse", command=browse_exe, width=10).grid(row=exe_row, column=2, padx=5, pady=10)
            args_row = exe_row + 1
        else:
            exe_var = tk.StringVar(value="")
            args_row = exe_row

        # Startup Args (all)
        ttk.Label(dialog, text="Startup Args:").grid(row=args_row, column=0, padx=10, pady=10, sticky=tk.W)
        args_var = tk.StringVar()
        args_entry = ttk.Entry(dialog, textvariable=args_var, width=35)
        args_entry.grid(row=args_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)

        # Console output
        console_row = args_row + 1
        ttk.Label(dialog, text="Installation Progress:").grid(row=console_row, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        console_frame = ttk.Frame(dialog)
        console_frame.grid(row=console_row+1, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        console_output = scrolledtext.ScrolledText(console_frame, width=70, height=10, background="black", foreground="white")
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var)
        status_label.grid(row=console_row+2, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        progress = ttk.Progressbar(dialog, mode="indeterminate")
        progress.grid(row=console_row+3, column=0, columnspan=3, padx=10, pady=5, sticky="ew")

        dialog.grid_rowconfigure(console_row+1, weight=1)
        for i in range(3):
            dialog.grid_columnconfigure(i, weight=1 if i == 1 else 0)

        self.install_cancelled = False
        def append_console(text):
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)

    def add_server(self):
        """Add a new game server (Steam, Minecraft, or Other)"""
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Select server type dialog
        type_dialog = tk.Toplevel(self.root)
        type_dialog.title("Select Server Type")
        type_dialog.geometry("300x200")
        type_dialog.transient(self.root)
        type_dialog.grab_set()
        ttk.Label(type_dialog, text="Select Server Type:").pack(pady=10)
        type_var = tk.StringVar(value="Steam")
        for stype in self.supported_server_types:
            ttk.Radiobutton(type_dialog, text=stype, variable=type_var, value=stype).pack(anchor=tk.W, padx=30)
        def proceed():
            type_dialog.destroy()
        ttk.Button(type_dialog, text="Next", command=proceed).pack(pady=20)
        self.root.wait_window(type_dialog)
        server_type = type_var.get()

        if server_type == "Steam":
            credentials = self.get_steam_credentials()
            if not credentials:
                logger.debug("User cancelled Steam login")
                return
        else:
            credentials = None

        # Create dialog for server details
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Create {server_type} Server")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()

        # Server name
        ttk.Label(dialog, text="Server Name:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=35)
        name_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)

        # Server type (readonly)
        ttk.Label(dialog, text="Server Type:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        ttk.Label(dialog, text=server_type).grid(row=1, column=1, sticky=tk.W)

        # Minecraft version list (fetch only if needed)
        mc_versions = []
        if server_type == "Minecraft":
            try:
                mc_versions = self.server_manager.get_minecraft_versions()
                if not mc_versions:
                    messagebox.showerror("Error", "Could not fetch Minecraft versions from Mojang.")
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Minecraft support not available: {str(e)}")
                return
                
            # Default to latest release
            latest_release = next((v for v in mc_versions if v["id"] == mc_versions[0]["id"]), mc_versions[0])
            selected_version = tk.StringVar(value=latest_release["id"])
            
            # Minecraft version dropdown
            ttk.Label(dialog, text="Minecraft Version:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
            version_combo = ttk.Combobox(dialog, textvariable=selected_version, values=[v["id"] for v in mc_versions], state="readonly", width=32)
            version_combo.grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            
            # Modloader selection
            ttk.Label(dialog, text="Modloader:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
            selected_modloader = tk.StringVar(value="Vanilla")
            modloader_frame = ttk.Frame(dialog)
            modloader_frame.grid(row=3, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            modloaders = ["Vanilla", "Fabric", "Forge", "NeoForge"]
            for i, modloader in enumerate(modloaders):
                ttk.Radiobutton(modloader_frame, text=modloader, variable=selected_modloader, value=modloader).grid(row=0, column=i, padx=5, sticky=tk.W)
            
            app_id_row = 4
        else:
            selected_version = tk.StringVar(value="")
            selected_modloader = tk.StringVar(value="")
            app_id_row = 2

        # App ID (Steam only)
        if server_type == "Steam":
            ttk.Label(dialog, text="App ID:").grid(row=app_id_row, column=0, padx=10, pady=10, sticky=tk.W)
            app_id_var = tk.StringVar()
            app_id_entry = ttk.Entry(dialog, textvariable=app_id_var, width=35)
            app_id_entry.grid(row=app_id_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            install_dir_row = app_id_row + 1
        else:
            app_id_var = tk.StringVar(value="")
            install_dir_row = app_id_row

        # Install directory
        ttk.Label(dialog, text="Install Directory:").grid(row=install_dir_row, column=0, padx=10, pady=10, sticky=tk.W)
        install_dir_var = tk.StringVar()
        install_dir_entry = ttk.Entry(dialog, textvariable=install_dir_var, width=25)
        install_dir_entry.grid(row=install_dir_row, column=1, padx=10, pady=10, sticky=tk.W)
        ttk.Label(dialog, text="(Leave blank for default location)", foreground="gray").grid(row=install_dir_row+1, column=1, padx=10, sticky=tk.W)
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Installation Directory")
            if directory:
                install_dir_var.set(directory)
        ttk.Button(dialog, text="Browse", command=browse_directory, width=10).grid(row=install_dir_row, column=2, padx=5, pady=10)

        # Executable (Minecraft/Other)
        exe_row = install_dir_row + 2
        if server_type in ("Minecraft", "Other"):
            ttk.Label(dialog, text="Executable Path:").grid(row=exe_row, column=0, padx=10, pady=10, sticky=tk.W)
            exe_var = tk.StringVar()
            exe_entry = ttk.Entry(dialog, textvariable=exe_var, width=35)
            exe_entry.grid(row=exe_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            def browse_exe():
                fp = filedialog.askopenfilename(title="Select Executable",
                    filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd"),("All","*.*")])
                if fp:
                    exe_var.set(fp)
            ttk.Button(dialog, text="Browse", command=browse_exe, width=10).grid(row=exe_row, column=2, padx=5, pady=10)
            args_row = exe_row + 1
        else:
            exe_var = tk.StringVar(value="")
            args_row = exe_row

        # Startup Args (all)
        ttk.Label(dialog, text="Startup Args:").grid(row=args_row, column=0, padx=10, pady=10, sticky=tk.W)
        args_var = tk.StringVar()
        args_entry = ttk.Entry(dialog, textvariable=args_var, width=35)
        args_entry.grid(row=args_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)

        # Console output
        console_row = args_row + 1
        ttk.Label(dialog, text="Installation Progress:").grid(row=console_row, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        console_frame = ttk.Frame(dialog)
        console_frame.grid(row=console_row+1, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        console_output = scrolledtext.ScrolledText(console_frame, width=70, height=10, background="black", foreground="white")
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var)
        status_label.grid(row=console_row+2, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        progress = ttk.Progressbar(dialog, mode="indeterminate")
        progress.grid(row=console_row+3, column=0, columnspan=3, padx=10, pady=5, sticky="ew")

        dialog.grid_rowconfigure(console_row+1, weight=1)
        for i in range(3):
            dialog.grid_columnconfigure(i, weight=1 if i == 1 else 0)

        self.install_cancelled = False
        def append_console(text):
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)

        def install_server():
            try:
                server_name = name_var.get().strip()
                app_id = app_id_var.get().strip() if server_type == "Steam" else ""
                install_dir = install_dir_var.get().strip()
                executable_path = exe_var.get().strip() if server_type in ("Minecraft", "Other") else ""
                startup_args = args_var.get().strip()

                if not server_name:
                    messagebox.showerror("Validation Error", "Server name is required.")
                    return
                if server_type == "Steam" and (not app_id or not app_id.isdigit()):
                    messagebox.showerror("Validation Error", "Steam App ID must be a number.")
                    return
                if server_type in ("Minecraft", "Other") and server_type == "Other" and not executable_path:
                    messagebox.showerror("Validation Error", "Executable path is required for Other server types.")
                    return

                # Set default install dir if blank
                if not install_dir:
                    if server_type == "Steam":
                        if self.steam_cmd_path:
                            install_dir = os.path.join(self.steam_cmd_path, "steamapps", "common", server_name)
                        else:
                            install_dir = os.path.join("C:\\steamcmd", "steamapps", "common", server_name)
                    elif server_type == "Minecraft":
                        minecraft_path = self.config.get("defaults", {}).get("minecraftServersPath", "minecraft_servers")
                        if self.server_manager_dir:
                            install_dir = os.path.join(self.server_manager_dir, minecraft_path, server_name)
                        else:
                            install_dir = os.path.join(os.getcwd(), minecraft_path, server_name)
                    else:
                        other_path = self.config.get("defaults", {}).get("otherServersPath", "other_servers")
                        if self.server_manager_dir:
                            install_dir = os.path.join(self.server_manager_dir, other_path, server_name)
                        else:
                            install_dir = os.path.join(os.getcwd(), other_path, server_name)

                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                status_var.set("Installing server...")

                # Use server manager to install the server
                if self.server_manager:
                    success, message = self.server_manager.install_server_complete(
                        server_name=server_name,
                        server_type=server_type,
                        install_dir=install_dir,
                        executable_path=executable_path,
                        startup_args=startup_args,
                        app_id=app_id,
                        version=selected_version.get() if server_type == "Minecraft" else "",
                        modloader=selected_modloader.get() if server_type == "Minecraft" else "",
                        steam_cmd_path=self.steam_cmd_path or "",
                        credentials=credentials,
                        progress_callback=append_console
                    )
                else:
                    success = False
                    message = "Server manager not initialized"

                if success:
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

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=console_row+4, column=0, columnspan=3, padx=10, pady=10)
        create_button = ttk.Button(button_frame, text="Create", width=15)
        create_button.pack(side=tk.LEFT, padx=5)
        cancel_button = ttk.Button(button_frame, text="Cancel", width=15, state=tk.DISABLED)
        cancel_button.pack(side=tk.LEFT, padx=5)
        
        def start_installation():
            installation_thread = threading.Thread(target=install_server)
            installation_thread.daemon = True
            installation_thread.start()
            
        def cancel_installation():
            self.install_cancelled = True
            cancel_button.config(state=tk.DISABLED)
            status_var.set("Cancelling installation...")
            append_console("[INFO] Cancellation requested, stopping installation process...")
            
        create_button.config(command=start_installation)
        cancel_button.config(command=cancel_installation)
        
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
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def api_headers(self):
        # Remove API headers since we're using direct SQL access
        return {}

    def update_server_list(self, force_refresh=False):
        # Skip update if it's been less than configured interval since the last update and force_refresh isn't specified
        update_interval = self.variables.get("serverListUpdateInterval", 30)
        if not force_refresh and \
           (self.variables["lastServerListUpdate"] != datetime.datetime.min) and \
           (datetime.datetime.now() - self.variables["lastServerListUpdate"]).total_seconds() < update_interval:
            log_dashboard_event("SERVER_LIST_UPDATE", f"Skipping update - last update was less than {update_interval} seconds ago", "DEBUG")
            return
            
        # Clear current items
        for item in self.server_list.get_children():
            self.server_list.delete(item)
            
        # Get server configurations
        servers_path = self.paths["servers"]
        if os.path.exists(servers_path):
            for file in os.listdir(servers_path):
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(servers_path, file), 'r') as f:
                            server_config = json.load(f)
                            
                        # Check if server is running
                        status = "Offline"
                        pid = "N/A"
                        cpu_usage = "N/A"
                        memory_usage = "N/A"
                        uptime = "N/A"
                        
                        # Get process if running
                        if "ProcessId" in server_config:
                            try:
                                process_id = server_config["ProcessId"]
                                if self.is_process_running(process_id):
                                    process = psutil.Process(process_id)
                                    status = "Running"
                                    pid = str(process_id)
                                    
                                    # Get CPU usage
                                    try:
                                        cpu_usage = f"{process.cpu_percent(interval=0.1):.1f}%"
                                    except:
                                        cpu_usage = "N/A"
                                        
                                    # Get memory usage
                                    try:
                                        memory_mb = process.memory_info().rss / (1024 * 1024)
                                        memory_usage = f"{memory_mb:.1f} MB"
                                    except:
                                        memory_usage = "N/A"
                                        
                                    # Calculate uptime
                                    try:
                                        start_time = datetime.datetime.fromisoformat(server_config.get('StartTime', ''))
                                        uptime_delta = datetime.datetime.now() - start_time
                                        days = uptime_delta.days
                                        hours, remainder = divmod(uptime_delta.seconds, 3600)
                                        minutes, _ = divmod(remainder, 60)
                                        
                                        if days > 0:
                                            uptime = f"{days}d {hours}h {minutes}m"
                                        else:
                                            uptime = f"{hours}h {minutes}m"
                                    except:
                                        uptime = "Unknown"
                                else:
                                    # Process exists in config but is not running
                                    # Clean up the process ID in the config
                                    server_config.pop('ProcessId', None)
                                    server_config.pop('StartTime', None)
                                    server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                    
                                    # Clean up process history
                                    if process_id in self.variables["processStatHistory"]:
                                        del self.variables["processStatHistory"][process_id]
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                            except:
                                # Process doesn't exist, clean up the config
                                process_id = server_config.get("ProcessId", "N/A")
                                server_config.pop('ProcessId', None)
                                server_config.pop('StartTime', None)
                                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                
                                # Clean up process history
                                if process_id in self.variables["processStatHistory"]:
                                    del self.variables["processStatHistory"][process_id]
                                
                                # Save updated configuration
                                with open(os.path.join(servers_path, file), 'w') as f:
                                    json.dump(server_config, f, indent=4)
                                
                        # Add to list
                        self.server_list.insert("", tk.END, values=(
                            server_config["Name"],
                            status,
                            pid,
                            cpu_usage,
                            memory_usage,
                            uptime
                        ))
                        
                    except Exception as e:
                        logger.error(f"Failed to process server config {file}: {str(e)}")
        
        # Update last refresh time
        self.variables["lastServerListUpdate"] = datetime.datetime.now()
        self.variables["lastProcessUpdate"] = datetime.datetime.now()
    
    def check_webserver_status(self):
        """Check if the web server is running and return status"""
        if self.variables["offlineMode"]:
            return "Offline Mode"
            
        try:
            # Try to read the web server PID file first
            webserver_pid_file = os.path.join(self.paths["temp"], "webserver.pid")
            if os.path.exists(webserver_pid_file):
                try:
                    with open(webserver_pid_file, 'r') as f:
                        pid_info = json.load(f)
                    
                    pid = pid_info.get("ProcessId")
                    port = pid_info.get("Port", self.variables["webserverPort"])
                    
                    # Update web port from PID file if available
                    if port:
                        self.variables["webserverPort"] = port
                    
                    # Check if process is running
                    if pid and self.is_process_running(pid):
                        return "Connected"
                except Exception as e:
                    logger.debug(f"Error checking web server PID file: {str(e)}")
            
            # If we get here, try to connect to the port directly
            if self.is_port_open('localhost', self.variables["webserverPort"]):
                return "Connected"
            else:
                return "Disconnected"
                
        except Exception as e:
            logger.error(f"Error checking web server status: {str(e)}")
            return "Error"
    
    def is_process_running(self, pid):
        """Check if a process with the given PID is running"""
        try:
            return psutil.pid_exists(pid)
        except:
            return False
    
    def is_port_open(self, host, port, timeout=1):
        """Check if a port is open on the specified host"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False
    
    def toggle_offline_mode(self):
        """Toggle offline mode"""
        self.variables["offlineMode"] = self.offline_var.get()
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
    def update_webserver_status(self):
        """Update the web server status display"""
        try:
            status = self.check_webserver_status()
            self.variables["webserverStatus"] = status
            
            # Update status label with appropriate color
            if status == "Connected":
                self.webserver_status.config(text=status, foreground="green")
            elif status == "Offline Mode":
                self.webserver_status.config(text=status, foreground="orange")
            else:
                self.webserver_status.config(text=status, foreground="red")
                
            # Update offline mode checkbox
            self.offline_var.set(self.variables["offlineMode"])
            
        except Exception as e:
            logger.error(f"Error updating web server status: {str(e)}")
            self.webserver_status.config(text="Error", foreground="red")
    
    def update_system_info(self):
        """Update system information in the UI"""
        try:
            # Update web server status
            self.update_webserver_status()
            
            # Computer name and OS info
            computer_name = platform.node()
            os_info = f"{platform.system()} {platform.version()}"
            
            self.system_name.config(text=computer_name)
            self.os_info.config(text=os_info)
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.metric_labels["cpu"].config(text=f"{cpu_percent:.1f}%")
            
            # Memory usage
            memory = psutil.virtual_memory()
            total_mem_gb = memory.total / (1024 * 1024 * 1024)
            used_mem_gb = memory.used / (1024 * 1024 * 1024)
            self.metric_labels["memory"].config(text=f"{used_mem_gb:.1f} GB / {total_mem_gb:.1f} GB")
            
            # Disk usage
            disk_usage = []
            total_size = 0
            total_used = 0
            
            for part in psutil.disk_partitions(all=False):
                if part.fstype:
                    usage = psutil.disk_usage(part.mountpoint)
                    total_size += usage.total
                    total_used += usage.used
            
            total_size_gb = total_size / (1024 * 1024 * 1024)
            total_used_gb = total_used / (1024 * 1024 * 1024)
            
            self.metric_labels["disk"].config(text=f"{total_used_gb:.0f} GB / {total_size_gb:.0f} GB")
            
            # Network usage
            network_stats = psutil.net_io_counters()
            
            if self.variables["lastNetworkStats"]:
                last_stats = self.variables["lastNetworkStats"]
                last_time = self.variables["lastNetworkStatsTime"]
                time_diff = (datetime.datetime.now() - last_time).total_seconds()
                
                bytes_sent = network_stats.bytes_sent - last_stats.bytes_sent
                bytes_recv = network_stats.bytes_recv - last_stats.bytes_recv
                
                send_rate = bytes_sent / time_diff / 1024  # KB/s
                recv_rate = bytes_recv / time_diff / 1024  # KB/s
                
                if send_rate > 1024 or recv_rate > 1024:
                    send_rate = send_rate / 1024  # MB/s
                    recv_rate = recv_rate / 1024  # MB/s
                    self.metric_labels["network"].config(text=f"↓{recv_rate:.1f} MB/s | ↑{send_rate:.1f} MB/s")
                else:
                    self.metric_labels["network"].config(text=f"↓{recv_rate:.1f} KB/s | ↑{send_rate:.1f} KB/s")
            else:
                self.metric_labels["network"].config(text="Calculating...")
            
            self.variables["lastNetworkStats"] = network_stats
            self.variables["lastNetworkStatsTime"] = datetime.datetime.now()
            
            # GPU info - placeholder since getting GPU info is more complex
            self.metric_labels["gpu"].config(text="N/A")
            
            # System uptime
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.datetime.now() - boot_time
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
            self.metric_labels["uptime"].config(text=uptime_str)
            
            # Update last refresh time
            self.variables["lastFullUpdate"] = datetime.datetime.now()
            
        except Exception as e:
            logger.error(f"Error updating system info: {str(e)}")
    
    def run(self):
        """Run the dashboard application"""
        logger.info("Starting dashboard")
        
        # Initial updates
        self.update_server_list(force_refresh=True)
        
        # Show the window
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.variables["formDisplayed"] = True
        
        # Center window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')
        
        # Start main loop
        self.root.mainloop()
    
    def on_close(self):
        """Handle window close event"""
        logger.info("Dashboard closing")
        
        # Clean up resources
        try:
            # Remove PID file
            pid_file = os.path.join(self.paths["temp"], "dashboard.pid")
            if os.path.exists(pid_file):
                os.remove(pid_file)
                logger.debug("Removed PID file")
                
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
            
        try:
            # Use the server manager to start the server
            success, message = self.server_manager.start_server_advanced(
                server_name, 
                callback=lambda status: self.update_server_status(server_name, status)
            )
            
            if success:
                messagebox.showinfo("Success", message)
                self.update_server_list(force_refresh=True)
            else:
                messagebox.showerror("Error", message)
                
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            messagebox.showerror("Error", f"Failed to start server: {str(e)}")

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
            
        try:
            # Use the server manager to stop the server
            success, message = self.server_manager.stop_server_advanced(
                server_name,
                callback=lambda status: self.update_server_status(server_name, status)
            )
            
            if success:
                messagebox.showinfo("Success", message)
                self.update_server_list(force_refresh=True)
            else:
                messagebox.showinfo("Info", message)
                self.update_server_list(force_refresh=True)
                
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            messagebox.showerror("Error", f"Failed to stop server: {str(e)}")
    
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
            
        try:
            # Use the server manager to restart the server
            success, message = self.server_manager.restart_server_advanced(
                server_name,
                callback=lambda status: self.update_server_status(server_name, status)
            )
            
            if success:
                messagebox.showinfo("Success", message)
                self.update_server_list(force_refresh=True)
            else:
                messagebox.showerror("Error", message)
                
        except Exception as e:
            logger.error(f"Error restarting server: {str(e)}")
            messagebox.showerror("Error", f"Failed to restart server: {str(e)}")
    
    def view_process_details(self):
        """View detailed process information for a server"""
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
            with open(config_file, 'r') as f:
                server_config = json.load(f)
                
            # Check if server has a process ID registered
            if 'ProcessId' not in server_config:
                messagebox.showinfo("Not Running", f"Server '{server_name}' is not running.")
                return
                
            process_id = server_config['ProcessId']
            
            # Check if process is still running
            if not self.is_process_running(process_id):
                messagebox.showinfo("Not Running", f"Server process (PID {process_id}) is not running.")
                return
                
            # Create detail dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Process Details: {server_name} (PID: {process_id})")
            dialog.geometry("600x500")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Create a frame with padding
            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Get process information
            try:
                process = psutil.Process(process_id)
                
                # Basic info
                info_frame = ttk.LabelFrame(main_frame, text="Basic Information")
                info_frame.pack(fill=tk.X, pady=(0, 10))
                
                # Get create time
                try:
                    create_time = datetime.datetime.fromtimestamp(process.create_time())
                    create_time_str = create_time.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    create_time_str = "Unknown"
                
                # Calculate uptime
                if 'StartTime' in server_config:
                    try:
                        start_time = datetime.datetime.fromisoformat(server_config['StartTime'])
                        uptime = datetime.datetime.now() - start_time
                        days = uptime.days
                        hours, remainder = divmod(uptime.seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        
                        if days > 0:
                            uptime_str = f"{days}d {hours}h {minutes}m"
                        else:
                            uptime_str = f"{hours}h {minutes}m {seconds}s"
                    except:
                        uptime_str = "Unknown"
                else:
                    uptime_str = "Unknown"
                
                # Create info grid
                info_grid = ttk.Frame(info_frame)
                info_grid.pack(fill=tk.X, padx=10, pady=10)
                
                # Row 1
                ttk.Label(info_grid, text="PID:", width=15).grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=str(process_id)).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
                
                ttk.Label(info_grid, text="Status:", width=15).grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=process.status()).grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
                
                
                # Row 2
                ttk.Label(info_grid, text="Started:", width=15).grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=create_time_str).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
                
                ttk.Label(info_grid, text="Uptime:", width=15).grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=uptime_str).grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
                
                # Row 3
                ttk.Label(info_grid, text="Executable:", width=15).grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
                exe_label = ttk.Label(info_grid, text=process.exe())
                exe_label.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)
                
                # System resource usage
                resource_frame = ttk.LabelFrame(main_frame, text="Resource Usage")
                resource_frame.pack(fill=tk.X, pady=(0, 10))
                
                # Get current CPU and memory usage
                cpu_percent = process.cpu_percent(interval=0.1)
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                
                # Create resource grid
                resource_grid = ttk.Frame(resource_frame)
                resource_grid.pack(fill=tk.X, padx=10, pady=10)
                
                # Row 1
                ttk.Label(resource_grid, text="CPU Usage:", width=15).grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
                ttk.Label(resource_grid, text=f"{cpu_percent:.1f}%").grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
                
                ttk.Label(resource_grid, text="Memory Usage:", width=15).grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
                ttk.Label(resource_grid, text=f"{memory_mb:.1f} MB").grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
                
                # Row 2
                ttk.Label(resource_grid, text="Threads:", width=15).grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
                ttk.Label(resource_grid, text=str(process.num_threads())).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
                
                ttk.Label(resource_grid, text="Open Files:", width=15).grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
                try:
                    open_files = len(process.open_files())
                    ttk.Label(resource_grid, text=str(open_files)).grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
                except:
                    ttk.Label(resource_grid, text="N/A").grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
                
                # Child processes
                child_frame = ttk.LabelFrame(main_frame, text="Child Processes")
                child_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
                
                # Create a list for child processes
                child_list = ttk.Treeview(child_frame, columns=("pid", "name", "status", "cpu", "memory"), show="headings")
                child_list.heading("pid", text="PID")
                child_list.heading("name", text="Name")
                child_list.heading("status", text="Status")
                child_list.heading("cpu", text="CPU %")
                child_list.heading("memory", text="Memory")
                
                child_list.column("pid", width=60)
                child_list.column("name", width=200)
                child_list.column("status", width=80)
                child_list.column("cpu", width=60)
                child_list.column("memory", width=80)
                
                # Add scrollbar to child list
                child_scroll = ttk.Scrollbar(child_frame, orient=tk.VERTICAL, command=child_list.yview)
                child_list.configure(yscrollcommand=child_scroll.set)
                
                # Pack child list components
                child_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                child_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                
                # Populate child list
                try:
                    children = process.children(recursive=False)
                    for child in children:
                        try:
                            child_cpu = child.cpu_percent(interval=0.1)
                            child_mem = child.memory_info().rss / (1024 * 1024)
                            child_list.insert("", tk.END, values=(
                                child.pid,
                                child.name(),
                                child.status(),
                                f"{child_cpu:.1f}",
                                f"{child_mem:.1f} MB"
                            ))
                        except:
                            # Process might have terminated
                            pass
                except:
                    ttk.Label(child_frame, text="Could not retrieve child processes").pack(padx=10, pady=10)
                
                # Log files
                log_frame = ttk.LabelFrame(main_frame, text="Log Files")
                log_frame.pack(fill=tk.X, pady=(0, 10))
                
                # Show log file paths
                log_grid = ttk.Frame(log_frame)
                log_grid.pack(fill=tk.X, padx=10, pady=10)
                
                # Stdout log
                if 'LogStdout' in server_config and server_config['LogStdout']:
                    ttk.Label(log_grid, text="Stdout Log:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
                    stdout_path = server_config['LogStdout']
                    path_label = ttk.Label(log_grid, text=stdout_path)
                    path_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
                    
                    # Add open button
                    def open_stdout_log():
                        try:
                            if os.path.exists(stdout_path):
                                if sys.platform == 'win32':
                                    os.startfile(stdout_path)
                                elif sys.platform == 'darwin':
                                    subprocess.call(['open', stdout_path])
                                else:
                                    subprocess.call(['xdg-open', stdout_path])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")
                    
                    ttk.Button(log_grid, text="Open", command=open_stdout_log, width=10).grid(row=0, column=2, padx=5, pady=2)
                
                # Stderr log
                if 'LogStderr' in server_config and server_config['LogStderr']:
                    ttk.Label(log_grid, text="Stderr Log:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
                    stderr_path = server_config['LogStderr']
                    path_label = ttk.Label(log_grid, text=stderr_path)
                    path_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
                    
                    # Add open button
                    def open_stderr_log():
                        try:
                            if os.path.exists(stderr_path):
                                if sys.platform == 'win32':
                                    os.startfile(stderr_path)
                                elif sys.platform == 'darwin':
                                    subprocess.call(['open', stderr_path])
                                else:
                                    subprocess.call(['xdg-open', stderr_path])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")
                    
                    ttk.Button(log_grid, text="Open", command=open_stderr_log, width=10).grid(row=1, column=2, padx=5, pady=2)
                
                # Action buttons
                button_frame = ttk.Frame(main_frame)
                button_frame.pack(fill=tk.X, pady=10)
                
                # Refresh button
                def refresh_process_info():
                    dialog.destroy()
                    self.view_process_details()
                
                ttk.Button(button_frame, text="Refresh", command=refresh_process_info, width=15).pack(side=tk.LEFT, padx=5)
                
                # Stop process button
                def stop_from_details():
                    dialog.destroy()
                    self.stop_server()
                
                ttk.Button(button_frame, text="Stop Process", command=stop_from_details, width=15).pack(side=tk.RIGHT, padx=5)
                
                # Close button
                ttk.Button(button_frame, text="Close", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
                
            except Exception as e:
                logger.error(f"Error getting process details: {str(e)}")
                ttk.Label(main_frame, text=f"Error retrieving process information: {str(e)}").pack(padx=10, pady=10)
                ttk.Button(main_frame, text="Close", command=dialog.destroy).pack(pady=10)
            
            # Center dialog on parent window
            dialog.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
            dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error viewing process details: {str(e)}")
            messagebox.showerror("Error", f"Failed to view process details: {str(e)}")
    
    def update_server_status(self, server_name, status):
        """Update the status of a server in the UI"""
        try:
            # Find the server in the treeview
            for item in self.server_list.get_children():
                if self.server_list.item(item)['values'][0] == server_name:
                    # Get current values
                    values = list(self.server_list.item(item)['values'])
                    # Update status (index 1)
                    values[1] = status
                    # Update the item
                    self.server_list.item(item, values=values)
                    break
            
            # Force UI update
            self.root.update_idletasks()
        except Exception as e:
            logger.error(f"Error updating server status in UI: {str(e)}")
    
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
        dialog.geometry("650x550")
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
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()-dialog.winfo_width())//2
        y = self.root.winfo_rooty() + (self.root.winfo_height()-dialog.winfo_height())//2
        dialog.geometry(f"+{x}+{y}")

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
            with open(config_file, 'r') as f:
                server_config = json.load(f)
                
            install_dir = server_config.get('InstallDir', '')
            
            if not install_dir:
                messagebox.showerror("Error", "Server installation directory not configured.")
                return
                
            if not os.path.exists(install_dir):
                messagebox.showerror("Error", f"Server installation directory not found: {install_dir}")
                return
                
            # Open directory in file explorer
            if sys.platform == 'win32':
                os.startfile(install_dir)
            elif sys.platform == 'darwin':
                subprocess.call(['open', install_dir])
            else:
                subprocess.call(['xdg-open', install_dir])
                
            logger.info(f"Opened directory for server '{server_name}': {install_dir}")
            
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
        
        # Create removal options dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Remove Server")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Server name
        ttk.Label(main_frame, text=f"Remove server: {server_name}", font=("Segoe UI", 12, "bold")).pack(pady=10)
        
        # Options
        remove_files_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(main_frame, text="Also remove server files from disk", 
                       variable=remove_files_var).pack(pady=5)
        
        ttk.Label(main_frame, text="Warning: This action cannot be undone!", 
                 foreground="red").pack(pady=5)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=20)
        
        def confirm_removal():
            try:
                remove_files = remove_files_var.get()
                
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
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", message)
                    
            except Exception as e:
                logger.error(f"Error removing server: {str(e)}")
                messagebox.showerror("Error", f"Failed to remove server: {str(e)}")
        
        def cancel_removal():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Remove", command=confirm_removal, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel_removal, width=15).pack(side=tk.LEFT, padx=5)
        
        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

    def import_server(self):
        """Import an existing server from a directory"""
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
            dialog.title("Import Server")
            dialog.geometry("500x400")
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
            
            # Center dialog
            dialog.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
            dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error during import: {str(e)}")
            messagebox.showerror("Error", f"Failed to import server: {str(e)}")
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to import server: {str(e)}")

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
            progress_dialog.geometry("400x150")
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
            
            # Center progress dialog
            progress_dialog.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - progress_dialog.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - progress_dialog.winfo_height()) // 2
            progress_dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error in sync all: {str(e)}")
            messagebox.showerror("Error", f"Failed to synchronize data: {str(e)}")

    def add_agent(self):
        """Add a remote agent connection"""
        try:
            messagebox.showinfo("Feature Coming Soon", "Remote agent functionality will be available in a future version.")
        except Exception as e:
            logger.error(f"Error in add agent: {str(e)}")
            messagebox.showerror("Error", f"Failed to add agent: {str(e)}")

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