import os
import sys
import json
import datetime
import platform
import socket
import winreg
import psutil
import threading
import subprocess
import time
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import registry functions from common module
from Modules.common import initialize_paths_from_registry, initialize_registry_values

# Import logging functions
from Modules.server_logging import get_dashboard_logger

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
        from Modules.minecraft import detect_java_installations, get_minecraft_java_requirement, check_java_compatibility
        
        dialog = tk.Toplevel(root)
        dialog.title("Select Java Installation")
        dialog.geometry("600x400")
        dialog.resizable(True, True)
        dialog.transient(root)
        dialog.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title and version info
        title_label = ttk.Label(main_frame, text="Select Java Installation", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 10))
        
        if minecraft_version:
            required_java = get_minecraft_java_requirement(minecraft_version)
            info_label = ttk.Label(main_frame, 
                                 text=f"Minecraft {minecraft_version} requires Java {required_java} or later",
                                 font=("Segoe UI", 9))
            info_label.pack(pady=(0, 15))
        
        # Java installations list
        list_frame = ttk.LabelFrame(main_frame, text="Available Java Installations", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Treeview for Java installations
        columns = ("version", "path", "compatibility")
        java_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        java_tree.heading("version", text="Java Version")
        java_tree.heading("path", text="Installation Path")
        java_tree.heading("compatibility", text="Compatibility")
        
        java_tree.column("version", width=150, minwidth=100)
        java_tree.column("path", width=300, minwidth=200)
        java_tree.column("compatibility", width=120, minwidth=100)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=java_tree.yview)
        java_tree.configure(yscrollcommand=scrollbar.set)
        
        java_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate with detected installations
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
            
            # Store installation data in the item
            java_tree.set(item_id, "data", installation)
        
        # Configure tag colors
        java_tree.tag_configure("compatible", foreground="green")
        java_tree.tag_configure("incompatible", foreground="red")
        
        # Refresh button
        refresh_frame = ttk.Frame(main_frame)
        refresh_frame.pack(fill=tk.X, pady=(0, 15))
        
        def refresh_java_list():
            for item in java_tree.get_children():
                java_tree.delete(item)
            
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
        
        # Custom Java path entry
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
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        result = {}  # Will store the selected Java installation
        
        def on_select():
            # Check if custom path is provided
            custom_path = custom_path_var.get().strip()
            if custom_path:
                from Modules.minecraft import get_java_version
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
        
        center_window(dialog, 600, 400, root)
        
        # Wait for dialog to close
        root.wait_window(dialog)
        
        return result.get("java")
        
    except Exception as e:
        logger.error(f"Error creating Java selection dialog: {str(e)}")
        messagebox.showerror("Error", f"Failed to create Java selection dialog: {str(e)}")
        return None


def load_appid_scanner_list(server_manager_dir):
    """Load the AppID list from database only (no JSON fallback)"""
    try:
        # Load from database only
        dedicated_servers, metadata = load_appid_list_from_database()
        
        if dedicated_servers:
            logger.info(f"Loaded {len(dedicated_servers)} dedicated servers from database")
            return dedicated_servers, metadata
        else:
            logger.warning("No dedicated servers found in database")
            return [], {}
            
    except Exception as e:
        logger.error(f"Error loading AppID scanner list from database: {e}")
        return [], {}


def load_appid_list_from_database():
    """Load AppID list directly from database"""
    try:
        # Import database components
        from Modules.Database.steam_database import get_steam_engine
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
            requires_subscription = Column(Boolean, default=False)  # Whether the server requires a paid subscription
            anonymous_install = Column(Boolean, default=True)  # Whether the server can be installed anonymously
            publisher = Column(String(255))
            release_date = Column(String(50))
            description = Column(Text)
            tags = Column(Text)  # JSON string of tags
            price = Column(String(20))
            platforms = Column(String(100))  # JSON string of supported platforms
            last_updated = Column(DateTime)
            source = Column(String(50), default='steamdb')
        
        # Connect to database
        engine = get_steam_engine()
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
                "requires_subscription": getattr(app, 'requires_subscription', False),
                "anonymous_install": getattr(app, 'anonymous_install', True),
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
        
        if dedicated_servers:
            logger.info(f"Successfully loaded {len(dedicated_servers)} dedicated servers from steam database")
        else:
            logger.warning("No dedicated servers found in steam database. Database may be empty.")
        
        return dedicated_servers, metadata
        
    except ImportError as e:
        logger.error(f"Database modules not available: {e}")
        return [], {}
    except Exception as e:
        logger.error(f"Error loading AppID list from database: {e}")
        return [], {}


def check_appid_in_database(appid):
    """Check if an AppID exists in the Steam database and return server info"""
    if not appid:
        return None
    
    try:
        # Import database components
        from Modules.Database.steam_database import get_steam_engine
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
            requires_subscription = Column(Boolean, default=False)
            anonymous_install = Column(Boolean, default=True)
            publisher = Column(String(255))
            release_date = Column(String(50))
            description = Column(Text)
            tags = Column(Text)
            price = Column(String(20))
            platforms = Column(String(100))
            last_updated = Column(DateTime)
            source = Column(String(50), default='steamdb')
        
        # Convert appid to int if it's a string
        try:
            appid_int = int(appid)
        except (ValueError, TypeError):
            logger.debug(f"Invalid AppID format: {appid}")
            return None
        
        # Connect to database
        engine = get_steam_engine()
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Query for the specific AppID
        app = session.query(SteamApp).filter(SteamApp.appid == appid_int).first()
        
        if app:
            app_info = {
                "appid": app.appid,
                "name": app.name,
                "type": app.type or "Unknown",
                "is_server": getattr(app, 'is_server', False),
                "is_dedicated_server": getattr(app, 'is_dedicated_server', False),
                "requires_subscription": getattr(app, 'requires_subscription', False),
                "anonymous_install": getattr(app, 'anonymous_install', True),
                "publisher": app.publisher or "",
                "description": app.description or "",
                "exists": True
            }
        else:
            app_info = None
        
        session.close()
        return app_info
        
    except ImportError as e:
        logger.debug(f"Database modules not available for AppID check: {e}")
        return None
    except Exception as e:
        logger.debug(f"Error checking AppID {appid} in database: {e}")
        return None


def detect_server_type_from_appid(appid):
    """Detect server type based on AppID from database"""
    if not appid:
        return "Other"
    
    app_info = check_appid_in_database(appid)
    if app_info and app_info.get('exists'):
        if app_info.get('is_dedicated_server') or app_info.get('is_server'):
            return "Steam"
    
    return "Other"


def detect_server_type_from_directory(directory_path):
    """Detect server type from directory contents and configuration"""
    if not directory_path or not os.path.exists(directory_path):
        return "Other"
    
    try:
        # Look for common server files and configuration
        server_type = "Other"
        
        # Check for common Steam server executables and files
        steam_server_files = [
            'srcds.exe', 'srcds_run', 'srcds_linux', 'hlds.exe', 'hlds_run',
            'steamcmd.exe', 'steam_appid.txt'
        ]
        
        # Check for Minecraft server files
        minecraft_server_files = [
            'server.jar', 'minecraft_server.jar', 'paper.jar', 'spigot.jar',
            'forge.jar', 'server.properties', 'bukkit.yml', 'spigot.yml'
        ]
        
        # Check directory contents
        dir_contents = []
        for root, dirs, files in os.walk(directory_path):
            dir_contents.extend([f.lower() for f in files])
            # Only check first level to avoid deep recursion
            if root == directory_path:
                continue
            break
        
        # Check for Steam server indicators
        if any(steam_file.lower() in dir_contents for steam_file in steam_server_files):
            server_type = "Steam"
        
        # Check for steam_appid.txt file specifically
        steam_appid_path = os.path.join(directory_path, 'steam_appid.txt')
        if os.path.exists(steam_appid_path):
            try:
                with open(steam_appid_path, 'r') as f:
                    appid = f.read().strip()
                    if appid.isdigit():
                        # Verify this AppID exists in our database
                        detected_type = detect_server_type_from_appid(appid)
                        if detected_type == "Steam":
                            return "Steam"
            except Exception as e:
                logger.debug(f"Error reading steam_appid.txt: {e}")
        
        # Check for Minecraft server indicators
        if any(mc_file.lower() in dir_contents for mc_file in minecraft_server_files):
            if server_type == "Other":  # Don't override Steam detection
                server_type = "Minecraft"
        
        return server_type
        
    except Exception as e:
        logger.debug(f"Error detecting server type from directory {directory_path}: {e}")
        return "Other"


def find_appid_in_directory(directory_path):
    """Find Steam AppID from directory contents"""
    if not directory_path or not os.path.exists(directory_path):
        return None
    
    try:
        # Check for steam_appid.txt file
        steam_appid_path = os.path.join(directory_path, 'steam_appid.txt')
        if os.path.exists(steam_appid_path):
            try:
                with open(steam_appid_path, 'r') as f:
                    appid = f.read().strip()
                    if appid.isdigit():
                        return appid
            except Exception as e:
                logger.debug(f"Error reading steam_appid.txt: {e}")
        
        # Check for other common Steam configuration files
        steam_config_files = [
            'steamapps/appmanifest_*.acf',
            'Steam/steamapps/appmanifest_*.acf',
            '.steam/steamapps/appmanifest_*.acf'
        ]
        
        import glob
        for pattern in steam_config_files:
            search_path = os.path.join(directory_path, pattern)
            matches = glob.glob(search_path)
            if matches:
                # Try to extract AppID from filename
                for match in matches:
                    filename = os.path.basename(match)
                    if filename.startswith('appmanifest_') and filename.endswith('.acf'):
                        appid_str = filename[12:-4]  # Remove 'appmanifest_' and '.acf'
                        if appid_str.isdigit():
                            return appid_str
        
        return None
        
    except Exception as e:
        logger.debug(f"Error finding AppID in directory {directory_path}: {e}")
        return None


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
                # Try to get app information from database
                app_info = check_appid_in_database(server_config["AppId"])
                
                if app_info and app_info.get("exists"):
                    export_data["dependencies"]["steam_app_info"] = {
                        "appid": app_info["appid"],
                        "name": app_info["name"],
                        "type": app_info["type"],
                        "is_dedicated_server": app_info["is_dedicated_server"],
                        "requires_subscription": app_info["requires_subscription"],
                        "anonymous_install": app_info["anonymous_install"]
                    }
                    export_data["dependencies"]["requires_steam_install"] = True
                    export_data["dependencies"]["app_verified"] = True
                else:
                    # AppID not found in database
                    export_data["dependencies"]["steam_app_info"] = {
                        "appid": server_config["AppId"],
                        "name": "Unknown (not in database)",
                        "verified": False
                    }
                    export_data["dependencies"]["requires_steam_install"] = True
                    export_data["dependencies"]["app_verified"] = False
                    export_data["dependencies"]["app_warning"] = f"AppID {server_config['AppId']} not found in Steam database"
                        
            except Exception as e:
                logger.warning(f"Could not load Steam app information: {str(e)}")
                export_data["dependencies"]["steam_app_error"] = str(e)
        
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
        
        # Handle Steam server dependencies and AppID verification
        if server_config.get("Type") == "Steam":
            app_id = server_config.get("AppId")
            if app_id:
                # Verify AppID exists in current database
                app_info = check_appid_in_database(app_id)
                
                if app_info and app_info.get("exists"):
                    # AppID verified in current database
                    server_config["AppIdVerified"] = True
                    server_config["AppName"] = app_info.get("name", "Unknown")
                    logger.info(f"Verified Steam AppID {app_id} ({app_info.get('name', 'Unknown')})")
                    
                    if auto_install and dependencies.get("requires_steam_install"):
                        server_config["RequiresInstallation"] = True
                        server_config["InstallationPending"] = True
                else:
                    # AppID not found in current database
                    server_config["AppIdVerified"] = False
                    
                    # Check if export had app info
                    export_app_info = dependencies.get("steam_app_info", {})
                    if export_app_info.get("name"):
                        server_config["AppName"] = f"{export_app_info['name']} (unverified)"
                        logger.warning(f"Steam AppID {app_id} not found in database, using exported name: {export_app_info['name']}")
                    else:
                        server_config["AppName"] = f"Unknown AppID {app_id}"
                        logger.warning(f"Steam AppID {app_id} not found in database and no export info available")
                    
                    # Still allow installation if requested, but mark as unverified
                    if auto_install:
                        server_config["RequiresInstallation"] = True
                        server_config["InstallationPending"] = True
                        server_config["InstallationUnverified"] = True
            else:
                logger.warning("Steam server missing AppID during import")
        
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
    warnings = []
    
    if not server_name.strip():
        errors.append("Server name is required.")
    
    if server_type == "Steam":
        if not app_id or not app_id.strip():
            errors.append("App ID is required for Steam servers.")
        elif not app_id.strip().isdigit():
            errors.append("App ID must be a valid number.")
        else:
            # Validate AppID exists in database
            app_info = check_appid_in_database(app_id.strip())
            if not app_info or not app_info.get('exists'):
                warnings.append(f"Warning: AppID {app_id.strip()} not found in Steam database. This may be an invalid or outdated AppID.")
            elif not app_info.get('is_dedicated_server'):
                warnings.append(f"Warning: AppID {app_id.strip()} ({app_info.get('name', 'Unknown')}) is not marked as a dedicated server.")
    
    if server_type == "Other":
        if not executable_path or not executable_path.strip():
            errors.append("Executable path is required for Other server types.")
    
    # Combine errors and warnings
    all_messages = errors + warnings
    return all_messages


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
    
    center_window(dialog, 400, 150, parent)
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
            from Modules.minecraft import detect_java_installations
            
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
                from Modules.minecraft import fetch_minecraft_versions
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
                        from Modules.minecraft import check_java_compatibility
                        is_compatible, _, _, message = check_java_compatibility(selected_version, java['path'])
                        if not is_compatible:
                            messagebox.showwarning("Compatibility Warning", 
                                                 f"Selected Java may not be compatible:\n{message}")
            
            def auto_select_java():
                selected_version = form_vars['version'].get()
                if selected_version:
                    from Modules.minecraft import get_recommended_java_for_minecraft
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
                dedicated_servers_data, metadata = load_appid_scanner_list(server_manager_dir)
                
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
                            "requires_subscription": server.get("requires_subscription", False),
                            "anonymous_install": server.get("anonymous_install", True),
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
            columns = ("name", "appid", "subscription", "type")
            server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
            server_tree.heading("name", text="Server Name")
            server_tree.heading("appid", text="App ID")
            server_tree.heading("subscription", text="Subscription")
            server_tree.heading("type", text="Type")
            server_tree.column("name", width=300)
            server_tree.column("appid", width=80)
            server_tree.column("subscription", width=150)
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
                        # Determine subscription status
                        requires_sub = server.get("requires_subscription", False)
                        anonymous = server.get("anonymous_install", True)
                        
                        if requires_sub:
                            sub_status = "Subscription Required"
                        elif anonymous:
                            sub_status = "Free/Anonymous"
                        else:
                            sub_status = "Auth Required"
                        
                        server_tree.insert("", tk.END, values=(
                            server_name, 
                            server["appid"],
                            sub_status,
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
        # Remember currently selected server(s) to restore selection after refresh
        selected_items = server_list.selection()
        selected_server_names = []
        
        for item in selected_items:
            try:
                values = server_list.item(item)['values']
                if values and len(values) > 0:
                    server_name = values[0]
                    selected_server_names.append(server_name)
                    log_dashboard_event("SERVER_LIST_UPDATE", f"Preserving selection for server: {server_name}", "DEBUG")
            except (IndexError, KeyError, tk.TclError) as e:
                # Handle case where item doesn't exist, has no values, or Tkinter error
                log_dashboard_event("SERVER_LIST_UPDATE", f"Could not preserve selection for item: {str(e)}", "DEBUG")
                pass
        
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
        
        # Restore selection if any servers were previously selected
        if selected_server_names:
            selections_restored = 0
            for item in server_list.get_children():
                try:
                    values = server_list.item(item)['values']
                    if values and len(values) > 0:
                        server_name = values[0]
                        if server_name in selected_server_names:
                            server_list.selection_add(item)
                            selections_restored += 1
                            log_dashboard_event("SERVER_LIST_UPDATE", f"Restored selection for server: {server_name}", "DEBUG")
                except (IndexError, KeyError, tk.TclError) as e:
                    # Handle case where item doesn't exist, has no values, or Tkinter error
                    log_dashboard_event("SERVER_LIST_UPDATE", f"Could not restore selection for item: {str(e)}", "DEBUG")
                    pass
            
            if selections_restored > 0:
                log_dashboard_event("SERVER_LIST_UPDATE", f"Restored {selections_restored} server selection(s)", "INFO")
            elif selected_server_names:
                log_dashboard_event("SERVER_LIST_UPDATE", f"Could not restore any of {len(selected_server_names)} previously selected servers", "WARNING")
        
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
        from Modules.minecraft import detect_java_installations, check_java_compatibility, get_recommended_java_for_minecraft
        
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
                from Modules.minecraft import get_java_version
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
                from Modules.minecraft import MinecraftServerManager
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
            
        # Auto-detect server type from directory
        detected_server_type = detect_server_type_from_directory(install_dir)
        detected_appid = find_appid_in_directory(install_dir)
        
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

        # Server type with auto-detection
        ttk.Label(main_frame, text="Server Type:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.W)
        type_var = tk.StringVar(value=detected_server_type)
        type_combo = ttk.Combobox(main_frame, textvariable=type_var, values=supported_server_types, width=32)
        type_combo.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Show detection result
        if detected_server_type != "Other":
            detection_text = f"Auto-detected as: {detected_server_type}"
            if detected_appid:
                app_info = check_appid_in_database(detected_appid)
                if app_info and app_info.get('exists'):
                    detection_text += f" (AppID: {detected_appid} - {app_info.get('name', 'Unknown')})"
                else:
                    detection_text += f" (AppID: {detected_appid})"
            ttk.Label(main_frame, text=detection_text, foreground="green", font=("Segoe UI", 8)).grid(
                row=1, column=3, padx=10, pady=10, sticky=tk.W
            )
        
        # Installation directory (readonly)
        ttk.Label(main_frame, text="Install Directory:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.W)
        ttk.Label(main_frame, text=install_dir, wraplength=300).grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # Steam AppID field (for Steam servers)
        appid_var = tk.StringVar(value=detected_appid or "")
        appid_label = ttk.Label(main_frame, text="Steam AppID:")
        appid_entry = ttk.Entry(main_frame, textvariable=appid_var, width=25)
        
        # Browse AppID button
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
                dedicated_servers_data, metadata = load_appid_scanner_list(server_manager_dir)
                
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
                            "requires_subscription": server.get("requires_subscription", False),
                            "anonymous_install": server.get("anonymous_install", True),
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
            columns = ("name", "appid", "subscription", "type")
            server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
            server_tree.heading("name", text="Server Name")
            server_tree.heading("appid", text="App ID")
            server_tree.heading("subscription", text="Subscription")
            server_tree.heading("type", text="Type")
            server_tree.column("name", width=300)
            server_tree.column("appid", width=80)
            server_tree.column("subscription", width=150)
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
                        # Determine subscription status
                        requires_sub = server.get("requires_subscription", False)
                        anonymous = server.get("anonymous_install", True)
                        
                        if requires_sub:
                            sub_status = "Subscription Required"
                        elif anonymous:
                            sub_status = "Free/Anonymous"
                        else:
                            sub_status = "Auth Required"
                        
                        server_tree.insert("", tk.END, values=(
                            server_name, 
                            server["appid"],
                            sub_status,
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
        
        appid_browse_btn = ttk.Button(main_frame, text="Browse", command=browse_appid, width=10)
        
        # Initially hide AppID field
        appid_row = 3
        
        def update_appid_visibility():
            if type_var.get() == "Steam":
                appid_label.grid(row=appid_row, column=0, padx=10, pady=10, sticky=tk.W)
                appid_entry.grid(row=appid_row, column=1, padx=10, pady=10, sticky=tk.W)
                appid_browse_btn.grid(row=appid_row, column=2, padx=5, pady=10)
            else:
                appid_label.grid_remove()
                appid_entry.grid_remove()
                appid_browse_btn.grid_remove()
        
        # Bind type change to visibility update
        type_var.trace('w', lambda *args: update_appid_visibility())
        update_appid_visibility()
        
        # Executable path
        exe_row = appid_row + 1
        ttk.Label(main_frame, text="Executable:").grid(row=exe_row, column=0, padx=10, pady=10, sticky=tk.W)
        exe_var = tk.StringVar()
        exe_entry = ttk.Entry(main_frame, textvariable=exe_var, width=25)
        exe_entry.grid(row=exe_row, column=1, padx=10, pady=10, sticky=tk.W)
        
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
        
        ttk.Button(main_frame, text="Browse", command=browse_exe, width=10).grid(row=exe_row, column=2, padx=5, pady=10)
        
        # Startup arguments
        args_row = exe_row + 1
        ttk.Label(main_frame, text="Startup Args:").grid(row=args_row, column=0, padx=10, pady=10, sticky=tk.W)
        args_var = tk.StringVar()
        args_entry = ttk.Entry(main_frame, textvariable=args_var, width=35)
        args_entry.grid(row=args_row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
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
        
        detect_row = args_row + 1
        ttk.Button(main_frame, text="Auto-detect", command=auto_detect, width=15).grid(row=detect_row, column=1, pady=10)
        
        # Return result variable
        result = {'success': False, 'server_name': None}
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=detect_row + 1, column=0, columnspan=3, pady=20)
        
        def import_config():
            try:
                server_name = name_var.get().strip()
                server_type = type_var.get()
                executable_path = exe_var.get().strip()
                startup_args = args_var.get().strip()
                steam_appid = appid_var.get().strip()
                
                if not server_name:
                    messagebox.showerror("Validation Error", "Server name is required.")
                    return
                    
                if not executable_path:
                    messagebox.showerror("Validation Error", "Executable path is required.")
                    return
                
                # Validate Steam AppID if server type is Steam
                if server_type == "Steam":
                    if not steam_appid:
                        messagebox.showerror("Validation Error", "Steam AppID is required for Steam servers.")
                        return
                    
                    # Check if AppID exists in database
                    app_info = check_appid_in_database(steam_appid)
                    if not app_info or not app_info.get('exists'):
                        response = messagebox.askyesno(
                            "AppID Not Found", 
                            f"AppID {steam_appid} was not found in the Steam database. "
                            "This may mean the AppID is invalid or the database needs updating.\n\n"
                            "Do you want to continue with the import anyway?"
                        )
                        if not response:
                            return
                    else:
                        # Show AppID verification info
                        app_name = app_info.get('name', 'Unknown')
                        is_dedicated = app_info.get('is_dedicated_server', False)
                        if not is_dedicated:
                            response = messagebox.askyesno(
                                "AppID Warning", 
                                f"AppID {steam_appid} ({app_name}) is not marked as a dedicated server in our database. "
                                "This may not be a valid server AppID.\n\n"
                                "Do you want to continue anyway?"
                            )
                            if not response:
                                return
                
                # Use server manager to import the server (pass AppID for Steam servers)
                if server_manager:
                    if server_type == "Steam":
                        success, message = server_manager.import_server_config(
                            server_name, server_type, install_dir, executable_path, startup_args, steam_appid
                        )
                    else:
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
        center_window(dialog, 600, 500, parent)
        
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
            app_id = server_config['AppId']
            info_text += f"\nSteam App ID: {app_id}"
            
            # Verify AppID in current database
            app_info = check_appid_in_database(app_id)
            if app_info and app_info.get('exists'):
                info_text += f" - {app_info.get('name', 'Unknown')} ✓"
            else:
                # Check if export had app info
                export_app_info = dependencies.get("steam_app_info", {})
                if export_app_info.get("name") and export_app_info.get("verified", True):
                    info_text += f" - {export_app_info['name']} (not in local database) ⚠️"
                else:
                    info_text += " - Unknown/Unverified ❌"
            
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


def show_server_rename_dialog(parent, current_server_name, server_config, server_manager, paths, server_manager_dir):
    """Create a dialog to rename a server and modify its AppID
    
    Args:
        parent: Parent window
        current_server_name (str): Current name of the server
        server_config (dict): Current server configuration
        server_manager: Server manager instance
        paths (dict): Application paths dictionary
        server_manager_dir (str): Server manager directory path
        
    Returns:
        dict: Result containing success status, new name, and new AppID
    """
    try:
        dialog = tk.Toplevel(parent)
        dialog.title(f"Rename Server: {current_server_name}")
        dialog.transient(parent)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Current info section
        current_frame = ttk.LabelFrame(main_frame, text="Current Configuration", padding=10)
        current_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(current_frame, text="Current Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(current_frame, text=current_server_name, font=("Segoe UI", 10)).grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        
        current_server_type = server_config.get('Type', 'Unknown')
        ttk.Label(current_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(current_frame, text=current_server_type, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        current_appid = server_config.get('AppID', 'N/A')
        if current_server_type == 'Steam':
            ttk.Label(current_frame, text="Current AppID:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
            ttk.Label(current_frame, text=str(current_appid), font=("Segoe UI", 10)).grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        # New configuration section
        new_frame = ttk.LabelFrame(main_frame, text="New Configuration", padding=10)
        new_frame.pack(fill=tk.X, pady=(0, 20))
        
        # New server name
        ttk.Label(new_frame, text="New Server Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, padx=5, pady=10)
        new_name_var = tk.StringVar(value=current_server_name)
        name_entry = ttk.Entry(new_frame, textvariable=new_name_var, width=30, font=("Segoe UI", 10))
        name_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=10)
        name_entry.select_range(0, tk.END)
        name_entry.focus()
        
        # AppID field (only for Steam servers)
        new_appid_var = tk.StringVar(value=str(current_appid) if current_appid != 'N/A' else '')
        appid_entry = None
        
        if current_server_type == 'Steam':
            ttk.Label(new_frame, text="New AppID:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, padx=5, pady=10)
            appid_entry = ttk.Entry(new_frame, textvariable=new_appid_var, width=15, font=("Segoe UI", 10))
            appid_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=10)
            
            # AppID help
            help_label = ttk.Label(new_frame, text="Enter Steam AppID (numbers only)", 
                                 foreground="gray", font=("Segoe UI", 8))
            help_label.grid(row=1, column=2, sticky=tk.W, padx=5, pady=10)
        
        # Configure grid weights
        new_frame.columnconfigure(1, weight=1)
        
        # Warning label
        warning_frame = ttk.Frame(main_frame)
        warning_frame.pack(fill=tk.X, pady=(0, 20))
        
        warning_label = ttk.Label(warning_frame, 
                                text="Warning: Renaming will update all configuration files. Make sure the server is stopped.",
                                foreground="orange", font=("Segoe UI", 9), wraplength=400)
        warning_label.pack()
        
        # Result storage
        result = {"success": False, "new_name": None, "new_appid": None, "cancelled": True}
        
        def validate_inputs():
            """Validate the input values"""
            new_name = new_name_var.get().strip()
            errors = []
            
            # Validate server name
            if not new_name:
                errors.append("Server name cannot be empty")
            elif new_name != current_server_name:
                # Check if new name already exists
                if server_manager and hasattr(server_manager, 'get_server_config'):
                    try:
                        existing_config = server_manager.get_server_config(new_name)
                        if existing_config:
                            errors.append(f"Server name '{new_name}' already exists")
                    except:
                        pass  # Server doesn't exist, which is good
            
            # Validate AppID for Steam servers
            if current_server_type == 'Steam':
                new_appid = new_appid_var.get().strip()
                if not new_appid:
                    errors.append("AppID cannot be empty for Steam servers")
                elif not new_appid.isdigit():
                    errors.append("AppID must contain only numbers")
            
            return errors
        
        def on_rename():
            """Handle rename button click"""
            errors = validate_inputs()
            if errors:
                messagebox.showerror("Validation Error", "\n".join(errors))
                return
            
            new_name = new_name_var.get().strip()
            new_appid = new_appid_var.get().strip() if current_server_type == 'Steam' else None
            
            # Confirm the operation
            confirm_msg = f"Are you sure you want to rename '{current_server_name}' to '{new_name}'?"
            if current_server_type == 'Steam' and new_appid != str(current_appid):
                confirm_msg += f"\n\nAppID will be changed from '{current_appid}' to '{new_appid}'"
            
            if messagebox.askyesno("Confirm Rename", confirm_msg):
                result.update({
                    "success": True,
                    "new_name": new_name,
                    "new_appid": int(new_appid) if new_appid else None,
                    "cancelled": False
                })
                dialog.destroy()
        
        def on_cancel():
            """Handle cancel button click"""
            result["cancelled"] = True
            dialog.destroy()
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Rename", command=on_rename, width=12).pack(side=tk.RIGHT)
        
        # Handle window close event (X button)
        def on_dialog_close():
            result["cancelled"] = True
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        # Center dialog relative to parent
        center_window(dialog, 500, 350, parent)
        
        # Wait for dialog to close
        parent.wait_window(dialog)
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating server rename dialog: {e}")
        messagebox.showerror("Error", f"Failed to create rename dialog:\n{str(e)}")
        return {"success": False, "new_name": None, "new_appid": None, "cancelled": True}


def rename_server_configuration(old_name, new_name, new_appid, server_manager, paths):
    """Rename a server and update its configuration
    
    Args:
        old_name (str): Current server name
        new_name (str): New server name
        new_appid (int): New AppID (for Steam servers, None for others)
        server_manager: Server manager instance
        paths (dict): Application paths dictionary
        
    Returns:
        tuple: (success, message)
    """
    try:
        if not server_manager:
            return False, "Server manager not available"
        
        # Get current server configuration
        current_config = server_manager.get_server_config(old_name)
        if not current_config:
            return False, f"Server '{old_name}' not found"
        
        # Check if server is running
        server_status, _ = server_manager.get_server_status(old_name)
        if server_status == "Running":
            return False, f"Server '{old_name}' is currently running. Please stop it before renaming."
        
        # Create new configuration with updated values
        new_config = current_config.copy()
        
        # Update AppID if provided (Steam servers)
        if new_appid is not None and current_config.get('Type') == 'Steam':
            new_config['AppID'] = new_appid
            logger.info(f"Updated AppID from {current_config.get('AppID')} to {new_appid}")
        
        # If name is changing, handle the rename
        if old_name != new_name:
            # Use the simplest and safest approach: save new config, then remove old
            try:
                # First check if new name already exists
                existing_config = server_manager.get_server_config(new_name)
                if existing_config:
                    return False, f"A server with the name '{new_name}' already exists"
                
                # Update the config data with new name
                new_config['Name'] = new_name
                new_config['LastUpdate'] = datetime.datetime.now().isoformat()
                
                # Save the configuration with the new name
                server_manager.save_server_config(new_name, new_config)
                
                # Remove the old configuration only after new one is saved successfully
                success, msg = server_manager.remove_server_config(old_name)
                if not success:
                    # If old removal fails, cleanup the new config to avoid duplicates
                    try:
                        server_manager.remove_server_config(new_name)
                    except:
                        pass
                    return False, f"Failed to remove old server configuration: {msg}"
                
                logger.info(f"Successfully renamed server from '{old_name}' to '{new_name}'")
                return True, f"Successfully renamed server to '{new_name}'"
                
            except Exception as e:
                logger.error(f"Error during server rename: {str(e)}")
                return False, f"Failed to rename server: {str(e)}"
        
        # If only AppID changed (same name)
        else:
            # Use save_server_config for simple config updates
            try:
                server_manager.save_server_config(old_name, new_config)
                logger.info(f"Successfully updated configuration for server '{old_name}'")
                return True, f"Successfully updated server configuration"
            except Exception as e:
                logger.error(f"Error updating server config: {str(e)}")
                return False, f"Failed to update server configuration: {str(e)}"
    
    except Exception as e:
        logger.error(f"Error renaming server '{old_name}' to '{new_name}': {e}")
        return False, f"Error during rename operation: {str(e)}"


def re_detect_server_type_from_config(server_config):
    """Re-detect server type from existing server configuration"""
    if not server_config:
        return "Other"
    
    current_type = server_config.get('Type', 'Other')
    
    # If already Steam, check if AppID is valid
    if current_type == "Steam":
        app_id = server_config.get('AppId')
        if app_id:
            app_info = check_appid_in_database(app_id)
            if app_info and app_info.get('exists'):
                return "Steam"  # Valid Steam server
            else:
                logger.warning(f"Server has Steam type but invalid AppID {app_id}, changing to Other")
                return "Other"
    
    # Check install directory for clues
    install_dir = server_config.get('InstallDir')
    if install_dir:
        detected_type = detect_server_type_from_directory(install_dir)
        if detected_type != "Other":
            # Found evidence in directory
            if detected_type == "Steam":
                # Look for AppID in directory
                found_appid = find_appid_in_directory(install_dir)
                if found_appid:
                    app_info = check_appid_in_database(found_appid)
                    if app_info and app_info.get('exists'):
                        # Update configuration with found AppID
                        server_config['AppId'] = found_appid
                        server_config['AppName'] = app_info.get('name', 'Unknown')
                        return "Steam"
            else:
                return detected_type
    
    # Check executable path for clues
    executable_path = server_config.get('ExecutablePath', '')
    if executable_path:
        exe_lower = executable_path.lower()
        if any(steam_exe in exe_lower for steam_exe in ['srcds', 'hlds', 'steamcmd']):
            return "Steam"
        elif any(mc_exe in exe_lower for mc_exe in ['server.jar', 'minecraft_server', 'paper', 'spigot', 'forge']):
            return "Minecraft"
    
    return current_type  # Keep current type if no better detection


def update_server_configuration_with_detection(server_config_path):
    """Update server configuration file with improved type detection"""
    try:
        if not os.path.exists(server_config_path):
            return False, "Configuration file not found"
        
        # Load current configuration
        with open(server_config_path, 'r') as f:
            server_config = json.load(f)
        
        old_type = server_config.get('Type', 'Other')
        new_type = re_detect_server_type_from_config(server_config)
        
        if old_type != new_type:
            server_config['Type'] = new_type
            server_config['TypeUpdated'] = datetime.datetime.now().isoformat()
            server_config['PreviousType'] = old_type
            
            # Save updated configuration
            with open(server_config_path, 'w') as f:
                json.dump(server_config, f, indent=4)
            
            logger.info(f"Updated server type from {old_type} to {new_type}: {server_config.get('Name', 'Unknown')}")
            return True, f"Updated server type from {old_type} to {new_type}"
        else:
            return True, "No type change needed"
        
    except Exception as e:
        logger.error(f"Error updating server configuration: {str(e)}")
        return False, f"Failed to update configuration: {str(e)}"


def batch_update_server_types(paths):
    """Batch update all server configurations with improved type detection"""
    try:
        servers_path = os.path.join(paths["root"], "servers")
        if not os.path.exists(servers_path):
            return 0, []
        
        updated_count = 0
        updated_servers = []
        
        for file in os.listdir(servers_path):
            if file.endswith('.json'):
                config_path = os.path.join(servers_path, file)
                try:
                    success, message = update_server_configuration_with_detection(config_path)
                    if success and "Updated server type" in message:
                        updated_count += 1
                        with open(config_path, 'r') as f:
                            config = json.load(f)
                        updated_servers.append({
                            'name': config.get('Name', 'Unknown'),
                            'old_type': config.get('PreviousType', 'Unknown'),
                            'new_type': config.get('Type', 'Unknown')
                        })
                except Exception as e:
                    logger.error(f"Error updating {file}: {str(e)}")
        
        return updated_count, updated_servers
        
    except Exception as e:
        logger.error(f"Error in batch update: {str(e)}")
        return 0, []
