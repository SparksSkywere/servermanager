# Steam server auto-updater
import os
import sys
import time
import logging
import argparse
import subprocess
import datetime
import winreg

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import psutil
except ImportError:
    psutil = None

from Modules.common import setup_module_path, setup_module_logging, get_server_manager_dir
setup_module_path()

try:
    from debug.debug import enable_debug, log_exception
except ImportError:
    def enable_debug():
        logging.getLogger().setLevel(logging.DEBUG)
        return True
    
    def log_exception(e, message="Exception"):
        logging.error(f"{message}: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())

logger: logging.Logger = setup_module_logging("AutoAppUpdate")

class AutoUpdater:
    # - Checks Steam servers for updates
    # - Applies updates with optional force
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.steam_cmd_path = None
        self.paths = {}
        
        parser = argparse.ArgumentParser(description='Auto Update Steam Servers')
        parser.add_argument('--check', action='store_true', help='Check only')
        parser.add_argument('--force', action='store_true', help='Force update')
        parser.add_argument('--server', help='Specific server')
        parser.add_argument('--log', help='Log file')
        parser.add_argument('--debug', action='store_true', help='Debug mode')
        args = parser.parse_args()
        
        self.check_only = args.check
        self.force_update = args.force
        self.specific_server = args.server
        
        if args.debug:
            enable_debug()
            logger.setLevel(logging.DEBUG)
        
        if not self.initialise():
            logger.error("Init failed. Exiting.")
            sys.exit(1)
        
    def initialise(self):
        # Init paths/config from registry
        # - Validates SteamCMD, creates dirs
        try:
            self.server_manager_dir = get_server_manager_dir()
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            steam_cmd_dir = winreg.QueryValueEx(key, "SteamCMDPath")[0]
            self.steam_cmd_path = os.path.join(steam_cmd_dir, "steamcmd.exe")
            winreg.CloseKey(key)
            
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules")
            }
            
            # Directories are now created in Start-ServerManager.pyw
            
            logger.info(f"Init complete. SM dir: {self.server_manager_dir}")
            logger.info(f"SteamCMD: {self.steam_cmd_path}")
            
            # Validate SteamCMD
            if not os.path.exists(self.steam_cmd_path):
                logger.error(f"SteamCMD not found: {self.steam_cmd_path}")
                return False
                
            return True
            
        except Exception as e:
            log_exception(e, "Initialisation failed")
            return False
    
    def get_server_list(self):
        # Get list of servers to check for updates
        # Supports both specific server targeting and AutoUpdate flag filtering
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            servers = []
            
            # If specific server was requested, only check that one
            if self.specific_server:
                server_config = manager.get_server(self.specific_server)
                if server_config:
                    if server_config.get("AppId") and server_config.get("InstallPath"):
                        servers.append(server_config)
                    else:
                        logger.warning(f"Server {self.specific_server} has invalid configuration")
                else:
                    logger.error(f"Server configuration not found: {self.specific_server}")
            else:
                # Get all server configurations from database
                all_servers = manager.get_all_servers()
                for server_config in all_servers:
                    if server_config.get("AppId") and server_config.get("InstallPath"):
                        if server_config.get("AutoUpdate", True):  # Only include servers with auto-update enabled
                            servers.append(server_config)
                
            logger.info(f"Found {len(servers)} servers to check for updates")
            return servers
            
        except Exception as e:
            logger.error(f"Error getting server list: {str(e)}")
            return []
    
    def check_for_update(self, app_id):
        # Check if an update is available for the given AppID
        # Uses SteamCMD app_info_print to detect available updates
        try:
            logger.info(f"Checking for updates for AppID: {app_id}")
            logger.debug(f"[SUBPROCESS_TRACE] check_for_updates called for AppID: {app_id}")
            
            # Run SteamCMD to check for updates
            cmd = [
                self.steam_cmd_path,
                "+login", "anonymous",
                "+app_info_update", "1",
                "+app_info_print", str(app_id),  # Ensure app_id is a string
                "+quit"
            ]
            
            # Use CREATE_NO_WINDOW to prevent console popup on Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = subprocess.CREATE_NO_WINDOW
                logger.debug(f"[SUBPROCESS_TRACE] SteamCMD using CREATE_NO_WINDOW flag: {creationflags}")
            
            logger.debug(f"[SUBPROCESS_TRACE] Executing SteamCMD: {cmd[0]}")
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=creationflags)
            logger.debug(f"[SUBPROCESS_TRACE] SteamCMD completed with returncode: {result.returncode}")
            
            # Check if there was an error
            if result.returncode != 0:
                logger.error(f"SteamCMD returned error code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False
            
            # Use set for O(1) lookup instead of nested loop
            update_indicators = {
                "update state", "needs update", "downloading update", "update available"
            }
            
            for line in result.stdout.lower().split('\n'):
                if "false" in line or "0" in line:
                    continue
                if any(indicator in line for indicator in update_indicators):
                    logger.info(f"Update available for AppID: {app_id}")
                    return True
            
            logger.info(f"No updates available for AppID: {app_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error checking for updates: {str(e)}")
            return False
    
    def update_server(self, server):
        # Update a server using SteamCMD
        # Handles server shutdown/restart and validates files during update
        try:
            app_id = server.get("AppId")
            install_path = server.get("InstallPath")
            server_name = server.get("Name", "Unknown")
            
            logger.info(f"Updating server: {server_name} (AppID: {app_id})")
            
            # Check if server is running before update
            was_running = self.is_server_running(server)
            
            # First check if server is running
            if was_running:
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
                "+app_update", str(app_id), "validate",  # Ensure app_id is a string
                "+quit"
            ]
            
            logger.info(f"Running update command: {' '.join(cmd)}")
            logger.debug(f"[SUBPROCESS_TRACE] Running SteamCMD update for {server_name}")
            
            # Use CREATE_NO_WINDOW to prevent console popup on Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = subprocess.CREATE_NO_WINDOW
                logger.debug(f"[SUBPROCESS_TRACE] SteamCMD update using CREATE_NO_WINDOW flag: {creationflags}")
            
            # Run the update
            with open(log_file, 'w') as f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
                
                # Capture and log output in real-time
                if process.stdout is not None:  # Fixed potential None attribute error
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
            
            # Restart the server if it was running before the update
            if was_running:
                logger.info(f"Restarting server: {server_name}")
                self.start_server(server)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating server: {str(e)}")
            return False
    
    def is_server_running(self, server):
        # Check if a server is currently running
        # Uses psutil to verify process existence and status
        if psutil is None:
            logger.warning("psutil not available, cannot check server process status")
            return False
            
        if "PID" in server and server["PID"]:
            try:
                # Check if process is running
                pid = int(server["PID"])
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
        # Stop a running server using external script
        try:
            server_name = server.get("Name", "Unknown")
            script_path = os.path.join(self.paths["scripts"], "stop_server.py")
            
            if os.path.exists(script_path):
                # Use CREATE_NO_WINDOW to prevent console popup on Windows
                startupinfo = None
                creationflags = 0
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                subprocess.run([sys.executable, script_path, server_name], check=True,
                              startupinfo=startupinfo, creationflags=creationflags)
                logger.info(f"Server stopped: {server_name}")
                return True
            else:
                logger.error(f"Stop server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            return False
    
    def start_server(self, server):
        # Start a server using external script
        try:
            server_name = server.get("Name", "Unknown")
            script_path = os.path.join(self.paths["scripts"], "start_server.py")
            
            if os.path.exists(script_path):
                # Use CREATE_NO_WINDOW to prevent console popup on Windows
                startupinfo = None
                creationflags = 0
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                subprocess.run([sys.executable, script_path, server_name], check=True,
                              startupinfo=startupinfo, creationflags=creationflags)
                logger.info(f"Server started: {server_name}")
                return True
            else:
                logger.error(f"Start server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            return False
    
    def save_server_config(self, server):
        # Save updated server configuration with LastUpdateTime timestamp
        try:
            server_name = server.get("Name", "Unknown")
            
            # Save to database
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            result = manager.update_server(server_name, server)
            
            if result:
                logger.info(f"Server configuration updated: {server_name}")
                return True
            else:
                logger.error(f"Failed to save server configuration: {server_name}")
                return False
        except Exception as e:
            logger.error(f"Error saving server configuration: {str(e)}")
            return False
    
    def run(self):
        # Run the auto-updater with comprehensive update processing
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
            log_exception(e, "Auto-updater failed")
            return 1

def main():
    # Main entry point for the auto-updater
    try:
        updater = AutoUpdater()
        return updater.run()
    except Exception as e:
        log_exception(e, "Unhandled exception")
        return 1

if __name__ == "__main__":
    sys.exit(main())
