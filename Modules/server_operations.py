# Server operations including start, stop, restart, and status management
import os
import sys
import json
import logging
import subprocess
import winreg
import time
from datetime import datetime

import logging

try:
    from Modules.server_logging import get_component_logger, log_server_action
    logger = get_component_logger("ServerOperations")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("ServerOperations")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("ServerOperations module debug mode enabled via environment")
try:
    import psutil
except ImportError:
    psutil = None

# logging configuration handled by centralized logging module when imported; fallback basicConfig already applied if import failed above

def get_subprocess_creation_flags(hide_window=True):
    # Get appropriate creation flags for subprocess calls on Windows to prevent console windows
    if sys.platform != 'win32':
        return 0
    
    return subprocess.CREATE_NO_WINDOW if hide_window else 0
logger = logging.getLogger("ServerOperations")

class ServerOperations:
    # Class for server management operations
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        
        # Initialize from registry
        self.initialize_from_registry()
    
    def initialize_from_registry(self):
        # Initialize paths from registry settings
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            if not self.server_manager_dir:
                logger.error("Server manager directory not found in registry")
                return False
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts")
            }
            
            # Ensure directories exist
            for path_name, path in self.paths.items():
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    logger.error(f"Failed to create directory {path_name} at {path}: {str(e)}")
                    return False
                
            logger.info(f"Server operations initialized from registry")
            return True
            
        except FileNotFoundError:
            logger.error(f"Registry key not found: {self.registry_path}")
            return False
        except winreg.error as e:
            logger.error(f"Registry error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize server operations from registry: {str(e)}")
            return False

# Create instance
server_ops = ServerOperations()

# Export functions for module usage
def get_all_servers():
    # Get a list of all configured servers
    servers = []
    servers_dir = server_ops.paths.get("servers")
    
    if not servers_dir or not os.path.exists(servers_dir):
        logger.error(f"Servers directory not found: {servers_dir}")
        return servers
    
    try:
        for file in os.listdir(servers_dir):
            if file.endswith(".json"):
                try:
                    with open(os.path.join(servers_dir, file), 'r') as f:
                        server_config = json.load(f)
                    servers.append(server_config)
                except Exception as e:
                    logger.error(f"Error loading server config {file}: {str(e)}")
    except Exception as e:
        logger.error(f"Error accessing servers directory: {str(e)}")
    
    return servers

def get_server_status(server_name):
    # Get status of a specific server
    try:
        servers_dir = server_ops.paths.get("servers")
        if not servers_dir:
            logger.error("Servers directory path not configured")
            return None
            
        config_path = os.path.join(servers_dir, f"{server_name}.json")
        
        if not os.path.exists(config_path):
            logger.error(f"Server configuration not found: {config_path}")
            return None
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Check if server process is running
        status = "Unknown"
        if "PID" in config and config["PID"]:
            try:
                if psutil:
                    process = psutil.Process(config["PID"])
                    if process.is_running():
                        status = "Running"
                        # Add process info
                        config["CPU"] = process.cpu_percent()
                        config["Memory"] = process.memory_info().rss
                    else:
                        status = "Stopped"
                        config["PID"] = None
                else:
                    logger.warning("psutil not available, cannot check process status")
                    status = "Unknown"
            except Exception:
                status = "Stopped"
                config["PID"] = None
        else:
            status = "Stopped"
        
        config["Status"] = status
        return config
    except Exception as e:
        logger.error(f"Error getting server status: {str(e)}")
        return None

def start_server(server_name):
    # Start a server
    try:
        scripts_dir = server_ops.paths.get("scripts")
        if not scripts_dir:
            logger.error("Scripts directory path not configured")
            return False
            
        script_path = os.path.join(scripts_dir, "start_server.py")
        
        if not os.path.exists(script_path):
            logger.error(f"Start server script not found: {script_path}")
            return False
        
        subprocess.run([sys.executable, script_path, server_name], check=True,
                       creationflags=get_subprocess_creation_flags())
        logger.info(f"Server {server_name} started")
        return True
    except Exception as e:
        logger.error(f"Error starting server {server_name}: {str(e)}")
        return False

def stop_server(server_name, force=False):
    # Stop a server
    try:
        scripts_dir = server_ops.paths.get("scripts")
        if not scripts_dir:
            logger.error("Scripts directory path not configured")
            return False
            
        script_path = os.path.join(scripts_dir, "stop_server.py")
        
        if not os.path.exists(script_path):
            logger.error(f"Stop server script not found: {script_path}")
            return False
        
        cmd = [sys.executable, script_path, server_name]
        if force:
            cmd.append("--force")
        
        subprocess.run(cmd, check=True,
                       creationflags=get_subprocess_creation_flags())
        logger.info(f"Server {server_name} stopped")
        return True
    except Exception as e:
        logger.error(f"Error stopping server {server_name}: {str(e)}")
        return False

def restart_server(server_name):
    # Restart a server
    if stop_server(server_name):
        # Wait a moment for server to fully stop
        time.sleep(2)
        return start_server(server_name)
    return False

def install_server(server_name, validate=True):
    # Install or update a server
    try:
        # This is a placeholder - full implementation would involve SteamCMD
        logger.info(f"Installing/updating server {server_name}")
        return True
    except Exception as e:
        logger.error(f"Error installing server {server_name}: {str(e)}")
        return False

def check_for_updates(server_name):
    # Check if updates are available for a server
    try:
        # This is a placeholder - full implementation would involve SteamCMD
        logger.info(f"Checking for updates for server {server_name}")
        return False
    except Exception as e:
        logger.error(f"Error checking for updates for server {server_name}: {str(e)}")
        return False
