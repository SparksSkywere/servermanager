# Logging management
import os
import sys
import traceback
import gzip
import shutil
import logging
import logging.handlers
import datetime
import time
import threading
import winreg
import json

# Registry constants
REGISTRY_ROOT = winreg.HKEY_LOCAL_MACHINE
REGISTRY_PATH = r"Software\SkywereIndustries\Servermanager"

DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
DEFAULT_MAX_SIZE = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3

def get_server_manager_dir():
    # Get SM dir from registry-falls back to script parent
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir.strip('"').strip()
    except Exception as e:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_manager_dir = os.path.dirname(script_dir)
        return server_manager_dir

def early_crash_log(component_name, message):
    # Emergency logging before LogManager exists
    try:
        server_manager_dir = get_server_manager_dir()
        logs_dir = os.path.join(server_manager_dir, "logs", "components")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, f"{component_name}.log")
        timestamp = datetime.datetime.now().strftime(DEFAULT_DATE_FORMAT)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {component_name} - STARTUP - {message}\n")
    except Exception:
        pass

class LogManager:
    # - Manages all logging
    # - Rotation, compression, stats tracking
    _main_logger_initialized = False

    def __init__(self):
        self.server_manager_dir = None
        self.paths = {}
        self.log_level = logging.INFO
        self.formatters = {}
        self.handlers = {}
        self.loggers = {}
        self._dashboard_logger: logging.Logger = logging.getLogger("temp")  # will be replaced in initialise
        self._setup_formatters()
        self._maintenance_thread = None
        self._maintenance_stop_event = threading.Event()
        self._log_stats = {
            'errors': 0,
            'warnings': 0,
            'last_reset': time.time()
        }

        self.initialise()

    def _setup_formatters(self):
        self.formatters = {
            "default": logging.Formatter(DEFAULT_LOG_FORMAT, DEFAULT_DATE_FORMAT),
            "detailed": logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s',
                DEFAULT_DATE_FORMAT
            ),
            "json": logging.Formatter(
                '{"timestamp": "%(asctime)s", "logger": "%(name)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(filename)s", "line": %(lineno)d}',
                DEFAULT_DATE_FORMAT
            )
        }

    def initialise(self):
        # Pull paths from registry
        self.server_manager_dir = get_server_manager_dir()

        self.paths = {
            "root": self.server_manager_dir,
            "logs": os.path.join(self.server_manager_dir, "logs")
        }

        # Directories are now created in Start-ServerManager.pyw

        # Setup main application logger
        self._setup_main_logger()

        # Initialize dashboard logger eagerly
        dashboard_log_file = os.path.join(self.paths["logs"], "components", "Dashboard.log")
        self._dashboard_logger = self.get_logger("dashboard", dashboard_log_file, formatter_name="detailed")

    def _setup_main_logger(self):
        if LogManager._main_logger_initialized:
            return

        main_log_file = os.path.join(self.paths["logs"], "components", "Main.log")
        self.main_logger = self.get_logger("servermanager.main", main_log_file, formatter_name="detailed")
        self.main_logger.info("LogManager initialised successfully")
        LogManager._main_logger_initialized = True

    def set_log_level(self, level_name):
        # Set the log level based on a string name
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }

        old_level = self.log_level
        self.log_level = level_map.get(level_name.upper(), logging.INFO)

        # Update existing loggers
        for logger in self.loggers.values():
            logger.setLevel(self.log_level)

        if hasattr(self, 'main_logger'):
            self.main_logger.info(f"Log level changed from {logging.getLevelName(old_level)} to {logging.getLevelName(self.log_level)}")

    def get_logger(self, name, log_file=None, level=None, formatter_name="default",
                  max_size=DEFAULT_MAX_SIZE, backup_count=DEFAULT_BACKUP_COUNT):
        # Get or create a logger with the specified configuration
        if name in self.loggers:
            return self.loggers[name]

        # Create new logger
        logger = logging.getLogger(name)
        logger.handlers.clear()  # Clear any existing handlers

        # Set level (use instance level if not specified)
        if level is None:
            level = self.log_level
        logger.setLevel(level)

        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(self.formatters.get(formatter_name, self.formatters["default"]))
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

        # Add file handler if specified
        if log_file:
            # If log_file is a relative path, use logs directory
            if not os.path.isabs(log_file):
                log_file = os.path.join(self.paths["logs"], log_file)

            # Ensure directory exists
            os.makedirs(os.path.dirname(log_file), exist_ok=True)

            # Create rotating file handler
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_size,
                backupCount=backup_count
            )
            file_handler.setFormatter(self.formatters.get(formatter_name, self.formatters["default"]))
            file_handler.setLevel(level)
            logger.addHandler(file_handler)

            # Store handler for later reference
            handler_key = f"{name}_{log_file}"
            self.handlers[handler_key] = file_handler

        # Prevent propagation to root logger
        logger.propagate = False

        # Store logger for later reference
        self.loggers[name] = logger

        return logger

    def get_server_logger(self, server_name):
        # Get a logger specifically for a server
        # Create server log directory
        server_log_dir = os.path.join(self.paths["logs"], "servers", server_name)
        os.makedirs(server_log_dir, exist_ok=True)

        # Use timestamp in log file name
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(server_log_dir, f"{timestamp}.log")

        return self.get_logger(f"server.{server_name}", log_file, formatter_name="detailed")

    def get_component_logger(self, component_name):
        # Get a logger for a specific component
        # Consolidate related components into shared log files to reduce log file count
        LOG_CONSOLIDATION = {
            # Dashboard-related logs -> Dashboard.log
            'Dashboard': 'Dashboard',
            'DashboardTracker': 'Dashboard',
            'DashboardFunctions': 'Dashboard',
            'SubhostDashboard': 'Dashboard',

            # Server management logs -> ServerManager.log
            'ServerManager': 'ServerManager',
            'ServerOperations': 'ServerManager',
            'ServerUpdateManager': 'ServerManager',
            'ServerConsole': 'ServerManager',
            'ServerManagerWebServer': 'ServerManager',
            'ServerManagerService': 'ServerManager',

            # Database logs -> Database.log
            'UserDatabase': 'Database',
            'SteamDatabase': 'Database',
            'MinecraftDatabase': 'Database',
            'ClusterDatabase': 'Database',
            'DatabaseUtils': 'Database',
            'AppIDScanner': 'Database',
            'MinecraftIDScanner': 'Database',
            'Authentication': 'Database',
            'SQL_Connection': 'Database',

            # Network/Cluster logs -> Network.log
            'Network': 'Network',
            'ClusterAPI': 'Network',
            'SimpleCluster': 'Network',
            'Agents': 'Network',

            # System services -> Services.log
            'Launcher': 'Services',
            'TrayIcon': 'Services',
            'WebServer': 'Services',
            'StopServerManager': 'Services',

            # Analytics/Monitoring -> Analytics.log
            'Analytics': 'Analytics',
            'SNMP': 'Analytics',
            'Grafana': 'Analytics',

            # Communication -> Communications.log
            'Notifications': 'Communications',
            'MailServer': 'Communications',

            # Common utilities -> Common.log
            'Common': 'Common',

            # User management -> UserManagement.log
            'UserManagement': 'UserManagement',

            # Minecraft specific -> Minecraft.log
            'Minecraft': 'Minecraft',

            # Scheduling -> Scheduler.log
            'Scheduler': 'Scheduler',

            # Verification tools -> ServerVerifier.log
            'ServerVerifier': 'ServerVerifier',
        }

        # Get consolidated log file name, or use component name if not mapped
        log_filename = LOG_CONSOLIDATION.get(component_name, component_name)
        log_file = os.path.join(self.paths["logs"], "components", f"{log_filename}.log")

        # Use a unique logger name but shared log file
        return self.get_logger(f"component.{component_name}", log_file, formatter_name="detailed")

    def get_debug_logger(self, debug_module_name="debug"):
        # Get a logger for debug modules that writes to logs/debug/ directory
        # Ensure debug directory exists
        debug_dir = os.path.join(self.paths["logs"], "debug")
        os.makedirs(debug_dir, exist_ok=True)

        log_file = os.path.join(debug_dir, f"{debug_module_name}.log")
        return self.get_logger(f"debug.{debug_module_name}", log_file, formatter_name="detailed")

    def get_error_logger(self):
        if "errors" not in self.loggers:
            log_file = os.path.join(self.paths["logs"], "components", "Errors.log")
            logger = self.get_logger("errors", log_file, formatter_name="detailed", level=logging.ERROR)
            return logger
        return self.loggers["errors"]

    def get_dashboard_logger(self):
        return self._dashboard_logger

    def configure_dashboard_logging(self, debug_mode=False, config=None):
        # Configure logging specifically for the dashboard
        try:
            # Get dashboard logger
            dashboard_logger = self.get_dashboard_logger()

            # Set log level based on debug mode and config
            if debug_mode:
                self.set_log_level("DEBUG")
                dashboard_logger.setLevel(logging.DEBUG)
            else:
                log_level = "INFO"
                if config and "logging" in config and "logLevel" in config["logging"]:
                    log_level = config["logging"]["logLevel"]
                self.set_log_level(log_level)
                dashboard_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

            dashboard_logger.info("Dashboard logging configured successfully")
            return True

        except Exception as e:
            print(f"Failed to configure dashboard logging: {str(e)}")
            return False

    def write_pid_file(self, process_type, pid, temp_path):
        # Write process ID to file
        try:
            pid_file = os.path.join(temp_path, f"{process_type}.pid")

            # Create PID info dictionary
            pid_info = {
                "ProcessId": pid,
                "StartTime": datetime.datetime.now().isoformat(),
                "ProcessType": process_type
            }

            # Write PID info to file as JSON
            with open(pid_file, 'w', encoding='utf-8') as f:
                json.dump(pid_info, f)

            dashboard_logger = self.get_dashboard_logger()
            dashboard_logger.debug(f"PID file created for {process_type}: {pid}")
            return True

        except Exception as e:
            dashboard_logger = self.get_dashboard_logger()
            dashboard_logger.error(f"Failed to write PID file for {process_type}: {str(e)}")
            return False

    def log_server_action(self, server_name, action, result="SUCCESS", details=None):
        # Log server-related actions
        dashboard_logger = self.get_dashboard_logger()

        msg = f"Server: {server_name} | Action: {action} | Result: {result}"
        if details:
            msg += f" | Details: {details}"

        if result == "SUCCESS":
            dashboard_logger.info(msg)
        elif result == "WARNING":
            dashboard_logger.warning(msg)
        else:
            dashboard_logger.error(msg)

    def log_installation_progress(self, server_name, stage, message):
        # Log server installation progress
        dashboard_logger = self.get_dashboard_logger()
        dashboard_logger.info(f"Installation [{server_name}] {stage}: {message}")

    def log_process_monitoring(self, message, level="INFO"):
        # Log process monitoring events
        dashboard_logger = self.get_dashboard_logger()

        if level.upper() == "DEBUG":
            dashboard_logger.debug(f"Process Monitor: {message}")
        elif level.upper() == "WARNING":
            dashboard_logger.warning(f"Process Monitor: {message}")
        elif level.upper() == "ERROR":
            dashboard_logger.error(f"Process Monitor: {message}")
        else:
            dashboard_logger.info(f"Process Monitor: {message}")

    def log_dashboard_event(self, event_type, message, level="INFO"):
        # Log general dashboard events
        dashboard_logger = self.get_dashboard_logger()

        formatted_msg = f"[{event_type}] {message}"

        if level.upper() == "DEBUG":
            dashboard_logger.debug(formatted_msg)
        elif level.upper() == "WARNING":
            dashboard_logger.warning(formatted_msg)
        elif level.upper() == "ERROR":
            dashboard_logger.error(formatted_msg)
        elif level.upper() == "CRITICAL":
            dashboard_logger.critical(formatted_msg)
        else:
            dashboard_logger.info(formatted_msg)

    def log_system_state(self, component, state, details=None):
        # Log system state changes
        if hasattr(self, 'main_logger'):
            msg = f"Component: {component} | State: {state}"
            if details:
                msg += f" | Details: {details}"
            self.main_logger.info(msg)

    def compress_old_logs(self, max_age_days=7):
        # Compress log files older than the specified age
        try:
            compressed_count = 0

            # Walk through all log directories
            for log_dir in [self.paths["logs"]]:
                for root, dirs, files in os.walk(log_dir):
                    for file in files:
                        if file.endswith('.log') and not file.endswith('.gz'):
                            file_path = os.path.join(root, file)

                            # Check file age
                            file_age = time.time() - os.path.getmtime(file_path)
                            max_age_seconds = max_age_days * 24 * 60 * 60

                            if file_age > max_age_seconds:
                                try:
                                    # Compress file
                                    compressed_path = f"{file_path}.gz"

                                    with open(file_path, 'rb') as f_in:
                                        with gzip.open(compressed_path, 'wb') as f_out:
                                            shutil.copyfileobj(f_in, f_out)

                                    # Verify compression and remove original
                                    if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 0:
                                        os.remove(file_path)
                                        compressed_count += 1
                                        if hasattr(self, 'main_logger'):
                                            self.main_logger.info(f"Compressed log file: {file_path}")
                                except Exception as e:
                                    if hasattr(self, 'main_logger'):
                                        self.main_logger.error(f"Failed to compress {file_path}: {str(e)}")

            if hasattr(self, 'main_logger'):
                self.main_logger.info(f"Log compression completed. Compressed {compressed_count} files.")
            return True

        except Exception as e:
            if hasattr(self, 'main_logger'):
                self.main_logger.error(f"Error in log compression: {str(e)}")
            return False

    def delete_old_logs(self, max_age_days=30):
        # Delete log files older than the specified age
        try:
            deleted_count = 0

            # Walk through all log directories
            for log_dir in [self.paths["logs"]]:
                for root, dirs, files in os.walk(log_dir):
                    for file in files:
                        if file.endswith('.log') or file.endswith('.gz'):
                            file_path = os.path.join(root, file)

                            # Check file age
                            file_age = time.time() - os.path.getmtime(file_path)
                            max_age_seconds = max_age_days * 24 * 60 * 60

                            if file_age > max_age_seconds:
                                try:
                                    os.remove(file_path)
                                    deleted_count += 1
                                    if hasattr(self, 'main_logger'):
                                        self.main_logger.info(f"Deleted old log file: {file_path}")
                                except Exception as e:
                                    if hasattr(self, 'main_logger'):
                                        self.main_logger.error(f"Failed to delete {file_path}: {str(e)}")

            if hasattr(self, 'main_logger'):
                self.main_logger.info(f"Log cleanup completed. Deleted {deleted_count} files.")
            return True

        except Exception as e:
            if hasattr(self, 'main_logger'):
                self.main_logger.error(f"Error in log cleanup: {str(e)}")
            return False

    def log_exception(self, logger, message="An exception occurred", exc_info=None):
        # Log an exception with traceback
        if exc_info is None:
            exc_info = sys.exc_info()

        exc_type, exc_value, exc_traceback = exc_info

        if exc_type is not None:
            # Format the traceback
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            tb_text = ''.join(tb_lines)

            # Log the exception
            logger.error(f"{message}: {exc_value}\n{tb_text}")

            # Also log to error logger
            error_logger = self.get_error_logger()
            error_logger.error(f"{message}: {exc_value}\n{tb_text}")

            # Update stats
            self._log_stats['errors'] += 1
        else:
            logger.error(message)

    def get_log_statistics(self):
        # Get logging statistics
        current_time = time.time()
        uptime = current_time - self._log_stats['last_reset']

        stats = {
            'uptime_seconds': uptime,
            'errors': self._log_stats['errors'],
            'warnings': self._log_stats['warnings'],
            'active_loggers': len(self.loggers),
            'log_directories': list(self.paths.keys())
        }

        return stats

    def start_log_maintenance(self, compress_interval=86400, delete_interval=604800):
        # Start a background thread for log maintenance
        self._maintenance_stop_event.clear()

        def maintenance_thread():
            if hasattr(self, 'main_logger'):
                self.main_logger.info("Log maintenance thread started")

            while not self._maintenance_stop_event.is_set():
                try:
                    # Compress logs
                    self.compress_old_logs()

                    # Delete old logs
                    self.delete_old_logs()

                    # Log statistics
                    stats = self.get_log_statistics()
                    if hasattr(self, 'main_logger'):
                        self.main_logger.info(f"Maintenance completed. Stats: {stats}")

                    # Wait until next maintenance (interruptible)
                    self._maintenance_stop_event.wait(compress_interval)

                except Exception as e:
                    if hasattr(self, 'main_logger'):
                        self.log_exception(self.main_logger, "Error in log maintenance thread")
                    self._maintenance_stop_event.wait(3600)  # Wait an hour on error (interruptible)

        # Stop existing maintenance thread if running
        if self._maintenance_thread and self._maintenance_thread.is_alive():
            if hasattr(self, 'main_logger'):
                self.main_logger.warning("Stopping existing maintenance thread")

        # Start new thread
        self._maintenance_thread = threading.Thread(target=maintenance_thread, daemon=True)
        self._maintenance_thread.start()

        return self._maintenance_thread

    def shutdown(self):
        # Gracefully shutdown the log manager
        if hasattr(self, 'main_logger'):
            self.main_logger.info("LogManager shutting down...")

        # Close all handlers
        for logger in self.loggers.values():
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

        # Clear references
        self.loggers.clear()
        self.handlers.clear()

# Create global instance - eager initialization
_log_manager = LogManager()

def _get_log_manager():
    return _log_manager

# Export functions for easy access
def get_logger(name, log_file=None, level=None, formatter_name="default",
               max_size=DEFAULT_MAX_SIZE, backup_count=DEFAULT_BACKUP_COUNT):
    return _get_log_manager().get_logger(name, log_file, level, formatter_name, max_size, backup_count)
def get_server_logger(server_name):
    return _get_log_manager().get_server_logger(server_name)
def get_component_logger(component_name) -> logging.Logger:
    return _get_log_manager().get_component_logger(component_name)
def get_debug_logger(debug_module_name="debug"):
    return _get_log_manager().get_debug_logger(debug_module_name)
def get_error_logger():
    return _get_log_manager().get_error_logger()
def get_dashboard_logger() -> logging.Logger:
    return _get_log_manager().get_dashboard_logger()
def log_exception(logger, message="An exception occurred", exc_info=None):
    _get_log_manager().log_exception(logger, message, exc_info)
def log_system_state(component, state, details=None):
    _get_log_manager().log_system_state(component, state, details)
def start_log_maintenance():
    return _get_log_manager().start_log_maintenance()
def get_log_statistics():
    return _get_log_manager().get_log_statistics()
def configure_dashboard_logging(debug_mode=False, config=None):
    return _get_log_manager().configure_dashboard_logging(debug_mode, config)
def write_pid_file(process_type, pid, temp_path):
    return _get_log_manager().write_pid_file(process_type, pid, temp_path)
def log_server_action(server_name, action, result="SUCCESS", details=None):
    _get_log_manager().log_server_action(server_name, action, result, details)
def log_installation_progress(server_name, stage, message):
    _get_log_manager().log_installation_progress(server_name, stage, message)
def log_process_monitoring(message, level="INFO"):
    _get_log_manager().log_process_monitoring(message, level)
def log_dashboard_event(event_type, message, level="INFO"):
    _get_log_manager().log_dashboard_event(event_type, message, level)
