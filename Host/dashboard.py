import os
import sys
import subprocess
import threading
import logging
import winreg
import json
import time
import psutil
import platform
import datetime
import tempfile
import shutil
import socket
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from PIL import Image, ImageTk
import ctypes
import urllib.request
import urllib.error
import requests

# Try to import required libraries, install if not present
try:
    import vdf
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "vdf"])
    import vdf

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Dashboard")

class ServerManagerDashboard:
    def __init__(self, debug_mode=False):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.steam_cmd_path = None
        self.paths = {}
        self.servers = []
        self.debug_mode = debug_mode
        self.variables = {
            "previousNetworkStats": {},
            "previousNetworkTime": datetime.datetime.now(),
            "lastServerListUpdate": datetime.datetime.min,
            "lastFullUpdate": datetime.datetime.min,
            "debugLoggingEnabled": False,
            "defaultSteamPath": "",
            "offlineMode": False,
            "formDisplayed": False,
            "debugMode": True,
            "verificationInProgress": False,
            "networkAdapters": [],
            "lastNetworkStats": {},
            "lastNetworkStatsTime": datetime.datetime.now(),
            "systemInfo": {},
            "diskInfo": [],
            "gpuInfo": None,
            "systemRefreshInterval": 4,
            "lastProcessUpdate": datetime.datetime.min,  # New: track when processes were last updated
            "processMonitoringInterval": 5,  # New: how often to check processes (seconds)
            "processStatHistory": {},  # New: store historical data for processes
            "maxProcessHistoryPoints": 20,  # New: maximum history points to keep
            "failedProcessRestarts": {},  # New: track failed restart attempts
            "webserverStatus": "Disconnected",  # New: track web server status
            "webserverPort": 8080  # New: web server port
        }
        
        # Initialize paths from registry and setup the application
        if not self.initialize():
            logger.error("Failed to initialize dashboard")
            sys.exit(1)
            
        # Configure file logging after paths are initialized
        self.configure_file_logging()
        
        # Set up the UI
        self.root = tk.Tk()
        self.root.title("Server Manager Dashboard")
        self.root.geometry("1200x700")
        self.root.minsize(800, 600)
        
        self.setup_ui()
        
        # Write PID file
        self.write_pid_file("dashboard", os.getpid())
        
        # Initialize system info and timers
        self.update_system_info()
        self.start_timers()
        
        self.supported_server_types = ["Steam", "Minecraft", "Other"]
        
        self.api_url = f"http://localhost:{self.variables['webserverPort']}/api/tracker/servers"
        self.api_token = None  # Set after login
        
        # Prompt for login and set self.api_token
        self.api_login()
        
    def configure_file_logging(self):
        """Set up logging to file"""
        try:
            log_path = os.path.join(self.paths["logs"], "dashboard.log")
            
            # Add file handler to logger
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            # Set log level based on debug mode
            if self.debug_mode:
                logger.setLevel(logging.DEBUG)
            else:
                logger.setLevel(logging.INFO)
                
            logger.info(f"File logging configured: {log_path}")
        except Exception as e:
            logger.error(f"Failed to configure file logging: {str(e)}")
    
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            
            # Try to get SteamCmd path
            try:
                self.steam_cmd_path = winreg.QueryValueEx(key, "SteamCmdPath")[0]
            except:
                self.steam_cmd_path = None
                
            # Try to get WebPort from registry
            try:
                self.variables["webserverPort"] = int(winreg.QueryValueEx(key, "WebPort")[0])
            except:
                self.variables["webserverPort"] = 8080
                logger.warning(f"WebPort not found in registry, using default: 8080")
                
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
                "modules": os.path.join(self.server_manager_dir, "modules")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
            # Set default SteamCmd path if not found in registry
            if not self.steam_cmd_path:
                self.steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
                logger.warning(f"SteamCmd path not found in registry, using default: {self.steam_cmd_path}")
            
            # Set default install directory
            self.variables["defaultSteamPath"] = self.steam_cmd_path
            self.variables["defaultInstallDir"] = os.path.join(self.steam_cmd_path, "steamapps", "common")
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
    
    def write_pid_file(self, process_type, pid):
        """Write process ID to file"""
        try:
            pid_file = os.path.join(self.paths["temp"], f"{process_type}.pid")
            
            # Create PID info dictionary
            pid_info = {
                "ProcessId": pid,
                "StartTime": datetime.datetime.now().isoformat(),
                "ProcessType": process_type
            }
            
            # Write PID info to file as JSON
            with open(pid_file, 'w') as f:
                json.dump(pid_info, f)
                
            logger.debug(f"PID file created for {process_type}: {pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to write PID file for {process_type}: {str(e)}")
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
        self.server_list.heading("pid", text="PID")  # New column for PID
        self.server_list.heading("cpu", text="CPU Usage")
        self.server_list.heading("memory", text="Memory Usage")
        self.server_list.heading("uptime", text="Uptime")
        
        # Define column widths
        self.server_list.column("name", width=150)
        self.server_list.column("status", width=80)
        self.server_list.column("pid", width=60)  # New column width
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
        self.server_context_menu.add_command(label="Restart Server", command=self.restart_server)  # New menu item
        self.server_context_menu.add_command(label="View Process Details", command=self.view_process_details)  # New menu item
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
            self.server_context_menu.entryconfigure("Restart Server", state=tk.NORMAL)  # New menu item
            self.server_context_menu.entryconfigure("View Process Details", state=tk.NORMAL)  # New menu item
            self.server_context_menu.entryconfigure("Configure Server", state=tk.NORMAL)
        else:
            # Disable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Start Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Restart Server", state=tk.DISABLED)  # New menu item
            self.server_context_menu.entryconfigure("View Process Details", state=tk.DISABLED)  # New menu item
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
    
    def fetch_minecraft_versions(self):
        """Fetch available Minecraft server versions from Mojang's manifest."""
        try:
            manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
            with urllib.request.urlopen(manifest_url, timeout=10) as resp:
                manifest = json.load(resp)
            versions = []
            for v in manifest["versions"]:
                if v["type"] in ("release", "snapshot"):
                    versions.append({
                        "id": v["id"],
                        "type": v["type"],
                        "url": v["url"]
                    })
            return versions
        except Exception as e:
            logger.error(f"Failed to fetch Minecraft versions: {str(e)}")
            return []

    def get_minecraft_server_jar_url(self, version_id, versions_list):
        """Get the download URL for the server jar for a given version."""
        try:
            for v in versions_list:
                if v["id"] == version_id:
                    with urllib.request.urlopen(v["url"], timeout=10) as resp:
                        version_data = json.load(resp)
                    return version_data["downloads"]["server"]["url"]
        except Exception as e:
            logger.error(f"Failed to get server jar URL for {version_id}: {str(e)}")
        return None

    def fetch_fabric_installer_url(self, mc_version):
        """Fetch Fabric installer URL for a given Minecraft version."""
        try:
            meta_url = "https://meta.fabricmc.net/v2/versions/installer"
            with urllib.request.urlopen(meta_url, timeout=10) as resp:
                installers = json.load(resp)
            if installers:
                return installers[0]["url"]  # Always use latest installer
        except Exception as e:
            logger.error(f"Failed to fetch Fabric installer: {str(e)}")
        return None

    def fetch_forge_installer_url(self, mc_version):
        """Fetch Forge installer URL for a given Minecraft version."""
        try:
            meta_url = f"https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
            with urllib.request.urlopen(meta_url, timeout=10) as resp:
                promotions = json.load(resp)
            key = f"{mc_version}-recommended"
            if key in promotions["promos"]:
                forge_version = promotions["promos"][key]
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
                return url
        except Exception as e:
            logger.error(f"Failed to fetch Forge installer: {str(e)}")
        return None

    def fetch_neoforge_installer_url(self, mc_version):
        """Fetch NeoForge installer URL for a given Minecraft version."""
        try:
            meta_url = f"https://api.neoforged.net/v1/projects/neoforge/versions?game_versions={mc_version}"
            with urllib.request.urlopen(meta_url, timeout=10) as resp:
                versions = json.load(resp)
            if versions:
                # Pick latest version for this MC version
                version = versions[0]
                url = version.get("installer_url")
                if url:
                    return url
        except Exception as e:
            logger.error(f"Failed to fetch NeoForge installer: {str(e)}")
        return None

    def add_server(self):
        """Add a new game server (Steam, Minecraft, or Other)"""
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
            mc_versions = self.fetch_minecraft_versions()
            if not mc_versions:
                messagebox.showerror("Error", "Could not fetch Minecraft versions from Mojang.")
                return
            # Default to latest release
            latest_release = next((v for v in mc_versions if v["id"] == mc_versions[0]["id"]), mc_versions[0])
            selected_version = tk.StringVar(value=latest_release["id"])
        else:
            selected_version = tk.StringVar(value="")

        # App ID (Steam only)
        if server_type == "Steam":
            ttk.Label(dialog, text="App ID:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
            app_id_var = tk.StringVar()
            app_id_entry = ttk.Entry(dialog, textvariable=app_id_var, width=35)
            app_id_entry.grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        else:
            app_id_var = tk.StringVar(value="")

        # Install directory
        ttk.Label(dialog, text="Install Directory:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
        install_dir_var = tk.StringVar()
        install_dir_entry = ttk.Entry(dialog, textvariable=install_dir_var, width=25)
        install_dir_entry.grid(row=3, column=1, padx=10, pady=10, sticky=tk.W)
        ttk.Label(dialog, text="(Leave blank for default location)", foreground="gray").grid(row=4, column=1, padx=10, sticky=tk.W)
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Installation Directory")
            if directory:
                install_dir_var.set(directory)
        ttk.Button(dialog, text="Browse", command=browse_directory, width=10).grid(row=3, column=2, padx=5, pady=10)

        # Executable (Minecraft/Other)
        if server_type in ("Minecraft", "Other"):
            ttk.Label(dialog, text="Executable Path:").grid(row=5, column=0, padx=10, pady=10, sticky=tk.W)
            exe_var = tk.StringVar()
            exe_entry = ttk.Entry(dialog, textvariable=exe_var, width=35)
            exe_entry.grid(row=5, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
            def browse_exe():
                fp = filedialog.askopenfilename(title="Select Executable",
                    filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd"),("All","*.*")])
                if fp:
                    exe_var.set(fp)
            ttk.Button(dialog, text="Browse", command=browse_exe, width=10).grid(row=5, column=2, padx=5, pady=10)
        else:
            exe_var = tk.StringVar(value="")

        # Startup Args (all)
        ttk.Label(dialog, text="Startup Args:").grid(row=6, column=0, padx=10, pady=10, sticky=tk.W)
        args_var = tk.StringVar()
        args_entry = ttk.Entry(dialog, textvariable=args_var, width=35)
        args_entry.grid(row=6, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)

        # Console output
        ttk.Label(dialog, text="Installation Progress:").grid(row=7, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        console_frame = ttk.Frame(dialog)
        console_frame.grid(row=8, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        console_output = scrolledtext.ScrolledText(console_frame, width=70, height=10, background="black", foreground="white")
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var)
        status_label.grid(row=9, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        progress = ttk.Progressbar(dialog, mode="indeterminate")
        progress.grid(row=10, column=0, columnspan=3, padx=10, pady=5, sticky="ew")

        dialog.grid_rowconfigure(8, weight=1)
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
                if server_type in ("Minecraft", "Other") and not executable_path:
                    messagebox.showerror("Validation Error", "Executable path is required.")
                    return

                server_config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
                if os.path.exists(server_config_path):
                    messagebox.showerror("Validation Error", "A server with this name already exists.")
                    return

                # Set default install dir if blank
                if not install_dir:
                    if server_type == "Steam":
                        install_dir = os.path.join(self.steam_cmd_path, "steamapps", "common", server_name)
                    elif server_type == "Minecraft":
                        install_dir = os.path.join(self.server_manager_dir, "minecraft_servers", server_name)
                    else:
                        install_dir = os.path.join(self.server_manager_dir, "other_servers", server_name)
                if not os.path.exists(install_dir):
                    os.makedirs(install_dir, exist_ok=True)
                    append_console(f"[INFO] Created installation directory: {install_dir}")

                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                status_var.set("Installing server...")

                if server_type == "Steam":
                    # ...existing Steam install logic...
                    # (copy from original add_server, but only for Steam)
                    steam_cmd_exe = os.path.join(self.steam_cmd_path, "steamcmd.exe")
                    if not os.path.exists(steam_cmd_exe):
                        messagebox.showerror("Configuration Error", 
                                            f"SteamCmd executable not found at: {steam_cmd_exe}\n"
                                            "Please make sure SteamCmd is properly installed.")
                        return
                    append_console("Starting Steam server installation...")
                    login_cmd = "+login anonymous" if credentials["anonymous"] else f"+login \"{credentials['username']}\" \"{credentials['password']}\""
                    steam_cmd_args = [
                        steam_cmd_exe,
                        login_cmd,
                        f"+force_install_dir \"{install_dir}\"",
                        f"+app_update {app_id} validate",
                        "+quit"
                    ]
                    append_console(f"[INFO] Running SteamCMD: {' '.join(steam_cmd_args)}")
                    self.install_process = subprocess.Popen(
                        " ".join(steam_cmd_args),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace'
                    )
                    # ...existing Steam install monitoring...
                    installation_success = False
                    while True:
                        if self.install_cancelled:
                            append_console("[INFO] Installation cancelled by user")
                            self.install_process.terminate()
                            break
                        line = self.install_process.stdout.readline()
                        if not line and self.install_process.poll() is not None:
                            break
                        if line:
                            line = line.strip()
                            append_console(line)
                            if "Success! App" in line and "fully installed" in line:
                                installation_success = True
                                status_var.set("Installation complete!")
                    error_output = self.install_process.stderr.read()
                    if error_output:
                        append_console("[WARN] SteamCMD Errors:")
                        append_console(error_output)
                    exit_code = self.install_process.returncode
                    append_console(f"[INFO] SteamCMD process completed with exit code: {exit_code}")
                    if exit_code != 0 and not installation_success:
                        raise Exception(f"SteamCMD failed with exit code: {exit_code}")
                elif server_type == "Minecraft":
                    mc_version = selected_version.get()
                    modloader = selected_modloader.get()
                    if modloader == "Vanilla":
                        jar_url = self.get_minecraft_server_jar_url(mc_version, mc_versions)
                        if not jar_url:
                            raise Exception(f"Could not find server jar for version {mc_version}")
                        append_console(f"[INFO] Downloading Minecraft Vanilla server {mc_version} ...")
                        jar_path = os.path.join(install_dir, f"minecraft_server.{mc_version}.jar")
                        urllib.request.urlretrieve(jar_url, jar_path)
                        append_console("[INFO] Download complete.")
                        executable_path = jar_path
                        # Accept EULA
                        with open(os.path.join(install_dir, "eula.txt"), "w") as f:
                            f.write("eula=true\n")
                        append_console("[INFO] EULA accepted.")
                    elif modloader == "Fabric":
                        append_console(f"[INFO] Downloading Fabric installer for {mc_version} ...")
                        fabric_url = self.fetch_fabric_installer_url(mc_version)
                        if not fabric_url:
                            raise Exception("Could not fetch Fabric installer.")
                        fabric_installer = os.path.join(install_dir, "fabric-installer.jar")
                        urllib.request.urlretrieve(fabric_url, fabric_installer)
                        append_console("[INFO] Fabric installer downloaded.")
                        # Run Fabric installer
                        cmd = [sys.executable, "-m", "subprocess", "java", "-jar", fabric_installer, "server", "-mcversion", mc_version, "-downloadMinecraft"]
                        subprocess.run(["java", "-jar", fabric_installer, "server", "-mcversion", mc_version, "-downloadMinecraft"], cwd=install_dir)
                        # Find fabric-server-launch.jar
                        for fname in os.listdir(install_dir):
                            if fname.startswith("fabric-server-launch") and fname.endswith(".jar"):
                                executable_path = os.path.join(install_dir, fname)
                                break
                        else:
                            raise Exception("Fabric server jar not found after install.")
                        with open(os.path.join(install_dir, "eula.txt"), "w") as f:
                            f.write("eula=true\n")
                        append_console("[INFO] Fabric server installed and EULA accepted.")
                    elif modloader == "Forge":
                        append_console(f"[INFO] Downloading Forge installer for {mc_version} ...")
                        forge_url = self.fetch_forge_installer_url(mc_version)
                        if not forge_url:
                            raise Exception("Could not fetch Forge installer.")
                        forge_installer = os.path.join(install_dir, "forge-installer.jar")
                        urllib.request.urlretrieve(forge_url, forge_installer)
                        append_console("[INFO] Forge installer downloaded.")
                        # Run Forge installer (server)
                        subprocess.run(["java", "-jar", forge_installer, "--installServer"], cwd=install_dir)
                        # Find forge jar
                        forge_jar = None
                        for fname in os.listdir(install_dir):
                            if fname.startswith("forge-") and fname.endswith(".jar") and "installer" not in fname:
                                forge_jar = os.path.join(install_dir, fname)
                                break
                        if not forge_jar:
                            raise Exception("Forge server jar not found after install.")
                        executable_path = forge_jar
                        with open(os.path.join(install_dir, "eula.txt"), "w") as f:
                            f.write("eula=true\n")
                        append_console("[INFO] Forge server installed and EULA accepted.")
                    elif modloader == "NeoForge":
                        append_console(f"[INFO] Downloading NeoForge installer for {mc_version} ...")
                        neoforge_url = self.fetch_neoforge_installer_url(mc_version)
                        if not neoforge_url:
                            raise Exception("Could not fetch NeoForge installer.")
                        neoforge_installer = os.path.join(install_dir, "neoforge-installer.jar")
                        urllib.request.urlretrieve(neoforge_url, neoforge_installer)
                        append_console("[INFO] NeoForge installer downloaded.")
                        subprocess.run(["java", "-jar", neoforge_installer, "--installServer"], cwd=install_dir)
                        # Find neoforge jar
                        neoforge_jar = None
                        for fname in os.listdir(install_dir):
                            if fname.startswith("neoforge-") and fname.endswith(".jar") and "installer" not in fname:
                                neoforge_jar = os.path.join(install_dir, fname)
                                break
                        if not neoforge_jar:
                            raise Exception("NeoForge server jar not found after install.")
                        executable_path = neoforge_jar
                        with open(os.path.join(install_dir, "eula.txt"), "w") as f:
                            f.write("eula=true\n")
                        append_console("[INFO] NeoForge server installed and EULA accepted.")
                    else:
                        raise Exception("Unknown mod loader selected.")
                # Save server configuration
                server_config = {
                    "Name": server_name,
                    "Type": server_type,
                    "AppID": app_id,
                    "InstallDir": install_dir,
                    "ExecutablePath": executable_path,
                    "StartupArgs": startup_args,
                    "Created": datetime.datetime.now().isoformat(),
                    "LastUpdate": datetime.datetime.now().isoformat()
                }
                if server_type == "Minecraft":
                    server_config["Version"] = selected_version.get()
                    server_config["ModLoader"] = selected_modloader.get()
                os.makedirs(self.paths["servers"], exist_ok=True)
                with open(server_config_path, 'w') as f:
                    json.dump(server_config, f, indent=4)
                append_console(f"[INFO] Server configuration saved to: {server_config_path}")
                self.update_server_list(force_refresh=True)
                messagebox.showinfo("Success", "Server created successfully!")
                dialog.destroy()
            except Exception as e:
                logger.error(f"Error installing server: {str(e)}")
                append_console(f"[ERROR] {str(e)}")
                status_var.set("Installation failed!")
                create_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.DISABLED)
            finally:
                progress.stop()

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=11, column=0, columnspan=3, padx=10, pady=10)
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

    def api_login(self):
        """Prompt for login and obtain API token"""
        from tkinter.simpledialog import askstring
        while True:
            username = askstring("Login", "Username:")
            password = askstring("Login", "Password:", show="*")
            if not username or not password:
                messagebox.showerror("Login Required", "Username and password required.")
                continue
            try:
                resp = requests.post(
                    f"http://localhost:{self.variables['webserverPort']}/api/auth/login",
                    json={"username": username, "password": password},
                    timeout=5
                )
                if resp.status_code == 200:
                    self.api_token = resp.json()["token"]
                    break
                else:
                    messagebox.showerror("Login Failed", resp.json().get("error", "Unknown error"))
            except Exception as e:
                messagebox.showerror("Login Error", str(e))

    def api_headers(self):
        return {"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}

    def update_server_list(self, force_refresh=False):
        # Skip update if it's been less than 5 seconds since the last update and force_refresh isn't specified
        if not force_refresh and \
           (self.variables["lastServerListUpdate"] != datetime.datetime.min) and \
           (datetime.datetime.now() - self.variables["lastServerListUpdate"]).total_seconds() < 5:
            logger.debug("Skipping server list update - last update was less than 5 seconds ago")
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
                                process = psutil.Process(process_id)
                                
                                if process.is_running():
                                    status = "Running"
                                    pid = str(process_id)
                                    
                                    # Get CPU usage
                                    try:
                                        cpu_percent = process.cpu_percent(interval=0.1)
                                        cpu_usage = f"{cpu_percent:.1f}%"
                                        
                                        # Store in history
                                        if process_id not in self.variables["processStatHistory"]:
                                            self.variables["processStatHistory"][process_id] = {
                                                "cpu": [],
                                                "memory": [],
                                                "timestamps": []
                                            }
                                        
                                        history = self.variables["processStatHistory"][process_id]
                                        history["cpu"].append(cpu_percent)
                                        
                                        # Limit history size
                                        if len(history["cpu"]) > self.variables["maxProcessHistoryPoints"]:
                                            history["cpu"].pop(0)
                                            
                                    except:
                                        cpu_usage = "N/A"
                                        
                                    # Get memory usage
                                    try:
                                        memory_info = process.memory_info()
                                        memory_mb = memory_info.rss / (1024 * 1024)
                                        memory_usage = f"{memory_mb:.1f} MB"
                                        
                                        # Store in history
                                        if process_id in self.variables["processStatHistory"]:
                                            history = self.variables["processStatHistory"][process_id]
                                            history["memory"].append(memory_mb)
                                            history["timestamps"].append(datetime.datetime.now())
                                            
                                            # Limit history size
                                            if len(history["memory"]) > self.variables["maxProcessHistoryPoints"]:
                                                history["memory"].pop(0)
                                                history["timestamps"].pop(0)
                                    except:
                                        memory_usage = "N/A"
                                        
                                    # Calculate uptime
                                    try:
                                        # Calculate uptime if start time is available
                                        if "StartTime" in server_config:
                                            start_time = datetime.datetime.fromisoformat(server_config["StartTime"])
                                            now = datetime.datetime.now()
                                            delta = now - start_time
                                            
                                            days = delta.days
                                            hours, remainder = divmod(delta.seconds, 3600)
                                            minutes, seconds = divmod(remainder, 60)
                                            
                                            if days > 0:
                                                uptime = f"{days}d {hours}h {minutes}m"
                                            else:
                                                uptime = f"{hours}h {minutes}m {seconds}s"
                                        else:
                                            uptime = "Running"
                                    except:
                                        uptime = "Running"
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
                        # Now check if we can connect to the port
                        if self.is_port_open('localhost', self.variables["webserverPort"]):
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
    
    def start_timers(self):
        """Start update timers"""
        # System info update timer - 5 seconds
        self.root.after(5000, self.system_info_timer)
        
        # Server list update timer - 30 seconds
        self.root.after(30000, self.server_list_timer)
        
        # Web server status update timer - 15 seconds
        self.root.after(15000, self.webserver_status_timer)
        
        # Process monitoring timer - 10 seconds
        self.root.after(10000, self.process_monitor_timer)
    
    def system_info_timer(self):
        """Timer callback for system info updates"""
        self.update_system_info()
        self.root.after(5000, self.system_info_timer)
    
    def server_list_timer(self):
        """Timer callback for server list updates"""
        self.update_server_list()
        self.root.after(30000, self.server_list_timer)
    
    def webserver_status_timer(self):
        """Timer callback for web server status updates"""
        self.update_webserver_status()
        self.root.after(15000, self.webserver_status_timer)
    
    def process_monitor_timer(self):
        """Timer callback for process monitoring"""
        self.monitor_processes()
        interval = self.variables["processMonitoringInterval"] * 1000  # Convert to milliseconds
        self.root.after(interval, self.process_monitor_timer)
    
    def monitor_processes(self):
        """Monitor running server processes"""
        try:
            # Skip if it's been less than processMonitoringInterval seconds since the last update
            if (self.variables["lastProcessUpdate"] != datetime.datetime.min) and \
               (datetime.datetime.now() - self.variables["lastProcessUpdate"]).total_seconds() < self.variables["processMonitoringInterval"]:
                return
                
            # Check each server's process
            servers_path = self.paths["servers"]
            if os.path.exists(servers_path):
                for file in os.listdir(servers_path):
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(servers_path, file), 'r') as f:
                                server_config = json.load(f)
                                
                            server_name = server_config.get("Name", "Unknown")
                            
                            # Check if server has a process ID registered
                            if "ProcessId" in server_config:
                                process_id = server_config["ProcessId"]
                                
                                # Check if process is still running
                                if not self.is_process_running(process_id):
                                    logger.warning(f"Server '{server_name}' process (PID {process_id}) is no longer running")
                                    
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
                                    
                                    # Update the server list
                                    self.update_server_list(force_refresh=True)
                                else:
                                    # Process is running, update statistics
                                    try:
                                        process = psutil.Process(process_id)
                                        cpu_percent = process.cpu_percent(interval=0.1)
                                        memory_info = process.memory_info()
                                        memory_mb = memory_info.rss / (1024 * 1024)
                                        
                                        # Store in history
                                        if process_id not in self.variables["processStatHistory"]:
                                            self.variables["processStatHistory"][process_id] = {
                                                "cpu": [],
                                                "memory": [],
                                                "timestamps": []
                                            }
                                        
                                        history = self.variables["processStatHistory"][process_id]
                                        history["cpu"].append(cpu_percent)
                                        history["memory"].append(memory_mb)
                                        history["timestamps"].append(datetime.datetime.now())
                                        
                                        # Limit history size
                                        while len(history["cpu"]) > self.variables["maxProcessHistoryPoints"]:
                                            history["cpu"].pop(0)
                                            history["memory"].pop(0)
                                            history["timestamps"].pop(0)
                                            
                                    except Exception as e:
                                        logger.error(f"Error updating process statistics for {server_name}: {str(e)}")
                        except Exception as e:
                            logger.error(f"Error monitoring server process in {file}: {str(e)}")
                            
            # Update the last process update time
            self.variables["lastProcessUpdate"] = datetime.datetime.now()
            
        except Exception as e:
            logger.error(f"Error in process monitoring: {str(e)}")
    
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
        config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
        if not os.path.exists(config_file):
            messagebox.showerror("Error", f"Server configuration file not found: {config_file}")
            return
        with open(config_file, 'r') as f:
            server_config = json.load(f)
        if 'ProcessId' in server_config and self.is_process_running(server_config['ProcessId']):
            messagebox.showinfo("Already Running", f"Server '{server_name}' is already running with PID {server_config['ProcessId']}.")
            return
        server_type = server_config.get("Type", "Other")
        install_dir = server_config.get('InstallDir', '')
        executable_path = server_config.get('ExecutablePath', '')
        startup_args = server_config.get('StartupArgs', '')
        if not executable_path:
            messagebox.showinfo("Configuration Needed", "No executable specified. Please configure the server startup settings.")
            self.configure_server()
            return
        # Resolve executable path
        exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
        if not os.path.exists(exe_full):
            messagebox.showerror("Error", f"Executable not found: {exe_full}")
            return
        # Build command
        if server_type == "Minecraft":
            cmd = f'java -Xmx1024M -Xms1024M -jar "{exe_full}" nogui {startup_args}'
            shell = True
        elif exe_full.lower().endswith(('.bat', '.cmd')):
            cmd = f'start "" /D "{install_dir}" cmd /c "{exe_full}" {startup_args}'
            shell = True
        elif exe_full.lower().endswith('.sh') and sys.platform != 'win32':
            cmd = ['/bin/sh', exe_full] + (startup_args.split() if startup_args else [])
            shell = False
        else:
            cmd = f'"{exe_full}" {startup_args}'
            shell = True
        # ...existing log setup...
        server_logs_dir = os.path.join(install_dir, "logs")
        os.makedirs(server_logs_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stdout_log = os.path.join(server_logs_dir, f"server_stdout_{timestamp}.log")
        stderr_log = os.path.join(server_logs_dir, f"server_stderr_{timestamp}.log")
        logger.info(f"Starting server: {server_name} with command: {cmd}")
        self.update_server_status(server_name, "Starting...")
        with open(stdout_log, 'a') as stdout_file, open(stderr_log, 'a') as stderr_file:
            start_time = datetime.datetime.now()
            time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            stdout_file.write(f"\n--- Server started at {time_str} ---\n")
            stdout_file.write(f"Command: {cmd}\n\n")
            if shell:
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=install_dir,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                )
            else:
                process = subprocess.Popen(
                    cmd,
                    cwd=install_dir,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                )
        time.sleep(1)
        if not psutil.pid_exists(process.pid):
            messagebox.showerror("Start Failed", f"Server process terminated immediately after starting. Check logs at {stderr_log}")
            return
        self.variables["processStatHistory"][process.pid] = {
            "cpu": [], "memory": [], "timestamps": []
        }
        server_config['ProcessId'] = process.pid
        server_config['StartTime'] = start_time.isoformat()
        server_config['LastUpdate'] = datetime.datetime.now().isoformat()
        server_config['LogStdout'] = stdout_log
        server_config['LogStderr'] = stderr_log
        with open(config_file, 'w') as f:
            json.dump(server_config, f, indent=4)
        self.update_server_list(force_refresh=True)
        messagebox.showinfo("Success", f"Server '{server_name}' started successfully with PID {process.pid}.")

    def stop_server(self):
        """Stop the selected game server"""

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
                
                # Clean up the process ID in the config
                server_config.pop('ProcessId', None)
                server_config.pop('StartTime', None)
                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                
                # Save updated configuration
                with open(config_file, 'w') as f:
                    json.dump(server_config, f, indent=4)
                    
                # Update server list
                self.update_server_list(force_refresh=True)
                return
                
            # Confirm server stop
            confirm = messagebox.askyesno("Confirm Stop", 
                                        f"Are you sure you want to stop the server '{server_name}' (PID {process_id})?",
                                        icon=messagebox.WARNING)
            
            if not confirm:
                return
                
            # Update status in UI temporarily
            self.update_server_status(server_name, "Stopping...")
                
            # Try to use custom stop command if available
            if 'StopCommand' in server_config and server_config['StopCommand']:
                try:
                    stop_cmd = server_config['StopCommand']
                    install_dir = server_config.get('InstallDir', '')
                    
                    logger.info(f"Executing custom stop command: {stop_cmd}")
                    
                    # Execute stop command with timeout
                    stop_process = subprocess.Popen(
                        stop_cmd, 
                        shell=True, 
                        cwd=install_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    try:
                        stdout, stderr = stop_process.communicate(timeout=30)
                        if stderr:
                            logger.warning(f"Stop command produced error output: {stderr.decode('utf-8', errors='replace')}")
                    except subprocess.TimeoutExpired:
                        stop_process.kill()
                        logger.warning("Stop command timed out after 30 seconds")
                    
                    # Wait a bit to see if the process stops
                    for _ in range(5):  # Try for 5 seconds
                        if not self.is_process_running(process_id):
                            # Process stopped successfully
                            server_config.pop('ProcessId', None)
                            server_config.pop('StartTime', None)
                            server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                            
                            # Clean up process history
                            if process_id in self.variables["processStatHistory"]:
                                del self.variables["processStatHistory"][process_id]
                            
                            # Save updated configuration
                            with open(config_file, 'w') as f:
                                json.dump(server_config, f, indent=4)
                                
                            # Update server list
                            self.update_server_list(force_refresh=True)
                            
                            messagebox.showinfo("Success", f"Server '{server_name}' stopped successfully.")
                            return
                        time.sleep(1)
                        
                    logger.warning(f"Custom stop command did not stop the server, using force termination")
                except Exception as e:
                    logger.error(f"Error executing custom stop command: {str(e)}")
            
            # If we got here, either the custom stop command failed or wasn't available
            # Try to terminate the process
            try:
                process = psutil.Process(process_id)
                
                # Get all child processes
                children = []
                try:
                    children = process.children(recursive=True)
                except:
                    logger.warning(f"Could not get child processes for PID {process_id}")
                
                # First try graceful termination
                try:
                    process.terminate()
                    logger.info(f"Sent termination signal to process {process_id}")
                except:
                    logger.warning(f"Failed to terminate process {process_id}")
                
                # Wait up to 5 seconds for the process to terminate
                gone, alive = psutil.wait_procs([process], timeout=5)
                
                if process in alive:
                    # If it doesn't terminate, kill it forcefully
                    logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                    process.kill()
                
                # Terminate any remaining child processes
                if children:
                    for child in children:
                        try:
                            if child.is_running():
                                child.kill()
                                logger.info(f"Killed child process with PID {child.pid}")
                        except:
                            pass
                
                logger.info(f"Terminated server process with PID {process_id}")
                
                # Update server configuration
                server_config.pop('ProcessId', None)
                server_config.pop('StartTime', None)
                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                
                # Clean up process history
                if process_id in self.variables["processStatHistory"]:
                    del self.variables["processStatHistory"][process_id]
                
                # Save updated configuration
                with open(config_file, 'w') as f:
                    json.dump(server_config, f, indent=4)
                    
                # Update server list
                self.update_server_list(force_refresh=True)
                
                messagebox.showinfo("Success", f"Server '{server_name}' stopped successfully.")
                
            except Exception as e:
                logger.error(f"Failed to stop server process: {str(e)}")
                messagebox.showerror("Error", f"Failed to stop server: {str(e)}")
                
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
        
        # Confirm restart
        confirm = messagebox.askyesno("Confirm Restart", 
                                    f"Are you sure you want to restart the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        
        if not confirm:
            return
            
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                messagebox.showerror("Error", f"Server configuration file not found: {config_file}")
                return
                
            # Read server configuration
            with open(config_file, 'r') as f:
                server_config = json.load(f)
            
            # Check if server is running
            is_running = False
            if 'ProcessId' in server_config:
                process_id = server_config['ProcessId']
                is_running = self.is_process_running(process_id)
            
            # Update status in UI temporarily
            self.update_server_status(server_name, "Restarting...")
            
            # If running, stop first
            if is_running:
                # Store a copy of the config before stopping
                config_copy = server_config.copy()
                
                # Stop the server
                self.stop_server()
                
                # Wait a moment for process to fully terminate
                time.sleep(2)
            
            # Start the server
            self.start_server()
            
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
        config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
        if not os.path.exists(config_file):
            messagebox.showerror("Error", f"Server configuration file not found: {config_file}")
            return
        with open(config_file, 'r') as f:
            server_config = json.load(f)
        install_dir = server_config.get('InstallDir','')
        if not install_dir or not os.path.exists(install_dir):
            messagebox.showerror("Error", "Server installation directory not found.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure Server: {server_name}")
        dialog.geometry("600x450")
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
        ttk.Label(start, text="Executable Path:").grid(row=0,column=0,padx=10,pady=5,sticky=tk.W)
        exe_var = tk.StringVar(value=server_config.get('ExecutablePath',''))
        exe_entry = ttk.Entry(start, textvariable=exe_var, width=40); exe_entry.grid(row=0,column=1,sticky=tk.W)
        def browse_exe():
            fp = filedialog.askopenfilename(initialdir=install_dir,
                filetypes=[("Exec","*.exe;*.bat;*.cmd;*.sh"),("All","*.*")])
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                exe_var.set(rel)
        ttk.Button(start, text="Browse", command=browse_exe).grid(row=0,column=2)

        # Args, stop command, working dir
        ttk.Label(start, text="Startup Args:").grid(row=1,column=0,padx=10,pady=5,sticky=tk.W)
        args_var = tk.StringVar(value=server_config.get('StartupArgs',''))
        ttk.Entry(start, textvariable=args_var, width=40).grid(row=1,column=1,columnspan=2,sticky=tk.W)
        ttk.Label(start, text="Stop Command:").grid(row=2,column=0,padx=10,pady=5,sticky=tk.W)
        stop_var = tk.StringVar(value=server_config.get('StopCommand',''))
        ttk.Entry(start, textvariable=stop_var, width=40).grid(row=2,column=1,columnspan=2,sticky=tk.W)
        ttk.Label(start, text="Working Dir:").grid(row=3,column=0,padx=10,pady=5,sticky=tk.W)
        wd_var = tk.StringVar(value=server_config.get('WorkingDir',''))
        wd_entry = ttk.Entry(start, textvariable=wd_var, width=40); wd_entry.grid(row=3,column=1,sticky=tk.W)
        def browse_wd():
            d = filedialog.askdirectory(initialdir=install_dir)
            if d:
                rel = os.path.relpath(d, install_dir) if os.path.commonpath([d,install_dir])==install_dir else d
                wd_var.set(rel)
        ttk.Button(start, text="Browse", command=browse_wd).grid(row=3,column=2)

        # Save/Cancel/Test
        btns = ttk.Frame(frm); btns.pack(fill=tk.X,pady=10)
        def save():
            ep = exe_var.get().strip(); sa = args_var.get().strip()
            sc = stop_var.get().strip(); wd = wd_var.get().strip()
            if not ep:
                messagebox.showerror("Validation Error","Executable path is required."); return
            # resolve abs paths for validation
            ep_abs = ep if os.path.isabs(ep) else os.path.join(install_dir,ep)
            wd_abs = wd if os.path.isabs(wd) else (os.path.join(install_dir,wd) if wd else install_dir)
            if not os.path.exists(ep_abs):
                if not messagebox.askyesno("Warning",f"Executable not found: {ep_abs}\nSave anyway?"): return
            server_config.update({
                'ExecutablePath': ep,
                'StartupArgs': sa,
                'StopCommand': sc,
                'WorkingDir': wd,
                'LastUpdate': datetime.datetime.now().isoformat()
            })
            with open(config_file,'w') as f: json.dump(server_config,f,indent=4)
            messagebox.showinfo("Success","Configuration saved."); dialog.destroy()
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

def main():
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(description='Server Manager Dashboard')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    # Create and run dashboard
    dashboard = ServerManagerDashboard(debug_mode=args.debug)
    dashboard.run()

if __name__ == "__main__":
    main()
