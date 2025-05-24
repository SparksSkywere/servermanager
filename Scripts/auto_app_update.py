import os
import sys
import json
import time
import logging
import argparse
import subprocess
import datetime
import winreg
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("AutoAppUpdate")

class AutoUpdater:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.steam_cmd_path = None
        self.paths = {}
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Auto Update Steam Game Servers')
        parser.add_argument('--check', action='store_true', help='Only check for updates without applying them')
        parser.add_argument('--force', action='store_true', help='Force update even if server is running')
        parser.add_argument('--server', help='Specific server to update')
        parser.add_argument('--log', help='Log file path')
        args = parser.parse_args()
        
        self.check_only = args.check
        self.force_update = args.force
        self.specific_server = args.server
        
        # Initialize paths and set up logging
        self.initialize()
        
        # Configure file logging
        log_file = args.log if args.log else os.path.join(self.paths["logs"], "auto-app-update.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            steam_cmd_dir = winreg.QueryValueEx(key, "SteamCMDPath")[0]
            self.steam_cmd_path = os.path.join(steam_cmd_dir, "steamcmd.exe")
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            logger.info(f"SteamCMD path: {self.steam_cmd_path}")
            
            # Validate SteamCMD path
            if not os.path.exists(self.steam_cmd_path):
                logger.error(f"SteamCMD not found at: {self.steam_cmd_path}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
    
    def get_server_list(self):
        """Get list of servers to check for updates"""
        try:
            servers_dir = self.paths["servers"]
            servers = []
            
            # If specific server was requested, only check that one
            if self.specific_server:
                server_path = os.path.join(servers_dir, f"{self.specific_server}.json")
                if os.path.exists(server_path):
                    try:
                        with open(server_path, 'r') as f:
                            server_config = json.load(f)
                            if server_config.get("AppId") and server_config.get("InstallPath"):
                                servers.append(server_config)
                            else:
                                logger.warning(f"Server {self.specific_server} has invalid configuration")
                    except Exception as e:
                        logger.error(f"Error loading server configuration: {str(e)}")
                else:
                    logger.error(f"Server configuration not found: {self.specific_server}")
            else:
                # Look for all server configurations
                if os.path.exists(servers_dir):
                    for filename in os.listdir(servers_dir):
                        if filename.endswith(".json"):
                            try:
                                with open(os.path.join(servers_dir, filename), 'r') as f:
                                    server_config = json.load(f)
                                    if server_config.get("AppId") and server_config.get("InstallPath"):
                                        if server_config.get("AutoUpdate", True):  # Only include servers with auto-update enabled
                                            servers.append(server_config)
                            except Exception as e:
                                logger.error(f"Error loading server configuration {filename}: {str(e)}")
                
            logger.info(f"Found {len(servers)} servers to check for updates")
            return servers
            
        except Exception as e:
            logger.error(f"Error getting server list: {str(e)}")
            return []
    
    def check_for_update(self, app_id):
        """Check if an update is available for the given AppID"""
        try:
            logger.info(f"Checking for updates for AppID: {app_id}")
            
            # Run SteamCMD to check for updates
            cmd = [
                self.steam_cmd_path,
                "+login", "anonymous",
                "+app_info_update", "1",
                "+app_info_print", app_id,
                "+quit"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Check if there was an error
            if result.returncode != 0:
                logger.error(f"SteamCMD returned error code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False
            
            # Look for update indicators in the output
            update_indicators = [
                "update state",
                "needs update",
                "downloading update",
                "update available"
            ]
            
            for line in result.stdout.lower().split('\n'):
                for indicator in update_indicators:
                    if indicator in line and "false" not in line and "0" not in line:
                        logger.info(f"Update available for AppID: {app_id}")
                        return True
            
            logger.info(f"No updates available for AppID: {app_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error checking for updates: {str(e)}")
            return False
    
    def update_server(self, server):
        """Update a server using SteamCMD"""
        try:
            app_id = server.get("AppId")
            install_path = server.get("InstallPath")
            server_name = server.get("Name", "Unknown")
            
            logger.info(f"Updating server: {server_name} (AppID: {app_id})")
            
            # First check if server is running
            if self.is_server_running(server):
                if not self.force_update:
                    logger.warning(f"Server {server_name} is running. Use --force to update anyway.")
                    return False
                
                # Stop the server first
                logger.info(f"Force-stopping server: {server_name}")
                self.stop_server(server)
                time.sleep(5)  # Give it time to fully stop
            
            # Create timestamp for log file
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(self.paths["logs"], f"update_{server_name}_{timestamp}.log")
            
            # Prepare SteamCMD command
            cmd = [
                self.steam_cmd_path,
                "+login", "anonymous",
                "+force_install_dir", install_path,
                "+app_update", app_id, "validate",
                "+quit"
            ]
            
            logger.info(f"Running update command: {' '.join(cmd)}")
            
            # Run the update
            with open(log_file, 'w') as f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True
                )
                
                # Capture and log output in real-time
                for line in iter(process.stdout.readline, ''):
                    f.write(line)
                    f.flush()
                    line = line.strip()
                    if line:
                        logger.debug(line)
                
                # Wait for process to complete
                return_code = process.wait()
            
            if return_code != 0:
                logger.error(f"Update failed with code: {return_code}")
                return False
            
            logger.info(f"Update completed successfully for server: {server_name}")
            
            # Update the last update time in the server config
            server["LastUpdateTime"] = datetime.datetime.now().isoformat()
            self.save_server_config(server)
            
            # Restart the server if it was running before
            if self.is_server_running(server) or "PID" in server:
                logger.info(f"Restarting server: {server_name}")
                self.start_server(server)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating server: {str(e)}")
            return False
    
    def is_server_running(self, server):
        """Check if a server is currently running"""
        if "PID" in server and server["PID"]:
            try:
                # Check if process is running
                pid = int(server["PID"])
                import psutil
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                        return False
                    return True
                return False
            except Exception as e:
                logger.error(f"Error checking server process: {str(e)}")
                return False
        return False
    
    def stop_server(self, server):
        """Stop a running server"""
        try:
            server_name = server.get("Name", "Unknown")
            script_path = os.path.join(self.paths["scripts"], "stop_server.py")
            
            if os.path.exists(script_path):
                subprocess.run([sys.executable, script_path, server_name], check=True)
                logger.info(f"Server stopped: {server_name}")
                return True
            else:
                logger.error(f"Stop server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            return False
    
    def start_server(self, server):
        """Start a server"""
        try:
            server_name = server.get("Name", "Unknown")
            script_path = os.path.join(self.paths["scripts"], "start_server.py")
            
            if os.path.exists(script_path):
                subprocess.run([sys.executable, script_path, server_name], check=True)
                logger.info(f"Server started: {server_name}")
                return True
            else:
                logger.error(f"Start server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            return False
    
    def save_server_config(self, server):
        """Save updated server configuration"""
        try:
            server_name = server.get("Name", "Unknown")
            server_path = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            with open(server_path, 'w') as f:
                json.dump(server, f, indent=4)
                
            logger.info(f"Server configuration updated: {server_name}")
            return True
        except Exception as e:
            logger.error(f"Error saving server configuration: {str(e)}")
            return False
    
    def run(self):
        """Run the auto-updater"""
        try:
            logger.info("Starting automatic server update check")
            
            # Get list of servers to check
            servers = self.get_server_list()
            if not servers:
                logger.warning("No servers found to check for updates")
                return 0
            
            updates_available = 0
            updates_applied = 0
            
            # Process each server
            for server in servers:
                app_id = server.get("AppId")
                server_name = server.get("Name", "Unknown")
                
                logger.info(f"Processing server: {server_name} (AppID: {app_id})")
                
                # Check for updates
                has_update = self.check_for_update(app_id)
                
                if has_update:
                    updates_available += 1
                    
                    if not self.check_only:
                        # Apply the update
                        if self.update_server(server):
                            updates_applied += 1
                            logger.info(f"Successfully updated server: {server_name}")
                        else:
                            logger.error(f"Failed to update server: {server_name}")
                
            # Summarize results
            logger.info(f"Update check completed: {updates_available} updates available")
            
            if not self.check_only:
                logger.info(f"Updates applied: {updates_applied} of {updates_available}")
            
            return 0
            
        except Exception as e:
            logger.error(f"Auto-updater failed: {str(e)}")
            return 1

def main():
    try:
        updater = AutoUpdater()
        return updater.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
