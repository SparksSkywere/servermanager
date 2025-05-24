import os
import sys
import json
import logging
import winreg
import datetime
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Common")

class ServerManagerPaths:
    """Class to handle paths for the server manager"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.initialized = False
        
        # Try to initialize from registry
        self.initialize_from_registry()
        
    def initialize_from_registry(self):
        """Initialize paths from registry settings"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "modules": os.path.join(self.server_manager_dir, "modules"),
                "static": os.path.join(self.server_manager_dir, "static"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid")
            }
            
            # Ensure all directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            self.initialized = True
            logger.info(f"Paths initialized from registry. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize paths from registry: {str(e)}")
            
            # Fallback to current directory or script directory
            if not self.initialize_fallback():
                raise Exception("Failed to initialize paths")
                
    def initialize_fallback(self):
        """Initialize with fallback paths if registry fails"""
        try:
            # Try to use the script directory's parent as the server manager directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.server_manager_dir = os.path.dirname(script_dir)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "modules": os.path.join(self.server_manager_dir, "modules"),
                "static": os.path.join(self.server_manager_dir, "static"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid")
            }
            
            # Ensure all directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            self.initialized = True
            logger.warning(f"Using fallback paths. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize fallback paths: {str(e)}")
            return False
            
    def get_path(self, path_key):
        """Get a specific path by key"""
        if not self.initialized:
            raise Exception("Paths not initialized")
            
        if path_key in self.paths:
            return self.paths[path_key]
        else:
            raise KeyError(f"Path key not found: {path_key}")
            
    def get_pid_file(self, process_type):
        """Get a specific PID file path by process type"""
        if not self.initialized:
            raise Exception("Paths not initialized")
            
        if process_type in self.pid_files:
            return self.pid_files[process_type]
        else:
            raise KeyError(f"PID file for process type not found: {process_type}")

# Process and PID file management functions
class ProcessManager:
    """Class to manage processes and PID files"""
    def __init__(self, paths_manager):
        self.paths_manager = paths_manager
        
    def write_pid_file(self, process_type, pid):
        """Write process ID information to a PID file"""
        try:
            pid_file = self.paths_manager.get_pid_file(process_type)
            
            # Create PID info dictionary
            pid_info = {
                "ProcessId": pid,
                "StartTime": datetime.datetime.now().isoformat(),
                "ProcessType": process_type
            }
            
            # Write PID info to file as JSON
            with open(pid_file, 'w') as f:
                json.dump(pid_info, f, indent=4)
                
            logger.debug(f"PID file created for {process_type}: {pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to write PID file for {process_type}: {str(e)}")
            return False
            
    def read_pid_file(self, process_type):
        """Read process ID information from a PID file"""
        try:
            pid_file = self.paths_manager.get_pid_file(process_type)
            
            if not os.path.exists(pid_file):
                logger.debug(f"PID file not found for {process_type}")
                return None
                
            with open(pid_file, 'r') as f:
                pid_info = json.load(f)
                
            return pid_info
        except Exception as e:
            logger.error(f"Failed to read PID file for {process_type}: {str(e)}")
            return None
            
    def remove_pid_file(self, process_type):
        """Remove a PID file"""
        try:
            pid_file = self.paths_manager.get_pid_file(process_type)
            
            if os.path.exists(pid_file):
                os.remove(pid_file)
                logger.debug(f"PID file removed for {process_type}")
                return True
            else:
                logger.debug(f"PID file not found for {process_type}")
                return False
        except Exception as e:
            logger.error(f"Failed to remove PID file for {process_type}: {str(e)}")
            return False
            
    def is_process_running(self, pid):
        """Check if a process with the given PID is running"""
        try:
            if not pid:
                return False
                
            return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except Exception:
            return False
            
    def is_component_running(self, process_type):
        """Check if a server manager component is running"""
        pid_info = self.read_pid_file(process_type)
        
        if not pid_info:
            return False
            
        return self.is_process_running(pid_info.get("ProcessId"))
            
    def kill_process(self, pid, force=False):
        """Kill a process by PID"""
        try:
            if not pid or not self.is_process_running(pid):
                return True
                
            process = psutil.Process(pid)
            
            if force:
                process.kill()
            else:
                process.terminate()
                
            return True
        except Exception as e:
            logger.error(f"Failed to kill process {pid}: {str(e)}")
            return False

# Configuration management
class ConfigManager:
    """Class to manage server manager configuration"""
    def __init__(self, paths_manager):
        self.paths_manager = paths_manager
        self.config = {}
        self.config_file = os.path.join(paths_manager.get_path("config"), "config.json")
        
        # Load configuration
        self.load_config()
        
    def load_config(self):
        """Load configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
                logger.debug(f"Configuration loaded from {self.config_file}")
            else:
                logger.warning(f"Configuration file not found: {self.config_file}")
                self.create_default_config()
                
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            self.create_default_config()
            return False
            
    def create_default_config(self):
        """Create default configuration"""
        try:
            self.config = {
                "version": "0.1",
                "web_port": 8080,
                "enable_auto_updates": True,
                "enable_tray_icon": True,
                "check_updates_interval": 3600,  # seconds
                "log_level": "INFO",
                "max_log_size": 10485760,  # 10 MB
                "max_log_files": 10
            }
            
            # Save default configuration
            self.save_config()
            
            logger.info("Default configuration created")
            return True
        except Exception as e:
            logger.error(f"Failed to create default configuration: {str(e)}")
            return False
            
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
                
            logger.debug(f"Configuration saved to {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration: {str(e)}")
            return False
            
    def get(self, key, default=None):
        """Get a configuration value"""
        return self.config.get(key, default)
        
    def set(self, key, value):
        """Set a configuration value and save"""
        self.config[key] = value
        return self.save_config()

# System utilities
class SystemUtils:
    """Class for system utilities"""
    @staticmethod
    def get_system_info():
        """Get system information"""
        try:
            info = {
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "percent": psutil.virtual_memory().percent
                },
                "disk": {
                    "total": psutil.disk_usage('/').total,
                    "free": psutil.disk_usage('/').free,
                    "percent": psutil.disk_usage('/').percent
                }
            }
            
            return info
        except Exception as e:
            logger.error(f"Failed to get system information: {str(e)}")
            return {}
    
    @staticmethod
    def get_process_info(pid):
        """Get process information by PID"""
        try:
            if not pid or not psutil.pid_exists(pid):
                return None
                
            process = psutil.Process(pid)
            
            info = {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_info": {
                    "rss": process.memory_info().rss,
                    "vms": process.memory_info().vms
                },
                "create_time": datetime.datetime.fromtimestamp(process.create_time()).isoformat(),
                "threads": len(process.threads())
            }
            
            return info
        except Exception as e:
            logger.error(f"Failed to get process information for PID {pid}: {str(e)}")
            return None

# Create global instances for easy access
paths = ServerManagerPaths()
process_manager = ProcessManager(paths)
config_manager = ConfigManager(paths)
system_utils = SystemUtils()

# Export these instances to make them available to other modules
__all__ = ['paths', 'process_manager', 'config_manager', 'system_utils']
