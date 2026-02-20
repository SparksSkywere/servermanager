# Server operations
import os
import sys
import logging
import subprocess
import winreg
import time

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import psutil
except ImportError:
    psutil = None

from Modules.common import (
    setup_module_path, get_subprocess_creation_flags, setup_module_logging,
    get_server_manager_dir
)
setup_module_path()

logger: logging.Logger = setup_module_logging("ServerOperations")

class ServerOperations:
    # - Server start/stop/restart
    # - Status monitoring
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        
        self.initialise_from_registry()
    
    def initialise_from_registry(self):
        # Pull paths from registry
        try:
            self.server_manager_dir = get_server_manager_dir()
            
            if not self.server_manager_dir:
                logger.error("SM dir not in registry")
                return False
            
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts")
            }
            
            for path_name, path in self.paths.items():
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    logger.error(f"Dir create failed {path_name}: {str(e)}")
                    return False
                
            logger.info(f"Server operations initialised from registry")
            return True
            
        except FileNotFoundError:
            logger.error(f"Registry key not found: {self.registry_path}")
            return False
        except winreg.error as e:
            logger.error(f"Registry error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialise server operations from registry: {str(e)}")
            return False

# Create instance
server_ops = ServerOperations()

# Export functions for module usage
def get_all_servers():
    # Get a list of all configured servers from database
    try:
        from Modules.Database.server_configs_database import ServerConfigManager
        manager = ServerConfigManager()
        return manager.get_all_servers()
    except Exception as e:
        logger.error(f"Error getting servers from database: {str(e)}")
        return []

def get_server_status(server_name):
    # Get status of a specific server
    try:
        # Get server config from database
        from Modules.Database.server_configs_database import ServerConfigManager
        manager = ServerConfigManager()
        config = manager.get_server(server_name)
        
        if not config:
            logger.error(f"Server configuration not found: {server_name}")
            return None
        
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
