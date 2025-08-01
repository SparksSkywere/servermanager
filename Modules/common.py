import os
import sys
import json
import logging
import winreg
import time
import datetime
import psutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Common")

# Registry utility functions
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
                "icons": os.path.join(self.server_manager_dir, "icons"),
                "data": os.path.join(self.server_manager_dir, "data")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid")
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
                "icons": os.path.join(self.server_manager_dir, "icons"),
                "data": os.path.join(self.server_manager_dir, "data")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid")
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
                
            # Always try to merge current registry values
            try:
                success, steam_cmd, webserver_port, registry_values = initialize_registry_values(
                    r"Software\SkywereIndustries\Servermanager"
                )
                if success:
                    # Override with current registry values
                    self.config["web_port"] = webserver_port
                    if steam_cmd:
                        self.config["steam_cmd_path"] = steam_cmd
            except Exception as e:
                logger.warning(f"Could not load current registry values: {str(e)}")
                
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            self.create_default_config()
            return False
            
    def create_default_config(self):
        """Create default configuration"""
        try:
            # Start with default config
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
            
            # Try to override with registry values
            try:
                success, steam_cmd, webserver_port, registry_values = initialize_registry_values(
                    r"Software\SkywereIndustries\Servermanager"
                )
                if success:
                    self.config["web_port"] = webserver_port
                    self.config["steam_cmd_path"] = steam_cmd
                    # Add other registry values as needed
                    if registry_values:
                        for key, value in registry_values.items():
                            self.config[f"registry_{key.lower()}"] = value
            except Exception as e:
                logger.warning(f"Could not load registry values for config: {str(e)}")
            
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

# Import debug module for exception logging
try:
    from Modules.debug import log_exception
except ImportError:
    # Fallback if debug module not available
    def log_exception(e, message="An exception occurred"):
        logger.error(f"{message}: {str(e)}")

# System utilities
class SystemUtils:
    """Class for system utilities"""
    @staticmethod
    def get_system_info():
        """Get system information"""
        try:
            # Try to use debug module first
            try:
                from Modules.debug import get_system_info
                return get_system_info()
            except ImportError:
                # Fallback to direct implementation
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
            log_exception(e, "Failed to get system information")
            return {}
    
    @staticmethod
    def get_process_info(pid):
        """Get process information by PID"""
        try:
            # Try to use debug module first
            try:
                from Modules.debug import get_process_info
                return get_process_info(pid)
            except ImportError:
                # Fallback to direct implementation
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
                    "create_time": datetime.datetime.fromtimestamp(process.create_time()).isoformat()
                }
                
                return info
        except Exception as e:
            log_exception(e, f"Failed to get process information for PID {pid}")
            return None

# Create global instances for easy access
paths = ServerManagerPaths()
process_manager = ProcessManager(paths)
config_manager = ConfigManager(paths)
system_utils = SystemUtils()

# Base class for all Server Manager modules
class ServerManagerModule:
    """Base class for all Server Manager modules that provides common functionality"""
    
    def __init__(self, module_name=None):
        self.module_name = module_name or self.__class__.__name__
        self.logger = logging.getLogger(self.module_name)
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        
        # Use global instances for shared functionality
        self._paths_manager = paths
        self._process_manager = process_manager
        self._config_manager = config_manager
        
        # Ensure paths are initialized
        if not self._paths_manager.initialized:
            self.logger.warning("Paths not initialized, attempting to initialize...")
            if not self._paths_manager.initialize_from_registry():
                self.logger.error("Failed to initialize paths")
                raise Exception("Failed to initialize Server Manager paths")
    
    @property
    def paths(self):
        """Get the paths dictionary"""
        return self._paths_manager.paths
        
    @property 
    def server_manager_dir(self):
        """Get the server manager directory"""
        return self._paths_manager.server_manager_dir
        
    @property
    def config(self):
        """Get configuration"""
        return self._config_manager.config
        
    @property
    def web_port(self):
        """Get the web server port from configuration"""
        return self.get_config_value("web_port", 8080)
        
    @web_port.setter
    def web_port(self, value):
        """Set the web server port in configuration"""
        self.set_config_value("web_port", value)
        
    def is_process_running(self, pid):
        """Check if a process with the given PID is running"""
        return self._process_manager.is_process_running(pid)
        
    def write_pid_file(self, process_type, pid):
        """Write process ID information to a PID file"""
        return self._process_manager.write_pid_file(process_type, pid)
        
    def read_pid_file(self, process_type):
        """Read process ID information from a PID file"""
        return self._process_manager.read_pid_file(process_type)
        
    def remove_pid_file(self, process_type):
        """Remove a PID file"""
        return self._process_manager.remove_pid_file(process_type)
        
    def is_component_running(self, process_type):
        """Check if a server manager component is running"""
        return self._process_manager.is_component_running(process_type)
        
    def get_config_value(self, key, default=None):
        """Get a configuration value"""
        return self._config_manager.get(key, default)
        
    def set_config_value(self, key, value):
        """Set a configuration value and save"""
        return self._config_manager.set(key, value)
        
    def get_path(self, path_key):
        """Get a specific path by key"""
        return self._paths_manager.get_path(path_key)

# Export these instances to make them available to other modules
__all__ = ['paths', 'process_manager', 'config_manager', 'system_utils', 'ServerManagerModule',
           'initialize_paths_from_registry', 'initialize_registry_values']
