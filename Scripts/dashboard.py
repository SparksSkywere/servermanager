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

# Try to import required libraries, install if not present
try:
    import vdf  # For Steam app manifest parsing
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
            "systemRefreshInterval": 5,
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
        columns = ("name", "status", "cpu", "memory", "uptime")
        self.server_list = ttk.Treeview(self.servers_frame, columns=columns, show="headings")
        
        # Define column headings
        self.server_list.heading("name", text="Server Name")
        self.server_list.heading("status", text="Status")
        self.server_list.heading("cpu", text="CPU Usage")
        self.server_list.heading("memory", text="Memory Usage")
        self.server_list.heading("uptime", text="Uptime")
        
        # Define column widths
        self.server_list.column("name", width=150)
        self.server_list.column("status", width=100)
        self.server_list.column("cpu", width=100)
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
            self.server_context_menu.entryconfigure("Configure Server", state=tk.NORMAL)
        else:
            # Disable server-specific options
            self.server_context_menu.entryconfigure("Open Folder Directory", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Remove Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Start Server", state=tk.DISABLED)
            self.server_context_menu.entryconfigure("Stop Server", state=tk.DISABLED)
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
    
    def add_server(self):
        """Add a new game server"""
        # Get Steam credentials
        credentials = self.get_steam_credentials()
        if not credentials:
            logger.debug("User cancelled Steam login")
            return
            
        logger.debug(f"Steam login type: {'Anonymous' if credentials['anonymous'] else 'Account'}")
        
        # Create dialog for server details
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Game Server")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Server name
        ttk.Label(dialog, text="Server Name:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=35)
        name_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # App ID
        ttk.Label(dialog, text="App ID:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        app_id_var = tk.StringVar()
        app_id_entry = ttk.Entry(dialog, textvariable=app_id_var, width=35)
        app_id_entry.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Install directory
        ttk.Label(dialog, text="Install Directory:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        install_dir_var = tk.StringVar()
        install_dir_entry = ttk.Entry(dialog, textvariable=install_dir_var, width=25)
        install_dir_entry.grid(row=2, column=1, padx=10, pady=10, sticky=tk.W)
        
        ttk.Label(dialog, text="(Leave blank for default location)", foreground="gray").grid(row=3, column=1, padx=10, sticky=tk.W)
        
        # Browse button
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Installation Directory")
            if directory:
                install_dir_var.set(directory)
                
        ttk.Button(dialog, text="Browse", command=browse_directory, width=10).grid(row=2, column=2, padx=5, pady=10)
        
        # Console output
        ttk.Label(dialog, text="Installation Progress:").grid(row=4, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        
        console_frame = ttk.Frame(dialog)
        console_frame.grid(row=5, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")
        
        console_output = scrolledtext.ScrolledText(console_frame, width=70, height=15, background="black", foreground="white")
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)
        
        # Status and progress
        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var)
        status_label.grid(row=6, column=0, columnspan=3, padx=10, pady=5, sticky=tk.W)
        
        progress = ttk.Progressbar(dialog, mode="indeterminate")
        progress.grid(row=7, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        
        # Configure grid weights
        dialog.grid_rowconfigure(5, weight=1)
        for i in range(3):
            dialog.grid_columnconfigure(i, weight=1 if i == 1 else 0)
        
        # Installation thread
        self.install_cancelled = False
        
        def append_console(text):
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)
        
        def install_server():
            try:
                # Validate inputs
                server_name = name_var.get().strip()
                app_id = app_id_var.get().strip()
                install_dir = install_dir_var.get().strip()
                
                if not server_name:
                    messagebox.showerror("Validation Error", "Server name is required.")
                    return
                    
                if not app_id or not app_id.isdigit():
                    messagebox.showerror("Validation Error", "Steam App ID must be a number.")
                    return
                
                # Check if server already exists
                server_config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
                if os.path.exists(server_config_path):
                    messagebox.showerror("Validation Error", "A server with this name already exists.")
                    return
                
                # Check if SteamCmd exists
                steam_cmd_exe = os.path.join(self.steam_cmd_path, "steamcmd.exe")
                if not os.path.exists(steam_cmd_exe):
                    messagebox.showerror("Configuration Error", 
                                        f"SteamCmd executable not found at: {steam_cmd_exe}\n"
                                        "Please make sure SteamCmd is properly installed.")
                    return
                
                # Validate install directory if specified
                if install_dir:
                    # Check if path is valid
                    try:
                        install_dir = os.path.abspath(install_dir)
                    except:
                        messagebox.showerror("Validation Error", "Invalid installation path specified.")
                        return
                        
                    # Check if directory exists and is empty
                    if os.path.exists(install_dir) and os.listdir(install_dir):
                        result = messagebox.askyesno("Warning", 
                                                    "The specified installation directory is not empty. Continue anyway?",
                                                    icon=messagebox.WARNING)
                        if not result:
                            return
                    
                # Update UI
                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                status_var.set("Installing server...")
                
                # Reset console
                console_output.config(state=tk.NORMAL)
                console_output.delete(1.0, tk.END)
                console_output.config(state=tk.DISABLED)
                
                # Log basic info
                append_console("Starting server installation...")
                append_console(f"[INFO] SteamCmd path: {self.steam_cmd_path}")
                append_console(f"[INFO] Server name: {server_name}")
                append_console(f"[INFO] App ID: {app_id}")
                
                # Show the appropriate install directory message
                if not install_dir:
                    default_path = os.path.join(os.path.join(self.steam_cmd_path, "steamapps", "common"), server_name)
                    append_console(f"[INFO] Using default install directory: {default_path}")
                    install_dir = default_path
                else:
                    append_console(f"[INFO] Install directory: {install_dir}")
                
                # Create install directory if it doesn't exist
                if not os.path.exists(install_dir):
                    os.makedirs(install_dir, exist_ok=True)
                    append_console(f"[INFO] Created installation directory: {install_dir}")
                
                # Prepare SteamCMD command
                if credentials["anonymous"]:
                    login_cmd = "+login anonymous"
                else:
                    login_cmd = f"+login \"{credentials['username']}\" \"{credentials['password']}\""
                
                steam_cmd_args = [
                    steam_cmd_exe,
                    login_cmd,
                    f"+force_install_dir \"{install_dir}\"",
                    f"+app_update {app_id} validate",
                    "+quit"
                ]
                
                append_console(f"[INFO] Running SteamCMD with command: {' '.join(steam_cmd_args)}")
                
                # Start installation process
                self.install_process = subprocess.Popen(
                    " ".join(steam_cmd_args),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                
                # Flags for tracking installation progress
                installation_success = False
                verification_in_progress = False
                
                # Monitor installation process
                while True:
                    # Check if cancelled
                    if self.install_cancelled:
                        append_console("[INFO] Installation cancelled by user")
                        self.install_process.terminate()
                        break
                    
                    # Read output line
                    line = self.install_process.stdout.readline()
                    if not line and self.install_process.poll() is not None:
                        break
                    
                    if line:
                        line = line.strip()
                        append_console(line)
                        
                        # Track installation progress
                        if "Success! App" in line and "fully installed" in line:
                            installation_success = True
                            verification_in_progress = False
                            status_var.set("Installation complete!")
                        
                        elif any(marker in line for marker in ["Verifying installation", "[    ] Verifying", "Update state", "verifying"]):
                            verification_in_progress = True
                            
                            # Extract progress percentage if available
                            if "verifying install, progress:" in line:
                                try:
                                    progress_pct = line.split("progress:")[1].strip().split()[0]
                                    status_var.set(f"Verifying installation: {progress_pct}%")
                                except:
                                    status_var.set("Verifying installation...")
                            else:
                                status_var.set("Verifying installation...")
                
                # Get error output
                error_output = self.install_process.stderr.read()
                if error_output:
                    append_console("[WARN] SteamCMD Errors:")
                    append_console(error_output)
                
                # Check installation result
                exit_code = self.install_process.returncode
                append_console(f"[INFO] SteamCMD process completed with exit code: {exit_code}")
                
                if exit_code != 0 and not installation_success:
                    raise Exception(f"SteamCMD failed with exit code: {exit_code}")
                
                # Verify installation directory exists and contains files
                if not os.path.exists(install_dir):
                    raise Exception(f"Installation directory not created: {install_dir}")
                
                # Count files in installation directory
                file_count = sum(len(files) for _, _, files in os.walk(install_dir))
                append_console(f"[INFO] Installation directory contains {file_count} files/directories")
                
                # Create server configuration
                server_config = {
                    "Name": server_name,
                    "AppID": app_id,
                    "InstallDir": install_dir,
                    "Created": datetime.datetime.now().isoformat(),
                    "LastUpdate": datetime.datetime.now().isoformat()
                }
                
                # Create servers directory if it doesn't exist
                os.makedirs(self.paths["servers"], exist_ok=True)
                
                # Save server configuration
                config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
                with open(config_file, 'w') as f:
                    json.dump(server_config, f, indent=4)
                
                append_console(f"[INFO] Server configuration saved to: {config_file}")
                
                # Save installation log
                game_logs_path = os.path.join(self.paths["logs"], "Game_Logs")
                os.makedirs(game_logs_path, exist_ok=True)
                
                log_file_path = os.path.join(game_logs_path, f"{server_name}_install.log")
                with open(log_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Server Installation Log\n")
                    f.write(f"# Server Name: {server_name}\n")
                    f.write(f"# App ID: {app_id}\n")
                    f.write(f"# Installation Directory: {install_dir}\n")
                    f.write(f"# Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    # Get console contents
                    console_output.config(state=tk.NORMAL)
                    log_content = console_output.get(1.0, tk.END)
                    console_output.config(state=tk.DISABLED)
                    
                    f.write(log_content)
                
                append_console("[INFO] Installation log saved to: " + log_file_path)
                
                # Also save a copy in the server directory
                server_logs_path = os.path.join(install_dir, "logs")
                os.makedirs(server_logs_path, exist_ok=True)
                
                server_log_file = os.path.join(server_logs_path, "Game_Install.log")
                with open(server_log_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Server Installation Log\n")
                    f.write(f"# Server Name: {server_name}\n")
                    f.write(f"# App ID: {app_id}\n")
                    f.write(f"# Installation Directory: {install_dir}\n")
                    f.write(f"# Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    f.write(log_content)
                
                append_console("[INFO] Installation log copy saved in server directory")
                append_console("[SUCCESS] Server created successfully")
                
                # Update server list
                self.update_server_list(force_refresh=True)
                
                # Show success message
                messagebox.showinfo("Success", "Server created successfully!")
                
                # Close dialog
                dialog.destroy()
                
            except Exception as e:
                logger.error(f"Error installing server: {str(e)}")
                append_console(f"[ERROR] {str(e)}")
                status_var.set("Installation failed!")
                create_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.DISABLED)
            finally:
                # Reset UI
                progress.stop()
                
        # Create and cancel buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=8, column=0, columnspan=3, padx=10, pady=10)
        
        create_button = ttk.Button(button_frame, text="Create", width=15)
        create_button.pack(side=tk.LEFT, padx=5)
        
        cancel_button = ttk.Button(button_frame, text="Cancel", width=15, state=tk.DISABLED)
        cancel_button.pack(side=tk.LEFT, padx=5)
        
        # Button commands
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
        
        # Dialog close handling
        def on_close():
            if cancel_button.instate(['!disabled']):
                result = messagebox.askyesno("Confirm Exit", 
                                           "An installation is in progress. Do you want to cancel it?",
                                           icon=messagebox.QUESTION)
                if result:
                    cancel_installation()
                    # Give some time for cancellation to process
                    dialog.after(1000, dialog.destroy)
                    return
                else:
                    return
            dialog.destroy()
            
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        
        # Center dialog on parent window
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
    
    def remove_server(self):
        """Remove a selected game server"""
        selected_items = self.server_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return
            
        server_name = self.server_list.item(selected_items[0])['values'][0]
        
        # Confirm removal
        confirm = messagebox.askyesno("Confirm Removal", 
                                     f"Are you sure you want to remove the server '{server_name}'?",
                                     icon=messagebox.WARNING)
        
        if not confirm:
            return
            
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if os.path.exists(config_file):
                # Read server configuration
                with open(config_file, 'r') as f:
                    server_config = json.load(f)
                    
                # Check if server has a process ID registered
                if 'ProcessId' in server_config:
                    try:
                        process_id = server_config['ProcessId']
                        # Check if process is running
                        if psutil.pid_exists(process_id):
                            process = psutil.Process(process_id)
                            process.terminate()
                            logger.info(f"Terminated server process with PID {process_id}")
                    except Exception as e:
                        logger.warning(f"Failed to stop server process: {str(e)}")
                
                # Remove configuration file
                os.remove(config_file)
                logger.info(f"Removed server configuration file: {config_file}")
                
                # Update server list
                self.update_server_list(force_refresh=True)
                
                messagebox.showinfo("Success", "Server removed successfully.")
            else:
                messagebox.showinfo("Not Found", f"Server configuration file not found: {config_file}")
        except Exception as e:
            logger.error(f"Error removing server: {str(e)}")
            messagebox.showerror("Error", f"Failed to remove server: {str(e)}")
    
    def open_server_directory(self):
        """Open the directory of a selected server"""
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
                
            # Get installation directory
            if 'InstallDir' not in server_config:
                messagebox.showerror("Error", "Installation directory not specified in server configuration.")
                return
                
            install_dir = server_config['InstallDir']
            
            # Check if directory exists
            if not os.path.exists(install_dir):
                result = messagebox.askyesno("Directory Not Found", 
                                          f"The installation directory does not exist: {install_dir}\n\nDo you want to create it?",
                                          icon=messagebox.WARNING)
                
                if result:
                    os.makedirs(install_dir, exist_ok=True)
                else:
                    return
            
            # Open directory in file explorer
            if sys.platform == 'win32':
                os.startfile(install_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', install_dir])
            else:
                subprocess.Popen(['xdg-open', install_dir])
                
            logger.debug(f"Opened directory: {install_dir}")
            
        except Exception as e:
            logger.error(f"Error opening server directory: {str(e)}")
            messagebox.showerror("Error", f"Failed to open directory: {str(e)}")
    
    def import_server(self):
        """Import an existing server"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Import Existing Server")
        dialog.geometry("450x250")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Server name
        ttk.Label(dialog, text="Server Name:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=35)
        name_entry.grid(row=0, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Server path
        ttk.Label(dialog, text="Server Path:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        path_var = tk.StringVar()
        path_entry = ttk.Entry(dialog, textvariable=path_var, width=25)
        path_entry.grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)
        
        # Browse button
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Server Directory")
            if directory:
                path_var.set(directory)
                
        ttk.Button(dialog, text="Browse", command=browse_directory, width=10).grid(row=1, column=2, padx=5, pady=10)
        
        # App ID
        ttk.Label(dialog, text="Steam AppID:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        app_id_var = tk.StringVar()
        app_id_entry = ttk.Entry(dialog, textvariable=app_id_var, width=35)
        app_id_entry.grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Executable Path
        ttk.Label(dialog, text="Executable Path:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
        exec_path_var = tk.StringVar()
        exec_path_entry = ttk.Entry(dialog, textvariable=exec_path_var, width=35)
        exec_path_entry.grid(row=3, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Import button
        def do_import():
            try:
                server_name = name_var.get().strip()
                server_path = path_var.get().strip()
                app_id = app_id_var.get().strip()
                exec_path = exec_path_var.get().strip()
                
                # Validate inputs
                if not server_name or not server_path or not app_id:
                    messagebox.showerror("Error", "Server name, path and AppID are required fields.")
                    return
                    
                # Validate path exists
                if not os.path.exists(server_path):
                    messagebox.showerror("Error", "The specified server path does not exist.")
                    return
                
                # Create server configuration
                server_config = {
                    "Name": server_name,
                    "InstallDir": server_path,
                    "AppID": app_id,
                    "ExecutablePath": exec_path,
                    "Created": datetime.datetime.now().isoformat(),
                    "LastUpdate": datetime.datetime.now().isoformat(),
                    "Imported": True
                }
                
                # Create servers directory if it doesn't exist
                os.makedirs(self.paths["servers"], exist_ok=True)
                
                # Check if server already exists
                config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
                if os.path.exists(config_file):
                    result = messagebox.askyesno("Warning", 
                                               "A server with this name already exists. Do you want to overwrite it?",
                                               icon=messagebox.WARNING)
                    if not result:
                        return
                
                # Save server configuration
                with open(config_file, 'w') as f:
                    json.dump(server_config, f, indent=4)
                    
                # Update server list
                self.update_server_list(force_refresh=True)
                
                messagebox.showinfo("Success", "Server imported successfully!")
                dialog.destroy()
                
            except Exception as e:
                logger.error(f"Error importing server: {str(e)}")
                messagebox.showerror("Error", f"Failed to import server: {str(e)}")
        
        import_button = ttk.Button(dialog, text="Import", command=do_import, width=15)
        import_button.grid(row=4, column=0, columnspan=3, padx=10, pady=20)
        
        # Center dialog on parent window
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
    
    def add_agent(self):
        """Add a new agent"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Agent")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Agent name
        ttk.Label(dialog, text="Agent Name:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=30)
        name_entry.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # IP Address
        ttk.Label(dialog, text="IP Address:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        ip_var = tk.StringVar()
        ip_entry = ttk.Entry(dialog, textvariable=ip_var, width=30)
        ip_entry.grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)
        
        # Port
        ttk.Label(dialog, text="Port:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        port_var = tk.StringVar(value="8080")
        port_entry = ttk.Entry(dialog, textvariable=port_var, width=30)
        port_entry.grid(row=2, column=1, padx=10, pady=10, sticky=tk.W)
        
        # Add button
        def do_add():
            try:
                agent_name = name_var.get().strip()
                ip_address = ip_var.get().strip()
                port = port_var.get().strip()
                
                # Validate inputs
                if not agent_name or not ip_address or not port:
                    messagebox.showerror("Error", "Please fill in all fields.")
                    return
                
                # Create agent configuration
                agent_config = {
                    "Name": agent_name,
                    "IP": ip_address,
                    "Port": port,
                    "Added": datetime.datetime.now().isoformat()
                }
                
                # Create agents directory if it doesn't exist
                agents_path = os.path.join(self.server_manager_dir, "agents")
                os.makedirs(agents_path, exist_ok=True)
                
                # Save agent configuration
                with open(os.path.join(agents_path, f"{agent_name}.json"), 'w') as f:
                    json.dump(agent_config, f, indent=4)
                
                messagebox.showinfo("Success", "Agent added successfully!")
                dialog.destroy()
                
            except Exception as e:
                logger.error(f"Error adding agent: {str(e)}")
                messagebox.showerror("Error", f"Failed to add agent: {str(e)}")
        
        add_button = ttk.Button(dialog, text="Add Agent", command=do_add, width=15)
        add_button.grid(row=3, column=0, columnspan=2, padx=10, pady=20)
        
        # Center dialog on parent window
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
    
    def sync_all(self):
        """Sync all servers (placeholder)"""
        messagebox.showinfo("Sync Disabled", "Sync functionality is not available in this version.")
    
    def refresh_all(self):
        """Refresh server list and system info"""
        self.update_server_list(force_refresh=True)
        self.update_system_info()
        
        if self.variables["debugMode"]:
            messagebox.showinfo("Update Complete", "System information updated successfully.")
    
    def update_server_list(self, force_refresh=False):
        """Update the server list in the UI"""
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
                        cpu_usage = "N/A"
                        memory_usage = "N/A"
                        uptime = "N/A"
                        
                        # Get process if running
                        if "ProcessId" in server_config:
                            try:
                                process = psutil.Process(server_config["ProcessId"])
                                if process.is_running():
                                    status = "Running"
                                    try:
                                        cpu_usage = f"{process.cpu_percent(interval=0.1):.1f}%"
                                    except:
                                        cpu_usage = "N/A"
                                        
                                    try:
                                        memory_usage = f"{process.memory_info().rss / (1024 * 1024):.1f} MB"
                                    except:
                                        memory_usage = "N/A"
                                        
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
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                            except:
                                # Process doesn't exist, clean up the config
                                server_config.pop('ProcessId', None)
                                server_config.pop('StartTime', None)
                                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                
                                # Save updated configuration
                                with open(os.path.join(servers_path, file), 'w') as f:
                                    json.dump(server_config, f, indent=4)
                                
                        # Add to list
                        self.server_list.insert("", tk.END, values=(
                            server_config["Name"],
                            status,
                            cpu_usage,
                            memory_usage,
                            uptime
                        ))
                        
                    except Exception as e:
                        logger.error(f"Failed to process server config {file}: {str(e)}")
        
        # Update last refresh time
        self.variables["lastServerListUpdate"] = datetime.datetime.now()
    
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
        """Start the selected game server"""
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
                
            # Check if server is already running
            if 'ProcessId' in server_config and self.is_process_running(server_config['ProcessId']):
                messagebox.showinfo("Already Running", f"Server '{server_name}' is already running.")
                return
                
            # Check for executable path
            if 'ExecutablePath' not in server_config or not server_config['ExecutablePath']:
                # No executable path specified, show configuration dialog
                messagebox.showinfo("Configuration Needed", 
                                    "No executable specified. Please configure the server startup settings.")
                self.configure_server()
                return
                
            executable_path = server_config['ExecutablePath']
            install_dir = server_config.get('InstallDir', '')
            
            # Validate executable path
            if not os.path.exists(executable_path):
                messagebox.showerror("Error", f"Executable not found: {executable_path}")
                return
                
            # Get startup arguments if available
            startup_args = server_config.get('StartupArgs', '')
            
            # Build the command
            if executable_path.lower().endswith(('.bat', '.cmd')):
                # For batch files, use call to ensure we don't block
                cmd = f'start "" /D "{install_dir}" cmd /c "{executable_path}" {startup_args}'
                shell = True
            elif executable_path.lower().endswith('.sh') and sys.platform != 'win32':
                # For shell scripts on non-Windows platforms
                cmd = ['/bin/sh', executable_path]
                if startup_args:
                    cmd.extend(startup_args.split())
                shell = False
            else:
                # For regular executables
                cmd = f'"{executable_path}" {startup_args}'
                shell = True
                
            # Create logs directory if it doesn't exist
            server_logs_dir = os.path.join(install_dir, "logs")
            os.makedirs(server_logs_dir, exist_ok=True)
            
            # Set up log files
            stdout_log = os.path.join(server_logs_dir, "server_stdout.log")
            stderr_log = os.path.join(server_logs_dir, "server_stderr.log")
            
            # Start the process
            logger.info(f"Starting server: {server_name} with command: {cmd}")
            
            # Open log files
            with open(stdout_log, 'a') as stdout_file, open(stderr_log, 'a') as stderr_file:
                # Write startup timestamp
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                stdout_file.write(f"\n--- Server started at {timestamp} ---\n")
                
                # Start the process
                if shell:
                    process = subprocess.Popen(
                        cmd,
                        shell=True,
                        cwd=install_dir,
                        stdout=stdout_file,
                        stderr=stderr_file
                    )
                else:
                    process = subprocess.Popen(
                        cmd,
                        cwd=install_dir,
                        stdout=stdout_file,
                        stderr=stderr_file
                    )
                
            # Update server configuration with process ID
            server_config['ProcessId'] = process.pid
            server_config['StartTime'] = datetime.datetime.now().isoformat()
            server_config['LastUpdate'] = datetime.datetime.now().isoformat()
            
            # Save updated configuration
            with open(config_file, 'w') as f:
                json.dump(server_config, f, indent=4)
                
            # Update server list
            self.update_server_list(force_refresh=True)
            
            messagebox.showinfo("Success", f"Server '{server_name}' started successfully.")
            
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
                messagebox.showinfo("Not Running", f"Server '{server_name}' is not running.")
                
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
                                        f"Are you sure you want to stop the server '{server_name}'?",
                                        icon=messagebox.WARNING)
            
            if not confirm:
                return
                
            # Try to use custom stop command if available
            if 'StopCommand' in server_config and server_config['StopCommand']:
                try:
                    stop_cmd = server_config['StopCommand']
                    install_dir = server_config.get('InstallDir', '')
                    
                    logger.info(f"Executing custom stop command: {stop_cmd}")
                    subprocess.run(stop_cmd, shell=True, cwd=install_dir, timeout=30)
                    
                    # Wait a bit to see if the process stops
                    time.sleep(2)
                    
                    # Check if process is still running
                    if not self.is_process_running(process_id):
                        # Process stopped successfully
                        server_config.pop('ProcessId', None)
                        server_config.pop('StartTime', None)
                        server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                        
                        # Save updated configuration
                        with open(config_file, 'w') as f:
                            json.dump(server_config, f, indent=4)
                            
                        # Update server list
                        self.update_server_list(force_refresh=True)
                        
                        messagebox.showinfo("Success", f"Server '{server_name}' stopped successfully.")
                        return
                    else:
                        logger.warning(f"Custom stop command did not stop the server, using force termination")
                except Exception as e:
                    logger.error(f"Error executing custom stop command: {str(e)}")
            
            # If we got here, either the custom stop command failed or wasn't available
            # Try to terminate the process
            try:
                process = psutil.Process(process_id)
                
                # First try graceful termination
                process.terminate()
                
                # Wait up to 5 seconds for the process to terminate
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    # If it doesn't terminate, kill it forcefully
                    logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                    process.kill()
                
                logger.info(f"Terminated server process with PID {process_id}")
                
                # Update server configuration
                server_config.pop('ProcessId', None)
                server_config.pop('StartTime', None)
                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                
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
    
    def configure_server(self):
        """Configure server executable and startup settings"""
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
                
            # Get installation directory
            install_dir = server_config.get('InstallDir', '')
            if not install_dir or not os.path.exists(install_dir):
                messagebox.showerror("Error", "Server installation directory not found.")
                return
                
            # Create configuration dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Configure Server: {server_name}")
            dialog.geometry("600x450")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Create a frame with padding
            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Server information display
            info_frame = ttk.LabelFrame(main_frame, text="Server Information")
            info_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(info_frame, text=f"Name: {server_name}", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=10, pady=2)
            ttk.Label(info_frame, text=f"AppID: {server_config.get('AppID', 'N/A')}").pack(anchor=tk.W, padx=10, pady=2)
            ttk.Label(info_frame, text=f"Install Directory: {install_dir}").pack(anchor=tk.W, padx=10, pady=2)
            
            # Startup configuration
            startup_frame = ttk.LabelFrame(main_frame, text="Startup Configuration")
            startup_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Executable path
            ttk.Label(startup_frame, text="Executable Path:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.W)
            exec_path_var = tk.StringVar(value=server_config.get('ExecutablePath', ''))
            exec_path_entry = ttk.Entry(startup_frame, textvariable=exec_path_var, width=40)
            exec_path_entry.grid(row=0, column=1, padx=5, pady=10, sticky=tk.W)
            
            # Browse button for executable
            def browse_executable():
                filetypes = [
                    ("Executables", "*.exe;*.bat;*.cmd;*.sh"),
                    ("All files", "*.*")
                ]
                filepath = filedialog.askopenfilename(
                    title="Select Server Executable",
                    initialdir=install_dir,
                    filetypes=filetypes
                )
                if filepath:
                    # Convert to relative path if it's within the install directory
                    if os.path.commonpath([filepath, install_dir]) == install_dir:
                        rel_path = os.path.relpath(filepath, install_dir)
                        exec_path_var.set(rel_path)
                    else:
                        exec_path_var.set(filepath)
                    
            browse_btn = ttk.Button(startup_frame, text="Browse", command=browse_executable, width=10)
            browse_btn.grid(row=0, column=2, padx=5, pady=10)
            
            # Startup arguments
            ttk.Label(startup_frame, text="Startup Arguments:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
            startup_args_var = tk.StringVar(value=server_config.get('StartupArgs', ''))
            startup_args_entry = ttk.Entry(startup_frame, textvariable=startup_args_var, width=40)
            startup_args_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=10, sticky=tk.W+tk.E)
            
            # Custom stop command
            ttk.Label(startup_frame, text="Stop Command:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
            stop_cmd_var = tk.StringVar(value=server_config.get('StopCommand', ''))
            stop_cmd_entry = ttk.Entry(startup_frame, textvariable=stop_cmd_var, width=40)
            stop_cmd_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=10, sticky=tk.W+tk.E)
            
            # Working directory options
            ttk.Label(startup_frame, text="Working Directory:").grid(row=3, column=0, padx=10, pady=10, sticky=tk.W)
            working_dir_var = tk.StringVar(value=server_config.get('WorkingDir', ''))
            working_dir_entry = ttk.Entry(startup_frame, textvariable=working_dir_var, width=40)
            working_dir_entry.grid(row=3, column=1, padx=5, pady=10, sticky=tk.W)
            
            # Browse button for working directory
            def browse_working_dir():
                directory = filedialog.askdirectory(
                    title="Select Working Directory",
                    initialdir=install_dir
                )
                if directory:
                    # Convert to relative path if it's within the install directory
                    if os.path.commonpath([directory, install_dir]) == install_dir:
                        rel_path = os.path.relpath(directory, install_dir)
                        working_dir_var.set(rel_path)
                    else:
                        working_dir_var.set(directory)
                    
            working_dir_btn = ttk.Button(startup_frame, text="Browse", command=browse_working_dir, width=10)
            working_dir_btn.grid(row=3, column=2, padx=5, pady=10)
            
            # Help text
            help_text = ttk.Label(
                main_frame, 
                text="Note: For relative paths, use paths relative to the installation directory.\n"
                     "For the stop command, leave blank to use the default termination method.",
                foreground="gray"
            )
            help_text.pack(fill=tk.X, pady=5)
            
            # Buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=10)
            
            def save_configuration():
                try:
                    # Get values from form
                    exec_path = exec_path_var.get().strip()
                    startup_args = startup_args_var.get().strip()
                    stop_cmd = stop_cmd_var.get().strip()
                    working_dir = working_dir_var.get().strip()
                    
                    # Validate executable path
                    if not exec_path:
                        messagebox.showerror("Validation Error", "Executable path is required.")
                        return
                        
                    # Resolve paths
                    if not os.path.isabs(exec_path):
                        exec_path_abs = os.path.join(install_dir, exec_path)
                    else:
                        exec_path_abs = exec_path
                        
                    if working_dir and not os.path.isabs(working_dir):
                        working_dir_abs = os.path.join(install_dir, working_dir)
                    else:
                        working_dir_abs = working_dir if working_dir else install_dir
                    
                    # Check if executable exists
                    if not os.path.exists(exec_path_abs):
                        result = messagebox.askyesno(
                            "Warning", 
                            f"The specified executable was not found: {exec_path_abs}\n\nSave anyway?",
                            icon=messagebox.WARNING
                        )
                        if not result:
                            return
                    
                    # Update server configuration
                    server_config['ExecutablePath'] = exec_path
                    server_config['StartupArgs'] = startup_args
                    server_config['StopCommand'] = stop_cmd
                    server_config['WorkingDir'] = working_dir
                    server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                    
                    # Save updated configuration
                    with open(config_file, 'w') as f:
                        json.dump(server_config, f, indent=4)
                        
                    messagebox.showinfo("Success", "Server configuration saved successfully.")
                    dialog.destroy()
                    
                except Exception as e:
                    logger.error(f"Error saving server configuration: {str(e)}")
                    messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
            
            save_btn = ttk.Button(button_frame, text="Save", command=save_configuration, width=10)
            save_btn.pack(side=tk.RIGHT, padx=5)
            
            cancel_btn = ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=10)
            cancel_btn.pack(side=tk.RIGHT, padx=5)
            
            # Test button
            def test_executable():
                try:
                    exec_path = exec_path_var.get().strip()
                    
                    if not exec_path:
                        messagebox.showerror("Error", "No executable specified.")
                        return
                        
                    # Resolve path
                    if not os.path.isabs(exec_path):
                        exec_path_abs = os.path.join(install_dir, exec_path)
                    else:
                        exec_path_abs = exec_path
                        
                    # Check if file exists
                    if not os.path.exists(exec_path_abs):
                        messagebox.showerror("Error", f"Executable not found: {exec_path_abs}")
                        return
                        
                    # Show success message
                    messagebox.showinfo("Success", f"Executable found: {exec_path_abs}")
                    
                except Exception as e:
                    logger.error(f"Error testing executable: {str(e)}")
                    messagebox.showerror("Error", f"Test failed: {str(e)}")
            
            test_btn = ttk.Button(button_frame, text="Test Path", command=test_executable, width=10)
            test_btn.pack(side=tk.LEFT, padx=5)
            
            # Center dialog on parent window
            dialog.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
            dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error configuring server: {str(e)}")
            messagebox.showerror("Error", f"Failed to configure server: {str(e)}")
    
    def update_server_list(self, force_refresh=False):
        """Update the server list in the UI"""
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
                        cpu_usage = "N/A"
                        memory_usage = "N/A"
                        uptime = "N/A"
                        
                        # Get process if running
                        if "ProcessId" in server_config:
                            try:
                                process = psutil.Process(server_config["ProcessId"])
                                if process.is_running():
                                    status = "Running"
                                    try:
                                        cpu_usage = f"{process.cpu_percent(interval=0.1):.1f}%"
                                    except:
                                        cpu_usage = "N/A"
                                        
                                    try:
                                        memory_usage = f"{process.memory_info().rss / (1024 * 1024):.1f} MB"
                                    except:
                                        memory_usage = "N/A"
                                        
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
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                            except:
                                # Process doesn't exist, clean up the config
                                server_config.pop('ProcessId', None)
                                server_config.pop('StartTime', None)
                                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                
                                # Save updated configuration
                                with open(os.path.join(servers_path, file), 'w') as f:
                                    json.dump(server_config, f, indent=4)
                                
                        # Add to list
                        self.server_list.insert("", tk.END, values=(
                            server_config["Name"],
                            status,
                            cpu_usage,
                            memory_usage,
                            uptime
                        ))
                        
                    except Exception as e:
                        logger.error(f"Failed to process server config {file}: {str(e)}")
        
        # Update last refresh time
        self.variables["lastServerListUpdate"] = datetime.datetime.now()
    
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
