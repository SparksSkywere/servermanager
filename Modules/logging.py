import os
import sys
import json
import logging
import datetime
import threading
import winreg
from pathlib import Path

# Default logging format
DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT = 5

class LogManager:
    """Class for managing logs with rotation and compression"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.log_level = logging.INFO
        self.formatters = {}
        self.handlers = {}
        self.loggers = {}
        
        # Initialize from registry
        self.initialize()
    
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
        except Exception as e:
            logging.error(f"Failed to initialize log manager from registry: {str(e)}")
            
            # Use a fallback path
            self.server_manager_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
    
    def set_log_level(self, level_name):
        """Set the log level based on a string name"""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        
        self.log_level = level_map.get(level_name.upper(), logging.INFO)
        
        # Update existing loggers
        for logger in self.loggers.values():
            logger.setLevel(self.log_level)
    
    def get_logger(self, name, log_file=None, level=None, formatter_name="default", 
                  max_size=DEFAULT_MAX_SIZE, backup_count=DEFAULT_BACKUP_COUNT):
        """Get or create a logger with the specified configuration"""
        if name in self.loggers:
            return self.loggers[name]
        
        # Create new logger
        logger = logging.getLogger(name)
        
        # Set level (use instance level if not specified)
        if level is None:
            level = self.log_level
        logger.setLevel(level)
        
        # Add console handler if it doesn't already have one
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(self.formatters.get(formatter_name, self.formatters["default"]))
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
            logger.addHandler(file_handler)
            
            # Store handler for later reference
            handler_key = f"{name}_{log_file}"
            self.handlers[handler_key] = file_handler
        
        # Store logger for later reference
        self.loggers[name] = logger
        
        return logger
    
    def get_server_logger(self, server_name):
        """Get a logger specifically for a server"""
        # Create server log directory
        server_log_dir = os.path.join(self.paths["logs"], server_name)
        os.makedirs(server_log_dir, exist_ok=True)
        
        # Use timestamp in log file name
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        log_file = os.path.join(server_log_dir, f"{timestamp}.log")
        
        return self.get_logger(f"server.{server_name}", log_file)
    
    def get_component_logger(self, component_name):
        """Get a logger for a specific component"""
        log_file = os.path.join(self.paths["logs"], f"{component_name}.log")
        return self.get_logger(f"component.{component_name}", log_file)
    
    def compress_old_logs(self, max_age_days=7):
        """Compress log files older than the specified age"""
        try:
            logs_dir = self.paths["logs"]
            
            # Get current time
            now = time.time()
            max_age_seconds = max_age_days * 24 * 60 * 60
            
            # Walk through log directory
            for root, dirs, files in os.walk(logs_dir):
                for file in files:
                    if file.endswith('.log') and not file.endswith('.gz'):
                        file_path = os.path.join(root, file)
                        
                        # Check file age
                        file_age = now - os.path.getmtime(file_path)
                        
                        if file_age > max_age_seconds:
                            # Compress file
                            compressed_path = f"{file_path}.gz"
                            
                            with open(file_path, 'rb') as f_in:
                                with gzip.open(compressed_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            
                            # Remove original file if compression was successful
                            if os.path.exists(compressed_path):
                                os.remove(file_path)
                                print(f"Compressed old log file: {file_path}")
            
            return True
        except Exception as e:
            print(f"Error compressing old logs: {str(e)}")
            return False
    
    def delete_old_logs(self, max_age_days=30):
        """Delete log files older than the specified age"""
        try:
            logs_dir = self.paths["logs"]
            
            # Get current time
            now = time.time()
            max_age_seconds = max_age_days * 24 * 60 * 60
            
            # Walk through log directory
            for root, dirs, files in os.walk(logs_dir):
                for file in files:
                    if file.endswith('.log') or file.endswith('.gz'):
                        file_path = os.path.join(root, file)
                        
                        # Check file age
                        file_age = now - os.path.getmtime(file_path)
                        
                        if file_age > max_age_seconds:
                            # Delete file
                            os.remove(file_path)
                            print(f"Deleted old log file: {file_path}")
            
            return True
        except Exception as e:
            print(f"Error deleting old logs: {str(e)}")
            return False
    
    def log_exception(self, logger, message="An exception occurred"):
        """Log an exception with traceback"""
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        if exc_type is not None:
            # Format the traceback
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            tb_text = ''.join(tb_lines)
            
            # Log the exception
            logger.error(f"{message}: {exc_value}\n{tb_text}")
        else:
            logger.error(message)
    
    def start_log_maintenance(self, compress_interval=86400, delete_interval=604800):
        """Start a background thread for log maintenance"""
        def maintenance_thread():
            while True:
                try:
                    # Compress logs
                    self.compress_old_logs()
                    
                    # Delete old logs
                    self.delete_old_logs()
                    
                    # Sleep until next maintenance
                    time.sleep(compress_interval)
                except Exception as e:
                    print(f"Error in log maintenance thread: {str(e)}")
                    time.sleep(3600)  # Sleep for an hour on error
        
        # Start thread
        t = threading.Thread(target=maintenance_thread, daemon=True)
        t.start()
        
        return t

# Create global instance
log_manager = LogManager()

# Export functions for easy access
def get_logger(name, log_file=None, level=None, formatter_name="default", 
               max_size=DEFAULT_MAX_SIZE, backup_count=DEFAULT_BACKUP_COUNT):
    return log_manager.get_logger(name, log_file, level, formatter_name, max_size, backup_count)

def get_server_logger(server_name):
    return log_manager.get_server_logger(server_name)

def get_component_logger(component_name):
    return log_manager.get_component_logger(component_name)

def log_exception(logger, message="An exception occurred"):
    log_manager.log_exception(logger, message)
