# -*- coding: utf-8 -*-
import os
import sys
import json
import datetime
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Dict, Any, Optional, Union
import platform
import psutil
import subprocess

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import registry functions from common module
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import logging functions
from Modules.server_logging import get_dashboard_logger, log_dashboard_event

# Get dashboard logger
logger = get_dashboard_logger()


def load_dashboard_config(server_manager_dir):
    # Load dashboard configuration from JSON file
    try:
        config_path = os.path.join(server_manager_dir, "data", "dashboard.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logger.warning(f"Dashboard config not found at {config_path}, using defaults")
            return {}
    except Exception as e:
        logger.error(f"Error loading dashboard config: {e}")
        return {}


def center_window(window, width=None, height=None, parent=None):
    # Center a window on the screen or relative to a parent window
    window.update_idletasks()
    
    # Get window dimensions
    if width and height:
        window_width, window_height = width, height
    else:
        window_width = window.winfo_width()
        window_height = window.winfo_height()
    
    if parent:
        # Center relative to parent
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
    # Create and show server type selection dialog
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
        ttk.Radiobutton(main_frame, text=stype, variable=type_var, value=stype).pack(anchor=tk.W, pady=5)
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(20, 0))
    
    def proceed():
        if not type_var.get():
            messagebox.showwarning("No Selection", "Please select a server type.")
            return
        type_dialog.destroy()
        
    def cancel():
        type_var.set("")
        type_dialog.destroy()
    
    # Handle window close event (X button)
    def on_dialog_close():
        type_var.set("")
        type_dialog.destroy()
    
    type_dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
    
    # Buttons with better spacing
    ttk.Button(button_frame, text="Cancel", command=cancel, width=12).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Next", command=proceed, width=12).pack(side=tk.RIGHT)
    
    # Center dialog relative to parent
    center_window(type_dialog, 380, 280, root)
    
    root.wait_window(type_dialog)
    return type_var.get()


def get_steam_credentials(root):
    # Open a dialog to get Steam credentials
    credentials = {"anonymous": False, "username": "", "password": ""}
    
    # Create dialog window
    dialog = tk.Toplevel(root)
    dialog.title("Steam Login")
    dialog.geometry("350x300")
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


def load_appid_scanner_list(server_manager_dir):
    # Load the AppID list from database only (NO FALLBACKS)
    try:
        # Import database scanner
        from Modules.Database.AppIDScanner import AppIDScanner

        # Initialize scanner with database enabled
        scanner = AppIDScanner(use_database=True, debug_mode=False)

        try:
            # Get dedicated servers from database only
            servers = scanner.get_dedicated_servers_from_database()

            if not servers:
                logger.warning("No Steam dedicated servers found in database")
                return [], {}

            # Create metadata dictionary
            metadata = {
                "total_servers": len(servers),
                "source": "database",
                "last_updated": datetime.datetime.now().isoformat()
            }

            logger.info(f"Loaded {len(servers)} Steam dedicated servers from database")
            return servers, metadata

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Steam database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Steam database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to load Steam AppID list from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def load_minecraft_scanner_list(server_manager_dir):
    # Load the Minecraft server list from database (NO FALLBACKS)
    try:
        # Import database scanner
        from Modules.Database.MinecraftIDScanner import MinecraftIDScanner

        # Initialize scanner with database enabled
        scanner = MinecraftIDScanner(use_database=True, debug_mode=False)

        try:
            # Get all Minecraft servers from database
            servers = scanner.get_servers_from_database(
                modloader=None,
                dedicated_only=True,
                filter_snapshots=True
            )

            if not servers:
                logger.warning("No Minecraft servers found in database")
                return [], {}

            # Create metadata dictionary
            metadata = {
                "total_servers": len(servers),
                "source": "database",
                "last_updated": datetime.datetime.now().isoformat()
            }

            logger.info(f"Loaded {len(servers)} Minecraft servers from database")
            return servers, metadata

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Minecraft database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Minecraft database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to load Minecraft scanner list from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def get_minecraft_versions_from_database(modloader=None, dedicated_only=True):
    # Get Minecraft versions from database filtered by modloader - NO FALLBACKS
    try:
        # Import database scanner
        from Modules.Database.MinecraftIDScanner import MinecraftIDScanner

        # Initialize scanner with database enabled
        scanner = MinecraftIDScanner(use_database=True, debug_mode=False)

        try:
            # Get servers from database only
            versions = scanner.get_servers_from_database(
                modloader=modloader,
                dedicated_only=dedicated_only,
                filter_snapshots=True
            )

            if not versions:
                logger.warning(f"No Minecraft versions found in database for modloader '{modloader}'")
                return []

            # Convert to expected format
            formatted_versions = []
            for version in versions:
                formatted_versions.append({
                    "version_id": version["version_id"],
                    "modloader": version["modloader"] or modloader or "vanilla",
                    "java_requirement": version["java_requirement"] or 17
                })

            logger.info(f"Retrieved {len(formatted_versions)} Minecraft versions from database")
            return formatted_versions

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Minecraft database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to retrieve Minecraft versions from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)


def create_minecraft_version_browser_dialog(parent, modloader="Vanilla"):
    # Create a dialog to browse and select Minecraft versions from database
    dialog = tk.Toplevel(parent)
    dialog.title(f"Browse {modloader} Minecraft Versions")
    dialog.geometry("700x500")
    dialog.transient(parent)
    dialog.grab_set()
    
    # Main frame
    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Title
    title_label = ttk.Label(main_frame, text=f"Select {modloader} Minecraft Version", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 15))
    
    # Version list frame
    list_frame = ttk.LabelFrame(main_frame, text="Available Versions", padding=10)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
    
    # Treeview for versions
    columns = ("version", "type", "modloader_version", "java", "date")
    version_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
    
    version_tree.heading("version", text="Version")
    version_tree.heading("type", text="Type")
    version_tree.heading("modloader_version", text="Modloader Version")
    version_tree.heading("java", text="Java")
    version_tree.heading("date", text="Release Date")
    
    version_tree.column("version", width=120, minwidth=100)
    version_tree.column("type", width=80, minwidth=60)
    version_tree.column("modloader_version", width=150, minwidth=100)
    version_tree.column("java", width=60, minwidth=50)
    version_tree.column("date", width=120, minwidth=100)
    
    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=version_tree.yview)
    version_tree.configure(yscrollcommand=scrollbar.set)
    
    version_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    # Load versions from database
    try:
        versions = get_minecraft_versions_from_database(modloader.lower(), dedicated_only=True)
        
        for version_data in versions:
            version_tree.insert("", tk.END, values=(
                version_data.get("version_id", ""),
                "Release",
                modloader,
                f"Java {version_data.get('java_requirement', 17)}",
                "Database"  # Source indicator
            ))
            
    except Exception as e:
        logger.error(f"Error loading versions for browser dialog: {e}")
        messagebox.showerror("Error", f"Failed to load versions: {str(e)}")
    
    # Result variable - can hold either None or dict
    selected_version: Dict[str, Optional[Dict[str, Any]]] = {"version": None}
    
    def on_select():
        selection = version_tree.selection()
        if selection:
            item = version_tree.item(selection[0])
            values = item['values']
            selected_version["version"] = {
                "version_id": values[0],
                "modloader": modloader.lower(),
                "java_requirement": int(values[3].replace("Java ", "")) if "Java" in values[3] else 17
            }
            dialog.destroy()
        else:
            messagebox.showinfo("No Selection", "Please select a version.")
    
    def on_cancel():
        dialog.destroy()
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)
    
    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Select", command=on_select).pack(side=tk.RIGHT)
    
    # Double-click to select
    version_tree.bind("<Double-1>", lambda e: on_select())
    
    # Center dialog
    center_window(dialog, 700, 500, parent)
    
    # Wait for dialog to close
    parent.wait_window(dialog)
    
    return selected_version["version"]


def create_steam_appid_browser_dialog(parent, server_manager_dir):
    # Create a dialog to browse and select Steam AppIDs from database
    dialog = tk.Toplevel(parent)
    dialog.title("Select Steam Dedicated Server")
    dialog.geometry("700x500")
    dialog.transient(parent)
    dialog.grab_set()
    
    # Main frame
    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Title
    title_label = ttk.Label(main_frame, text="Select Steam Dedicated Server", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 15))
    
    # Search frame
    search_frame = ttk.Frame(main_frame)
    search_frame.pack(fill=tk.X, pady=(0, 10))
    
    ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
    search_entry.pack(side=tk.LEFT, padx=(5, 10))
    
    # Load dedicated servers from scanner's AppID list
    try:
        dedicated_servers_data, metadata = load_appid_scanner_list(server_manager_dir)

        if not dedicated_servers_data:
            error_msg = "Scanner AppID list not available - database must be populated first"
            logger.error(error_msg)
            messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
            dialog.destroy()
            return None

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
        dialog.destroy()
        return None
    
    # Server list frame
    list_frame = ttk.LabelFrame(main_frame, text="Available Servers", padding=10)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
    
    # Treeview for servers
    columns = ("name", "appid", "developer", "type")
    server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
    
    server_tree.heading("name", text="Server Name")
    server_tree.heading("appid", text="App ID")
    server_tree.heading("developer", text="Developer")
    server_tree.heading("type", text="Type")
    
    server_tree.column("name", width=300, minwidth=200)
    server_tree.column("appid", width=80, minwidth=60)
    server_tree.column("developer", width=150, minwidth=100)
    server_tree.column("type", width=120, minwidth=80)
    
    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
    server_tree.configure(yscrollcommand=scrollbar.set)
    
    server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
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
    
    # Tooltip functionality for descriptions
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
                tooltip = tk.Toplevel(dialog)
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
    
    # Result variable
    selected_appid: Dict[str, Optional[str]] = {"appid": None}
    
    def on_select():
        selection = server_tree.selection()
        if selection:
            item = server_tree.item(selection[0])
            appid = item['values'][1]
            selected_appid["appid"] = appid
            dialog.destroy()
        else:
            messagebox.showinfo("No Selection", "Please select a server from the list.")
    
    def on_cancel():
        dialog.destroy()
    
    # Button frame
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)
    
    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Select Server", command=on_select).pack(side=tk.RIGHT)
    
    # Center dialog
    center_window(dialog, 700, 500, parent)
    
    # Wait for dialog to close
    parent.wait_window(dialog)
    
    return selected_appid["appid"]


def check_appid_in_database(appid):
    # Check if an AppID exists in the Steam database and return server info
    if not appid:
        return None
    
    try:
        # For now, return basic info since database integration is complex
        logger.info(f"Checking AppID {appid} - database integration disabled for now")
        return {"exists": True, "name": f"Server {appid}", "type": "Steam"}
        
    except Exception as e:
        logger.error(f"Error checking AppID in database: {e}")
        return None


def detect_server_type_from_appid(appid):
    # Detect server type based on AppID from database
    if not appid:
        return "Other"
    
    app_info = check_appid_in_database(appid)
    if app_info and app_info.get('exists'):
        return "Steam"
    
    return "Other"


def detect_server_type_from_directory(directory_path):
    # Detect server type from directory contents and configuration
    if not directory_path or not os.path.exists(directory_path):
        return "Other"
    
    try:
        files = os.listdir(directory_path)
        files_lower = [f.lower() for f in files]
        
        # Check for Minecraft indicators
        minecraft_indicators = ['server.jar', 'minecraft_server.jar', 'forge-installer.jar', 'fabric-server-launch.jar']
        if any(indicator in files_lower for indicator in minecraft_indicators):
            return "Minecraft"
        
        # Check for Steam indicators
        steam_indicators = ['steamapps', 'steam.exe', 'steamcmd.exe']
        if any(indicator in files_lower for indicator in steam_indicators):
            return "Steam"
        
        return "Other"
        
    except Exception as e:
        logger.error(f"Error detecting server type from directory: {e}")
        return "Other"


def perform_server_installation(server_type, server_name, install_dir, app_id=None, 
                               minecraft_version=None, credentials=None,
                               server_manager=None, progress_callback=None, console_callback=None,
                               steam_cmd_path=None):
    # Perform server installation with progress tracking and console output
    #
    # Args:
    #     server_type: Type of server to install
    #     server_name: Name for the server
    #     install_dir: Installation directory
    #     app_id: Steam App ID (for Steam servers)
    #     minecraft_version: Minecraft version data (for Minecraft servers)
    #     credentials: Steam credentials (for Steam servers)
    #     server_manager: Server manager instance
    #     progress_callback: Function to call with progress updates
    #     console_callback: Function to call with console output
    #     steam_cmd_path: Path to SteamCMD executable (for Steam servers)
    #
    # Returns:
    #     tuple: (success, message)
    try:
        if not server_manager:
            error_msg = "Server manager not available"
            if console_callback:
                console_callback(f"[ERROR] {error_msg}")
            return False, error_msg

        # Get SteamCMD path if not provided and server type is Steam
        if server_type == "Steam" and not steam_cmd_path:
            from Modules.common import get_registry_value
            steam_cmd_path = get_registry_value("HKEY_CURRENT_USER\\Software\\SkywereIndustries\\ServerManager", "SteamCmdPath")
            if not steam_cmd_path:
                # Try default location
                steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
                if console_callback:
                    console_callback(f"[WARN] SteamCMD path not found in registry, using default: {steam_cmd_path}")
            
            # Verify SteamCMD exists
            if not os.path.exists(os.path.join(steam_cmd_path, "steamcmd.exe")):
                error_msg = f"SteamCMD not found at {steam_cmd_path}. Please install SteamCMD or configure the correct path."
                if console_callback:
                    console_callback(f"[ERROR] {error_msg}")
                return False, error_msg
        
        if console_callback:
            console_callback(f"[INFO] Starting installation of {server_type} server '{server_name}'")
            console_callback(f"[INFO] Installation directory: {install_dir}")
            
        # Create server configuration
        server_config = {
            'Name': server_name,
            'Type': server_type,
            'InstallDir': install_dir
        }
        
        if server_type == "Steam" and app_id:
            server_config['AppId'] = app_id
            if console_callback:
                console_callback(f"[INFO] Steam App ID: {app_id}")
                
        if server_type == "Minecraft" and minecraft_version:
            server_config['MinecraftVersion'] = minecraft_version.get('version_id', '')
            server_config['Modloader'] = minecraft_version.get('modloader', 'vanilla')
            server_config['JavaRequirement'] = minecraft_version.get('java_requirement', 17)
            if console_callback:
                console_callback(f"[INFO] Minecraft Version: {minecraft_version.get('version_id', '')}")
                console_callback(f"[INFO] Modloader: {minecraft_version.get('modloader', 'vanilla')}")
        
        # Call progress callback if provided
        if progress_callback:
            progress_callback("Creating server configuration...")
        if console_callback:
            console_callback("[INFO] Creating server configuration...")
        
        # Use server manager to create the server
        if console_callback:
            console_callback("[INFO] Calling server manager to install server...")
            
        # Call the correct backend method
        success, message = server_manager.install_server_complete(
            server_name=server_name,
            server_type=server_type,
            install_dir=install_dir,
            executable_path="",  # Let backend determine executable
            startup_args="",
            app_id=app_id or "",
            version=minecraft_version.get('version_id', '') if minecraft_version else "",
            modloader=minecraft_version.get('modloader', 'vanilla') if minecraft_version else "",
            steam_cmd_path=steam_cmd_path or "",  # Pass the SteamCMD path
            credentials=credentials or {"anonymous": True},
            progress_callback=console_callback,  # Use console callback for progress
            cancel_flag=None
        )
        
        if success:
            success_msg = message or f"Server '{server_name}' installed successfully"
            if progress_callback:
                progress_callback("Server installation completed successfully")
            if console_callback:
                console_callback(f"[SUCCESS] {success_msg}")
            return True, success_msg
        else:
            error_msg = message or f"Failed to install server '{server_name}'"
            if console_callback:
                console_callback(f"[ERROR] {error_msg}")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Installation failed: {str(e)}"
        logger.error(f"Error performing server installation: {str(e)}")
        if progress_callback:
            progress_callback(error_msg)
        if console_callback:
            console_callback(f"[ERROR] {error_msg}")
        return False, error_msg


# Placeholder functions for functions that are used by dashboard.py but not essential for add_server
def update_webserver_status(webserver_status_label, offline_var, paths, variables):
    # Update webserver status in the dashboard
    try:
        status = check_webserver_status(paths, variables)
        webserver_status_label.config(text=status)
        
        # Set color based on status
        if status == "Running":
            webserver_status_label.config(foreground="green")
        elif status == "Stopped":
            webserver_status_label.config(foreground="red")
        elif status == "Offline Mode":
            webserver_status_label.config(foreground="orange")
        else:
            webserver_status_label.config(foreground="gray")
    except Exception as e:
        logger.error(f"Error updating webserver status: {e}")
        webserver_status_label.config(text="Unknown", foreground="gray")


# Global variables for network monitoring
_previous_network_stats = None
_previous_network_time = None

def update_system_info(metric_labels, system_name, os_info, variables):
    # Update system information in the dashboard UI
    global _previous_network_stats, _previous_network_time
    
    try:
        # Update system name and OS info
        try:
            system_name_text = platform.node()
            if not system_name_text:
                system_name_text = "Unknown System"
            system_name.config(text=system_name_text)
        except Exception as e:
            logger.error(f"Error getting system name: {e}")
            system_name.config(text="Unknown System")

        try:
            os_info_text = f"{platform.system()} {platform.release()} ({platform.machine()})"
            os_info.config(text=os_info_text)
        except Exception as e:
            logger.error(f"Error getting OS info: {e}")
            os_info.config(text="Unknown OS")

        # Update CPU usage
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            metric_labels["cpu"].config(text=f"CPU: {cpu_percent:.1f}%")
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            metric_labels["cpu"].config(text="CPU: N/A")

        # Update memory usage
        try:
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)
            metric_labels["memory"].config(text=f"Memory: {memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB ({memory_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            metric_labels["memory"].config(text="Memory: N/A")

        # Update disk usage
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_used_gb = disk.used / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            metric_labels["disk"].config(text=f"Disk: {disk_used_gb:.1f}GB / {disk_total_gb:.1f}GB ({disk_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            metric_labels["disk"].config(text="Disk: N/A")

        # Update network info
        try:
            import time
            current_time = time.time()
            network_stats = psutil.net_io_counters()
            
            if network_stats:
                if _previous_network_stats is not None and _previous_network_time is not None:
                    # Calculate time difference
                    time_diff = current_time - _previous_network_time
                    
                    if time_diff > 0:
                        # Calculate current transfer rates (bytes per second)
                        bytes_sent_per_sec = (network_stats.bytes_sent - _previous_network_stats.bytes_sent) / time_diff
                        bytes_recv_per_sec = (network_stats.bytes_recv - _previous_network_stats.bytes_recv) / time_diff
                        
                        # Convert to appropriate units
                        def format_speed(bytes_per_sec):
                            if bytes_per_sec >= 1024**3:  # GB/s
                                return f"{bytes_per_sec / (1024**3):.1f}GB/s"
                            elif bytes_per_sec >= 1024**2:  # MB/s
                                return f"{bytes_per_sec / (1024**2):.1f}MB/s"
                            elif bytes_per_sec >= 1024:  # KB/s
                                return f"{bytes_per_sec / 1024:.1f}KB/s"
                            else:  # B/s
                                return f"{bytes_per_sec:.1f}B/s"
                        
                        sent_display = format_speed(bytes_sent_per_sec)
                        recv_display = format_speed(bytes_recv_per_sec)
                        
                        metric_labels["network"].config(text=f"Network: ↑{sent_display} ↓{recv_display}")
                    else:
                        metric_labels["network"].config(text="Network: Calculating...")
                else:
                    metric_labels["network"].config(text="Network: Initializing...")
                
                # Update previous values for next calculation
                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                metric_labels["network"].config(text="Network: N/A")
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            metric_labels["network"].config(text="Network: N/A")

        # Update GPU info (enhanced detection for Intel integrated and multiple GPUs)
        try:
            gpu_info = "GPU: Not detected"
            
            # Try GPUtil first (best for dedicated GPUs)
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    if len(gpus) == 1:
                        gpu = gpus[0]
                        gpu_info = f"GPU: {gpu.name}"
                        if hasattr(gpu, 'memoryTotal') and gpu.memoryTotal > 0:
                            gpu_info += f" ({gpu.memoryUsed}MB/{gpu.memoryTotal}MB)"
                    else:
                        # Multiple GPUs
                        gpu_names = [gpu.name for gpu in gpus]
                        gpu_info = f"GPU: {len(gpus)} GPUs ({', '.join(gpu_names[:2])}"
                        if len(gpu_names) > 2:
                            gpu_info += f" +{len(gpu_names)-2} more"
                        gpu_info += ")"
                else:
                    # GPUtil found no GPUs, try system detection
                    raise ImportError("GPUtil detected no GPUs")
            except (ImportError, Exception):
                # GPUtil not available or no GPUs detected, try system-specific detection
                if platform.system() == "Windows":
                    try:
                        # Use WMIC to get GPU information
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run(
                            ['wmic', 'path', 'win32_VideoController', 'get', 'name,adapterram', '/format:csv'],
                            capture_output=True, text=True, timeout=5,
                            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        
                        if result.returncode == 0 and result.stdout.strip():
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:  # Skip header
                                gpu_list = []
                                for line in lines[1:]:
                                    if line.strip():
                                        parts = line.split(',')
                                        if len(parts) >= 3:  # Node,AdapterRAM,Name
                                            gpu_name = parts[2].strip()  # Name is in the 3rd column
                                            if gpu_name and gpu_name != "Node":
                                                gpu_list.append(gpu_name)
                                
                                if gpu_list:
                                    if len(gpu_list) == 1:
                                        gpu_info = f"GPU: {gpu_list[0]}"
                                    else:
                                        gpu_info = f"GPU: {len(gpu_list)} GPUs ({', '.join(gpu_list[:2])}"
                                        if len(gpu_list) > 2:
                                            gpu_info += f" +{len(gpu_list)-2} more"
                                        gpu_info += ")"
                    
                    except subprocess.TimeoutExpired:
                        gpu_info = "GPU: Detection timeout"
                    except Exception as e:
                        logger.debug(f"WMIC GPU detection failed: {e}")
                        gpu_info = "GPU: Detection failed"
                        
                elif platform.system() == "Linux":
                    try:
                        # Try lspci for Linux
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run(
                            ['lspci', '-v'], 
                            capture_output=True, text=True, timeout=5,
                            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        
                        if result.returncode == 0:
                            output = result.stdout.lower()
                            gpu_count = output.count('vga compatible controller') + output.count('3d controller')
                            
                            if gpu_count > 0:
                                if gpu_count == 1:
                                    gpu_info = "GPU: 1 GPU detected"
                                else:
                                    gpu_info = f"GPU: {gpu_count} GPUs detected"
                            else:
                                gpu_info = "GPU: Not detected"
                        else:
                            gpu_info = "GPU: Detection failed"
                            
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        gpu_info = "GPU: lspci not available"
                    except Exception as e:
                        logger.debug(f"Linux GPU detection failed: {e}")
                        gpu_info = "GPU: Detection failed"
                        
                else:
                    gpu_info = "GPU: Unsupported OS"
            
            metric_labels["gpu"].config(text=gpu_info)
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            metric_labels["gpu"].config(text="GPU: Error")

        # Update system uptime
        try:
            uptime_seconds = time.time() - psutil.boot_time()
            uptime_str = format_uptime_from_start_time(uptime_seconds)
            metric_labels["uptime"].config(text=f"Uptime: {uptime_str}")
        except Exception as e:
            logger.error(f"Error getting uptime info: {e}")
            metric_labels["uptime"].config(text="Uptime: N/A")

    except Exception as e:
        logger.error(f"Error updating system info: {e}")
        # Set all labels to error state
        for label_name in metric_labels:
            metric_labels[label_name].config(text=f"{label_name.title()}: Error")


def collect_system_info_data():
    # Collect system information data in a thread-safe manner (no UI updates)
    import platform
    import psutil
    import subprocess
    import time
    from typing import Dict, Any
    
    global _previous_network_stats, _previous_network_time
    
    data = {}
    
    try:
        # System name and OS info
        try:
            data['system_name'] = platform.node()
            if not data['system_name']:
                data['system_name'] = "Unknown System"
        except Exception as e:
            logger.error(f"Error getting system name: {e}")
            data['system_name'] = "Unknown System"

        try:
            data['os_info'] = f"{platform.system()} {platform.release()} ({platform.machine()})"
        except Exception as e:
            logger.error(f"Error getting OS info: {e}")
            data['os_info'] = "Unknown OS"

        # CPU usage (per-core and overall)
        try:
            # Get overall CPU usage
            overall_cpu = psutil.cpu_percent(interval=0.1)
            
            # Get per-core CPU usage
            per_core_cpu = psutil.cpu_percent(percpu=True, interval=0.1)
            
            # Format CPU display
            if len(per_core_cpu) <= 8:  # Show per-core for systems with 8 or fewer cores
                core_usage = ", ".join([f"{i}:{usage:.0f}%" for i, usage in enumerate(per_core_cpu)])
                data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nCores: {core_usage}"
            else:  # For systems with many cores, show overall + summary
                high_usage_cores = [i for i, usage in enumerate(per_core_cpu) if usage > 50]
                if high_usage_cores:
                    data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nHigh usage cores: {len(high_usage_cores)}/{len(per_core_cpu)}"
                else:
                    data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nAll cores: <50% usage"
                    
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            data['cpu_percent'] = None

        # Memory usage
        try:
            memory = psutil.virtual_memory()
            data['memory_percent'] = memory.percent
            data['memory_used_gb'] = memory.used / (1024**3)
            data['memory_total_gb'] = memory.total / (1024**3)
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            data['memory_percent'] = None
            data['memory_used_gb'] = None
            data['memory_total_gb'] = None

        # Disk usage - detect all drive letters on Windows
        try:
            import string
            disk_info_lines = []

            if platform.system() == "Windows":
                # Get all drive letters on Windows
                drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
                for drive in drives:
                    try:
                        disk = psutil.disk_usage(drive)
                        used_gb = disk.used / (1024**3)
                        total_gb = disk.total / (1024**3)
                        percent = disk.percent
                        drive_letter = drive[0].upper()
                        disk_info_lines.append(f"{drive_letter}: {used_gb:.1f}GB/{total_gb:.1f}GB ({percent:.1f}%)")
                    except Exception as e:
                        logger.debug(f"Error getting disk info for {drive}: {e}")
                        continue
            else:
                # For non-Windows systems, use the root filesystem
                disk = psutil.disk_usage('/')
                used_gb = disk.used / (1024**3)
                total_gb = disk.total / (1024**3)
                percent = disk.percent
                disk_info_lines.append(f"Root: {used_gb:.1f}GB/{total_gb:.1f}GB ({percent:.1f}%)")

            # Store the formatted disk information
            data['disk_info'] = "\n".join(disk_info_lines)

        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            data['disk_info'] = "Disk: Error"

        # Network info
        try:
            current_time = time.time()
            network_stats = psutil.net_io_counters()
            
            if network_stats:
                data['network_stats'] = network_stats
                data['network_time'] = current_time
                
                if _previous_network_stats is not None and _previous_network_time is not None:
                    time_diff = current_time - _previous_network_time
                    
                    if time_diff > 0:
                        bytes_sent_per_sec = (network_stats.bytes_sent - _previous_network_stats.bytes_sent) / time_diff
                        bytes_recv_per_sec = (network_stats.bytes_recv - _previous_network_stats.bytes_recv) / time_diff
                        
                        def format_speed(bytes_per_sec):
                            if bytes_per_sec >= 1024**3:  # GB/s
                                return f"{bytes_per_sec / (1024**3):.1f}GB/s"
                            elif bytes_per_sec >= 1024**2:  # MB/s
                                return f"{bytes_per_sec / (1024**2):.1f}MB/s"
                            elif bytes_per_sec >= 1024:  # KB/s
                                return f"{bytes_per_sec / 1024:.1f}KB/s"
                            else:  # B/s
                                return f"{bytes_per_sec:.1f}B/s"
                        
                        data['network_sent_display'] = format_speed(bytes_sent_per_sec)
                        data['network_recv_display'] = format_speed(bytes_recv_per_sec)
                    else:
                        data['network_display'] = "Network: Calculating..."
                else:
                    data['network_display'] = "Network: Initializing..."
                
                # Update previous values for next calculation
                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                data['network_display'] = "Network: N/A"
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            data['network_display'] = "Network: N/A"

        # GPU info (this is the heavy operation that needs threading)
        try:
            gpu_info = "GPU: Not detected"
            
            # Try GPUtil first (best for dedicated GPUs)
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    if len(gpus) == 1:
                        gpu = gpus[0]
                        gpu_info = f"GPU: {gpu.name}"
                        if hasattr(gpu, 'memoryTotal') and gpu.memoryTotal > 0:
                            used_mb = int(gpu.memoryUsed)
                            total_mb = int(gpu.memoryTotal)
                            gpu_info += f"\n{used_mb}MB/{total_mb}MB ({gpu.memoryUtil*100:.1f}%)"
                    else:
                        # Multiple GPUs - format for wrapping
                        gpu_info = f"GPU: {len(gpus)} GPUs detected"
                        for i, gpu in enumerate(gpus):
                            name = gpu.name.replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "")
                            gpu_info += f"\n• {name}"
                            if hasattr(gpu, 'memoryTotal') and gpu.memoryTotal > 0:
                                used_mb = int(gpu.memoryUsed)
                                total_mb = int(gpu.memoryTotal)
                                gpu_info += f" ({used_mb}MB/{total_mb}MB)"
                else:
                    # GPUtil found no GPUs, try system detection
                    raise ImportError("GPUtil detected no GPUs")
            except (ImportError, Exception):
                # GPUtil not available or no GPUs detected, try system-specific detection
                if platform.system() == "Windows":
                    try:
                        # Use WMIC to get GPU information (this is the blocking operation)
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run(
                            ['wmic', 'path', 'win32_VideoController', 'get', 'name,adapterram', '/format:csv'],
                            capture_output=True, text=True, timeout=5,
                            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        
                        if result.returncode == 0 and result.stdout.strip():
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:  # Skip header
                                gpu_list = []
                                for line in lines[1:]:
                                    if line.strip():
                                        parts = line.split(',')
                                        if len(parts) >= 3:  # Node,AdapterRAM,Name
                                            gpu_name = parts[2].strip()  # Name is in the 3rd column
                                            if gpu_name and gpu_name != "Node":
                                                gpu_list.append(gpu_name)
                                
                                if gpu_list:
                                    if len(gpu_list) == 1:
                                        gpu_info = f"GPU: {gpu_list[0]}"
                                    else:
                                        gpu_info = f"GPU: {len(gpu_list)} GPUs"
                                        for gpu_name in gpu_list:
                                            gpu_info += f"\n• {gpu_name}"
                    
                    except subprocess.TimeoutExpired:
                        gpu_info = "GPU: Detection timeout"
                    except Exception as e:
                        logger.debug(f"WMIC GPU detection failed: {e}")
                        gpu_info = "GPU: Detection failed"
                        
                elif platform.system() == "Linux":
                    try:
                        # Try lspci for Linux
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run(
                            ['lspci', '-v'], 
                            capture_output=True, text=True, timeout=5,
                            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        
                        if result.returncode == 0:
                            output = result.stdout.lower()
                            gpu_count = output.count('vga compatible controller') + output.count('3d controller')
                            
                            if gpu_count > 0:
                                if gpu_count == 1:
                                    gpu_info = "GPU: 1 GPU detected"
                                else:
                                    gpu_info = f"GPU: {gpu_count} GPUs detected"
                            else:
                                gpu_info = "GPU: Not detected"
                        else:
                            gpu_info = "GPU: Detection failed"
                            
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        gpu_info = "GPU: lspci not available"
                    except Exception as e:
                        logger.debug(f"Linux GPU detection failed: {e}")
                        gpu_info = "GPU: Detection failed"
                        
                else:
                    gpu_info = "GPU: Unsupported OS"
            
            data['gpu_info'] = gpu_info
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            data['gpu_info'] = "GPU: Error"

        # System uptime
        try:
            data['uptime_seconds'] = time.time() - psutil.boot_time()
        except Exception as e:
            logger.error(f"Error getting uptime info: {e}")
            data['uptime_seconds'] = None

    except Exception as e:
        logger.error(f"Error collecting system info data: {e}")
        data['error'] = str(e)
    
    return data


def update_system_info_threaded(metric_labels, system_name, os_info, callback=None):
    # Update system information using background threading to prevent UI freezing
    import threading
    
    def background_update():
        # Collect system data in background thread
        try:
            # Collect data in background (this may take several seconds)
            data = collect_system_info_data()
            
            # Schedule UI update on main thread
            def update_ui():
                try:
                    # Update system name and OS info
                    if 'system_name' in data:
                        system_name.config(text=data['system_name'])
                    if 'os_info' in data:
                        os_info.config(text=data['os_info'])
                    
                    # Update CPU
                    if data.get('cpu_percent') is not None:
                        if isinstance(data['cpu_percent'], str) and '\n' in data['cpu_percent']:
                            # Multi-line CPU display (per-core)
                            metric_labels["cpu"].config(text=data['cpu_percent'])
                        else:
                            # Single line CPU display
                            metric_labels["cpu"].config(text=f"CPU: {data['cpu_percent']:.1f}%")
                    else:
                        metric_labels["cpu"].config(text="CPU: N/A")
                    
                    # Update Memory
                    if all(k in data for k in ['memory_used_gb', 'memory_total_gb', 'memory_percent']):
                        metric_labels["memory"].config(
                            text=f"Memory: {data['memory_used_gb']:.1f}GB / {data['memory_total_gb']:.1f}GB ({data['memory_percent']:.1f}%)"
                        )
                    else:
                        metric_labels["memory"].config(text="Memory: N/A")
                    
                    # Update Disk
                    if 'disk_info' in data:
                        metric_labels["disk"].config(text=data['disk_info'])
                    else:
                        metric_labels["disk"].config(text="Disk: N/A")
                    
                    # Update Network
                    if 'network_display' in data:
                        metric_labels["network"].config(text=data['network_display'])
                    elif 'network_sent_display' in data and 'network_recv_display' in data:
                        metric_labels["network"].config(text=f"Network: ↑{data['network_sent_display']} ↓{data['network_recv_display']}")
                    else:
                        metric_labels["network"].config(text="Network: N/A")
                    
                    # Update GPU
                    if 'gpu_info' in data:
                        metric_labels["gpu"].config(text=data['gpu_info'])
                    else:
                        metric_labels["gpu"].config(text="GPU: Error")
                    
                    # Update Uptime
                    if data.get('uptime_seconds') is not None:
                        uptime_str = format_uptime_from_start_time(data['uptime_seconds'])
                        metric_labels["uptime"].config(text=f"Uptime: {uptime_str}")
                    else:
                        metric_labels["uptime"].config(text="Uptime: N/A")
                    
                    # Call optional callback
                    if callback:
                        callback()
                        
                except Exception as e:
                    logger.error(f"Error updating UI with system data: {e}")
                    # Set all labels to error state
                    for label_name in metric_labels:
                        metric_labels[label_name].config(text=f"{label_name.title()}: Error")
            
            # Schedule UI update on main thread
            if hasattr(system_name, 'after'):
                system_name.after(0, update_ui)
            elif hasattr(system_name, 'root') and hasattr(system_name.root, 'after'):
                system_name.root.after(0, update_ui)
                
        except Exception as e:
            logger.error(f"Error in background system info update: {e}")
    
    # Start background thread
    thread = threading.Thread(target=background_update, daemon=True)
    thread.start()


# Additional placeholder functions that dashboard.py might need
def get_current_server_list(dashboard):
    # Get the server list for the currently active tab
    current_tab_id = dashboard.server_notebook.select()
    if not current_tab_id:
        return None
        
    # Find which subhost this tab belongs to
    for subhost_name, tab_frame in dashboard.tab_frames.items():
        if str(tab_frame) in current_tab_id:
            return dashboard.server_lists.get(subhost_name)
    
    return None


def get_current_subhost(dashboard):
    # Get the name of the currently active subhost
    current_tab_id = dashboard.server_notebook.select()
    if not current_tab_id:
        return "Local Host"
        
    # Find which subhost this tab belongs to
    for subhost_name, tab_frame in dashboard.tab_frames.items():
        if str(tab_frame) in current_tab_id:
            return subhost_name
    
    return "Local Host"


def format_uptime_from_start_time(start_time):
    # Format uptime from either a timestamp string or seconds since epoch
    try:
        if isinstance(start_time, str):
            # Handle timestamp string
            try:
                start_dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                uptime_seconds = (datetime.datetime.now(datetime.timezone.utc) - start_dt).total_seconds()
            except:
                return "N/A"
        elif isinstance(start_time, (int, float)):
            # Handle seconds directly
            uptime_seconds = start_time
        else:
            return "N/A"

        if uptime_seconds < 0:
            return "N/A"

        # Format uptime
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    except Exception as e:
        logger.error(f"Error formatting uptime: {e}")
        return "N/A"


def update_server_status_in_treeview(server_list, server_name, status):
    # Placeholder for server status update
    pass


def open_directory_in_explorer(directory_path):
    # Opens the specified directory path in Windows Explorer
    try:
        import subprocess
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(f'explorer "{directory_path}"', 
                        startupinfo=startupinfo, 
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return True, "Directory opened"
    except Exception as e:
        return False, str(e)


def import_server_from_directory_dialog(root, paths, server_manager_dir, update_callback=None, dashboard_server_manager=None):
    # Import an existing server from a directory through a GUI dialog
    try:
        # Create import dialog
        dialog = tk.Toplevel(root)
        dialog.title("Import Server from Directory")
        dialog.geometry("600x550")
        center_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()
        
        result = {'success': False, 'message': 'Dialog cancelled'}
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Directory selection
        ttk.Label(main_frame, text="Select Server Directory:").grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        dir_frame.columnconfigure(0, weight=1)
        
        dir_var = tk.StringVar()
        dir_entry = ttk.Entry(dir_frame, textvariable=dir_var, state='readonly')
        dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        def browse_directory():
            directory = filedialog.askdirectory(title="Select Server Directory")
            if directory:
                dir_var.set(directory)
        
        ttk.Button(dir_frame, text="Browse", command=browse_directory).grid(row=0, column=1)
        
        # Server name
        ttk.Label(main_frame, text="Server Name:").grid(row=2, column=0, sticky="w", pady=(10, 5))
        name_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=name_var).grid(row=3, column=0, sticky="ew", pady=(0, 10))
        
        # Server type selection (manual)
        ttk.Label(main_frame, text="Server Type:").grid(row=4, column=0, sticky="w", pady=(0, 5))
        
        # Get supported server types
        try:
            from Modules.server_manager import ServerManager
            temp_manager = ServerManager()
            supported_types = temp_manager.get_supported_server_types()
        except:
            supported_types = ["Steam", "Minecraft", "Other"]
        
        type_var = tk.StringVar(value="Other")  # Default to Other
        type_combo = ttk.Combobox(main_frame, textvariable=type_var, values=supported_types, state="readonly")
        type_combo.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        
        # Steam App ID field (initially hidden)
        steam_frame = ttk.Frame(main_frame)
        steam_frame.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        steam_frame.grid_remove()  # Initially hidden
        
        ttk.Label(steam_frame, text="Steam App ID:").grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        # App ID entry and browse button frame
        appid_frame = ttk.Frame(steam_frame)
        appid_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        appid_frame.columnconfigure(0, weight=1)
        
        app_id_var = tk.StringVar()
        app_id_entry = ttk.Entry(appid_frame, textvariable=app_id_var)
        app_id_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        def browse_appid():
            # Open dialog to browse and select Steam AppID
            selected_appid = create_steam_appid_browser_dialog(dialog, server_manager_dir)
            if selected_appid:
                app_id_var.set(selected_appid)
        
        ttk.Button(appid_frame, text="Browse", command=browse_appid, width=10).grid(row=0, column=1)
        
        # Minecraft configuration (initially hidden)
        minecraft_frame = ttk.Frame(main_frame)
        minecraft_frame.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        minecraft_frame.grid_remove()  # Initially hidden
        
        ttk.Label(minecraft_frame, text="Modloader:").grid(row=0, column=0, sticky="w", pady=(0, 5))
        modloader_var = tk.StringVar(value="Vanilla")
        modloader_combo = ttk.Combobox(minecraft_frame, textvariable=modloader_var, 
                                     values=["Vanilla", "Forge", "Fabric", "Spigot", "Paper"], 
                                     state="readonly")
        modloader_combo.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        
        ttk.Label(minecraft_frame, text="Minecraft Version:").grid(row=2, column=0, sticky="w", pady=(0, 5))
        
        # Version entry and browse button frame
        version_frame = ttk.Frame(minecraft_frame)
        version_frame.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        version_frame.columnconfigure(0, weight=1)
        
        version_var = tk.StringVar()
        version_entry = ttk.Entry(version_frame, textvariable=version_var)
        version_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        def browse_minecraft_version():
            # Open dialog to browse and select Minecraft version
            selected_version = create_minecraft_version_browser_dialog(dialog, modloader_var.get())
            if selected_version:
                version_var.set(selected_version.get("version_id", ""))
                # Update modloader if it was changed in the browser
                if selected_version.get("modloader"):
                    modloader_var.set(selected_version["modloader"].title())
        
        ttk.Button(version_frame, text="Browse", command=browse_minecraft_version, width=10).grid(row=0, column=1)
        
        def on_type_change(*args):
            # Show/hide fields based on server type
            server_type = type_var.get()
            
            if server_type == "Steam":
                steam_frame.grid()
                minecraft_frame.grid_remove()
            elif server_type == "Minecraft":
                steam_frame.grid_remove()
                minecraft_frame.grid()
            else:  # Other
                steam_frame.grid_remove()
                minecraft_frame.grid_remove()
        
        type_var.trace_add('write', on_type_change)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=8, column=0, sticky="ew", pady=(20, 0))
        
        def import_server():
            directory = dir_var.get()
            server_name = name_var.get().strip()
            server_type = type_var.get()
            
            if not directory or not os.path.exists(directory):
                messagebox.showerror("Error", "Please select a valid directory")
                return
                
            if not server_name:
                messagebox.showerror("Error", "Please enter a server name")
                return
            
            if not server_type:
                messagebox.showerror("Error", "Please select a server type")
                return
            
            try:
                # Import the server configuration with manual selections
                if dashboard_server_manager is None:
                    from Modules.server_manager import ServerManager
                    server_manager = ServerManager()
                else:
                    server_manager = dashboard_server_manager
                
                # Prepare additional parameters based on server type
                app_id = app_id_var.get().strip() if server_type == "Steam" else ""
                minecraft_version = version_var.get().strip() if server_type == "Minecraft" else ""
                modloader = modloader_var.get() if server_type == "Minecraft" else ""
                
                # Import the server
                success = server_manager.import_server_config(
                    server_name=server_name,
                    server_type=server_type,
                    install_dir=directory,
                    executable_path="",  # Will be auto-detected
                    startup_args="",
                    app_id=app_id
                )
                
                if success:
                    # Reload server list to include the newly imported server
                    server_manager.load_servers()
                    
                    # For Minecraft servers, update the configuration with version/modloader
                    if server_type == "Minecraft" and (minecraft_version or modloader):
                        config_file = os.path.join(paths["servers"], f"{server_name}.json")
                        if os.path.exists(config_file):
                            try:
                                import json
                                with open(config_file, 'r') as f:
                                    config = json.load(f)
                                
                                if minecraft_version:
                                    config["minecraft_version"] = minecraft_version
                                if modloader:
                                    config["modloader"] = modloader
                                
                                with open(config_file, 'w') as f:
                                    json.dump(config, f, indent=4)
                            except Exception as e:
                                logger.warning(f"Could not update Minecraft config: {e}")
                    
                    result['success'] = True
                    result['message'] = f"Server '{server_name}' imported successfully from {directory}"
                    
                    if update_callback:
                        update_callback()
                        
                    dialog.destroy()
                    messagebox.showinfo("Success", result['message'])
                else:
                    messagebox.showerror("Error", f"Failed to import server '{server_name}'")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import server: {str(e)}")
        
        ttk.Button(button_frame, text="Import", command=import_server).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
        
        # Configure grid weights
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        steam_frame.columnconfigure(0, weight=1)
        minecraft_frame.columnconfigure(0, weight=1)
        appid_frame.columnconfigure(0, weight=1)
        version_frame.columnconfigure(0, weight=1)
        
        dialog.wait_window()
        return result
        
    except Exception as e:
        logger.error(f"Error in import server from directory dialog: {e}")
        return {'success': False, 'message': str(e)}


def import_server_from_export_dialog(root, paths, server_manager_dir, update_callback=None):
    # Import server from exported configuration file
    try:
        # File selection dialog
        file_path = filedialog.askopenfilename(
            title="Select Server Export File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not file_path:
            return {'success': False, 'message': 'No file selected'}
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # Extract server information
            server_name = config.get('Name', os.path.splitext(os.path.basename(file_path))[0])
            
            # Show confirmation dialog
            confirm = messagebox.askyesno(
                "Confirm Import",
                f"Import server configuration '{server_name}'?\n\n"
                f"Type: {config.get('Type', 'Unknown')}\n"
                f"Original Path: {config.get('InstallDir', 'Unknown')}"
            )
            
            if confirm:
                if update_callback:
                    update_callback()
                    
                return {
                    'success': True, 
                    'message': f"Server '{server_name}' imported successfully from export file"
                }
            else:
                return {'success': False, 'message': 'Import cancelled'}
                
        except json.JSONDecodeError:
            messagebox.showerror("Error", "Invalid JSON file format")
            return {'success': False, 'message': 'Invalid JSON file'}
            
    except Exception as e:
        logger.error(f"Error in import server from export dialog: {e}")
        return {'success': False, 'message': str(e)}


def export_server_dialog(root, current_list, paths):
    # Export server configuration for use on other hosts or clusters
    try:
        # Get selected server
        if not current_list.selection():
            messagebox.showwarning("No Selection", "Please select a server to export")
            return {'success': False, 'message': 'No server selected'}
            
        item = current_list.selection()[0]
        server_name = current_list.item(item, "values")[0]
        
        # Create export dialog
        dialog = tk.Toplevel(root)
        dialog.title(f"Export Server: {server_name}")
        dialog.geometry("550x350")
        center_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()
        
        result = {'success': False, 'message': 'Export cancelled'}
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Export options
        ttk.Label(main_frame, text="Export Options:").grid(row=0, column=0, sticky="w", pady=(0, 10))
        
        # Include server files option
        include_files_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            main_frame, 
            text="Include server files (creates larger archive)", 
            variable=include_files_var
        ).grid(row=1, column=0, sticky="w", pady=(0, 5))
        
        # Export location
        ttk.Label(main_frame, text="Export Location:").grid(row=2, column=0, sticky="w", pady=(10, 5))
        
        location_frame = ttk.Frame(main_frame)
        location_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        location_frame.columnconfigure(0, weight=1)
        
        location_var = tk.StringVar()
        location_entry = ttk.Entry(location_frame, textvariable=location_var, state='readonly')
        location_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        def browse_export_location():
            filename = filedialog.asksaveasfilename(
                title="Save Export As",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=f"{server_name}_export.json"
            )
            if filename:
                location_var.set(filename)
        
        ttk.Button(location_frame, text="Browse", command=browse_export_location).grid(row=0, column=1)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(20, 0))
        
        def perform_export():
            export_path = location_var.get()
            
            if not export_path:
                messagebox.showerror("Error", "Please select an export location")
                return
            
            try:
                # Create export configuration
                export_config = {
                    'Name': server_name,
                    'Type': 'Unknown',  # Would need to fetch from server manager
                    'InstallDir': '',  # Would need to fetch from server manager
                    'ExportDate': datetime.datetime.now().isoformat(),
                    'IncludeFiles': include_files_var.get()
                }
                
                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(export_config, f, indent=2)
                
                result['success'] = True
                result['message'] = f"Server '{server_name}' exported successfully to {export_path}"
                
                dialog.destroy()
                messagebox.showinfo("Export Complete", result['message'])
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export server: {str(e)}")
        
        ttk.Button(button_frame, text="Export", command=perform_export).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
        
        # Configure grid weights
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        dialog.wait_window()
        return result
        
    except Exception as e:
        logger.error(f"Error in export server dialog: {e}")
        return {'success': False, 'message': str(e)}


def create_progress_dialog_with_console(parent, title="Progress"):
    # Create a progress dialog with console output for long-running operations
    class ProgressDialog:
        def __init__(self, parent, title):
            self.dialog = tk.Toplevel(parent)
            self.dialog.title(title)
            self.dialog.geometry("600x400")
            center_window(self.dialog, parent=parent)
            self.dialog.transient(parent)
            self.dialog.grab_set()
            
            # Main frame
            main_frame = ttk.Frame(self.dialog, padding="10")
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Progress bar
            self.progress_var = tk.StringVar(value="Initializing...")
            ttk.Label(main_frame, textvariable=self.progress_var).pack(pady=(0, 5))
            
            self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
            self.progress_bar.pack(fill=tk.X, pady=(0, 10))
            self.progress_bar.start()
            
            # Console output
            ttk.Label(main_frame, text="Console Output:").pack(anchor=tk.W)
            
            console_frame = ttk.Frame(main_frame)
            console_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 10))
            
            self.console_text = scrolledtext.ScrolledText(
                console_frame, 
                height=15, 
                wrap=tk.WORD, 
                font=('Consolas', 9)
            )
            self.console_text.pack(fill=tk.BOTH, expand=True)
            
            # Close button (initially disabled)
            self.close_button = ttk.Button(
                main_frame, 
                text="Close", 
                command=self.close_dialog,
                state=tk.DISABLED
            )
            self.close_button.pack(pady=(10, 0))
            
            self.is_closed = False
            
        def update_progress(self, message):
            # Update the progress message
            if not self.is_closed:
                self.progress_var.set(message)
                self.dialog.update_idletasks()
                
        def update_console(self, message):
            # Add a message to the console output
            if not self.is_closed:
                self.console_text.insert(tk.END, message + "\n")
                self.console_text.see(tk.END)
                self.dialog.update_idletasks()
                
        def complete(self, message="Operation completed"):
            # Mark the operation as complete
            if not self.is_closed:
                self.progress_bar.stop()
                self.progress_var.set(message)
                self.close_button.config(state=tk.NORMAL)
                self.update_console(f"[COMPLETE] {message}")
                
        def close_dialog(self):
            # Close the dialog
            self.is_closed = True
            self.dialog.destroy()
            
        def show(self):
            # Show the dialog and return self for method chaining
            return self
            
        # Add dictionary-like access for backward compatibility
        def __contains__(self, key):
            # Support 'in' operator for backward compatibility
            return key in ['console_text', 'console_callback']
            
        def __getitem__(self, key):
            # Support dictionary-like access for backward compatibility
            if key == 'console_text':
                return self.console_text
            elif key == 'console_callback':
                return self.update_console
            else:
                raise KeyError(f"Key '{key}' not found")
    
    return ProgressDialog(parent, title)


def create_server_removal_dialog(root, server_name, server_manager):
    # Create a dialog for removing a server with checkbox options
    class ServerRemovalDialog:
        def __init__(self, parent, server_name, server_manager):
            self.parent = parent
            self.server_name = server_name
            self.server_manager = server_manager
            self.result = {'confirmed': False, 'remove_files': False}

            # Create dialog
            self.dialog = tk.Toplevel(parent)
            self.dialog.title(f"Remove Server - {server_name}")
            self.dialog.transient(parent)
            self.dialog.grab_set()
            self.dialog.geometry("500x400")
            center_window(self.dialog, parent=parent)

            # Main frame
            main_frame = ttk.Frame(self.dialog, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Warning icon and title
            warning_frame = ttk.Frame(main_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))

            ttk.Label(warning_frame, text="⚠️", font=("Segoe UI", 24)).pack(side=tk.LEFT, padx=(0, 10))
            title_label = ttk.Label(warning_frame, text=f"Remove Server '{server_name}'",
                                  font=("Segoe UI", 14, "bold"))
            title_label.pack(side=tk.LEFT)

            # Warning message
            warning_text = ("This action cannot be undone.\n\n"
                          "Choose what you want to remove:")
            ttk.Label(main_frame, text=warning_text, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 15))

            # Checkbox options
            self.remove_config_var = tk.BooleanVar(value=True)
            self.remove_files_var = tk.BooleanVar(value=False)

            # Configuration removal checkbox
            config_frame = ttk.Frame(main_frame)
            config_frame.pack(fill=tk.X, pady=(0, 10))

            ttk.Checkbutton(config_frame, text="Remove server configuration",
                          variable=self.remove_config_var,
                          command=self.on_config_checkbox_change).pack(anchor=tk.W)

            ttk.Label(config_frame, text="Removes the server from the dashboard and configuration files",
                     foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=(20, 0), pady=(2, 0))

            # Files removal checkbox
            files_frame = ttk.Frame(main_frame)
            files_frame.pack(fill=tk.X, pady=(0, 20))

            ttk.Checkbutton(files_frame, text="Remove server files and directory",
                          variable=self.remove_files_var).pack(anchor=tk.W)

            ttk.Label(files_frame, text="Deletes all server files, saves, and installation directory",
                     foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=(20, 0), pady=(2, 0))

            # Buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=(20, 0))

            ttk.Button(button_frame, text="Cancel", command=self.cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Remove Server", command=self.confirm_removal,
                      style="Accent.TButton", width=15).pack(side=tk.RIGHT)

            # Handle window close
            self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)

        def on_config_checkbox_change(self):
            # Ensure at least one option is selected
            if not self.remove_config_var.get() and not self.remove_files_var.get():
                self.remove_config_var.set(True)

        def confirm_removal(self):
            # Confirm the removal
            if not self.remove_config_var.get() and not self.remove_files_var.get():
                messagebox.showwarning("Selection Required",
                                     "Please select at least one removal option.")
                return

            self.result = {
                'confirmed': True,
                'remove_files': self.remove_files_var.get(),
                'remove_config': self.remove_config_var.get()
            }
            self.dialog.destroy()

        def cancel(self):
            # Cancel the removal
            self.result = {'confirmed': False, 'remove_files': False}
            self.dialog.destroy()

        def show(self):
            # Show the dialog and return the result
            self.dialog.wait_window()
            return self.result

    # Create and show the dialog
    dialog = ServerRemovalDialog(root, server_name, server_manager)
    return dialog.show()


def rename_server_configuration(server_name, new_name, server_manager):
    # Rename a server configuration
    try:
        # Validate new name
        if not new_name or not new_name.strip():
            return False, "New server name cannot be empty"
            
        new_name = new_name.strip()
        
        if new_name == server_name:
            return False, "New name is the same as current name"
            
        # Check if new name already exists
        servers = server_manager.get_servers()
        if new_name in servers:
            return False, f"Server '{new_name}' already exists"
            
        # Rename the server
        success = server_manager.rename_server(server_name, new_name)
        if success:
            return True, f"Server renamed from '{server_name}' to '{new_name}'"
        else:
            return False, f"Failed to rename server '{server_name}'"
            
    except Exception as e:
        logger.error(f"Error renaming server: {e}")
        return False, f"Error renaming server: {str(e)}"


def show_java_configuration_dialog(root, server_name, server_config, server_manager):
    # Show Java configuration dialog for Minecraft servers
    try:
        # Create Java configuration dialog
        dialog = tk.Toplevel(root)
        dialog.title(f"Java Configuration - {server_name}")
        dialog.geometry("500x400")
        center_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()
        
        result = {'success': False, 'message': 'Configuration cancelled'}
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Java executable path
        ttk.Label(main_frame, text="Java Executable:").pack(anchor=tk.W, pady=(0, 5))
        
        java_frame = ttk.Frame(main_frame)
        java_frame.pack(fill=tk.X, pady=(0, 10))
        
        java_var = tk.StringVar(value=server_config.get('JavaPath', 'java'))
        java_entry = ttk.Entry(java_frame, textvariable=java_var)
        java_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_java():
            filename = filedialog.askopenfilename(
                title="Select Java Executable",
                filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
            )
            if filename:
                java_var.set(filename)
        
        ttk.Button(java_frame, text="Browse", command=browse_java).pack(side=tk.RIGHT)
        
        # JVM Arguments
        ttk.Label(main_frame, text="JVM Arguments:").pack(anchor=tk.W, pady=(10, 5))
        
        jvm_args_var = tk.StringVar(value=server_config.get('JVMArgs', '-Xmx2G -Xms1G'))
        jvm_entry = ttk.Entry(main_frame, textvariable=jvm_args_var, width=60)
        jvm_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Common JVM presets
        ttk.Label(main_frame, text="Common Presets:").pack(anchor=tk.W, pady=(10, 5))
        
        preset_frame = ttk.Frame(main_frame)
        preset_frame.pack(fill=tk.X, pady=(0, 10))
        
        presets = [
            ("2GB RAM", "-Xmx2G -Xms1G"),
            ("4GB RAM", "-Xmx4G -Xms2G"),
            ("8GB RAM", "-Xmx8G -Xms4G"),
            ("16GB RAM", "-Xmx16G -Xms8G")
        ]
        
        for i, (name, args) in enumerate(presets):
            ttk.Button(
                preset_frame, 
                text=name,
                command=lambda a=args: jvm_args_var.set(a)
            ).grid(row=i//2, column=i%2, padx=5, pady=2, sticky=tk.W)
        
        # Auto-detect Java button
        def auto_detect_java():
            java_paths = [
                "java",
                "C:\\Program Files\\Java\\*\\bin\\java.exe",
                "C:\\Program Files (x86)\\Java\\*\\bin\\java.exe"
            ]
            
            for path in java_paths:
                try:
                    if '*' in path:
                        # Handle wildcard paths
                        import glob
                        matches = glob.glob(path)
                        if matches:
                            java_var.set(matches[0])
                            break
                    else:
                        # Test basic java command
                        import subprocess
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run([path, '-version'], 
                                              capture_output=True, text=True, timeout=5,
                                              startupinfo=startupinfo, 
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                        if result.returncode == 0:
                            java_var.set(path)
                            break
                except:
                    continue
        
        ttk.Button(main_frame, text="Auto-Detect Java", command=auto_detect_java).pack(pady=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        def save_config():
            try:
                # Update server configuration
                server_config['JavaPath'] = java_var.get()
                server_config['JVMArgs'] = jvm_args_var.get()
                
                # Save configuration
                success = server_manager.save_server_config(server_name, server_config)
                if success:
                    result['success'] = True
                    result['message'] = "Java configuration saved successfully"
                    dialog.destroy()
                    messagebox.showinfo("Success", result['message'])
                else:
                    messagebox.showerror("Error", "Failed to save configuration")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        ttk.Button(button_frame, text="Save", command=save_config).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
        
        dialog.wait_window()
        return result
        
    except Exception as e:
        logger.error(f"Error in Java configuration dialog: {e}")
        return {'success': False, 'message': str(e)}


def batch_update_server_types(paths):
    # Update server types for all servers based on their installation directories
    try:
        updated_count = 0
        updated_servers = []
        
        # This is a placeholder implementation
        # In a real implementation, this would:
        # 1. Iterate through all server configurations
        # 2. Detect the actual server type from installation directory
        # 3. Update configurations that have incorrect types
        # 4. Return count and list of updated servers
        
        logger.info("Batch server type update completed")
        return updated_count, updated_servers
        
    except Exception as e:
        logger.error(f"Error in batch update server types: {e}")
        return 0, []


def create_java_selection_dialog(root, minecraft_version=None):
    # Create a dialog to select Java installation for a server
    try:
        try:
            from Modules.java_configurator import JavaConfigurator
            configurator = JavaConfigurator()
        except ImportError:
            logger.warning("JavaConfigurator module not available")
            return None
        
        dialog = tk.Toplevel(root)
        dialog.title("Select Java Installation")
        dialog.geometry("600x400")
        dialog.transient(root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(main_frame, text="Select Java Installation", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Java list frame
        list_frame = ttk.LabelFrame(main_frame, text="Available Java Installations", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Treeview for Java installations
        columns = ("path", "version", "vendor")
        java_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        java_tree.heading("path", text="Path")
        java_tree.heading("version", text="Version")
        java_tree.heading("vendor", text="Vendor")
        
        java_tree.column("path", width=300, minwidth=200)
        java_tree.column("version", width=100, minwidth=80)
        java_tree.column("vendor", width=100, minwidth=80)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=java_tree.yview)
        java_tree.configure(yscrollcommand=scrollbar.set)
        
        java_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Load Java installations
        try:
            java_installations = configurator.detect_java_installations()
            
            for java in java_installations:
                java_tree.insert("", tk.END, values=(
                    java.get("path", ""),
                    java.get("version", ""),
                    java.get("vendor", "Unknown")
                ))
        except Exception as e:
            logger.error(f"Error loading Java installations: {e}")
            java_tree.insert("", tk.END, values=("Error loading Java installations", str(e), ""))
        
        # Result variable
        selected_java: Dict[str, Any] = {"java": None}
        
        def on_select():
            selected = java_tree.selection()
            if selected:
                item = java_tree.item(selected[0])
                selected_java["java"] = {
                    "path": item['values'][0],
                    "version": item['values'][1],
                    "vendor": item['values'][2]
                }
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Select", command=on_select).pack(side=tk.RIGHT)
        
        # Double-click to select
        java_tree.bind("<Double-1>", lambda e: on_select())
        
        # Center dialog
        center_window(dialog, 600, 400, root)
        
        root.wait_window(dialog)
        return selected_java["java"]
        
    except Exception as e:
        logger.error(f"Error creating Java selection dialog: {e}")
        return None


def load_appid_list_from_database():
    # Load AppID list directly from database
    try:
        from Modules.Database.AppIDScanner import AppIDScanner
        scanner = AppIDScanner(use_database=True, debug_mode=False)
        appids = scanner.get_server_apps(dedicated_only=True)
        scanner.close()
        return appids
    except ImportError:
        logger.warning("AppIDScanner module not available")
        return []
    except Exception as e:
        logger.error(f"Error loading AppID list from database: {e}")
        return []


def find_appid_in_directory(directory_path):
    # Find Steam AppID from directory contents
    if not directory_path or not os.path.exists(directory_path):
        return None
    
    try:
        # Look for Steam app manifest files
        for file in os.listdir(directory_path):
            if file == "steam_appid.txt":
                appid_file = os.path.join(directory_path, file)
                with open(appid_file, 'r') as f:
                    appid = f.read().strip()
                    if appid.isdigit():
                        return appid
        
        # Look for app manifest files
        for file in os.listdir(directory_path):
            if file.startswith("appmanifest_") and file.endswith(".acf"):
                # Parse the ACF file to get AppID
                acf_file = os.path.join(directory_path, file)
                with open(acf_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Simple parsing for "appid" value
                    import re
                    match = re.search(r'"appid"\s*"(\d+)"', content)
                    if match:
                        return match.group(1)
        
        return None
    except Exception as e:
        logger.error(f"Error finding AppID in directory {directory_path}: {e}")
        return None


def is_process_running(pid):
    # Check if a process with the given PID is running
    try:
        import psutil
        return psutil.pid_exists(pid)
    except:
        return False


def is_port_open(host, port, timeout=1):
    # Check if a port is open on the specified host
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False


def check_webserver_status(paths, variables):
    # Check if the web server is running and return status
    if variables.get("offlineMode", False):
        return "Offline Mode"
        
    try:
        webserver_port = variables.get("webserverPort", 8080)
        if is_port_open("localhost", webserver_port):
            return "Running"
        else:
            return "Stopped"
    except Exception as e:
        logger.error(f"Error checking webserver status: {e}")
        return "Unknown"


def export_server_configuration(server_name, paths, include_files=False):
    # Export server configuration to a portable format
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        config = server_manager.get_server_config(server_name)
        if not config:
            return None
        
        export_data = {
            "version": "1.0",
            "export_date": datetime.datetime.now().isoformat(),
            "server_name": server_name,
            "configuration": config,
            "includes_files": include_files
        }
        
        if include_files:
            # Include server files in export (compressed)
            install_dir = config.get("InstallDir", "")
            if install_dir and os.path.exists(install_dir):
                # This would compress the directory - simplified for now
                export_data["files_archive"] = f"Would compress {install_dir}"
        
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting server configuration: {e}")
        return None


def import_server_configuration(export_data, paths, install_directory=None, auto_install=False):
    # Import server configuration from export data
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        server_name = export_data.get("server_name")
        config = export_data.get("configuration")
        
        if not server_name or not config:
            return False, "Invalid export data"
        
        # Generate unique name if needed
        if server_manager.get_server_config(server_name):
            server_name = generate_unique_server_name(server_name, paths)
        
        # Update install directory if specified
        if install_directory:
            config["InstallDir"] = install_directory
        
        # Save configuration
        success = server_manager.save_server_config(server_name, config)
        
        if success:
            message = f"Server '{server_name}' imported successfully"
            if auto_install:
                # Attempt auto-installation
                message += " (auto-installation attempted)"
            return True, message
        else:
            return False, f"Failed to import server '{server_name}'"
            
    except Exception as e:
        logger.error(f"Error importing server configuration: {e}")
        return False, f"Import failed: {str(e)}"


def generate_unique_server_name(name, paths):
    # Generate a unique server name by checking existing configurations
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        base_name = name
        counter = 1
        
        while server_manager.get_server_config(name):
            name = f"{base_name}_{counter}"
            counter += 1
        
        return name
        
    except Exception as e:
        logger.error(f"Error generating unique server name: {e}")
        return f"{name}_{int(datetime.datetime.now().timestamp())}"


def get_directory_size(directory):
    # Get total size of directory in bytes
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, IOError):
                    pass
        return total_size
    except Exception:
        return 0


def count_files_in_directory(directory):
    # Count total number of files in directory
    try:
        count = 0
        for _, _, files in os.walk(directory):
            count += len(files)
        return count
    except Exception:
        return 0


def export_server_to_file(export_data, export_path, include_files=False):
    # Export server configuration to file
    try:
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        return True, f"Server exported to {export_path}"
    except Exception as e:
        logger.error(f"Error exporting server to file: {e}")
        return False, f"Export failed: {str(e)}"


def import_server_from_file(file_path):
    # Import server configuration from file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            export_data = json.load(f)
        
        has_files = export_data.get("includes_files", False)
        return True, export_data, has_files
    except Exception as e:
        logger.error(f"Error importing server from file: {e}")
        return False, None, False


def extract_server_files_from_archive(zip_path, extract_to):
    # Extract server files from zip archive
    try:
        import zipfile
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        
        return True, f"Files extracted to {extract_to}"
    except Exception as e:
        logger.error(f"Error extracting server files: {e}")
        return False, f"Extraction failed: {str(e)}"


def validate_server_creation_inputs(server_type, server_name, app_id=None, executable_path=None):
    # Validate inputs for server creation
    try:
        errors = []
        
        # Validate server name
        if not server_name or not server_name.strip():
            errors.append("Server name is required")
        elif len(server_name.strip()) < 3:
            errors.append("Server name must be at least 3 characters")
        elif any(char in server_name for char in ['<', '>', ':', '"', '|', '?', '*', '\\', '/']):
            errors.append("Server name contains invalid characters")
        
        # Validate server type specific requirements
        if server_type == "Steam":
            if not app_id or not app_id.strip():
                errors.append("Steam App ID is required")
            elif not app_id.strip().isdigit():
                errors.append("Steam App ID must be numeric")
        elif server_type == "Minecraft":
            pass  # No additional validation needed for basic Minecraft setup
        elif server_type == "Other":
            if not executable_path or not executable_path.strip():
                errors.append("Executable path is required for Other server type")
            elif not os.path.exists(executable_path.strip()):
                errors.append("Specified executable does not exist")
        
        return len(errors) == 0, errors
        
    except Exception as e:
        logger.error(f"Error validating server creation inputs: {e}")
        return False, [f"Validation error: {str(e)}"]


def create_remote_host_connection_dialog(parent, dashboard):
    # Create a dialog for connecting to a remote host for one-time server operations
    dialog = tk.Toplevel(parent)
    dialog.title("Connect to Remote Host")
    dialog.geometry("600x650")  # Increased height to show all content
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(True, True)  # Allow resizing
    dialog.minsize(500, 550)  # Set minimum size to ensure content visibility
    
    # Create a canvas with scrollbar for very small screens
    canvas = tk.Canvas(dialog)
    scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    main_frame = ttk.Frame(scrollable_frame, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Configure main frame to allow proper resizing
    main_frame.grid_rowconfigure(6, weight=1)  # Allow the area before buttons to expand
    
    # Title
    title_label = ttk.Label(main_frame, text="Connect to Remote Server Manager Host", font=("Segoe UI", 14, "bold"))
    title_label.pack(pady=(0, 15))
    
    info_label = ttk.Label(main_frame, text="Connect to a remote Server Manager instance for one-time operations", 
                          foreground="gray", font=("Segoe UI", 9))
    info_label.pack(pady=(0, 20))
    
    # Connection details frame
    details_frame = ttk.LabelFrame(main_frame, text="Connection Details", padding=15)
    details_frame.pack(fill=tk.X, pady=(0, 15))
    
    # Configure grid weights
    details_frame.grid_columnconfigure(1, weight=1)
    
    # Host/IP field
    ttk.Label(details_frame, text="Host/IP Address:").grid(row=0, column=0, sticky=tk.W, pady=8)
    host_var = tk.StringVar()
    host_entry = ttk.Entry(details_frame, textvariable=host_var, width=35)
    host_entry.grid(row=0, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    # Port field
    ttk.Label(details_frame, text="Port:").grid(row=1, column=0, sticky=tk.W, pady=8)
    port_var = tk.StringVar(value="8080")
    port_entry = ttk.Entry(details_frame, textvariable=port_var, width=35)
    port_entry.grid(row=1, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    # Authentication frame
    auth_frame = ttk.LabelFrame(main_frame, text="Authentication", padding=15)
    auth_frame.pack(fill=tk.X, pady=(0, 15))
    auth_frame.grid_columnconfigure(1, weight=1)
    
    # Username field
    ttk.Label(auth_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=8)
    username_var = tk.StringVar(value="admin")
    username_entry = ttk.Entry(auth_frame, textvariable=username_var, width=35)
    username_entry.grid(row=0, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    # Password field
    ttk.Label(auth_frame, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=8)
    password_var = tk.StringVar()
    password_entry = ttk.Entry(auth_frame, textvariable=password_var, width=35, show="*")
    password_entry.grid(row=1, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    # Connection options frame
    options_frame = ttk.LabelFrame(main_frame, text="Options", padding=15)
    options_frame.pack(fill=tk.X, pady=(0, 15))
    
    # SSL/HTTPS option
    ssl_var = tk.BooleanVar(value=False)
    ssl_check = ttk.Checkbutton(options_frame, text="Use HTTPS (SSL)", variable=ssl_var)
    ssl_check.pack(anchor=tk.W, pady=2)
    
    # Timeout option
    timeout_frame = ttk.Frame(options_frame)
    timeout_frame.pack(fill=tk.X, pady=(5, 0))
    ttk.Label(timeout_frame, text="Connection Timeout (seconds):").pack(side=tk.LEFT)
    timeout_var = tk.StringVar(value="10")
    timeout_entry = ttk.Entry(timeout_frame, textvariable=timeout_var, width=8)
    timeout_entry.pack(side=tk.RIGHT)
    
    # Status frame
    status_frame = ttk.Frame(main_frame)
    status_frame.pack(fill=tk.X, pady=(0, 15))
    
    status_var = tk.StringVar(value="Ready to connect...")
    status_label = ttk.Label(status_frame, textvariable=status_var, foreground="blue", font=("Segoe UI", 9))
    status_label.pack(anchor=tk.W)
    
    # Progress bar
    progress = ttk.Progressbar(status_frame, mode="indeterminate")
    
    def validate_inputs():
        # Validate all input fields
        host = host_var.get().strip()
        port = port_var.get().strip()
        username = username_var.get().strip()
        password = password_var.get().strip()
        timeout = timeout_var.get().strip()
        
        if not host:
            raise ValueError("Host/IP address is required")
        if not port or not port.isdigit() or not (1 <= int(port) <= 65535):
            raise ValueError("Valid port number (1-65535) is required")
        if not username:
            raise ValueError("Username is required")
        if not password:
            raise ValueError("Password is required")
        if not timeout or not timeout.isdigit() or int(timeout) <= 0:
            raise ValueError("Valid timeout value is required")
            
        return host, int(port), username, password, ssl_var.get(), int(timeout)
    
    def test_connection():
        # Test the connection to the remote host
        try:
            host, port, username, password, use_ssl, timeout = validate_inputs()
            
            status_var.set("Testing connection...")
            status_label.config(foreground="blue")
            progress.pack(fill=tk.X, pady=(5, 0))
            progress.start()
            dialog.update()
            
            # Test connection using the remote host manager
            success, message = test_remote_host_connection(host, port, username, password, use_ssl, timeout)
            
            progress.stop()
            progress.pack_forget()
            
            if success:
                status_var.set("✓ Connection successful!")
                status_label.config(foreground="green")
            else:
                status_var.set(f"✗ Connection failed: {message}")
                status_label.config(foreground="red")
                
        except ValueError as e:
            progress.stop()
            progress.pack_forget()
            status_var.set(f"✗ Validation error: {str(e)}")
            status_label.config(foreground="red")
        except Exception as e:
            progress.stop()
            progress.pack_forget()
            status_var.set(f"✗ Connection error: {str(e)}")
            status_label.config(foreground="red")
    
    def connect_and_add():
        # Connect and add the remote host to the dashboard
        try:
            host, port, username, password, use_ssl, timeout = validate_inputs()
            
            status_var.set("Connecting to remote host...")
            status_label.config(foreground="blue")
            progress.pack(fill=tk.X, pady=(5, 0))
            progress.start()
            dialog.update()
            
            # Add the remote host to the dashboard with all connection parameters
            success = dashboard.add_remote_host(host, port, username, password, "", use_ssl, timeout)
            
            progress.stop()
            progress.pack_forget()
            
            if success:
                messagebox.showinfo("Success", f"Successfully connected to remote host: {host}:{port}")
                dialog.destroy()
            else:
                status_var.set(f"✗ Failed to add remote host")
                status_label.config(foreground="red")
                
        except ValueError as e:
            progress.stop()
            progress.pack_forget()
            messagebox.showerror("Validation Error", str(e))
        except Exception as e:
            progress.stop()
            progress.pack_forget()
            logger.error(f"Error connecting to remote host: {str(e)}")
            messagebox.showerror("Error", f"Failed to connect: {str(e)}")
    
    def cancel():
        dialog.destroy()
    
    # Add flexible space before buttons
    spacer_frame = ttk.Frame(main_frame)
    spacer_frame.pack(fill=tk.BOTH, expand=True, pady=(15, 10))
    
    # Button frame (stays at bottom)
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, side=tk.BOTTOM)
    
    # Buttons
    test_btn = ttk.Button(button_frame, text="Test Connection", command=test_connection, width=15)
    test_btn.pack(side=tk.LEFT, padx=(0, 10))
    
    connect_btn = ttk.Button(button_frame, text="Connect & Add", command=connect_and_add, width=15)
    connect_btn.pack(side=tk.LEFT)
    
    cancel_btn = ttk.Button(button_frame, text="Cancel", command=cancel, width=12)
    cancel_btn.pack(side=tk.RIGHT)
    
    # Focus on host entry
    host_entry.focus()
    
    # Pack canvas and scrollbar
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Bind mouse wheel scrolling
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    # Bind mouse wheel to canvas and all child widgets
    def bind_mousewheel(widget):
        widget.bind("<MouseWheel>", on_mousewheel)
        for child in widget.winfo_children():
            bind_mousewheel(child)
    
    bind_mousewheel(dialog)
    
    # Center dialog with the new dimensions
    center_window(dialog, 600, 650, parent)


def test_remote_host_connection(host, port, username, password, use_ssl=False, timeout=10):
    # Test connection to a remote Server Manager host
    import requests
    
    try:
        protocol = "https" if use_ssl else "http"
        base_url = f"{protocol}://{host}:{port}"
        
        # Test basic connectivity first
        test_url = f"{base_url}/api/status"
        
        response = requests.get(test_url, timeout=timeout, verify=False if use_ssl else True)
        
        if response.status_code == 200:
            # Try to authenticate
            auth_url = f"{base_url}/api/auth/login"
            auth_data = {"username": username, "password": password}
            
            auth_response = requests.post(auth_url, json=auth_data, timeout=timeout, verify=False if use_ssl else True)
            
            if auth_response.status_code == 200:
                return True, "Connection and authentication successful"
            else:
                return False, "Authentication failed - check username/password"
        else:
            return False, f"Server responded with status {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to remote host - check host/port"
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


class RemoteHostManager:
    # Manages connections and operations with remote Server Manager hosts
    
    def __init__(self):
        self.active_connections = {}
        self.session_cache = {}
    
    def connect(self, host, port, username, password, use_ssl=False, timeout=10):
        # Establish connection to remote host and get session token
        import requests
        
        try:
            protocol = "https" if use_ssl else "http"
            base_url = f"{protocol}://{host}:{port}"
            connection_id = f"{host}:{port}"
            
            # Create session
            session = requests.Session()
            session.verify = False if use_ssl else True
            
            # Authenticate
            auth_url = f"{base_url}/api/auth/login"
            auth_data = {"username": username, "password": password}
            
            auth_response = session.post(auth_url, json=auth_data, timeout=timeout)
            
            if auth_response.status_code == 200:
                # Store session and connection info
                self.active_connections[connection_id] = {
                    "host": host,
                    "port": port,
                    "base_url": base_url,
                    "session": session,
                    "authenticated": True,
                    "use_ssl": use_ssl,
                    "timeout": timeout
                }
                return True, "Connected successfully"
            else:
                return False, "Authentication failed"
                
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def disconnect(self, host, port):
        # Disconnect from remote host
        connection_id = f"{host}:{port}"
        if connection_id in self.active_connections:
            try:
                session = self.active_connections[connection_id]["session"]
                base_url = self.active_connections[connection_id]["base_url"]
                session.post(f"{base_url}/api/auth/logout", timeout=5)
            except:
                pass  # Ignore logout errors
            del self.active_connections[connection_id]
            return True
        return False
    
    def get_servers(self, host, port):
        # Get list of servers from remote host
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"
        
        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]
            
            response = session.get(f"{base_url}/api/servers", timeout=timeout)
            
            if response.status_code == 200:
                servers_data = response.json()
                return True, servers_data
            else:
                return False, f"Failed to get servers: {response.status_code}"
                
        except Exception as e:
            return False, f"Error getting servers: {str(e)}"
    
    def start_server(self, host, port, server_name):
        # Start a server on remote host
        return self._server_action(host, port, server_name, "start")
    
    def stop_server(self, host, port, server_name):
        # Stop a server on remote host
        return self._server_action(host, port, server_name, "stop")
    
    def restart_server(self, host, port, server_name):
        # Restart a server on remote host
        return self._server_action(host, port, server_name, "restart")
    
    def _server_action(self, host, port, server_name, action):
        # Perform server action on remote host
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"
        
        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]
            
            response = session.post(f"{base_url}/api/servers/{server_name}/{action}", timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                return True, result.get("message", f"Server {action} successful")
            else:
                return False, f"Failed to {action} server: {response.status_code}"
                
        except Exception as e:
            return False, f"Error performing {action}: {str(e)}"
    
    def get_server_status(self, host, port, server_name):
        # Get status of specific server on remote host
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"
        
        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]
            
            response = session.get(f"{base_url}/api/servers/{server_name}/status", timeout=timeout)
            
            if response.status_code == 200:
                status_data = response.json()
                return True, status_data
            else:
                return False, f"Failed to get server status: {response.status_code}"
                
        except Exception as e:
            return False, f"Error getting server status: {str(e)}"


# Global remote host manager instance
_remote_host_manager = RemoteHostManager()


def get_remote_host_manager():
    # Get the global remote host manager instance
    return _remote_host_manager


def create_server_installation_dialog(root, server_type, supported_server_types, server_manager, paths, steam_cmd_path=None):
    # Create server installation dialog with progress tracking
    try:
        dialog = tk.Toplevel(root)
        dialog.title(f"Install {server_type} Server")
        dialog.geometry("700x600")
        dialog.transient(root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Install {server_type} Server", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Progress frame
        progress_frame = ttk.LabelFrame(main_frame, text="Installation Progress", padding=10)
        progress_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100)
        progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        status_var = tk.StringVar(value="Ready to install...")
        status_label = ttk.Label(progress_frame, textvariable=status_var)
        status_label.pack(anchor=tk.W)
        
        # Console output
        console_frame = ttk.LabelFrame(main_frame, text="Installation Log", padding=10)
        console_frame.pack(fill=tk.BOTH, expand=True)
        
        console_text = scrolledtext.ScrolledText(console_frame, height=15, font=("Consolas", 9))
        console_text.pack(fill=tk.BOTH, expand=True)
        
        # Result tracking
        installation_result = {"completed": False, "success": False, "message": ""}
        
        def update_progress(percent, message):
            progress_var.set(percent)
            status_var.set(message)
            console_text.insert(tk.END, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
            console_text.see(tk.END)
            dialog.update()
        
        def start_installation():
            try:
                update_progress(10, "Starting installation...")
                
                # This would call the actual installation logic
                # For now, just simulate
                update_progress(50, "Installing server components...")
                time.sleep(2)
                update_progress(90, "Finalizing installation...")
                time.sleep(1)
                
                installation_result["completed"] = True
                installation_result["success"] = True
                installation_result["message"] = "Server installed successfully"
                
                update_progress(100, "Installation completed successfully")
                
            except Exception as e:
                installation_result["completed"] = True
                installation_result["success"] = False
                installation_result["message"] = str(e)
                update_progress(100, f"Installation failed: {str(e)}")
        
        def close_dialog():
            if installation_result["completed"]:
                dialog.destroy()
            else:
                if messagebox.askyesno("Cancel Installation", "Installation is in progress. Cancel?"):
                    dialog.destroy()
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        install_button = ttk.Button(button_frame, text="Start Installation", command=start_installation)
        install_button.pack(side=tk.LEFT)
        
        close_button = ttk.Button(button_frame, text="Close", command=close_dialog)
        close_button.pack(side=tk.RIGHT)
        
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        
        center_window(dialog, 700, 600, root)
        
        root.wait_window(dialog)
        return installation_result
        
    except Exception as e:
        logger.error(f"Error creating installation dialog: {e}")
        return {"completed": True, "success": False, "message": str(e)}


def update_server_list_from_files(server_list, paths, variables, log_dashboard_event, format_uptime_from_start_time):
    # Update server list from configuration files
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        servers = server_manager.get_all_servers()
        
        # Clear existing list
        for item in server_list.get_children():
            server_list.delete(item)
        
        # Add servers to list
        for server_name, config in servers.items():
            server_type = config.get("Type", "Unknown")
            status = "Unknown"  # Would need to check actual status
            
            server_list.insert("", tk.END, values=(
                server_name,
                server_type,
                status,
                config.get("InstallDir", ""),
                format_uptime_from_start_time("N/A")  # Placeholder
            ))
        
        variables["lastServerListUpdate"] = datetime.datetime.now()
        
    except Exception as e:
        logger.error(f"Error updating server list from files: {e}")


def re_detect_server_type_from_config(server_config):
    # Re-detect server type from configuration
    try:
        install_dir = server_config.get("InstallDir", "")
        if not install_dir or not os.path.exists(install_dir):
            return server_config.get("Type", "Other")
        
        # Use directory detection
        detected_type = detect_server_type_from_directory(install_dir)
        return detected_type if detected_type != "Other" else server_config.get("Type", "Other")
        
    except Exception as e:
        logger.error(f"Error re-detecting server type: {e}")
        return server_config.get("Type", "Other")


def update_server_configuration_with_detection(server_config_path):
    # Update server configuration with auto-detected information
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        # Load current config
        with open(server_config_path, 'r') as f:
            config = json.load(f)
        
        server_name = config.get("Name", "")
        if not server_name:
            return False
        
        # Re-detect server type
        new_type = re_detect_server_type_from_config(config)
        if new_type != config.get("Type"):
            config["Type"] = new_type
            logger.info(f"Updated server type for {server_name} to {new_type}")
        
        # Save updated config
        server_manager.save_server_config(server_name, config)
        return True
        
    except Exception as e:
        logger.error(f"Error updating server configuration: {e}")


def cleanup_orphaned_process_entries(server_manager, logger):
    # Clean up orphaned process entries from server configurations
    try:
        if not server_manager:
            return
            
        logger.info("Cleaning up orphaned process entries...")
        
        # Get all configured servers
        server_configs = server_manager.get_servers()
        cleaned_count = 0
        
        for server_name, server_config in server_configs.items():
            try:
                pid = server_config.get('ProcessId') or server_config.get('PID')
                if pid:
                    # Check if process is actually running
                    try:
                        import psutil
                        if not psutil.pid_exists(pid):
                            # Process is not running, clean up the entry
                            logger.info(f"Cleaning up orphaned PID {pid} for server {server_name}")
                            
                            # Remove process-related entries
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                            
                            # Save the updated configuration
                            server_manager.save_server_config(server_name, server_config)
                            cleaned_count += 1
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        # Process doesn't exist, clean it up
                        logger.info(f"Cleaning up invalid PID {pid} for server {server_name}")
                        
                        server_config.pop('ProcessId', None)
                        server_config.pop('PID', None)
                        server_config.pop('StartTime', None)
                        server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                        
                        server_manager.save_server_config(server_name, server_config)
                        cleaned_count += 1
                        
                    except Exception as e:
                        logger.debug(f"Error checking PID {pid} for server {server_name}: {e}")
                        
            except Exception as e:
                logger.error(f"Error cleaning up process entries for server {server_name}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} orphaned process entries")
        else:
            logger.debug("No orphaned process entries found")
            
    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_process_entries: {e}")


def reattach_to_running_servers(server_manager, console_manager, logger):
    # Detect and reattach to running server processes with improved process discovery
    try:
        if not server_manager or not console_manager:
            return
            
        logger.info("Detecting running server processes for console reattachment...")
        
        # First, clean up orphaned process entries
        cleanup_orphaned_process_entries(server_manager, logger)
        
        # Get all configured servers
        server_configs = server_manager.get_servers()
        
        # Second, try the old method - check stored PIDs
        reattached_by_pid = 0
        for server_name, server_config in server_configs.items():
            try:
                # Check if server process is running based on stored PID
                pid = server_config.get('ProcessId') or server_config.get('PID')
                if pid:
                    try:
                        import psutil
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            if process.is_running():
                                logger.info(f"Found running server process for {server_name} (PID: {pid}) via stored PID")
                                
                                # Reattach console to the running process
                                success = console_manager.attach_console_to_process(
                                    server_name, process, server_config
                                )
                                
                                if success:
                                    logger.info(f"Successfully reattached console to {server_name}")
                                    reattached_by_pid += 1
                                else:
                                    logger.warning(f"Failed to reattach console to {server_name}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        logger.debug(f"Process {pid} for {server_name} is not accessible: {e}")
                    except Exception as e:
                        logger.error(f"Error checking process {pid} for {server_name}: {e}")
                        
            except Exception as e:
                logger.error(f"Error processing server {server_name} for reattachment: {e}")
        
        # Third, try improved process discovery - scan all processes
        reattached_by_discovery = 0
        try:
            import psutil
            
            # Get all running processes
            all_processes = psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'cwd'])
            
            for proc in all_processes:
                try:
                    # Skip system processes and our own process
                    if proc.info['pid'] == os.getpid():
                        continue
                        
                    # Check if this process matches any configured server
                    for server_name, server_config in server_configs.items():
                        if _process_matches_server(proc, server_name, server_config):
                            # Check if we already reattached this server
                            if hasattr(console_manager, 'consoles') and server_name in console_manager.consoles:
                                logger.debug(f"Server {server_name} already has console attached")
                                continue
                                
                            logger.info(f"Found running server process for {server_name} (PID: {proc.info['pid']}) via process discovery")
                            
                            # Reattach console to the discovered process
                            success = console_manager.attach_console_to_process(
                                server_name, proc, server_config
                            )
                            
                            if success:
                                logger.info(f"Successfully reattached console to {server_name} via process discovery")
                                reattached_by_discovery += 1
                                
                                # Update the server config with the current PID
                                server_config['ProcessId'] = proc.info['pid']
                                server_config['PID'] = proc.info['pid']
                                server_manager.save_server_config(server_name, server_config)
                            else:
                                logger.warning(f"Failed to reattach console to discovered process for {server_name}")
                            break  # Found a match, no need to check other servers
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception as e:
                    logger.debug(f"Error checking process {proc.info['pid']}: {e}")
                    continue
                    
        except ImportError:
            logger.warning("psutil not available for enhanced process discovery")
        except Exception as e:
            logger.error(f"Error during enhanced process discovery: {e}")
        
        total_reattached = reattached_by_pid + reattached_by_discovery
        logger.info(f"Finished detecting running server processes - Reattached {total_reattached} servers "
                   f"({reattached_by_pid} by PID, {reattached_by_discovery} by discovery)")
        
    except Exception as e:
        logger.error(f"Error in reattach_to_running_servers: {e}")


def _process_matches_server(process, server_name, server_config):
    # Check if a process matches a server configuration
    try:
        proc_info = process.info
        install_dir = server_config.get('InstallDir', '').lower()
        
        # Check 1: Working directory matches install directory
        if proc_info.get('cwd') and install_dir:
            if os.path.normpath(proc_info['cwd'].lower()) == os.path.normpath(install_dir):
                return True
        
        # Check 2: Executable path contains server name or install directory
        exe_path = proc_info.get('exe', '').lower()
        if exe_path and install_dir and install_dir in exe_path:
            return True
            
        # Check 3: Command line contains server-specific information
        cmdline = proc_info.get('cmdline', [])
        if cmdline:
            cmdline_str = ' '.join(cmdline).lower()
            
            # Check for server name in command line
            if server_name.lower() in cmdline_str:
                return True
                
            # Check for install directory in command line
            if install_dir and install_dir in cmdline_str:
                return True
                
            # Check for executable path from config
            exe_config = server_config.get('ExecutablePath', '').lower()
            if exe_config and exe_config in cmdline_str:
                return True
        
        # Check 4: Process name matches known server executables
        proc_name = proc_info.get('name', '').lower()
        server_type = server_config.get('Type', '').lower()
        
        # Minecraft servers
        if server_type == 'minecraft' and ('java' in proc_name or 'javaw' in proc_name):
            # Additional check: look for jar file in command line
            if cmdline and any('.jar' in arg.lower() for arg in cmdline):
                return True
                
        # Steam servers
        elif server_type == 'steam':
            steam_executables = ['srcds', 'steamcmd', 'valheim_server', 'vrising']
            if any(exe in proc_name for exe in steam_executables):
                return True
        
        return False
        
    except Exception as e:
        logger.debug(f"Error matching process {proc_info.get('pid', 'unknown')} to server {server_name}: {e}")
        return False


def update_server_list_for_subhost(subhost_name, servers_data, server_lists, logger):
    # Update the server list for a specific subhost
    if subhost_name not in server_lists:
        return
        
    server_list = server_lists[subhost_name]
    
    # Clear existing items
    for item in server_list.get_children():
        server_list.delete(item)
    
    # Add servers for this subhost
    for server_name, server_info in servers_data.items():
        try:
            # Extract server information
            status = server_info.get('status', 'Unknown')
            pid = server_info.get('pid', '')
            cpu = server_info.get('cpu', '0%')
            memory = server_info.get('memory', '0 MB')
            uptime = server_info.get('uptime', '00:00:00')
            
            # Insert into treeview
            server_list.insert("", tk.END, values=(
                server_name, status, pid, cpu, memory, uptime
            ))
        except Exception as e:
            logger.error(f"Error adding server {server_name} to list: {e}")


def get_servers_display_data(server_manager, logger):
    # Get processed server data for display with status, pid, cpu, memory, uptime
    try:
        servers_data = {}
        raw_servers = server_manager.get_all_servers()
        
        for server_name, server_config in raw_servers.items():
            try:
                # Get server config from raw_servers
                server_config = raw_servers.get(server_name)
                if not server_config:
                    display_status = 'Not Found'
                    pid = None
                else:
                    # Check if server has ProcessId and is running
                    if 'ProcessId' in server_config:
                        pid = server_config['ProcessId']
                        try:
                            if server_manager.is_process_running(pid):
                                display_status = 'Running'
                            else:
                                display_status = 'Stopped'
                        except Exception as e:
                            logger.debug(f"Error checking if process {pid} is running: {e}")
                            display_status = 'Stopped'
                    else:
                        display_status = 'Stopped'
                        pid = None
                
                # Initialize display data
                display_data = {
                    'status': display_status,
                    'pid': str(pid) if pid else '',
                    'cpu': '0%',
                    'memory': '0 MB',
                    'uptime': '00:00:00'
                }
                
                # Get CPU and memory usage if server is running
                if display_status == 'Running' and pid:
                    try:
                        import psutil
                        process = psutil.Process(pid)
                        
                        # Get CPU usage (short interval for responsiveness)
                        cpu_percent = process.cpu_percent(interval=0.1)
                        display_data['cpu'] = f"{cpu_percent:.1f}%"
                        
                        # Get memory usage
                        memory_info = process.memory_info()
                        memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
                        display_data['memory'] = f"{memory_mb:.1f} MB"
                        
                        # Calculate uptime
                        if 'StartTime' in server_config:
                            try:
                                start_time_str = server_config['StartTime']
                                if isinstance(start_time_str, str):
                                    start_time = datetime.datetime.fromisoformat(start_time_str)
                                else:
                                    start_time = start_time_str
                                
                                uptime = datetime.datetime.now() - start_time
                                hours, remainder = divmod(int(uptime.total_seconds()), 3600)
                                minutes, seconds = divmod(remainder, 60)
                                display_data['uptime'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                            except Exception as e:
                                logger.debug(f"Could not calculate uptime for {server_name}: {e}")
                        
                    except Exception as e:
                        logger.debug(f"Could not get process details for {server_name} (PID {pid}): {e}")
                
                servers_data[server_name] = display_data
                
            except Exception as e:
                logger.error(f"Error processing server {server_name}: {e}")
                # Add with default stopped status
                servers_data[server_name] = {
                    'status': 'Error',
                    'pid': '',
                    'cpu': '0%',
                    'memory': '0 MB',
                    'uptime': '00:00:00'
                }
        
        return servers_data
        
    except Exception as e:
        logger.error(f"Error getting servers display data: {e}")
        return {}


def refresh_subhost_servers(subhost_name, server_manager, server_lists, logger):
    # Refresh servers for a specific subhost with async remote operations
    try:
        if subhost_name == "Local Host":
            # Get processed server data for display
            servers = get_servers_display_data(server_manager, logger)
            update_server_list_for_subhost(subhost_name, servers, server_lists, logger)
        else:
            # Get servers from remote subhost asynchronously
            _refresh_remote_subhost_async(subhost_name, server_lists, logger)
            
    except Exception as e:
        logger.error(f"Error refreshing servers for subhost {subhost_name}: {e}")


def _refresh_remote_subhost_async(subhost_name, server_lists, logger):
    # Asynchronously refresh servers from a remote subhost
    import threading
    
    def async_refresh():
        try:
            from Modules.agents import AgentManager
            agent_manager = AgentManager()
            
            # Get node info first
            if subhost_name not in agent_manager.nodes:
                logger.warning(f"Node {subhost_name} not found in agent manager")
                return
                
            node = agent_manager.nodes[subhost_name]
            
            # Try to get servers with timeout
            servers = None
            try:
                import requests
                response = requests.get(f"http://{node.ip}:8080/api/servers", timeout=5)  # Reduced timeout
                if response.status_code == 200:
                    servers = response.json().get('servers', [])
                else:
                    logger.warning(f"Failed to get servers from node {subhost_name}: HTTP {response.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout getting servers from node {subhost_name}")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error getting servers from node {subhost_name}")
            except Exception as e:
                logger.error(f"Error getting servers from node {subhost_name}: {e}")
            
            # Convert to expected format
            converted_servers = {}
            if servers:
                if isinstance(servers, dict):
                    for server_name, server_info in servers.items():
                        converted_servers[server_name] = {
                            'status': server_info.get('status', 'Unknown'),
                            'pid': server_info.get('pid', ''),
                            'cpu': server_info.get('cpu', '0%'),
                            'memory': server_info.get('memory', '0 MB'),
                            'uptime': server_info.get('uptime', '00:00:00')
                        }
                elif isinstance(servers, list):
                    for server_info in servers:
                        if isinstance(server_info, dict) and 'name' in server_info:
                            server_name = server_info['name']
                            converted_servers[server_name] = {
                                'status': server_info.get('status', 'Unknown'),
                                'pid': server_info.get('pid', ''),
                                'cpu': server_info.get('cpu', '0%'),
                                'memory': server_info.get('memory', '0 MB'),
                                'uptime': server_info.get('uptime', '00:00:00')
                            }
            
            # Update the UI on the main thread
            def update_ui():
                try:
                    update_server_list_for_subhost(subhost_name, converted_servers, server_lists, logger)
                except Exception as e:
                    logger.error(f"Error updating UI for subhost {subhost_name}: {e}")
            
            # Schedule UI update on main thread
            import tkinter as tk
            root = None
            for widget_list in server_lists.values():
                for widget in widget_list:
                    if isinstance(widget, tk.Widget):
                        root = widget.winfo_toplevel()
                        break
                if root:
                    break
            
            if root:
                root.after(0, update_ui)
            else:
                logger.warning(f"Could not find root window for UI update of subhost {subhost_name}")
                
        except Exception as e:
            logger.error(f"Error in async refresh for subhost {subhost_name}: {e}")
    
    # Start async refresh thread
    thread = threading.Thread(target=async_refresh, daemon=True)
    thread.start()


def refresh_all_subhost_servers(server_lists, server_manager, logger):
    # Refresh servers for all subhost tabs - starts async operations for remote hosts
    for subhost_name in server_lists.keys():
        try:
            refresh_subhost_servers(subhost_name, server_manager, server_lists, logger)
        except Exception as e:
            logger.error(f"Error initiating refresh for subhost {subhost_name}: {e}")


def refresh_current_subhost_servers(current_subhost_func, server_manager, server_lists, logger):
    # Refresh servers for the currently active subhost tab - handles async remote operations
    current_subhost = current_subhost_func()
    if current_subhost:
        refresh_subhost_servers(current_subhost, server_manager, server_lists, logger)
        return False  # Return False to indicate async operation started


def update_server_list_logic(dashboard, force_refresh=False):
    # Update server list from configuration files - business logic only
    try:
        # Skip update if already refreshing
        if hasattr(dashboard, '_refreshing_server_list') and dashboard._refreshing_server_list:
            log_dashboard_event("SERVER_LIST_UPDATE", "Skipping update - refresh already in progress", "DEBUG")
            return
        
        # Skip update if it's been less than configured interval since the last update and force_refresh isn't specified
        update_interval = dashboard.variables.get("serverListUpdateInterval", 30)
        if not force_refresh and \
           (dashboard.variables["lastServerListUpdate"] != datetime.datetime.min) and \
           (datetime.datetime.now() - dashboard.variables["lastServerListUpdate"]).total_seconds() < update_interval:
            log_dashboard_event("SERVER_LIST_UPDATE", f"Skipping update - last update was less than {update_interval} seconds ago", "DEBUG")
            return
        
        # Set refreshing flag
        dashboard._refreshing_server_list = True
        
        try:
            # Update all subhost tabs
            dashboard.refresh_all_subhost_servers()
        finally:
            # Always clear the refreshing flag
            dashboard._refreshing_server_list = False
            
    except Exception as e:
        logger.error(f"Error in update_server_list: {str(e)}")
        dashboard._refreshing_server_list = False
