import os
import sys
import json
import time
import logging
import winreg
import argparse
import subprocess
import ctypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("StopAllServers")

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
        self.pids_file = None
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Stop All Game Servers')
        parser.add_argument('--force', action='store_true', help='Force stop all servers')
        parser.add_argument('--timeout', type=int, default=30, help='Timeout in seconds for graceful shutdown')
        args = parser.parse_args()
        
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
                
            # Define PIDS.txt file path
            self.pids_file = os.path.join(self.server_manager_dir, "PIDS.txt")
            
            # Set up file logging
            log_file = os.path.join(self.paths["logs"], "stop-all-servers.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
    
    def get_server_list(self):
        """Get list of servers from configuration directory"""
        try:
            servers = []
            servers_dir = self.paths["servers"]
            
            if os.path.exists(servers_dir):
                for filename in os.listdir(servers_dir):
                    if filename.endswith(".json"):
                        try:
                            with open(os.path.join(servers_dir, filename), 'r') as f:
                                server_config = json.load(f)
                                server_name = server_config.get("Name")
                                if server_name:
                                    servers.append(server_name)
                        except Exception as e:
                            logger.error(f"Error loading server configuration {filename}: {str(e)}")
            
            # Also check PIDS.txt for any running servers
            if os.path.exists(self.pids_file):
                try:
                    with open(self.pids_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split(' - ', 1)
                            if len(parts) >= 2:
                                server_name = parts[1]
                                if server_name not in servers:
                                    servers.append(server_name)
                except Exception as e:
                    logger.error(f"Error reading PIDS.txt: {str(e)}")
            
            logger.info(f"Found {len(servers)} servers to stop")
            return servers
            
        except Exception as e:
            logger.error(f"Error getting server list: {str(e)}")
            return []
    
    def stop_server(self, server_name):
        """Stop a specific server"""
        try:
            logger.info(f"Stopping server: {server_name}")
            
            # Call the stop_server.py script
            stop_script = os.path.join(self.paths["root"], "scripts", "stop_server.py")
            
            if os.path.exists(stop_script):
                cmd = [sys.executable, stop_script, server_name]
                if self.force_stop:
                    cmd.append("--force")
                cmd.extend(["--timeout", str(self.timeout)])
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"Failed to stop server {server_name}: {result.stderr}")
                    return False
                
                logger.info(f"Server {server_name} stopped successfully")
                return True
            else:
                logger.error(f"Stop server script not found: {stop_script}")
                
                # Fallback method: Try to find PID in PIDS.txt and kill directly
                if os.path.exists(self.pids_file):
                    with open(self.pids_file, 'r') as f:
                        lines = f.readlines()
                    
                    for line in lines:
                        if f" - {server_name}" in line:
                            try:
                                pid = int(line.split(' - ')[0].strip())
                                logger.info(f"Found PID {pid} for server {server_name}, stopping directly")
                                
                                import psutil
                                if psutil.pid_exists(pid):
                                    process = psutil.Process(pid)
                                    process.terminate()
                                    
                                    # Wait for process to exit
                                    try:
                                        process.wait(timeout=self.timeout)
                                    except psutil.TimeoutExpired:
                                        if self.force_stop:
                                            process.kill()
                                    
                                    logger.info(f"Directly terminated process for server {server_name}")
                                    return True
                            except Exception as e:
                                logger.error(f"Error stopping process for server {server_name}: {str(e)}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error stopping server {server_name}: {str(e)}")
            return False
    
    def clear_pids_file(self):
        """Clear the PIDS.txt file"""
        try:
            if os.path.exists(self.pids_file):
                with open(self.pids_file, 'w') as f:
                    pass  # Empty the file
                logger.info("Cleared PIDS.txt file")
        except Exception as e:
            logger.error(f"Error clearing PIDS.txt: {str(e)}")
    
    def run(self):
        """Main execution method"""
        try:
            logger.info("Starting to stop all servers")
            
            # Get list of servers
            servers = self.get_server_list()
            if not servers:
                logger.info("No servers found to stop")
                return 0
            
            # Stop each server
            success_count = 0
            for server_name in servers:
                if self.stop_server(server_name):
                    success_count += 1
                    
                # Add a small delay between stops to prevent resource contention
                time.sleep(1)
            
            # Clear the PIDS file after stopping all servers
            self.clear_pids_file()
            
            logger.info(f"Stopped {success_count} of {len(servers)} servers")
            return 0
            
        except Exception as e:
            logger.error(f"Error stopping servers: {str(e)}")
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
