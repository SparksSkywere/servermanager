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

# Import documentation module
from Modules.documentation import show_help_dialog, show_about_dialog

# Import dashboard functions
from Host.dashboard_functions import (
    load_dashboard_config, initialize_paths_from_registry, initialize_registry_values,
    is_process_running, is_port_open, check_webserver_status, update_webserver_status,
    api_headers, get_steam_credentials, update_system_info, format_uptime_from_start_time,
    get_process_info, export_server_configuration, import_server_configuration,
    export_server_to_file, import_server_from_file, extract_server_files_from_archive,
    generate_unique_server_name, center_window, create_server_type_selection_dialog,
    update_server_status_in_treeview, validate_server_creation_inputs, 
    open_directory_in_explorer, create_confirmation_dialog, show_progress_dialog,
    create_server_installation_dialog, create_server_removal_dialog, perform_server_installation,
    update_server_list_from_files, create_progress_dialog_with_console
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
        self.config = load_dashboard_config(self.server_manager_dir)
        
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
        self.root.minsize(1000, 700)
        
        # Center the main window on screen
        center_window(self.root, 1400, 900)
        
        self.setup_ui()
        
        # Write PID file
        write_pid_file("dashboard", os.getpid(), self.paths["temp"])
        
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
        success, user = sql_login(self.user_manager, self.root)
        if not success:
            logger.info("Login cancelled, exiting application")
            self.root.destroy()
            sys.exit(0)
        self.current_user = user

    def initialize(self):
        """Initialize basic paths from registry"""
        success, self.server_manager_dir, self.paths = initialize_paths_from_registry(self.registry_path)
        return success

    def initialize_registry_values(self):
        """Initialize registry-managed values"""
        success, self.steam_cmd_path, webserver_port, self.registry_values = initialize_registry_values(self.registry_path)
        if success:
            self.variables["defaultSteamPath"] = self.steam_cmd_path or ""
            self.variables["webserverPort"] = webserver_port
            # Set default install directory
            if self.steam_cmd_path:
                self.variables["defaultInstallDir"] = os.path.join(self.steam_cmd_path, "steamapps", "common")
        return success
    
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
        """Add a new game server (Steam, Minecraft, or Other)"""
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialized.")
            return
            
        # Use the new function to get server type selection
        server_type = create_server_type_selection_dialog(self.root, self.supported_server_types)
        
        # Check if user cancelled
        if not server_type:
            return

        # Create the installation dialog components
        dialog_components = create_server_installation_dialog(
            self.root, server_type, self.supported_server_types, self.server_manager, self.paths
        )
        
        if not dialog_components:
            return

        dialog = dialog_components['dialog']
        main_frame = dialog_components['main_frame']
        form_vars = dialog_components['form_vars']
        credentials = dialog_components['credentials']

        # Console output section
        console_container = ttk.Frame(main_frame)
        console_container.pack(fill=tk.X, padx=15, pady=10)
        
        console_output = scrolledtext.ScrolledText(console_container, width=70, height=8, 
                                                 background="black", foreground="white", 
                                                 font=("Consolas", 9))
        console_output.pack(fill=tk.BOTH, expand=True)
        console_output.config(state=tk.DISABLED)

        # Status and progress bar
        status_container = ttk.Frame(main_frame)
        status_container.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        status_var = tk.StringVar(value="")
        status_label = ttk.Label(status_container, textvariable=status_var, font=("Segoe UI", 10))
        status_label.pack(anchor=tk.W, pady=(0, 5))
        
        progress = ttk.Progressbar(status_container, mode="indeterminate")
        progress.pack(fill=tk.X)

        # Installation control
        self.install_cancelled = tk.BooleanVar(value=False)
        
        def append_console(text):
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)

        def install_server():
            try:
                create_button.config(state=tk.DISABLED)
                cancel_button.config(state=tk.NORMAL)
                progress.start(10)
                
                # Use the new installation function
                success, message = perform_server_installation(
                    self.server_manager, server_type, form_vars, credentials, self.paths,
                    status_callback=status_var.set,
                    console_callback=append_console,
                    cancel_flag=self.install_cancelled,
                    steam_cmd_path=getattr(self, 'steam_cmd_path', None)
                )

                if success:
                    self.update_server_list(force_refresh=True)
                    messagebox.showinfo("Success", message)
                    dialog.destroy()
                else:
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

        # Button frame at the bottom
        button_container = ttk.Frame(main_frame)
        button_container.pack(fill=tk.X, padx=15, pady=15)
        
        # Create and Cancel buttons
        create_button = ttk.Button(button_container, text="Create Server", width=18)
        create_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        cancel_button = ttk.Button(button_container, text="Cancel Installation", width=18, state=tk.DISABLED)
        cancel_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        close_button = ttk.Button(button_container, text="Close", width=12)
        close_button.pack(side=tk.LEFT)
        
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
        
        # Center dialog relative to parent
        center_window(dialog, 700, 650, self.root)

    def update_server_list(self, force_refresh=False):
        """Update server list from configuration files"""
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
    
    def toggle_offline_mode(self):
        """Toggle offline mode"""
        self.variables["offlineMode"] = self.offline_var.get()
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
    def update_webserver_status(self):
        """Update the web server status display"""
        update_webserver_status(self.webserver_status, self.offline_var, self.paths, self.variables)
    
    def update_system_info(self):
        """Update system information in the UI"""
        try:
            # Update web server status
            self.update_webserver_status()
            
            # Use the function from dashboard_functions
            update_system_info(self.metric_labels, self.system_name, self.os_info, self.variables)
            
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
        """Update the status of a server in the UI"""
        update_server_status_in_treeview(self.server_list, server_name, status)
        # Force UI update
        self.root.update_idletasks()
    
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
