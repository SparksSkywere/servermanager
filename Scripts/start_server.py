import os
import sys
import json
import logging
import winreg
import argparse
import subprocess
import time
from datetime import datetime
import ctypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("StartServer")

def is_admin():
    """Check if the script is running with administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    """Re-run the script with admin privileges"""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

class ServerStarter:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.server_name = None
        self.params = {}
        self.no_window = False
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Start Game Server')
        parser.add_argument('server_name', help='Name of the server to start')
        parser.add_argument('--no-window', action='store_true', help='Start server without a window')
        parser.add_argument('--param', action='append', nargs=2, metavar=('KEY', 'VALUE'), 
                          help='Additional launch parameters in format: --param key value')
        args = parser.parse_args()
        
        self.server_name = args.server_name
        self.no_window = args.no_window
        
        # Convert parameters to dictionary
        if args.param:
            self.params = {key: value for key, value in args.param}
        
        # Initialize paths
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
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Ensure server logs directory exists
            server_logs = os.path.join(self.paths["logs"], self.server_name)
            os.makedirs(server_logs, exist_ok=True)
            
            # Set up file logging
            log_file = os.path.join(server_logs, "start.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
    
    def get_server_config(self):
        """Get server configuration from JSON file"""
        try:
            config_path = os.path.join(self.paths["servers"], f"{self.server_name}.json")
            
            if not os.path.exists(config_path):
                logger.error(f"Server configuration not found: {config_path}")
                return None
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Validate configuration
            required_fields = ["Name", "InstallPath", "ExecutablePath"]
            for field in required_fields:
                if field not in config:
                    logger.error(f"Missing required field in server configuration: {field}")
                    return None
            
            return config
            
        except Exception as e:
            logger.error(f"Error loading server configuration: {str(e)}")
            return None
    
    def save_server_config(self, config):
        """Save server configuration to JSON file"""
        try:
            config_path = os.path.join(self.paths["servers"], f"{self.server_name}.json")
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
            
            logger.info("Server configuration saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error saving server configuration: {str(e)}")
            return False
    
    def is_server_running(self, pid):
        """Check if a server is already running"""
        if not pid:
            return False
        
        try:
            import psutil
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                return process.is_running() and not process.status() == psutil.STATUS_ZOMBIE
            return False
        except Exception as e:
            logger.error(f"Error checking if server is running: {str(e)}")
            return False
    
    def start_server(self, config):
        """Start the server process"""
        try:
            # Check if server is already running
            if "PID" in config and self.is_server_running(config["PID"]):
                logger.warning(f"Server is already running with PID: {config['PID']}")
                return True
            
            # Get executable path
            exe_path = config["ExecutablePath"]
            if not os.path.isabs(exe_path):
                exe_path = os.path.join(config["InstallPath"], exe_path)
            
            if not os.path.exists(exe_path):
                logger.error(f"Server executable not found: {exe_path}")
                return False
            
            # Get launch parameters
            launch_params = config.get("LaunchParameters", "")
            
            # Add additional parameters if specified
            if self.params:
                for key, value in self.params.items():
                    # Check if parameter already exists
                    param_pattern = f"{key} "
                    if param_pattern in launch_params:
                        # Replace existing parameter
                        import re
                        launch_params = re.sub(f"{key}\\s+[\\w\\d\\-]+", f"{key} {value}", launch_params)
                    else:
                        # Add new parameter
                        launch_params += f" {key} {value}"
            
            # Prepare log files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(self.paths["logs"], self.server_name)
            stdout_log = os.path.join(log_dir, f"stdout_{timestamp}.log")
            stderr_log = os.path.join(log_dir, f"stderr_{timestamp}.log")
            
            # Start the server process
            logger.info(f"Starting server: {self.server_name}")
            logger.info(f"Executable: {exe_path}")
            logger.info(f"Working directory: {config['InstallPath']}")
            logger.info(f"Launch parameters: {launch_params}")
            
            if self.no_window:
                # Start without window
                process = subprocess.Popen(
                    [exe_path] + launch_params.split(),
                    stdout=open(stdout_log, 'w'),
                    stderr=open(stderr_log, 'w'),
                    cwd=config["InstallPath"],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Start with window
                process = subprocess.Popen(
                    [exe_path] + launch_params.split(),
                    cwd=config["InstallPath"]
                )
            
            pid = process.pid
            logger.info(f"Server started with PID: {pid}")
            
            # Update configuration with PID and status
            config["PID"] = pid
            config["Status"] = "Running"
            config["LastStartTime"] = datetime.now().isoformat()
            self.save_server_config(config)
            
            # Add PID to PIDS.txt
            pids_file = os.path.join(self.server_manager_dir, "PIDS.txt")
            with open(pids_file, 'a+') as f:
                f.write(f"{pid} - {self.server_name}\n")
            
            return True
            
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            return False
    
    def run(self):
        """Main execution method"""
        try:
            logger.info(f"Starting server: {self.server_name}")
            
            # Get server configuration
            config = self.get_server_config()
            if not config:
                logger.error("Failed to get server configuration")
                return 1
            
            # Start the server
            if self.start_server(config):
                logger.info("Server started successfully")
                return 0
            else:
                logger.error("Failed to start server")
                return 1
            
        except Exception as e:
            logger.error(f"Error in server starter: {str(e)}")
            return 1

def main():
    # Check for admin privileges
    if not is_admin():
        logger.warning("Administrator privileges required")
        run_as_admin()
    
    try:
        # Create and run starter
        starter = ServerStarter()
        return starter.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
