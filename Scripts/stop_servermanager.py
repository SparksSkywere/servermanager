import os
import sys
import json
import subprocess
import logging
import winreg
import argparse
import psutil
import time
import ctypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("StopServerManager")

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

class ServerManagerStopper:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.debug_mode = False
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Stop Server Manager')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        parser.add_argument('--force', action='store_true', help='Force stop all processes')
        args = parser.parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            self.debug_mode = True
            
        self.force_stop = args.force
        
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
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Set up file logging
            log_file = os.path.join(self.paths["logs"], "stop-servermanager.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
            
    def stop_process_by_pid(self, pid, process_name=None):
        """Stop a process by PID"""
        try:
            if not psutil.pid_exists(pid):
                logger.debug(f"Process {pid} ({process_name or 'unknown'}) is not running")
                return True
                
            process = psutil.Process(pid)
            logger.info(f"Stopping process: {process.name()} (PID: {pid})")
            
            # Try graceful termination first
            process.terminate()
            
            # Wait for process to terminate
            try:
                process.wait(timeout=5)
                logger.info(f"Process {pid} terminated gracefully")
                return True
            except psutil.TimeoutExpired:
                if self.force_stop:
                    logger.warning(f"Process {pid} did not terminate gracefully, killing forcefully")
                    process.kill()
                    return True
                else:
                    logger.warning(f"Process {pid} did not terminate gracefully")
                    return False
        except psutil.NoSuchProcess:
            logger.debug(f"Process {pid} does not exist")
            return True
        except Exception as e:
            logger.error(f"Error stopping process {pid}: {str(e)}")
            return False
            
    def stop_processes_from_pid_files(self):
        """Stop processes using PID files"""
        pid_files = [
            "launcher.pid",
            "webserver.pid",
            "trayicon.pid"
        ]
        
        stopped_count = 0
        
        for pid_file in pid_files:
            pid_path = os.path.join(self.paths["temp"], pid_file)
            if os.path.exists(pid_path):
                try:
                    with open(pid_path, 'r') as f:
                        pid_data = json.load(f)
                        
                    pid = pid_data.get("ProcessId")
                    process_type = pid_data.get("ProcessType", pid_file.replace(".pid", ""))
                    
                    if pid:
                        logger.info(f"Found PID file for {process_type}: {pid}")
                        if self.stop_process_by_pid(pid, process_type):
                            stopped_count += 1
                            
                    # Remove PID file
                    os.remove(pid_path)
                    
                except Exception as e:
                    logger.error(f"Error processing PID file {pid_file}: {str(e)}")
                    
        return stopped_count
            
    def stop_processes_by_name(self):
        """Stop Server Manager processes by name"""
        process_names = [
            "servermanager",
            "trayicon",
            "webserver",
            "launcher"
        ]
        
        stopped_count = 0
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Check if process name matches
                proc_name = proc.info['name'].lower()
                proc_match = any(name in proc_name for name in process_names)
                
                # Check if cmdline contains server manager path
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                cmdline_match = self.server_manager_dir.lower() in cmdline
                
                # Check if Python script matches
                python_script_match = False
                if 'python' in proc_name and cmdline:
                    python_script_match = any(
                        script in cmdline for script in [
                            'launcher.py', 'trayicon.py', 'webserver.py',
                            'stop_servermanager.py', 'start_servermanager.py'
                        ]
                    )
                
                # Skip self
                if proc.pid == os.getpid():
                    continue
                
                # Stop matching processes
                if proc_match or cmdline_match or python_script_match:
                    logger.info(f"Found matching process: {proc.info['name']} (PID: {proc.pid})")
                    if self.stop_process_by_pid(proc.pid, proc.info['name']):
                        stopped_count += 1
                
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                logger.error(f"Error checking process: {str(e)}")
                
        return stopped_count
    
    def stop_all_game_servers(self):
        """Stop all running game servers"""
        try:
            # First check if the stop_all_servers.py script exists
            stop_all_script = os.path.join(self.paths["scripts"], "stop_all_servers.py")
            if os.path.exists(stop_all_script):
                logger.info("Stopping all game servers using stop_all_servers.py")
                subprocess.run([sys.executable, stop_all_script], timeout=30)
                return True
                
            # Alternative method: look for PIDS.txt
            pids_file = os.path.join(self.server_manager_dir, "PIDS.txt")
            if os.path.exists(pids_file):
                logger.info("Stopping servers listed in PIDS.txt")
                with open(pids_file, 'r') as f:
                    for line in f:
                        parts = line.strip().split(' - ')
                        if len(parts) >= 2:
                            pid = int(parts[0])
                            server_name = parts[1]
                            logger.info(f"Stopping server: {server_name} (PID: {pid})")
                            self.stop_process_by_pid(pid, server_name)
                
                # Clear the PIDS file
                open(pids_file, 'w').close()
                return True
                
            return False
        except Exception as e:
            logger.error(f"Error stopping game servers: {str(e)}")
            return False
    
    def run(self):
        """Main execution method"""
        try:
            logger.info("Starting Server Manager shutdown process")
            
            # Stop all game servers first
            self.stop_all_game_servers()
            
            # Stop processes from PID files
            count1 = self.stop_processes_from_pid_files()
            
            # Stop processes by name
            count2 = self.stop_processes_by_name()
            
            logger.info(f"Stopped {count1 + count2} Server Manager processes")
            
            # Cleanup temp files
            for filename in os.listdir(self.paths["temp"]):
                if filename.endswith('.pid'):
                    try:
                        os.remove(os.path.join(self.paths["temp"], filename))
                    except:
                        pass
            
            logger.info("Server Manager shutdown complete")
            return 0
            
        except Exception as e:
            logger.error(f"Error stopping Server Manager: {str(e)}")
            return 1

def main():
    # Check for admin privileges
    if not is_admin():
        print("Requesting administrative privileges...")
        run_as_admin()
    
    try:
        # Create and run stopper
        stopper = ServerManagerStopper()
        return stopper.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
