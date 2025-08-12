import os
import sys
import json
import datetime
import platform
import socket
import winreg
import psutil
import threading
import tkinter as tk
import os
import sys
import json
import datetime
import psutil
import subprocess
import winreg
import time
import threading
import socket
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import zipfile

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import registry functions from common module
from Modules.common import initialize_paths_from_registry, initialize_registry_values

# Import logging functions
from Modules.logging import get_dashboard_logger

# Import debug functions
from debug.debug import get_process_info

# Get dashboard logger
logger = get_dashboard_logger()


def create_java_selection_dialog(root, minecraft_version=None):
    """Create a dialog to select Java installation for a server.
    
    Args:
        root: Parent window
        minecraft_version (str): Minecraft version to check compatibility (optional)
        
    Returns:
        dict: Selected Java installation info, or None if cancelled
    """
    try:
        # Import here to avoid circular imports
        from Scripts.minecraft import detect_java_installations, get_minecraft_java_requirement, check_java_compatibility
        
        dialog = tk.Toplevel(root)
        dialog.title("Select Java Installation")
        dialog.geometry("600x400")
        dialog.resizable(True, True)
        dialog.transient(root)
        dialog.grab_set()
        
        # Create main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title and info
        title_label = ttk.Label(main_frame, text="Select Java Installation", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 10))
        
        if minecraft_version:
            required_java = get_minecraft_java_requirement(minecraft_version)
            info_label = ttk.Label(main_frame, 
                                 text=f"Minecraft {minecraft_version} requires Java {required_java} or later",
                                 font=("Segoe UI", 9))
            info_label.pack(pady=(0, 15))
        
        # Create frame for java list
        list_frame = ttk.LabelFrame(main_frame, text="Available Java Installations", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Create treeview for Java installations
        columns = ("version", "path", "compatibility")
        java_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        # Define headings
        java_tree.heading("version", text="Java Version")
        java_tree.heading("path", text="Installation Path")
        java_tree.heading("compatibility", text="Compatibility")
        
        # Configure column widths
        java_tree.column("version", width=150, minwidth=100)
        java_tree.column("path", width=300, minwidth=200)
        java_tree.column("compatibility", width=120, minwidth=100)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=java_tree.yview)
        java_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack treeview and scrollbar
        java_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate with detected Java installations
        java_installations = detect_java_installations()
        selected_java = None
        
        for installation in java_installations:
            if minecraft_version:
                is_compatible, _, _, _ = check_java_compatibility(minecraft_version, installation["path"])
                compatibility_text = "✓ Compatible" if is_compatible else "✗ Incompatible"
                
                # Color code the entries
                if is_compatible:
                    tags = ("compatible",)
                else:
                    tags = ("incompatible",)
            else:
                compatibility_text = "N/A"
                tags = ()
            
            item_id = java_tree.insert("", tk.END, 
                                     values=(installation["display_name"], 
                                           installation["path"], 
                                           compatibility_text),
                                     tags=tags)
            
            # Store the installation data in the item
            java_tree.set(item_id, "data", installation)
        
        # Configure tags for coloring
        java_tree.tag_configure("compatible", foreground="green")
        java_tree.tag_configure("incompatible", foreground="red")
        
        # Add refresh button
        refresh_frame = ttk.Frame(main_frame)
        refresh_frame.pack(fill=tk.X, pady=(0, 15))
        
        def refresh_java_list():
            # Clear existing items
            for item in java_tree.get_children():
                java_tree.delete(item)
            
            # Repopulate
            java_installations = detect_java_installations()
            for installation in java_installations:
                if minecraft_version:
                    is_compatible, _, _, _ = check_java_compatibility(minecraft_version, installation["path"])
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
                java_tree.set(item_id, "data", installation)
        
        ttk.Button(refresh_frame, text="Refresh List", command=refresh_java_list).pack(side=tk.LEFT)
        
        # Add custom Java path entry
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
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        result = {}  # Will store the selected Java installation
        
        def on_select():
            # Check if custom path is provided
            custom_path = custom_path_var.get().strip()
            if custom_path:
                # Validate custom path
                from Scripts.minecraft import get_java_version
                major, version = get_java_version(custom_path)
                if major is not None:
                    result["java"] = {
                        "path": custom_path,
                        "version": version,
                        "major": major,
                        "display_name": f"Custom Java {major}"
                    }
                    dialog.destroy()
                    return
                else:
                    messagebox.showerror("Error", f"Invalid Java executable: {custom_path}")
                    return
            
            # Check if an item is selected from the list
            selection = java_tree.selection()
            if selection:
                item = selection[0]
                # Get the stored installation data
                for installation in java_installations:
                    if (java_tree.item(item)["values"][0] == installation["display_name"] and 
                        java_tree.item(item)["values"][1] == installation["path"]):
                        result["java"] = installation
                        break
                dialog.destroy()
            else:
                messagebox.showwarning("Warning", "Please select a Java installation or provide a custom path.")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Select", command=on_select, width=12).pack(side=tk.RIGHT)
        
        # Auto-select the first compatible Java if available
        if minecraft_version and java_installations:
            for i, installation in enumerate(java_installations):
                is_compatible, _, _, _ = check_java_compatibility(minecraft_version, installation["path"])
                if is_compatible:
                    # Select the first compatible Java
                    items = java_tree.get_children()
                    if i < len(items):
                        java_tree.selection_set(items[i])
                        java_tree.focus(items[i])
                    break
        
        # Center dialog
        center_window(dialog, 600, 400, root)
        
        # Wait for dialog to close
        root.wait_window(dialog)
        
        return result.get("java")
        
    except Exception as e:
        logger.error(f"Error creating Java selection dialog: {str(e)}")
        messagebox.showerror("Error", f"Failed to create Java selection dialog: {str(e)}")
        return None


def load_appid_scanner_list(server_manager_dir):
    """Load the AppID list from database or fallback to JSON"""
    try:
        # First try to load from database
        dedicated_servers, metadata = load_appid_list_from_database()
        
        if dedicated_servers:
            logger.info(f"Loaded {len(dedicated_servers)} dedicated servers from database")
            return dedicated_servers, metadata
        
        # Fallback to JSON file if database is empty or unavailable
        logger.info("Database empty or unavailable, falling back to JSON file")
        json_file_path = os.path.join(server_manager_dir, 'data', 'AppIDList.json')
        
        if os.path.exists(json_file_path):
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            dedicated_servers = data.get('dedicated_servers', [])
            metadata = data.get('metadata', {})
            
            logger.info(f"Loaded {len(dedicated_servers)} dedicated servers from JSON fallback")
            logger.info(f"Last updated: {metadata.get('last_updated', 'Unknown')}")
            
            return dedicated_servers, metadata
        else:
            logger.warning(f"Neither database nor JSON file available for AppID list")
            return [], {}
            
    except Exception as e:
        logger.error(f"Error loading AppID scanner list: {e}")
        return [], {}


def load_appid_list_from_database():
    """Load AppID list directly from database"""
    try:
        # Import database components
        from Modules.SQL_Connection import get_engine
        from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
        from sqlalchemy.orm import declarative_base, sessionmaker
        
        # Define the SteamApp model (matching AppIDScanner.py)
        Base = declarative_base()
        
        class SteamApp(Base):
            __tablename__ = 'steam_apps'
            
            appid = Column(Integer, primary_key=True)
            name = Column(String(255), nullable=False)
            type = Column(String(50))
            is_server = Column(Boolean, default=False)
            is_dedicated_server = Column(Boolean, default=False)
            developer = Column(String(255))
            publisher = Column(String(255))
            release_date = Column(String(50))
            description = Column(Text)
            tags = Column(Text)  # JSON string of tags
            price = Column(String(20))
            platforms = Column(String(100))  # JSON string of supported platforms
            last_updated = Column(DateTime)
            source = Column(String(50), default='steamdb')
        
        # Connect to database
        engine = get_engine()
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Query dedicated servers only
        apps = session.query(SteamApp).filter(SteamApp.is_dedicated_server == True).all()
        
        dedicated_servers = []
        latest_update = None
        
        for app in apps:
            server_entry = {
                "appid": app.appid,
                "name": app.name,
                "type": app.type or "Dedicated Server",
                "developer": app.developer or "",
                "publisher": app.publisher or "",
                "release_date": app.release_date or "",
                "description": app.description or "",
                "platforms": app.platforms or "",
                "source": app.source or "steam_api",
                "tags": app.tags or "[]"
            }
            dedicated_servers.append(server_entry)
            
            # Track latest update time - get the actual datetime value
            app_last_updated = getattr(app, 'last_updated', None)
            if app_last_updated is not None:
                if latest_update is None or app_last_updated > latest_update:
                    latest_update = app_last_updated
        
        # Close session
        session.close()
        
        # Create metadata
        metadata = {
            "last_updated": latest_update.isoformat() if latest_update is not None else "",
            "total_dedicated_servers": len(dedicated_servers),
            "source": "database",
            "version": "3.0",
            "filter_mode": "dedicated_only",
            "description": "Steam dedicated server applications from database"
        }
        
        return dedicated_servers, metadata
        
    except ImportError as e:
        logger.warning(f"Database modules not available: {e}")
        return [], {}
    except Exception as e:
        logger.warning(f"Error loading AppID list from database: {e}")
        return [], {}


def load_dashboard_config(server_manager_dir):
    """Load dashboard configuration from JSON file"""
    try:
        if not server_manager_dir:
            logger.warning("Server manager directory not initialized, using default config")
            return {}
            
        config_file = os.path.join(server_manager_dir, "data", "dashboard.json")
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded dashboard configuration from: {config_file}")
            return config
        else:
            logger.warning(f"Dashboard config file not found: {config_file}, using defaults")
            return {}
    except Exception as e:
        logger.error(f"Failed to load dashboard configuration: {str(e)}")
        return {}


def is_process_running(pid):
    """Check if a process with the given PID is running"""
    try:
        return psutil.pid_exists(pid)
    except:
        return False


def is_port_open(host, port, timeout=1):
    """Check if a port is open on the specified host"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def check_webserver_status(paths, variables):
    """Check if the web server is running and return status"""
    if variables.get("offlineMode", False):
        return "Offline Mode"
        
    try:
        # Try to read the web server PID file first
        webserver_pid_file = os.path.join(paths["temp"], "webserver.pid")
        if os.path.exists(webserver_pid_file):
            try:
                with open(webserver_pid_file, 'r') as f:
                    pid_info = json.load(f)
                
                pid = pid_info.get("ProcessId")
                port = pid_info.get("Port", variables.get("webserverPort", 8080))
                
                # Check if process is running
                if pid and is_process_running(pid):
                    return "Connected"
            except Exception as e:
                logger.debug(f"Error checking web server PID file: {str(e)}")
        
        # If we get here, try to connect to the port directly
        webserver_port = variables.get("webserverPort", 8080)
        if is_port_open('localhost', webserver_port):
            return "Connected"
        else:
            return "Disconnected"
            
    except Exception as e:
        logger.error(f"Error checking web server status: {str(e)}")
        return "Error"


def update_webserver_status(webserver_status_label, offline_var, paths, variables):
    """Update the web server status display"""
    try:
        status = check_webserver_status(paths, variables)
        variables["webserverStatus"] = status
        
        # Update status label with appropriate color
        if status == "Connected":
            webserver_status_label.config(text=status, foreground="green")
        elif status == "Offline Mode":
            webserver_status_label.config(text=status, foreground="orange")
        else:
            webserver_status_label.config(text=status, foreground="red")
            
        # Update offline mode checkbox
        offline_var.set(variables.get("offlineMode", False))
        
    except Exception as e:
        logger.error(f"Error updating web server status: {str(e)}")
        webserver_status_label.config(text="Error", foreground="red")


def api_headers():
    """Return API headers (currently using direct SQL access)"""
    return {}


def get_steam_credentials(root):
    """Open a dialog to get Steam credentials"""
    credentials = {"anonymous": False, "username": "", "password": ""}
    
    # Create dialog window
    dialog = tk.Toplevel(root)
    dialog.title("Steam Login")
    dialog.geometry("300x250")
    dialog.resizable(False, False)
    dialog.transient(root)
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
    x = root.winfo_rootx() + (root.winfo_width() - dialog.winfo_width()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")
    
    # Wait for dialog to close
    root.wait_window(dialog)
    
    # Return credentials if successful, None otherwise
    return credentials if result["success"] else None


def update_system_info(metric_labels, system_name, os_info, variables):
    """Update system information in the UI"""
    try:
        # Computer name and OS info
        computer_name = platform.node()
        os_info_text = f"{platform.system()} {platform.version()}"
        
        system_name.config(text=computer_name)
        os_info.config(text=os_info_text)
        
        # CPU usage - use non-blocking call (interval=None uses cached value)
        cpu_percent = psutil.cpu_percent(interval=None)
        metric_labels["cpu"].config(text=f"{cpu_percent:.1f}%")
        
        # Memory usage
        memory = psutil.virtual_memory()
        total_mem_gb = memory.total / (1024 * 1024 * 1024)
        used_mem_gb = memory.used / (1024 * 1024 * 1024)
        metric_labels["memory"].config(text=f"{used_mem_gb:.1f} GB / {total_mem_gb:.1f} GB")
        
        # Disk usage
        total_size = 0
        total_used = 0
        
        for part in psutil.disk_partitions(all=False):
            if part.fstype:
                usage = psutil.disk_usage(part.mountpoint)
                total_size += usage.total
                total_used += usage.used
        
        total_size_gb = total_size / (1024 * 1024 * 1024)
        total_used_gb = total_used / (1024 * 1024 * 1024)
        
        metric_labels["disk"].config(text=f"{total_used_gb:.0f} GB / {total_size_gb:.0f} GB")
        
        # Network usage
        network_stats = psutil.net_io_counters()
        
        if variables.get("lastNetworkStats"):
            last_stats = variables["lastNetworkStats"]
            last_time = variables["lastNetworkStatsTime"]
            time_diff = (datetime.datetime.now() - last_time).total_seconds()
            
            if time_diff > 0:
                bytes_sent = network_stats.bytes_sent - last_stats.bytes_sent
                bytes_recv = network_stats.bytes_recv - last_stats.bytes_recv
                
                send_rate = bytes_sent / time_diff / 1024  # KB/s
                recv_rate = bytes_recv / time_diff / 1024  # KB/s
                
                if send_rate > 1024 or recv_rate > 1024:
                    send_rate = send_rate / 1024  # MB/s
                    recv_rate = recv_rate / 1024  # MB/s
                    metric_labels["network"].config(text=f"↓{recv_rate:.1f} MB/s | ↑{send_rate:.1f} MB/s")
                else:
                    metric_labels["network"].config(text=f"↓{recv_rate:.1f} KB/s | ↑{send_rate:.1f} KB/s")
            else:
                metric_labels["network"].config(text="Calculating...")
        else:
            metric_labels["network"].config(text="Calculating...")
        
        variables["lastNetworkStats"] = network_stats
        variables["lastNetworkStatsTime"] = datetime.datetime.now()
        
        # GPU info - placeholder since getting GPU info is more complex
        metric_labels["gpu"].config(text="N/A")
        
        # System uptime
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        metric_labels["uptime"].config(text=uptime_str)
        
        # Update last refresh time
        variables["lastFullUpdate"] = datetime.datetime.now()
        
    except Exception as e:
        logger.error(f"Error updating system info: {str(e)}")


def export_server_configuration(server_name, paths, include_files=False):
    """Export server configuration to a portable format
    
    Args:
        server_name (str): Name of the server to export
        paths (dict): Application paths dictionary
        include_files (bool): Whether to include server files in export
        
    Returns:
        dict: Export data containing server configuration and metadata
    """
    try:
        # Find server configuration file
        servers_path = os.path.join(paths["root"], "servers")
        server_config_file = None
        
        if os.path.exists(servers_path):
            for file in os.listdir(servers_path):
                if file.endswith('.json'):
                    try:
                        with open(os.path.join(servers_path, file), 'r') as f:
                            config = json.load(f)
                        if config.get("Name") == server_name:
                            server_config_file = os.path.join(servers_path, file)
                            break
                    except:
                        continue
        
        if not server_config_file:
            raise ValueError(f"Server configuration not found for: {server_name}")
        
        # Load server configuration
        with open(server_config_file, 'r') as f:
            server_config = json.load(f)
        
        # Create export data structure
        export_data = {
            "export_metadata": {
                "version": "1.0",
                "exported_at": datetime.datetime.now().isoformat(),
                "exported_by": os.environ.get('USERNAME', 'Unknown'),
                "source_host": platform.node(),
                "export_type": "server_configuration",
                "includes_files": include_files
            },
            "server_configuration": server_config,
            "dependencies": {}
        }
        
        # Add Steam App ID information if it's a Steam server
        if server_config.get("Type") == "Steam" and server_config.get("AppId"):
            try:
                # Try to get app information from AppIDList
                appid_file = os.path.join(paths["data"], "AppIDList.json")
                if os.path.exists(appid_file):
                    with open(appid_file, 'r') as f:
                        app_data = json.load(f)
                    
                    # Find app info by ID
                    app_info = None
                    for app in app_data.get("dedicated_servers", []):
                        if str(app.get("appid")) == str(server_config["AppId"]):
                            app_info = app
                            break
                    
                    if app_info:
                        export_data["dependencies"]["steam_app_info"] = app_info
                        export_data["dependencies"]["requires_steam_install"] = True
                        
            except Exception as e:
                logger.warning(f"Could not load Steam app information: {str(e)}")
        
        # Add file information if requested
        if include_files and server_config.get("InstallDir"):
            install_dir = server_config["InstallDir"]
            if os.path.exists(install_dir):
                export_data["dependencies"]["install_directory_size"] = get_directory_size(install_dir)
                export_data["dependencies"]["file_count"] = count_files_in_directory(install_dir)
        
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting server configuration: {str(e)}")
        raise


def import_server_configuration(export_data, paths, install_directory=None, auto_install=False):
    """Import server configuration from export data
    
    Args:
        export_data (dict): Exported server configuration data
        paths (dict): Application paths dictionary
        install_directory (str): Target installation directory (optional)
        auto_install (bool): Whether to automatically install Steam servers
        
    Returns:
        tuple: (success, message, server_config)
    """
    try:
        # Validate export data
        if not export_data.get("server_configuration"):
            return False, "Invalid export data: Missing server configuration", None
        
        server_config = export_data["server_configuration"].copy()
        export_metadata = export_data.get("export_metadata", {})
        dependencies = export_data.get("dependencies", {})
        
        # Generate unique server name if conflicts exist
        original_name = server_config.get("Name", "Imported Server")
        server_config["Name"] = generate_unique_server_name(original_name, paths)
        
        # Update installation directory if specified
        if install_directory:
            server_config["InstallDir"] = install_directory
        
        # Handle Steam server dependencies
        if server_config.get("Type") == "Steam" and auto_install:
            app_id = server_config.get("AppId")
            if app_id and dependencies.get("requires_steam_install"):
                # This would trigger Steam installation process
                server_config["RequiresInstallation"] = True
                server_config["InstallationPending"] = True
        
        # Clean up runtime-specific data
        server_config.pop("ProcessId", None)
        server_config.pop("StartTime", None)
        server_config.pop("LastUpdate", None)
        server_config["ImportedAt"] = datetime.datetime.now().isoformat()
        server_config["ImportedFrom"] = export_metadata.get("source_host", "Unknown")
        server_config["OriginalExportDate"] = export_metadata.get("exported_at", "Unknown")
        
        # Save server configuration
        servers_path = os.path.join(paths["root"], "servers")
        os.makedirs(servers_path, exist_ok=True)
        
        # Generate unique filename
        safe_name = "".join(c for c in server_config["Name"] if c.isalnum() or c in (' ', '-', '_')).rstrip()
        config_filename = f"{safe_name.replace(' ', '_')}.json"
        config_path = os.path.join(servers_path, config_filename)
        
        # Ensure unique filename
        counter = 1
        while os.path.exists(config_path):
            config_path = os.path.join(servers_path, f"{safe_name.replace(' ', '_')}_{counter}.json")
            counter += 1
        
        # Save configuration
        with open(config_path, 'w') as f:
            json.dump(server_config, f, indent=4)
        
        logger.info(f"Successfully imported server configuration: {server_config['Name']}")
        
        return True, f"Server '{server_config['Name']}' imported successfully", server_config
        
    except Exception as e:
        logger.error(f"Error importing server configuration: {str(e)}")
        return False, f"Import failed: {str(e)}", None


def generate_unique_server_name(name, paths):
    """Generate a unique server name by checking existing configurations"""
    try:
        servers_path = os.path.join(paths["root"], "servers")
        existing_names = set()
        
        if os.path.exists(servers_path):
            for file in os.listdir(servers_path):
                if file.endswith('.json'):
                    try:
                        with open(os.path.join(servers_path, file), 'r') as f:
                            config = json.load(f)
                        existing_names.add(config.get("Name", ""))
                    except:
                        continue
        
        # If name is unique, return as is
        if name not in existing_names:
            return name
        
        # Generate unique name with counter
        counter = 1
        while f"{name} ({counter})" in existing_names:
            counter += 1
        
        return f"{name} ({counter})"
        
    except Exception as e:
        logger.error(f"Error generating unique server name: {str(e)}")
        return f"{name} (imported)"


def get_directory_size(directory):
    """Get total size of directory in bytes"""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, IOError):
                    continue
        return total_size
    except Exception:
        return 0


def count_files_in_directory(directory):
    """Count total number of files in directory"""
    try:
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            file_count += len(filenames)
        return file_count
    except Exception:
        return 0


def export_server_to_file(export_data, export_path, include_files=False):
    """Export server configuration to file
    
    Args:
        export_data (dict): Server export data
        export_path (str): Target file path
        include_files (bool): Whether to include server files
        
    Returns:
        tuple: (success, message)
    """
    try:
        if include_files:
            # Create zip archive with configuration and files
            with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add configuration file
                config_json = json.dumps(export_data, indent=4)
                zipf.writestr('server_config.json', config_json)
                
                # Add server files if they exist
                server_config = export_data.get("server_configuration", {})
                install_dir = server_config.get("InstallDir")
                
                if install_dir and os.path.exists(install_dir):
                    for root, dirs, files in os.walk(install_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, install_dir)
                            arcname = os.path.join('server_files', arcname)
                            try:
                                zipf.write(file_path, arcname)
                            except Exception as e:
                                logger.warning(f"Could not add file to archive: {file_path} - {str(e)}")
                
            return True, f"Server exported with files to: {export_path}"
        else:
            # Export configuration only as JSON
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=4)
            
            return True, f"Server configuration exported to: {export_path}"
        
    except Exception as e:
        logger.error(f"Error exporting server to file: {str(e)}")
        return False, f"Export failed: {str(e)}"


def import_server_from_file(file_path):
    """Import server configuration from file
    
    Args:
        file_path (str): Path to import file
        
    Returns:
        tuple: (success, export_data, has_files)
    """
    try:
        if file_path.endswith('.zip'):
            # Import from zip archive
            with zipfile.ZipFile(file_path, 'r') as zipf:
                # Read configuration
                config_data = zipf.read('server_config.json').decode('utf-8')
                export_data = json.loads(config_data)
                
                # Check if server files are included
                has_files = any(name.startswith('server_files/') for name in zipf.namelist())
                
                return True, export_data, has_files
        else:
            # Import from JSON file
            with open(file_path, 'r') as f:
                export_data = json.load(f)
            
            return True, export_data, False
        
    except Exception as e:
        logger.error(f"Error importing server from file: {str(e)}")
        return False, None, False


def extract_server_files_from_archive(zip_path, extract_to):
    """Extract server files from zip archive
    
    Args:
        zip_path (str): Path to zip file
        extract_to (str): Target extraction directory
        
    Returns:
        tuple: (success, message)
    """
    try:
        os.makedirs(extract_to, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            # Extract only server files
            for member in zipf.namelist():
                if member.startswith('server_files/'):
                    # Remove server_files/ prefix
                    target_path = member[len('server_files/'):]
                    if target_path:  # Skip empty paths
                        target_full_path = os.path.join(extract_to, target_path)
                        
                        # Ensure target directory exists
                        os.makedirs(os.path.dirname(target_full_path), exist_ok=True)
                        
                        # Extract file
                        with zipf.open(member) as source, open(target_full_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
        
        return True, f"Server files extracted to: {extract_to}"
        
    except Exception as e:
        logger.error(f"Error extracting server files: {str(e)}")
        return False, f"Extraction failed: {str(e)}"


def format_uptime_from_start_time(start_time_str):
    """Format uptime from start time string"""
    try:
        start_time = datetime.datetime.fromisoformat(start_time_str)
        uptime_delta = datetime.datetime.now() - start_time
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        else:
            return f"{hours}h {minutes}m"
    except:
        return "Unknown"


def center_window(window, width=None, height=None, parent=None):
    """Center a window on the screen or relative to a parent window"""
    window.update_idletasks()
    
    # Get window dimensions
    if width and height:
        window_width = width
        window_height = height
    else:
        window_width = window.winfo_width()
        window_height = window.winfo_height()
    
    if parent:
        # Center relative to parent window
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2
    else:
        # Center on screen
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
    
    window.geometry(f"{window_width}x{window_height}+{x}+{y}")


def create_server_type_selection_dialog(root, supported_server_types):
    """Create and show server type selection dialog"""
    type_dialog = tk.Toplevel(root)
    type_dialog.title("Select Server Type")
    type_dialog.transient(root)
    type_dialog.grab_set()
    
    # Create main frame with padding
    main_frame = ttk.Frame(type_dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Title label
    title_label = ttk.Label(main_frame, text="Select Server Type:", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 20))
    
    type_var = tk.StringVar(value="")  # Start with no selection
    
    # Radio buttons with better spacing
    for stype in supported_server_types:
        rb = ttk.Radiobutton(main_frame, text=stype, variable=type_var, value=stype, style="Large.TRadiobutton")
        rb.pack(anchor=tk.W, padx=20, pady=8)
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(20, 0))
    
    def proceed():
        # Only proceed if a type is actually selected
        if type_var.get():
            type_dialog.destroy()
        else:
            messagebox.showwarning("No Selection", "Please select a server type.")
        
    def cancel():
        type_var.set("")  # Clear selection to indicate cancellation
        type_dialog.destroy()
    
    # Handle window close event (X button)
    def on_dialog_close():
        type_var.set("")  # Clear selection when closing via X button
        type_dialog.destroy()
    
    type_dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
    
    # Buttons with better spacing
    ttk.Button(button_frame, text="Cancel", command=cancel, width=12).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Next", command=proceed, width=12).pack(side=tk.RIGHT)
    
    # Center dialog relative to parent
    center_window(type_dialog, 380, 280, root)
    
    root.wait_window(type_dialog)
    return type_var.get()


def update_server_status_in_treeview(server_list, server_name, status):
    """Update the status of a server in the UI treeview"""
    try:
        # Find the server in the treeview
        for item in server_list.get_children():
            values = server_list.item(item)['values']
            if len(values) > 0 and values[0] == server_name:
                # Get current values
                values = list(values)
                # Update status (index 1)
                values[1] = status
                # Update the item
                server_list.item(item, values=values)
                break
        
        # Force UI update
        server_list.update_idletasks()
    except Exception as e:
        logger.error(f"Error updating server status in UI: {str(e)}")


def validate_server_creation_inputs(server_type, server_name, app_id=None, executable_path=None):
    """Validate inputs for server creation"""
    errors = []
    
    if not server_name.strip():
        errors.append("Server name is required.")
    
    if server_type == "Steam":
        if not app_id or not app_id.strip():
            errors.append("App ID is required for Steam servers.")
        elif not app_id.strip().isdigit():
            errors.append("App ID must be a valid number.")
    
    if server_type == "Other":
        if not executable_path or not executable_path.strip():
            errors.append("Executable path is required for Other server types.")
    
    return errors


def open_directory_in_explorer(directory_path):
    """Open a directory in the system file explorer"""
    import subprocess
    try:
        if not os.path.exists(directory_path):
            return False, f"Directory not found: {directory_path}"
        
        # Open directory in file explorer
        if sys.platform == 'win32':
            os.startfile(directory_path)
        elif sys.platform == 'darwin':
            subprocess.call(['open', directory_path])
        else:
            subprocess.call(['xdg-open', directory_path])
        
        return True, "Directory opened successfully"
        
    except Exception as e:
        logger.error(f"Error opening directory: {str(e)}")
        return False, f"Failed to open directory: {str(e)}"


def create_confirmation_dialog(parent, title, message, confirm_text="Confirm", cancel_text="Cancel"):
    """Create a confirmation dialog and return the result"""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    
    # Configure dialog
    dialog.resizable(False, False)
    
    # Create main frame
    main_frame = ttk.Frame(dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Message label with wrapping
    message_label = ttk.Label(main_frame, text=message, wraplength=350, justify=tk.CENTER)
    message_label.pack(pady=(0, 20))
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)
    
    result = {"confirmed": False}
    
    def on_confirm():
        result["confirmed"] = True
        dialog.destroy()
    
    def on_cancel():
        result["confirmed"] = False
        dialog.destroy()
    
    # Buttons
    ttk.Button(button_frame, text=cancel_text, command=on_cancel, width=12).pack(side=tk.LEFT)
    ttk.Button(button_frame, text=confirm_text, command=on_confirm, width=12).pack(side=tk.RIGHT)
    
    # Center dialog
    center_window(dialog, 400, 150, parent)
    
    # Wait for dialog to close
    parent.wait_window(dialog)
    
    return result["confirmed"]


def show_progress_dialog(parent, title, task_function, *args, **kwargs):
    """Show a progress dialog while executing a task in a separate thread"""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    
    # Main frame
    main_frame = ttk.Frame(dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Status label
    status_var = tk.StringVar(value="Initializing...")
    status_label = ttk.Label(main_frame, textvariable=status_var)
    status_label.pack(pady=(0, 10))
    
    # Progress bar
    progress_bar = ttk.Progressbar(main_frame, mode="indeterminate", length=300)
    progress_bar.pack(pady=(0, 10))
    progress_bar.start(10)
    
    # Result storage
    task_result = {"success": False, "result": None, "error": None}
    
    def run_task():
        try:
            result = task_function(*args, **kwargs)
            task_result["success"] = True
            task_result["result"] = result
        except Exception as e:
            task_result["success"] = False
            task_result["error"] = str(e)
        finally:
            # Schedule UI update on main thread
            dialog.after(100, lambda: finish_task())
    
    def finish_task():
        progress_bar.stop()
        if task_result["success"]:
            status_var.set("Completed successfully!")
            dialog.after(1000, dialog.destroy)
        else:
            status_var.set(f"Error: {task_result['error']}")
            dialog.after(3000, dialog.destroy)
    
    # Start task in background thread
    import threading
    task_thread = threading.Thread(target=run_task, daemon=True)
    task_thread.start()
    
    # Center dialog
    center_window(dialog, 350, 120, parent)
    
    # Wait for dialog to close
    parent.wait_window(dialog)
    
    return task_result


def create_server_installation_dialog(root, server_type, supported_server_types, server_manager, paths, steam_cmd_path=None):
    """Create server installation dialog with Java selection for Minecraft servers"""
    try:
        # Import here to avoid circular imports
        if server_type == "Minecraft":
            from Scripts.minecraft import detect_java_installations
            
        installation_dialog = tk.Toplevel(root)
        installation_dialog.title(f"Install {server_type} Server")
        installation_dialog.geometry("700x600")
        installation_dialog.transient(root)
        installation_dialog.grab_set()
        
        # Create main frame
        main_frame = ttk.Frame(installation_dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Install {server_type} Server", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Form variables
        form_vars = {}
        
        # Server name
        name_frame = ttk.Frame(main_frame)
        name_frame.pack(fill=tk.X, pady=5)
        ttk.Label(name_frame, text="Server Name:", width=15).pack(side=tk.LEFT)
        form_vars['server_name'] = tk.StringVar()
        ttk.Entry(name_frame, textvariable=form_vars['server_name'], width=40).pack(side=tk.LEFT, padx=(10, 0))
        
        # Installation directory
        dir_frame = ttk.Frame(main_frame)
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Label(dir_frame, text="Install Directory:", width=15).pack(side=tk.LEFT)
        form_vars['install_dir'] = tk.StringVar()
        install_entry = ttk.Entry(dir_frame, textvariable=form_vars['install_dir'], width=35)
        install_entry.pack(side=tk.LEFT, padx=(10, 5))
        
        def browse_install_dir():
            directory = filedialog.askdirectory(title="Select Installation Directory")
            if directory:
                form_vars['install_dir'].set(directory)
        
        ttk.Button(dir_frame, text="Browse", command=browse_install_dir).pack(side=tk.LEFT)
        
        # Server-type specific fields
        if server_type == "Minecraft":
            # Minecraft version
            version_frame = ttk.Frame(main_frame)
            version_frame.pack(fill=tk.X, pady=5)
            ttk.Label(version_frame, text="Minecraft Version:", width=15).pack(side=tk.LEFT)
            form_vars['version'] = tk.StringVar(value="1.21.0")
            version_combo = ttk.Combobox(version_frame, textvariable=form_vars['version'], width=37)
            version_combo.pack(side=tk.LEFT, padx=(10, 0))
            
            # Try to populate with actual versions
            try:
                from Scripts.minecraft import fetch_minecraft_versions
                versions = fetch_minecraft_versions()
                if versions:
                    version_list = [v['id'] for v in versions[:20]]  # Latest 20 versions
                    version_combo['values'] = version_list
                else:
                    version_combo['values'] = ["1.21.0", "1.20.1", "1.19.4", "1.18.2", "1.17.1", "1.16.5"]
            except:
                version_combo['values'] = ["1.21.0", "1.20.1", "1.19.4", "1.18.2", "1.17.1", "1.16.5"]
            
            # Modloader
            modloader_frame = ttk.Frame(main_frame)
            modloader_frame.pack(fill=tk.X, pady=5)
            ttk.Label(modloader_frame, text="Modloader:", width=15).pack(side=tk.LEFT)
            form_vars['modloader'] = tk.StringVar(value="Vanilla")
            modloader_combo = ttk.Combobox(modloader_frame, textvariable=form_vars['modloader'], width=37)
            modloader_combo['values'] = ["Vanilla", "Forge", "Fabric", "NeoForge"]
            modloader_combo.pack(side=tk.LEFT, padx=(10, 0))
            
            # Java selection frame
            java_frame = ttk.LabelFrame(main_frame, text="Java Configuration", padding=10)
            java_frame.pack(fill=tk.X, pady=15)
            
            form_vars['selected_java'] = None
            java_info_var = tk.StringVar(value="No Java selected")
            
            # Java info display
            java_info_label = ttk.Label(java_frame, textvariable=java_info_var, foreground="blue")
            java_info_label.pack(pady=(0, 10))
            
            def select_java():
                # Get selected version for compatibility check
                selected_version = form_vars['version'].get()
                java = create_java_selection_dialog(installation_dialog, selected_version)
                if java:
                    form_vars['selected_java'] = java
                    java_info_var.set(f"Selected: {java['display_name']}")
                    
                    # Check compatibility and show warning if needed
                    if selected_version:
                        from Scripts.minecraft import check_java_compatibility
                        is_compatible, _, _, message = check_java_compatibility(selected_version, java['path'])
                        if not is_compatible:
                            messagebox.showwarning("Compatibility Warning", 
                                                 f"Selected Java may not be compatible:\n{message}")
            
            def auto_select_java():
                selected_version = form_vars['version'].get()
                if selected_version:
                    from Scripts.minecraft import get_recommended_java_for_minecraft
                    recommended = get_recommended_java_for_minecraft(selected_version)
                    if recommended:
                        form_vars['selected_java'] = recommended
                        java_info_var.set(f"Auto-selected: {recommended['display_name']}")
                    else:
                        messagebox.showwarning("No Suitable Java", 
                                             "No suitable Java installation found for this Minecraft version.")
                else:
                    messagebox.showwarning("Select Version", "Please select a Minecraft version first.")
            
            # Java selection buttons
            java_button_frame = ttk.Frame(java_frame)
            java_button_frame.pack(fill=tk.X)
            ttk.Button(java_button_frame, text="Select Java", command=select_java).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(java_button_frame, text="Auto-Select", command=auto_select_java).pack(side=tk.LEFT)
            
            # Auto-select Java when version changes
            def on_version_change(*args):
                if form_vars['selected_java'] is None:
                    auto_select_java()
            
            form_vars['version'].trace('w', on_version_change)
            
        elif server_type == "Steam":
            # App ID
            appid_frame = ttk.Frame(main_frame)
            appid_frame.pack(fill=tk.X, pady=5)
            ttk.Label(appid_frame, text="Steam App ID:", width=15).pack(side=tk.LEFT)
            form_vars['app_id'] = tk.StringVar()
            ttk.Entry(appid_frame, textvariable=form_vars['app_id'], width=40).pack(side=tk.LEFT, padx=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        result = {"success": False, "vars": form_vars}
        
        def on_install():
            # Validate inputs
            if not form_vars['server_name'].get().strip():
                messagebox.showerror("Error", "Please enter a server name.")
                return
            
            if not form_vars['install_dir'].get().strip():
                messagebox.showerror("Error", "Please select an installation directory.")
                return
            
            if server_type == "Minecraft" and form_vars['selected_java'] is None:
                messagebox.showerror("Error", "Please select a Java installation.")
                return
            
            if server_type == "Steam" and not form_vars['app_id'].get().strip():
                messagebox.showerror("Error", "Please enter a Steam App ID.")
                return
            
            result["success"] = True
            installation_dialog.destroy()
        
        def on_cancel():
            installation_dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Install", command=on_install, width=12).pack(side=tk.RIGHT)
        
        # Center dialog
        center_window(installation_dialog, 700, 600, root)
        
        # Wait for dialog to close
        root.wait_window(installation_dialog)
        
        return result if result["success"] else None
        
    except Exception as e:
        logger.error(f"Error creating server installation dialog: {str(e)}")
        messagebox.showerror("Error", f"Failed to create installation dialog: {str(e)}")
        return None
    """Create server installation dialog with all necessary components"""
    # Get credentials if needed
    credentials = None
    if server_type == "Steam":
        credentials = get_steam_credentials(root)
        if not credentials:
            return None

    # Create dialog for server details
    dialog = tk.Toplevel(root)
    dialog.title(f"Create {server_type} Server")
    dialog.transient(root)
    dialog.grab_set()
    
    # Create main frame with padding
    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Create scrollable frame for the form
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
    canvas.pack(side="left", fill="both", expand=True)
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
            mc_versions = server_manager.get_minecraft_versions() if server_manager else []
            if not mc_versions:
                messagebox.showerror("Error", "Failed to fetch Minecraft versions.")
                dialog.destroy()
                return None
        except Exception as e:
            messagebox.showerror("Error", f"Minecraft support not available: {str(e)}")
            dialog.destroy()
            return None
            
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
        app_id_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['app_id'], width=40, font=("Segoe UI", 10))
        app_id_entry.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
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
        if steam_cmd_path:
            help_text = f"(Leave blank for SteamCMD default location)"
        else:
            help_text = "(Leave blank for SteamCMD default location)"
    else:  # Minecraft or Other
        default_location = os.path.join(paths.get("root", ""), "servers")
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
                filetypes=[("Java/Jar/Exec","*.jar;*.exe;*.sh;*.bat;*.cmd;*.ps1"),("All","*.*")])
            if fp:
                form_vars['exe_path'].set(fp)
        ttk.Button(scrollable_frame, text="Browse", command=browse_exe, width=12).grid(row=current_row, column=2, padx=15, pady=10)
        current_row += 1

    # Startup Args (all)
    ttk.Label(scrollable_frame, text="Startup Args:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
    args_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['startup_args'], width=40, font=("Segoe UI", 10))
    args_entry.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)

    # Return the dialog components for further setup
    return {
        'dialog': dialog,
        'main_frame': main_frame,
        'form_vars': form_vars,
        'credentials': credentials,
        'server_type': server_type
    }


def create_server_removal_dialog(root, server_name, server_manager):
    """Create server removal confirmation dialog"""
    dialog = tk.Toplevel(root)
    dialog.title("Remove Server")
    dialog.transient(root)
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
    
    # Result storage
    result = {"confirmed": False, "remove_files": False}
    
    def confirm_removal():
        result["confirmed"] = True
        result["remove_files"] = remove_files_var.get()
        dialog.destroy()
        
    def cancel_removal():
        result["confirmed"] = False
        dialog.destroy()
    
    # Buttons
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(pady=20)
    
    ttk.Button(button_frame, text="Cancel", command=cancel_removal, width=12).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Remove", command=confirm_removal, width=12).pack(side=tk.RIGHT, padx=5)
    
    # Center dialog
    center_window(dialog, 400, 200, root)
    
    # Wait for dialog to close
    root.wait_window(dialog)
    
    return result


def perform_server_installation(server_manager, server_type, form_vars, credentials, paths, 
                               status_callback=None, console_callback=None, cancel_flag=None, steam_cmd_path=None):
    """Perform server installation with callbacks for progress updates"""
    try:
        server_name = form_vars['name'].get().strip()
        app_id = form_vars['app_id'].get().strip() if server_type == "Steam" else ""
        install_dir = form_vars['install_dir'].get().strip()
        executable_path = form_vars['exe_path'].get().strip() if server_type in ("Minecraft", "Other") else ""
        startup_args = form_vars['startup_args'].get().strip()

        # Validate inputs
        validation_errors = validate_server_creation_inputs(server_type, server_name, app_id, executable_path)
        if validation_errors:
            raise ValueError("\n".join(validation_errors))

        # Set default install dir if blank based on server type
        if not install_dir:
            if server_type == "Steam":
                # For Steam servers, let SteamCMD choose the default location by not specifying install_dir
                install_dir = ""  # Empty string tells SteamCMD to use its default
                if console_callback:
                    console_callback(f"[INFO] Using SteamCMD default installation directory")
            else:
                # Minecraft and Other servers go to servermanager location
                install_dir = os.path.join(paths.get("root", ""), "servers", server_name)
                if console_callback:
                    console_callback(f"[INFO] Using default ServerManager installation directory: {install_dir}")
        else:
            if console_callback:
                console_callback(f"[INFO] Using custom installation directory: {install_dir}")

        if status_callback:
            status_callback("Installing server...")
        if console_callback:
            console_callback(f"[INFO] Starting installation of {server_type} server: {server_name}")

        # Check for cancellation
        if cancel_flag and cancel_flag.get():
            if console_callback:
                console_callback("[INFO] Installation cancelled by user")
            return False, "Installation cancelled"

        # Use server manager to install the server
        if server_manager:
            # Use provided steam_cmd_path or get from server manager config or use default
            if not steam_cmd_path:
                steam_cmd_path = server_manager.config.get('steam_cmd_path')
            if not steam_cmd_path:
                steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
            
            if console_callback:
                console_callback(f"[INFO] Using SteamCMD path: {steam_cmd_path}")
            
            if server_type == "Steam":
                success, message = server_manager.install_server_complete(
                    server_name, server_type, install_dir, executable_path, startup_args,
                    app_id, "", "", steam_cmd_path, credentials, console_callback, cancel_flag
                )
            elif server_type == "Minecraft":
                minecraft_version = form_vars['minecraft_version'].get()
                modloader = form_vars['modloader'].get()
                success, message = server_manager.install_server_complete(
                    server_name, server_type, install_dir, executable_path, startup_args,
                    "", minecraft_version, modloader, "", None, console_callback, cancel_flag
                )
            else:  # Other
                success, message = server_manager.install_server_complete(
                    server_name, server_type, install_dir, executable_path, startup_args,
                    "", "", "", "", None, console_callback, cancel_flag
                )
        else:
            success = False
            message = "Server manager not initialized"

        if console_callback:
            if success:
                console_callback(f"[SUCCESS] {message}")
            else:
                console_callback(f"[ERROR] {message}")

        return success, message

    except Exception as e:
        error_msg = f"Error during server installation: {str(e)}"
        if console_callback:
            console_callback(f"[ERROR] {error_msg}")
        return False, error_msg


def update_server_list_from_files(server_list, paths, variables, log_dashboard_event, format_uptime_from_start_time):
    """Update server list treeview from configuration files"""
    try:
        # Clear current items
        for item in server_list.get_children():
            server_list.delete(item)
            
        # Get server configurations
        servers_path = paths["servers"]
        if os.path.exists(servers_path):
            for file in os.listdir(servers_path):
                if file.endswith(".json"):
                    try:
                        config_file = os.path.join(servers_path, file)
                        with open(config_file, 'r') as f:
                            server_config = json.load(f)
                        
                        server_name = server_config.get("Name", "Unknown")
                        server_type = server_config.get("Type", "Unknown")
                        process_id = server_config.get("ProcessId", 0)
                        
                        # Check if process is actually running and clean up orphaned PIDs
                        config_updated = False
                        if process_id and is_process_running(process_id):
                            status = "Running"
                            process_info = get_process_info(process_id)
                            if process_info:
                                cpu_usage = f"{process_info.get('cpu_percent', 0):.1f}%" if process_info.get('cpu_percent') else "N/A"
                                memory_mb = process_info.get('memory_info', {}).get('rss', 0) / (1024 * 1024) if process_info.get('memory_info') else 0
                                memory_usage = f"{memory_mb:.1f} MB" if memory_mb else "N/A"
                            else:
                                cpu_usage = "N/A"
                                memory_usage = "N/A"
                            
                            # Calculate uptime
                            start_time = server_config.get("StartTime")
                            if start_time:
                                uptime = format_uptime_from_start_time(start_time)
                            else:
                                uptime = "Unknown"
                        else:
                            # Process is not running
                            status = "Offline"
                            cpu_usage = "N/A"
                            memory_usage = "N/A"
                            uptime = "N/A"
                            
                            # Clean up orphaned process ID if it exists
                            if process_id:
                                logger.info(f"Cleaning up orphaned process ID {process_id} for server '{server_name}'")
                                server_config.pop('ProcessId', None)
                                server_config.pop('StartTime', None)
                                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                config_updated = True
                                log_dashboard_event("PROCESS_CLEANUP", f"Cleaned up orphaned PID {process_id} for server {server_name}", "INFO")
                            
                            process_id = "N/A"
                        
                        # Save updated configuration if needed
                        if config_updated:
                            try:
                                with open(config_file, 'w') as f:
                                    json.dump(server_config, f, indent=4)
                            except Exception as e:
                                logger.error(f"Failed to update config file {config_file}: {str(e)}")
                        
                        # Insert into treeview
                        server_list.insert("", "end", values=(
                            server_name, status, str(process_id), cpu_usage, memory_usage, uptime
                        ))
                        
                    except Exception as e:
                        logger.error(f"Error loading server config {file}: {str(e)}")
                        # Insert error entry
                        server_list.insert("", "end", values=(
                            file.replace(".json", ""), "Error", "N/A", "N/A", "N/A", "N/A"
                        ))
        
        # Update last refresh time
        variables["lastServerListUpdate"] = datetime.datetime.now()
        variables["lastProcessUpdate"] = datetime.datetime.now()
        
        log_dashboard_event("SERVER_LIST_UPDATE", "Server list updated successfully", "DEBUG")
        
    except Exception as e:
        logger.error(f"Error updating server list: {str(e)}")
        log_dashboard_event("SERVER_LIST_UPDATE", f"Error updating server list: {str(e)}", "ERROR")


def create_progress_dialog_with_console(parent, title, width=700, height=650):
    """Create a progress dialog with console output for long-running operations"""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(True, True)
    
    # Main frame with padding
    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Console output section
    console_container = ttk.Frame(main_frame)
    console_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    
    from tkinter import scrolledtext
    console_output = scrolledtext.ScrolledText(console_container, width=70, height=8, 
                                             background="black", foreground="white", 
                                             font=("Consolas", 9))
    console_output.pack(fill=tk.BOTH, expand=True)
    console_output.config(state=tk.DISABLED)

    # Status and progress bar
    status_container = ttk.Frame(main_frame)
    status_container.pack(fill=tk.X, pady=(0, 10))
    
    status_var = tk.StringVar(value="")
    status_label = ttk.Label(status_container, textvariable=status_var, font=("Segoe UI", 10))
    status_label.pack(anchor=tk.W, pady=(0, 5))
    
    progress = ttk.Progressbar(status_container, mode="indeterminate")
    progress.pack(fill=tk.X)

    # Callback functions
    def append_console(text):
        console_output.config(state=tk.NORMAL)
        console_output.insert(tk.END, text + "\n")
        console_output.see(tk.END)
        console_output.config(state=tk.DISABLED)
    
    def set_status(text):
        status_var.set(text)
        dialog.update_idletasks()
    
    def start_progress():
        progress.start(10)
    
    def stop_progress():
        progress.stop()

    # Center dialog relative to parent
    center_window(dialog, width, height, parent)
    
    return {
        'dialog': dialog,
        'console_text': console_output,  # Add direct access to console text widget
        'console_callback': append_console,
        'status_callback': set_status,
        'progress_start': start_progress,
        'progress_stop': stop_progress,
        'status_var': status_var
    }


def show_java_configuration_dialog(parent, server_name, server_config, server_manager, server_manager_dir, config):
    """Show Java configuration dialog for a specific server"""
    try:
        from Scripts.minecraft import detect_java_installations, check_java_compatibility, get_recommended_java_for_minecraft
        
        # Create dialog
        dialog = tk.Toplevel(parent)
        dialog.title(f"Java Configuration - {server_name}")
        dialog.geometry("700x600")
        dialog.transient(parent)
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
        
        # Return result variable
        result = {'success': False, 'java_path': None}
        
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
                if server_manager:
                    server_manager.save_server_config(server_name, server_config)
                
                # Update launch script
                from Scripts.minecraft import MinecraftServerManager
                manager = MinecraftServerManager(server_manager_dir, config)
                
                install_dir = server_config.get("InstallDir", "")
                if install_dir and os.path.exists(install_dir):
                    executable_path = server_config.get("ExecutablePath", "")
                    jar_file = os.path.basename(executable_path) if executable_path else "server.jar"
                    
                    script_path = manager.create_launch_script(install_dir, jar_file, 1024, "", selected_java_path)
                    
                messagebox.showinfo("Success", f"Java configuration updated for '{server_name}'!\nUsing: {selected_java_path}")
                result['success'] = True
                result['java_path'] = selected_java_path
                dialog.destroy()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Apply", command=on_apply, width=12).pack(side=tk.RIGHT)
        
        # Center dialog
        center_window(dialog, 700, 600, parent)
        
        # Auto-select recommended Java if none selected
        if not java_tree.selection() and version != "Unknown":
            auto_select_java()
        
        return result
        
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open Java configuration dialog: {str(e)}")
        return {'success': False, 'java_path': None}


def import_server_from_directory_dialog(parent, server_manager, server_manager_dir, supported_server_types, update_callback=None):
    """Import an existing server from a directory (legacy method)"""
    if server_manager is None:
        messagebox.showerror("Error", "Server manager not initialized.")
        return
        
    try:
        # Ask user to select a directory
        install_dir = filedialog.askdirectory(
            title="Select Server Installation Directory",
            initialdir=server_manager_dir
        )
        
        if not install_dir:
            return
            
        # Create import dialog
        dialog = tk.Toplevel(parent)
        dialog.title("Import Server from Directory")
        dialog.transient(parent)
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
        type_combo = ttk.Combobox(main_frame, textvariable=type_var, values=supported_server_types, width=32)
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
                filetypes=[("Executables", "*.exe;*.jar;*.bat;*.cmd;*.ps1;*.sh"), ("All files", "*.*")]
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
                if server_manager:
                    found_files = server_manager.auto_detect_server_executable(install_dir)
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
        
        # Return result variable
        result = {'success': False, 'server_name': None}
        
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
                if server_manager:
                    success, message = server_manager.import_server_config(
                        server_name, server_type, install_dir, executable_path, startup_args
                    )
                else:
                    success = False
                    message = "Server manager not initialized"
                
                if success:
                    # Call update callback if provided
                    if update_callback:
                        update_callback()
                    messagebox.showinfo("Success", message)
                    result['success'] = True
                    result['server_name'] = server_name
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", message)
                
            except Exception as e:
                logger.error(f"Error importing server: {str(e)}")
                messagebox.showerror("Error", f"Failed to import server: {str(e)}")

        ttk.Button(button_frame, text="Import", command=import_config, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
        
        # Center dialog relative to parent
        center_window(dialog, 500, 400, parent)
        
        return result
        
    except Exception as e:
        logger.error(f"Error during directory import: {str(e)}")
        messagebox.showerror("Error", f"Failed to import server from directory: {str(e)}")
        return {'success': False, 'server_name': None}


def import_server_from_export_dialog(parent, paths, server_manager_dir, update_callback=None):
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
            return {'success': False, 'server_name': None}
        
        # Import server data from file
        success, export_data, has_files = import_server_from_file(file_path)
        
        if not success or not export_data:
            messagebox.showerror("Import Error", "Failed to read export file. File may be corrupted or invalid.")
            return {'success': False, 'server_name': None}
        
        # Create import configuration dialog
        dialog = tk.Toplevel(parent)
        dialog.title("Import Server Configuration")
        dialog.transient(parent)
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
        unique_name = generate_unique_server_name(original_name, paths)
        name_var = tk.StringVar(value=unique_name)
        name_entry = ttk.Entry(config_frame, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W)
        
        # Installation directory
        ttk.Label(config_frame, text="Install Directory:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        default_install_dir = ""
        if has_files and server_manager_dir:
            default_install_dir = os.path.join(server_manager_dir, "servers", unique_name.replace(" ", "_"))
        
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
        
        # Return result variable
        result = {'success': False, 'server_name': None}
        
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
                    export_data, paths, install_dir, auto_install_var.get()
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
                
                # Call update callback if provided
                if update_callback:
                    update_callback()
                
                # Show completion message
                completion_msg = f"Server '{server_name}' imported successfully!"
                if auto_install_var.get():
                    completion_msg += "\n\nNote: Steam installation will be performed when the server is first started."
                
                messagebox.showinfo("Import Complete", completion_msg)
                result['success'] = True
                result['server_name'] = server_name
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
        center_window(dialog, 600, 550, parent)
        
        return result
        
    except Exception as e:
        logger.error(f"Error importing from export: {str(e)}")
        messagebox.showerror("Error", f"Failed to import server from export: {str(e)}")
        return {'success': False, 'server_name': None}


def export_server_dialog(parent, server_list, paths):
    """Export server configuration for use on other hosts or clusters"""
    selected_items = server_list.selection()
    if not selected_items:
        messagebox.showinfo("No Selection", "Please select a server to export first.")
        return {'success': False, 'server_name': None}
    
    try:
        server_name = server_list.item(selected_items[0])['values'][0]
        
        # Create export options dialog
        dialog = tk.Toplevel(parent)
        dialog.title(f"Export Server: {server_name}")
        dialog.transient(parent)
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
        
        # Return result variable
        result = {'success': False, 'server_name': server_name, 'export_path': None}
        
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
                export_data = export_server_configuration(server_name, paths, include_files)
                
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
                    result['success'] = True
                    result['export_path'] = export_path
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
        center_window(dialog, 500, 400, parent)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in export server: {str(e)}")
        messagebox.showerror("Error", f"Failed to export server: {str(e)}")
        return {'success': False, 'server_name': None, 'export_path': None}
