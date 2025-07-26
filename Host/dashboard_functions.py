import os
import sys
import json
import datetime
import platform
import socket
import winreg
import psutil
import tkinter as tk
from tkinter import ttk

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
