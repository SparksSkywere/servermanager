# Common utilities for Server Manager
import os
import sys
import logging
import winreg
import datetime
import psutil
import json
import traceback

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.server_logging import get_component_logger

# Centralised registry constants-use these, not hardcoded strings
REGISTRY_ROOT = winreg.HKEY_LOCAL_MACHINE
REGISTRY_PATH = r"Software\SkywereIndustries\Servermanager"

# Global flags to prevent duplicate logging
_registry_values_initialized = False
_paths_initialized = False

# Logging setup - centralised in server_logging.py
logger: logging.Logger = get_component_logger("Common")

# Registry utilities
def initialise_paths_from_registry(registry_path):
    # Grab paths from registry - returns (success, dir, paths dict)
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
            "modules": os.path.join(server_manager_dir, "modules")
        }

        # Ensure directories exist (excluding config and data)
        for path_key, path in paths.items():
            if path_key not in ["config", "data"]:
                os.makedirs(path, exist_ok=True)

        logger.info(f"Paths initialised from registry: {server_manager_dir}")
        return True, server_manager_dir, paths

    except Exception as e:
        logger.error(f"Path init failed: {str(e)}")
        return False, None, {}

def initialise_registry_values(registry_path):
    # Pull config values from registry - SteamCmd path, web port, etc.
    global _registry_values_initialized
    try:
        # Read registry for all installation-managed values
        key = winreg.OpenKey(REGISTRY_ROOT, registry_path)

        registry_values = {}
        steam_cmd_path = None
        webserver_port = 8080

        # Try to get SteamCmd path
        try:
            steam_cmd_path = winreg.QueryValueEx(key, "SteamCmdPath")[0]
        except (FileNotFoundError, OSError):
            steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
            logger.warning(f"SteamCmd path not found in registry, using default: {steam_cmd_path}")

        # Try to get WebPort from registry
        try:
            webserver_port = int(winreg.QueryValueEx(key, "WebPort")[0])
        except (FileNotFoundError, OSError, ValueError):
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
            except (FileNotFoundError, OSError):
                pass

            # Try to get cluster configuration
            try:
                registry_values["ClusterCreated"] = winreg.QueryValueEx(key, "ClusterCreated")[0]
            except (FileNotFoundError, OSError):
                pass

        except Exception as e:
            logger.warning(f"Some registry values could not be read: {str(e)}")

        winreg.CloseKey(key)

        if not _registry_values_initialized:
            logger.debug("Registry values initialised successfully")
            _registry_values_initialized = True
        return True, steam_cmd_path, webserver_port, registry_values

    except Exception as e:
        logger.error(f"Failed to initialise registry values: {str(e)}")
        return False, None, 8080, {}

# Base class for modules that initialise from Windows registry
class RegistryModule:
    # Shared __init__ for SecurityManager, ServerOperations, and similar registry-backed classes
    def __init__(self):
        self.registry_path = REGISTRY_PATH
        self.server_manager_dir = None
        self.paths = {}
        self.initialise_from_registry()

    def initialise_from_registry(self) -> bool:
        return False

# Path management
class ServerManagerPaths:
    # Path resolver for all server manager directories - Falls back to script dir if registry fails
    def __init__(self):
        self.registry_path = REGISTRY_PATH
        self.server_manager_dir = None
        self.paths = {}
        self.initialised = False

        self.initialise_from_registry()

    def initialise_from_registry(self):
        # Try registry first-fallback kicks in if this fails
        global _paths_initialized
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
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules"),
                "modules": os.path.join(self.server_manager_dir, "Modules"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }

            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid"),
                "server_automation": os.path.join(self.paths["temp"], "server_automation.pid")
            }

            # Directories are now created in Start-ServerManager.pyw
            self.initialised = True
            if not _paths_initialized:
                logger.debug(f"Paths ready: {self.server_manager_dir}")
                _paths_initialized = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialise paths from registry: {str(e)}")

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
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules"),
                "modules": os.path.join(self.server_manager_dir, "Modules"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }

            # Define PID file paths
            self.pid_files = {
                "launcher": os.path.join(self.paths["temp"], "launcher.pid"),
                "webserver": os.path.join(self.paths["temp"], "webserver.pid"),
                "trayicon": os.path.join(self.paths["temp"], "trayicon.pid"),
                "dashboard": os.path.join(self.paths["temp"], "dashboard.pid"),
                "server_automation": os.path.join(self.paths["temp"], "server_automation.pid")
            }

            # Directories are now created in Start-ServerManager.pyw for verification purposes
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

# Process management
class ProcessManager:
    # Manages PID files and process lifecycle
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
            with open(pid_file, 'w', encoding='utf-8') as f:
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

            with open(pid_file, 'r', encoding='utf-8') as f:
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

# Configuration management
class ConfigManager:
    # Handles app config via database - Falls back to JSON migration if db empty
    def __init__(self, paths_manager):
        self.paths_manager = paths_manager
        self.config = {}

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
        if not self.config:
            self.load_config()
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
    # Quick system info helpers - CPU, memory, disk, process stats
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

# Global instances
paths = ServerManagerPaths()
process_manager = ProcessManager(paths)
config_manager = ConfigManager(paths)
system_utils = SystemUtils()

# Base module class
class ServerManagerModule:
    # Inherit from this for common functionality - Paths, config, PID management baked in
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
def setup_module_logging(module_name) -> logging.Logger:
    # Logging setup for modules - centralized in server_logging.py
    from Modules.core.server_logging import get_component_logger
    logger = get_component_logger(module_name)

    # Debug mode is handled by server_logging.py
    return logger

def setup_module_path():
    # Add project root to sys.path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, project_root)

# Database utilities
def get_database_connection(db_path=None):
    # Centralized database connection utility
    import sqlite3
    if db_path is None:
        # Default database path
        server_manager_dir = get_server_manager_dir()
        db_path = os.path.join(server_manager_dir, "data", "servermanager.db")

    try:
        conn = sqlite3.connect(db_path)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database at {db_path}: {e}")
        raise

def execute_database_query(conn, query, params=None, fetch=False):
    # Centralized database query execution with error handling
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        if fetch:
            return cursor.fetchall()
        else:
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Database query failed: {query} - {e}")
        raise

# Error handling utilities
def handle_database_error(operation, error, logger):
    # Centralized database error handling
    logger.error(f"Database {operation} failed: {error}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return False

def handle_generic_error(operation, error, logger):
    # Centralized generic error handling
    logger.error(f"{operation} failed: {error}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    return False

# Web utilities
def get_base_url(host='localhost', port=8080):
    # Get base URL with appropriate protocol based on SSL settings
    ssl_enabled = os.getenv("SSL_ENABLED", "false").lower() == "true"
    protocol = "https" if ssl_enabled else "http"
    return f"{protocol}://{host}:{port}"

def get_allowed_origins(host='localhost', port=8080):
    # Get allowed CORS origins for both HTTP and HTTPS
    return [
        f"http://{host}:{port}",
        f"https://{host}:{port}",
        f"http://127.0.0.1:{port}",
        f"https://127.0.0.1:{port}",
    ]

def get_node_url(ip, port=8080):
    # Get node URL with appropriate protocol
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port number: {port}")
    ssl_enabled = os.getenv("SSL_ENABLED", "false").lower() == "true"
    protocol = "https" if ssl_enabled else "http"
    return f"{protocol}://{ip}:{port}"

def validate_port(port):
    # Validate port number
    try:
        port = int(port)
        if 1 <= port <= 65535:
            return port
        else:
            raise ValueError(f"Port {port} is out of valid range (1-65535)")
    except (TypeError, ValueError):
        raise ValueError(f"Invalid port: {port}")

def get_server_manager_dir():
    # Get SM dir from registry-falls back to script parent
    from Modules.core.server_logging import get_server_manager_dir as _get_server_manager_dir
    return _get_server_manager_dir()

def get_registry_value(key_path, value_name, default=None):
    # Generic registry value getter
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, key_path)
        value = winreg.QueryValueEx(key, value_name)[0]
        winreg.CloseKey(key)
        return value
    except Exception:
        return default

def set_registry_value(key_path, value_name, value, value_type=winreg.REG_SZ):
    # Generic registry value setter
    try:
        key = winreg.CreateKey(REGISTRY_ROOT, key_path)
        winreg.SetValueEx(key, value_name, 0, value_type, value)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error(f"Failed to set registry value {value_name}: {e}")
        return False

def get_registry_values(key_path, value_names, defaults=None):
    # Batch registry value getter - reads multiple values in one key open
    defaults = defaults or {}
    result = {}
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, key_path)
        for name in value_names:
            try:
                result[name] = winreg.QueryValueEx(key, name)[0]
            except Exception:
                result[name] = defaults.get(name)
        winreg.CloseKey(key)
    except Exception:
        for name in value_names:
            result[name] = defaults.get(name)
    return result

def get_host_type():
    # Get host type from registry (Host, SubHost, standalone)
    return get_registry_value(REGISTRY_PATH, "HostType", "standalone")

def get_host_address():
    # Get host address from registry
    return get_registry_value(REGISTRY_PATH, "HostAddress", "")

def is_cluster_enabled():
    # Check if clustering is enabled
    return get_registry_value(REGISTRY_PATH, "ClusterEnabled", "false") == "true"

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

def is_admin():
    # Check if current process has administrator privileges
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

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

# Automation settings utilities
def get_automation_settings_fields():
    # Return the standard automation settings field names
    return {
        'motd_command': 'MotdCommand',
        'motd_message': 'MotdMessage',
        'motd_interval': 'MotdInterval',
        'start_command': 'StartCommand',
        'stop_command': 'StopCommand',
        'save_command': 'SaveCommand',
        'scheduled_restart_enabled': 'ScheduledRestartEnabled',
        'warning_command': 'WarningCommand',
        'warning_intervals': 'WarningIntervals',
        'warning_message_template': 'WarningMessageTemplate'
    }

def get_default_automation_settings():
    # Return default values for automation settings
    return {
        'MotdCommand': '',
        'MotdMessage': '',
        'MotdInterval': 0,
        'StartCommand': '',
        'StopCommand': '',
        'SaveCommand': '',
        'ScheduledRestartEnabled': False,
        'WarningCommand': '',
        'WarningIntervals': '30,15,10,5,1',
        'WarningMessageTemplate': 'Server restarting in {message}'
    }

def load_automation_settings(server_config):
    # Load automation settings from server config with defaults
    defaults = get_default_automation_settings()
    settings = {}

    for key, field_name in get_automation_settings_fields().items():
        settings[key] = server_config.get(field_name, defaults.get(field_name, ''))

    return settings

def save_automation_settings(server_config, automation_data):
    # Save automation settings to server config
    fields = get_automation_settings_fields()

    for key, value in automation_data.items():
        if key in fields:
            field_name = fields[key]
            # Convert interval to int if it's motd_interval
            if key == 'motd_interval':
                try:
                    server_config[field_name] = int(value) if value else 0
                except (ValueError, TypeError):
                    server_config[field_name] = 0
            else:
                server_config[field_name] = value

    return server_config

def send_command_to_server(server_name: str, command: str) -> bool:
    # Send a command to a running server via shared dispatch order:
    try:
        try:
            from services.persistent_stdin import send_command_to_stdin_pipe, is_stdin_pipe_available
            if is_stdin_pipe_available(server_name):
                result = send_command_to_stdin_pipe(server_name, command)
                if isinstance(result, tuple):
                    return result[0]
                return result
        except ImportError:
            pass
        try:
            from services.command_queue import queue_command, is_relay_active
            if is_relay_active(server_name):
                result = queue_command(server_name, command)
                if isinstance(result, tuple):
                    return result[0]
                return result
        except ImportError:
            pass
        try:
            from services.stdin_relay import send_command_via_relay
            result = send_command_via_relay(server_name, command)
            if isinstance(result, tuple):
                return result[0]
            return result
        except ImportError:
            pass
        logger.warning(f"No command input method available for {server_name}")
        return False
    except Exception as e:
        logger.error(f"Error sending command to {server_name}: {str(e)}")
        return False

def make_2fa_callbacks(user_manager, username, code_var, status_var, result, dialog):
    # Create shared on_verify/on_cancel/on_key_press callbacks for 2FA dialogs
    def on_verify():
        token = code_var.get().strip()
        if not token:
            status_var.set("Please enter the 6-digit code")
            return
        if len(token) != 6 or not token.isdigit():
            status_var.set("Code must be 6 digits")
            return
        if user_manager.verify_2fa(username, token):
            result[0] = True
            dialog.destroy()
        else:
            status_var.set("Invalid code. Please try again.")
            code_var.set("")

    def on_cancel():
        result[0] = False
        dialog.destroy()

    def on_key_press(event):
        if event.keysym == 'Return':
            on_verify()
        elif event.keysym == 'Escape':
            on_cancel()

    return on_verify, on_cancel, on_key_press

# Exports
__all__ = [
    'paths', 'process_manager', 'config_manager', 'system_utils', 'ServerManagerModule',
    'RegistryModule', 'make_2fa_callbacks',
    'initialise_paths_from_registry', 'initialise_registry_values', 'REGISTRY_ROOT', 'REGISTRY_PATH',
    'setup_module_logging', 'setup_module_path', 'get_server_manager_dir', 'get_registry_value',
    'ensure_directory_exists', 'get_absolute_path', 'is_admin', 'get_subprocess_creation_flags',
    'should_hide_server_consoles', 'centre_window',
    'get_automation_settings_fields', 'get_default_automation_settings', 'load_automation_settings', 'save_automation_settings',
    'get_database_connection', 'execute_database_query', 'handle_database_error', 'handle_generic_error',
    'get_base_url', 'get_allowed_origins', 'get_node_url', 'validate_port',
    'set_registry_value', 'get_registry_values', 'get_host_type', 'get_host_address', 'is_cluster_enabled',
    'send_command_to_server'
]

