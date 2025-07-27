import os
import sys
import json
import datetime
import platform
import socket
import winreg
import psutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import zipfile

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import logging functions
from Modules.logging import get_dashboard_logger

# Get dashboard logger
logger = get_dashboard_logger()


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


def initialize_paths_from_registry(registry_path):
    """Initialize basic paths from registry"""
    try:
        # Read registry for basic paths
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        
        # Clean up path
        server_manager_dir = server_manager_dir.strip('"').strip()
        
        # Define paths structure
        paths = {
            "root": server_manager_dir,
            "logs": os.path.join(server_manager_dir, "logs"),
            "config": os.path.join(server_manager_dir, "config"),
            "temp": os.path.join(server_manager_dir, "temp"),
            "servers": os.path.join(server_manager_dir, "servers"),
            "modules": os.path.join(server_manager_dir, "modules"),
            "data": os.path.join(server_manager_dir, "data")
        }
        
        # Ensure directories exist
        for path in paths.values():
            os.makedirs(path, exist_ok=True)
        
        logger.info(f"Basic initialization complete. Server Manager directory: {server_manager_dir}")
        return True, server_manager_dir, paths
        
    except Exception as e:
        logger.error(f"Basic initialization failed: {str(e)}")
        return False, None, {}


def initialize_registry_values(registry_path):
    """Initialize registry-managed values"""
    try:
        # Read registry for all installation-managed values
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        
        registry_values = {}
        steam_cmd_path = None
        webserver_port = 8080
        
        # Try to get SteamCmd path
        try:
            steam_cmd_path = winreg.QueryValueEx(key, "SteamCmdPath")[0]
        except:
            steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
            logger.warning(f"SteamCmd path not found in registry, using default: {steam_cmd_path}")
            
        # Try to get WebPort from registry
        try:
            webserver_port = int(winreg.QueryValueEx(key, "WebPort")[0])
        except:
            webserver_port = 8080
            logger.warning(f"WebPort not found in registry, using default: 8080")
        
        # Read other registry values for reference
        try:
            registry_values = {
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
                registry_values["HostAddress"] = winreg.QueryValueEx(key, "HostAddress")[0]
            except:
                pass  # HostAddress only exists for subhost installations
                
        except Exception as e:
            logger.warning(f"Some registry values could not be read: {str(e)}")
        
        winreg.CloseKey(key)
        
        logger.info("Registry values initialized successfully")
        return True, steam_cmd_path, webserver_port, registry_values
        
    except Exception as e:
        logger.error(f"Failed to initialize registry values: {str(e)}")
        return False, None, 8080, {}


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
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
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


def get_process_info(process_id):
    """Get process information for a given PID"""
    try:
        if is_process_running(process_id):
            process = psutil.Process(process_id)
            
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
            
            return {
                "status": "Running",
                "pid": str(process_id),
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage
            }
        else:
            return {
                "status": "Offline",
                "pid": "N/A",
                "cpu_usage": "N/A",
                "memory_usage": "N/A"
            }
    except Exception as e:
        logger.error(f"Error getting process info for PID {process_id}: {str(e)}")
        return {
            "status": "Error",
            "pid": "N/A",
            "cpu_usage": "N/A",
            "memory_usage": "N/A"
        }
