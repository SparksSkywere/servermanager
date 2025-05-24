import os
import sys
import json
import logging
import winreg
import argparse
import time
from datetime import datetime
import ctypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("StopServer")

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

class ServerStopper:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.server_name = None
        self.force_stop = False
        self.timeout = 30
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Stop Game Server')
        parser.add_argument('server_name', help='Name of the server to stop')
        parser.add_argument('--force', action='store_true', help='Force stop the server')
        parser.add_argument('--timeout', type=int, default=30, help='Timeout in seconds for graceful shutdown')
        args = parser.parse_args()
        
        self.server_name = args.server_name
        self.force_stop = args.force
        self.timeout = args.timeout
        
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
            log_file = os.path.join(server_logs, "stop.log")
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
    
    def stop_server(self, config):
        """Stop the server process"""
        try:
            # Check if server has a PID
            if "PID" not in config or not config["PID"]:
                logger.warning("Server is not running (no PID found)")
                
                # Update status anyway
                config["Status"] = "Stopped"
                config["PID"] = None
                self.save_server_config(config)
                
                return True
            
            pid = config["PID"]
            logger.info(f"Stopping server with PID: {pid}")
            
            # Try to gracefully stop the process
            try:
                import psutil
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    
                    # Try graceful termination first
                    if not self.force_stop:
                        logger.info("Attempting graceful shutdown...")
                        process.terminate()
                        
                        # Wait for process to exit
                        try:
                            process.wait(timeout=self.timeout)
                            logger.info("Server stopped gracefully")
                        except psutil.TimeoutExpired:
                            logger.warning(f"Server did not stop gracefully within {self.timeout} seconds")
                            
                            if self.force_stop:
                                logger.info("Forcing server termination...")
                                process.kill()
                                logger.info("Server terminated forcefully")
                            else:
                                logger.error("Failed to stop server (timeout)")
                                return False
                    else:
                        # Force kill immediately
                        logger.info("Forcing server termination...")
                        process.kill()
                        logger.info("Server terminated forcefully")
                else:
                    logger.info(f"Process with PID {pid} does not exist")
            except Exception as e:
                logger.error(f"Error stopping process: {str(e)}")
                
                if self.force_stop:
                    # Try using os.kill as a last resort
                    try:
                        import signal
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(1)
                        os.kill(pid, signal.SIGKILL)
                    except Exception as e2:
                        logger.error(f"Error force killing process: {str(e2)}")
            
            # Update server configuration
            config["Status"] = "Stopped"
            config["PID"] = None
            self.save_server_config(config)
            
            # Remove PID from PIDS.txt
            self.remove_pid_from_file(pid)
            
            return True
            
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            return False
    
    def remove_pid_from_file(self, pid):
        """Remove PID from PIDS.txt file"""
        try:
            pids_file = os.path.join(self.server_manager_dir, "PIDS.txt")
            
            if os.path.exists(pids_file):
                with open(pids_file, 'r') as f:
                    lines = f.readlines()
                
                # Filter out the line with the PID
                new_lines = [line for line in lines if not line.startswith(f"{pid} ")]
                
                with open(pids_file, 'w') as f:
                    f.writelines(new_lines)
                
                logger.info(f"Removed PID {pid} from PIDS.txt")
        except Exception as e:
            logger.error(f"Error removing PID from file: {str(e)}")
    
    def run(self):
        """Main execution method"""
        try:
            logger.info(f"Stopping server: {self.server_name} (Force: {self.force_stop})")
            
            # Get server configuration
            config = self.get_server_config()
            if not config:
                logger.error("Failed to get server configuration")
                return 1
            
            # Stop the server
            if self.stop_server(config):
                logger.info("Server stopped successfully")
                return 0
            else:
                logger.error("Failed to stop server")
                return 1
            
        except Exception as e:
            logger.error(f"Error in server stopper: {str(e)}")
            return 1

def main():
    # Check for admin privileges
    if not is_admin():
        logger.warning("Administrator privileges required")
        run_as_admin()
    
    try:
        # Create and run stopper
        stopper = ServerStopper()
        return stopper.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
