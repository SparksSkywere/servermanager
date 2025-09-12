# Server Manager shutdown utility with process termination and cleanup functionality
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
import signal

# Add the parent directory to the path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Modules.common import ServerManagerModule

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("StopServerManager")
except Exception:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger("StopServerManager")

def is_admin():
    # Check if the script is running with administrator privileges
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    # Re-run the script with admin privileges
    # Use hidden window when restarting as admin
    if sys.platform == 'win32':
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 0)  # 0 = SW_HIDE
    else:
        # Unix systems may handle this differently
        print("Administrator privileges required")
    sys.exit()

class ServerManagerStopper(ServerManagerModule):
    def __init__(self):
        super().__init__("StopServerManager")
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
        
        # Set up file logging
        log_file = os.path.join(self.paths["logs"], "stop-servermanager.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
    def stop_process_by_pid(self, pid, process_name=None):
        # Stop a process by PID
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
                # Use more forceful approaches depending on platform
                if self.force_stop or True:  # Always force kill if process doesn't terminate
                    logger.warning(f"Process {pid} did not terminate gracefully, killing forcefully")
                    try:
                        if sys.platform == 'win32':
                            # On Windows, use taskkill which is more forceful
                            subprocess.call(['taskkill', '/F', '/PID', str(pid)], 
                                           stdout=subprocess.DEVNULL, 
                                           stderr=subprocess.DEVNULL)
                        else:
                            # On Unix, use SIGKILL
                            os.kill(pid, signal.SIGKILL)
                        
                        # Verify process is terminated
                        time.sleep(0.5)
                        if psutil.pid_exists(pid):
                            logger.error(f"Failed to kill process {pid} forcefully")
                            return False
                        return True
                    except Exception as e:
                        logger.error(f"Error forcefully killing process {pid}: {str(e)}")
                        return False
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
        # Stop processes using PID files
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
        # Stop Server Manager processes by name
        process_names = [
            "servermanager",
            "trayicon",
            "webserver",
            "launcher",
            "dashboard"  # Added dashboard to ensure it's also terminated
        ]
        
        # Add additional Python scripts to check for
        python_scripts = [
            'launcher.py', 
            'trayicon.py', 
            'webserver.py',
            'dashboard.py',
            'stop_servermanager.py', 
            'start_servermanager.py'
        ]
        
        stopped_count = 0
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Skip self
                if proc.pid == os.getpid():
                    continue
                    
                # Check if process name matches
                proc_name = proc.info['name'].lower()
                proc_match = any(name in proc_name for name in process_names)
                
                # Check if cmdline contains server manager path
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                cmdline_match = self.server_manager_dir and self.server_manager_dir.lower() in cmdline
                
                # Check if Python script matches
                python_script_match = False
                if 'python' in proc_name and cmdline:
                    python_script_match = any(script in cmdline for script in python_scripts)
                
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
        # Stop all running game servers
        try:
            # First check if the stop_all_servers.py script exists
            stop_all_script = os.path.join(self.paths["scripts"], "stop_all_servers.py")
            if os.path.exists(stop_all_script):
                logger.info("Stopping all game servers using stop_all_servers.py")
                
                # Run with hidden console
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE
                    
                    subprocess.run(
                        [sys.executable, stop_all_script], 
                        timeout=30,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    # Unix platforms
                    subprocess.run(
                        [sys.executable, stop_all_script], 
                        timeout=30,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                return True
                
            # Alternative method: look for PIDS.txt
            if self.server_manager_dir:
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
        # Main execution method
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
                        logger.debug(f"Removed PID file: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to remove PID file {filename}: {str(e)}")
            
            # Final check for any remaining processes
            time.sleep(1)  # Wait a moment for processes to terminate
            count3 = self.stop_processes_by_name()  # Run again to catch any stragglers
            if count3 > 0:
                logger.info(f"Stopped {count3} additional processes in final cleanup")
            
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