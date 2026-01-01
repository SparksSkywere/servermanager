# Common utilities for Server Manager
# - Registry, paths, process management, system bits
# - Shared across all modules-don't duplicate this rubbish elsewhere
import os
import sys
import json
import logging
import winreg
import time
import datetime
import psutil

# Centralised registry constants-use these, not hardcoded strings
REGISTRY_ROOT = winreg.HKEY_LOCAL_MACHINE
REGISTRY_PATH = r"Software\SkywereIndustries\Servermanager"

# Logging setup-falls back to basic config if server_logging unavailable
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("Common")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Common")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug mode on via environment")

# Registry utility functions
def initialise_paths_from_registry(registry_path):
    # Grab paths from registry-returns (success, dir, paths dict)
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, registry_path)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        
        # Clean up path
        server_manager_dir = server_manager_dir.strip('"').strip()
        
        # Define paths structure (excluding config and data folders since we use database now)
        paths = {
            "root": server_manager_dir,
            "logs": os.path.join(server_manager_dir, "logs"),
            "temp": os.path.join(server_manager_dir, "temp"),
            "servers": os.path.join(server_manager_dir, "servers"),
            "modules": os.path.join(server_manager_dir, "modules")
        }
        
        # Ensure directories exist (excluding config and data)
        for path_key, path in paths.items():
            if path_key not in ["config", "data"]:  # Skip config and data directories
                os.makedirs(path, exist_ok=True)
        
        logger.info(f"Paths initialised from registry: {server_manager_dir}")
        return True, server_manager_dir, paths
        
    except Exception as e:
        logger.error(f"Path init failed: {str(e)}")
        return False, None, {}


def initialise_registry_values(registry_path):
    # Pull config values from registry-SteamCmd path, web port, etc.
    try:
        # Read registry for all installation-managed values
        key = winreg.OpenKey(REGISTRY_ROOT, registry_path)
        
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
                
            # Try to get cluster configuration
            try:
                registry_values["ClusterCreated"] = winreg.QueryValueEx(key, "ClusterCreated")[0]
            except:
                pass  # ClusterCreated only exists for configured clusters
                
        except Exception as e:
            logger.warning(f"Some registry values could not be read: {str(e)}")
        
        winreg.CloseKey(key)
        
        logger.info("Registry values initialized successfully")
        return True, steam_cmd_path, webserver_port, registry_values
        
    except Exception as e:
        logger.error(f"Failed to initialize registry values: {str(e)}")
        return False, None, 8080, {}

class ServerManagerPaths:
    # - Path resolver for all server manager directories
    # - Falls back to script dir if registry fails
    def __init__(self):
        self.registry_path = REGISTRY_PATH
        self.server_manager_dir = None
        self.paths = {}
        self.initialised = False
        
        self.initialise_from_registry()
        
    def initialise_from_registry(self):
        # Try registry first-fallback kicks in if this fails
        try:
            # Read registry for paths
            key = winreg.OpenKey(REGISTRY_ROOT, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Define paths structure (excluding config and data folders since we use database now)
            self.paths = {
                "root": self.server_manager_dir,
                "project_root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules"),
                "modules": os.path.join(self.server_manager_dir, "Modules"),
                "static": os.path.join(self.server_manager_dir, "static"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid")
            }
            
            # Create dirs if missing (skip config/data-database handles those)
            for path_key, path in self.paths.items():
                if path_key not in ["config", "data"]:
                    os.makedirs(path, exist_ok=True)
                
            self.initialised = True
            logger.info(f"Paths ready: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize paths from registry: {str(e)}")
            
            # Registry failed-try fallback
            if not self.initialise_fallback():
                raise Exception("Path initialisation failed")
                
    def initialise_fallback(self):
        # Use script dir as fallback when registry is broken/missing
        try:
            # Try to use the script directory's parent as the server manager directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.server_manager_dir = os.path.dirname(script_dir)
            
            # Define paths structure (excluding config and data folders since we use database now)
            self.paths = {
                "root": self.server_manager_dir,
                "project_root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules"),
                "modules": os.path.join(self.server_manager_dir, "Modules"),
                "static": os.path.join(self.server_manager_dir, "static"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }
            
            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid")
            }
            
            # Create dirs if missing
            for path_key, path in self.paths.items():
                if path_key not in ["config", "data"]:
                    os.makedirs(path, exist_ok=True)
                
            self.initialised = True
            logger.warning(f"Fallback paths in use: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Fallback path init failed: {str(e)}")
            return False
            
    def get_path(self, path_key):
        # Return path for key-raises if uninitialised
        if not self.initialised:
            raise Exception("Paths not initialised")
            
        if path_key in self.paths:
            return self.paths[path_key]
        else:
            raise KeyError(f"Unknown path key: {path_key}")
            
    def get_pid_file(self, process_type):
        # PID file path for given process type
        if not self.initialised:
            raise Exception("Paths not initialised")
            
        if process_type in self.pid_files:
            return self.pid_files[process_type]
        else:
            raise KeyError(f"PID file for process type not found: {process_type}")

# Process and PID file handling
class ProcessManager:
    # - Manages PID files and process lifecycle
    # - Nothing fancy, just gets the job done
    def __init__(self, paths_manager):
        self.paths_manager = paths_manager
        
    def write_pid_file(self, process_type, pid):
        # Dump PID info to file
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
        # Load PID info from file-returns None if missing/corrupt
        try:
            pid_file = self.paths_manager.get_pid_file(process_type)
            
            if not os.path.exists(pid_file):
                logger.debug(f"No PID file for {process_type}")
                return None
                
            with open(pid_file, 'r') as f:
                pid_info = json.load(f)
                
            return pid_info
        except Exception as e:
            logger.error(f"PID read failed for {process_type}: {str(e)}")
            return None
            
    def remove_pid_file(self, process_type):
        # Delete PID file
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
        # Quick PID check-False if dead/missing
        try:
            if not pid:
                return False
                
            return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except Exception:
            return False
            
    def is_component_running(self, process_type):
        # Check if a server manager component is alive
        pid_info = self.read_pid_file(process_type)
        
        if not pid_info:
            return False
            
        return self.is_process_running(pid_info.get("ProcessId"))
            
    def kill_process(self, pid, force=False):
        # Terminate or kill process-force=True uses SIGKILL
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

# Config management
class ConfigManager:
    # - Handles app config via database
    # - Falls back to JSON migration if db empty
    def __init__(self, paths_manager):
        self.paths_manager = paths_manager
        self.config = {}
        
        self.load_config()
        
    def load_config(self):
        try:
            from Modules.Database.cluster_database import get_cluster_database
            db = get_cluster_database()
            
            config_data = db.get_main_config()
            
            # Migrate from JSON if database is empty
            if not config_data:
                # Check if old config folder exists for migration
                old_config_folder = os.path.join(self.paths_manager.server_manager_dir, "config")
                config_file = os.path.join(old_config_folder, "config.json")
                if os.path.exists(config_file):
                    logger.info("Migrating main config from JSON to database")
                    db.migrate_main_config_from_json(config_file)
                    # Reload after migration
                    config_data = db.get_main_config()
            
            # Update config with database values
            self.config.update(config_data)
            
            # Merge current registry values
            try:
                success, steam_cmd, webserver_port, registry_values = initialise_registry_values(
                    REGISTRY_PATH
                )
                if success:
                    self.config["web_port"] = webserver_port
                    if steam_cmd:
                        self.config["steam_cmd_path"] = steam_cmd
            except Exception as e:
                logger.warning(f"Registry values unavailable: {str(e)}")
                
            logger.debug("Configuration loaded from database")
            return True
        except Exception as e:
            logger.error(f"Failed to load configuration from database: {str(e)}")
            self.create_default_config()
            return False
            
    def create_default_config(self):
        # Set up sensible defaults
        try:
            self.config = {
                "version": "0.1",
                "web_port": 8080,
                "enable_auto_updates": True,
                "enable_tray_icon": True,
                "check_updates_interval": 3600,
                "log_level": "INFO",
                "max_log_size": 10485760,
                "max_log_files": 10
            }
            
            # Override with registry values if available
            try:
                success, steam_cmd, webserver_port, registry_values = initialise_registry_values(
                    REGISTRY_PATH
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
        try:
            from Modules.Database.cluster_database import get_cluster_database
            db = get_cluster_database()
            
            integer_keys = {'web_port', 'check_updates_interval', 'max_log_size', 'max_log_files'}
            boolean_keys = {'enable_auto_updates', 'enable_tray_icon'}
            
            for key, value in self.config.items():
                if key in integer_keys:
                    try:
                        db.set_main_config(key, int(value) if value else 0, config_type='integer')
                    except (ValueError, TypeError):
                        db.set_main_config(key, value)
                elif key in boolean_keys:
                    db.set_main_config(key, value, config_type='boolean')
                elif isinstance(value, (dict, list)):
                    db.set_main_config(key, value, config_type='json')
                else:
                    db.set_main_config(key, value)
                
            logger.debug("Configuration saved to database")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration to database: {str(e)}")
            return False
            
    def get(self, key, default=None):
        # Get a configuration value
        return self.config.get(key, default)
        
    def set(self, key, value):
        # Set a configuration value and save
        self.config[key] = value
        return self.save_config()

# Import debug module for exception logging
try:
    from debug.debug import log_exception
except ImportError:
    # Fallback if debug module not available
    def log_exception(e, message="An exception occurred"):
        logger.error(f"{message}: {str(e)}")

# System utils
class SystemUtils:
    # Quick system info helpers-CPU, memory, disk, process stats
    @staticmethod
    def get_system_info():
        # Returns dict of system metrics
        try:
            # Try to use debug module first
            try:
                from debug.debug import get_system_info
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
        # Grab process stats by PID-returns None if dead
        try:
            # Try to use debug module first
            try:
                from debug.debug import get_process_info
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

# Global instances-use these, don't create your own
paths = ServerManagerPaths()
process_manager = ProcessManager(paths)
config_manager = ConfigManager(paths)
system_utils = SystemUtils()

# Base class for all modules
class ServerManagerModule:
    # - Inherit from this for common functionality
    # - Paths, config, PID management baked in
    
    def __init__(self, module_name=None):
        self.module_name = module_name or self.__class__.__name__
        self.logger = logging.getLogger(self.module_name)
        self.registry_path = REGISTRY_PATH
        
        self._paths_manager = paths
        self._process_manager = process_manager
        self._config_manager = config_manager
        
        if not self._paths_manager.initialised:
            self.logger.warning("Paths uninitialised, fixing...")
            if not self._paths_manager.initialise_from_registry():
                self.logger.error("Path init failed")
                raise Exception("Failed to initialise paths")
    
    @property
    def paths(self):
        # Path dict
        return self._paths_manager.paths
        
    @property 
    def server_manager_dir(self):
        # Root directory
        return self._paths_manager.server_manager_dir
        
    @property
    def config(self):
        # Config dict
        return self._config_manager.config
        
    @property
    def web_port(self):
        # Web port-always int, defaults to 8080
        port = self.get_config_value("web_port", 8080)
        try:
            return int(port) if port else 8080
        except (ValueError, TypeError):
            return 8080
        
    @web_port.setter
    def web_port(self, value):
        # Set web port
        try:
            self.set_config_value("web_port", int(value) if value else 8080)
        except (ValueError, TypeError):
            self.set_config_value("web_port", 8080)
        
    def is_process_running(self, pid):
        # PID alive check
        return self._process_manager.is_process_running(pid)
        
    def write_pid_file(self, process_type, pid):
        # Write PID file
        return self._process_manager.write_pid_file(process_type, pid)
        
    def read_pid_file(self, process_type):
        # Read PID file
        return self._process_manager.read_pid_file(process_type)
        
    def remove_pid_file(self, process_type):
        # Delete PID file
        return self._process_manager.remove_pid_file(process_type)
        
    def is_component_running(self, process_type):
        # Component alive check
        return self._process_manager.is_component_running(process_type)
        
    def get_config_value(self, key, default=None):
        # Get config value
        return self._config_manager.get(key, default)
        
    def set_config_value(self, key, value):
        # Set and save config value
        return self._config_manager.set(key, value)
        
    def get_path(self, path_key):
        # Get path by key
        return self._paths_manager.get_path(path_key)

# Utility functions
def setup_module_logging(module_name):
    # Logging setup for modules-use this, not raw basicConfig
    try:
        from Modules.server_logging import get_component_logger
        logger = get_component_logger(module_name)
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        logger = logging.getLogger(module_name)

    if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
        logger.setLevel(logging.DEBUG)

    return logger

def setup_module_path():
    # Add project root to sys.path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, project_root)

def get_server_manager_dir():
    # Get SM dir from registry-falls back to script parent
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "ServerManagerPath")[0]
        winreg.CloseKey(key)
        return server_manager_dir.strip('"').strip()
    except Exception as e:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_manager_dir = os.path.dirname(script_dir)
        return server_manager_dir

def get_registry_value(key_path, value_name, default=None):
    # Generic registry value getter
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, key_path)
        value = winreg.QueryValueEx(key, value_name)[0]
        winreg.CloseKey(key)
        return value
    except Exception:
        return default

def ensure_directory_exists(directory_path):
    # Create dir if missing
    if not os.path.exists(directory_path):
        os.makedirs(directory_path, exist_ok=True)
    return directory_path

def get_absolute_path(relative_path):
    # Make path absolute
    if not os.path.isabs(relative_path):
        return os.path.abspath(relative_path)
    return relative_path

# Subprocess flags for Windows console hiding
def get_subprocess_creation_flags(hide_window=True, new_process_group=False):
    # Get creation flags for subprocess-Windows only
    import subprocess
    if sys.platform != 'win32':
        return 0
    flags = 0
    if hide_window:
        flags |= subprocess.CREATE_NO_WINDOW
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return flags

def should_hide_server_consoles(config=None):
    # Check hideServerConsoles config
    if config and 'configuration' in config:
        return config['configuration'].get('hideServerConsoles', True)
    return True

# JSON file I/O
def save_json_config(filepath, data, indent=4):
    # Write JSON with error handling
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=indent)
        return True
    except Exception as e:
        logger.error(f"JSON save failed: {filepath} - {e}")
        return False

def load_json_config(filepath, default=None):
    # Load JSON with fallback
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
        return default if default is not None else {}
    except Exception as e:
        logger.error(f"JSON load failed: {filepath} - {e}")
        return default if default is not None else {}

# Tkinter window positioning
def centre_window(window, width=None, height=None, parent=None):
    # Centre tkinter window on screen or relative to parent
    window.update_idletasks()
    if width and height:
        window_width, window_height = width, height
    else:
        window_width = window.winfo_width()
        window_height = window.winfo_height()
    
    if parent:
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2
    else:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
    
    window.geometry(f"{window_width}x{window_height}+{x}+{y}")

# Alias for backwards compat
center_window = centre_window

# Exports
__all__ = [
    'paths', 'process_manager', 'config_manager', 'system_utils', 'ServerManagerModule',
    'initialise_paths_from_registry', 'initialise_registry_values', 'REGISTRY_ROOT', 'REGISTRY_PATH',
    'setup_module_logging', 'setup_module_path', 'get_server_manager_dir', 'get_registry_value',
    'ensure_directory_exists', 'get_absolute_path', 'get_subprocess_creation_flags',
    'should_hide_server_consoles', 'save_json_config', 'load_json_config', 'centre_window', 'center_window'
]