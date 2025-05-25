import os
import sys
import time
import subprocess
import signal
import json
import argparse
import winreg
import logging
import ctypes
from pathlib import Path
from datetime import datetime

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Launcher")

class ServerManagerLauncher:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.processes = {}
        self.running = True
        self.is_service = False
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Launcher')
        parser.add_argument('--service', action='store_true', help='Run as a service')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        args = parser.parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            
        self.is_service = args.service
        
        # Initialize paths and configuration
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
            log_file = os.path.join(self.paths["logs"], "launcher.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            # Write PID file
            self.write_pid_file("launcher", os.getpid())
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
            
    def write_pid_file(self, process_type, pid):
        """Write process ID to file"""
        try:
            pid_file = os.path.join(self.paths["temp"], f"{process_type}.pid")
            
            # Create PID info dictionary
            pid_info = {
                "ProcessId": pid,
                "StartTime": datetime.now().isoformat(),
                "ProcessType": process_type
            }
            
            # Write PID info to file as JSON
            with open(pid_file, 'w') as f:
                json.dump(pid_info, f)
                
            logger.debug(f"PID file created for {process_type}: {pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to write PID file for {process_type}: {str(e)}")
            return False
            
    def start_tray_icon(self):
        """Start the system tray icon process"""
        try:
            tray_script = os.path.join(self.paths["scripts"], "trayicon.py")
            
            if not os.path.exists(tray_script):
                logger.error(f"Tray icon script not found: {tray_script}")
                return False
                
            # Check Python executable
            python_exe = sys.executable
            if not os.path.exists(python_exe):
                logger.error(f"Python executable not found: {python_exe}")
                return False
                
            logger.debug(f"Using Python executable: {python_exe}")
            logger.debug(f"Tray icon script path: {tray_script}")
            
            # Log directories to help with troubleshooting
            logger.debug(f"Current working directory: {os.getcwd()}")
            logger.debug(f"Server manager directory: {self.server_manager_dir}")
            logger.debug(f"Scripts directory: {self.paths['scripts']}")
            
            # Set up process to be completely hidden on all platforms
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                tray_process = subprocess.Popen(
                    [python_exe, tray_script, "--standalone"],
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
            else:
                # On Unix-based systems
                tray_process = subprocess.Popen(
                    [python_exe, tray_script, "--standalone"],
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
            
            # Wait a moment to see if the process exits immediately
            time.sleep(2)
            if tray_process.poll() is not None:
                exit_code = tray_process.returncode
                stdout, stderr = tray_process.communicate()
                logger.error(f"Tray icon process exited immediately with code {exit_code}")
                logger.error(f"Stdout: {stdout.decode('utf-8', errors='replace')}")
                logger.error(f"Stderr: {stderr.decode('utf-8', errors='replace')}")
                
                # Log specific error details to aid troubleshooting
                error_lines = stderr.decode('utf-8', errors='replace').splitlines()
                if error_lines:
                    for line in error_lines:
                        if "ERROR" in line:
                            logger.error(f"Tray icon error: {line}")
                
                return False
            
            self.processes["tray_icon"] = tray_process
            self.write_pid_file("trayicon", tray_process.pid)
            
            logger.info(f"Tray icon process started (PID: {tray_process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start tray icon: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
            
    def start_web_server(self):
        """Start the web server process"""
        try:
            web_script = os.path.join(self.paths["scripts"], "webserver.py")
            
            if not os.path.exists(web_script):
                logger.error(f"Web server script not found: {web_script}")
                return False
                
            # Start web server process with hidden console
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                web_process = subprocess.Popen(
                    [sys.executable, web_script],
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
            else:
                # On Unix-based systems
                web_process = subprocess.Popen(
                    [sys.executable, web_script],
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
            
            self.processes["web_server"] = web_process
            self.write_pid_file("webserver", web_process.pid)
            
            logger.info(f"Web server process started (PID: {web_process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start web server: {str(e)}")
            return False
    
    def start_processes(self):
        """Start all server manager component processes"""
        try:
            # Start tray icon
            if not self.start_tray_icon():
                logger.warning("Failed to start tray icon, continuing anyway")
                
            # Start web server
            if not self.start_web_server():
                logger.warning("Failed to start web server, continuing anyway")
                
            logger.info("All processes started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start processes: {str(e)}")
            return False
            
    def monitor_processes(self):
        """Monitor and restart processes if they crash"""
        restart_attempts = {"tray_icon": 0, "web_server": 0}
        max_restart_attempts = 3  # Maximum number of restart attempts
        
        while self.running:
            try:
                # Check tray icon
                if "tray_icon" in self.processes:
                    p = self.processes["tray_icon"]
                    if p.poll() is not None:
                        restart_attempts["tray_icon"] += 1
                        if restart_attempts["tray_icon"] <= max_restart_attempts:
                            logger.warning(f"Tray icon process exited with code {p.returncode}, restarting... (Attempt {restart_attempts['tray_icon']}/{max_restart_attempts})")
                            if not self.start_tray_icon():
                                logger.error("Failed to restart tray icon process")
                        else:
                            logger.error(f"Tray icon process has crashed {restart_attempts['tray_icon']} times. Giving up.")
                    else:
                        # Reset counter if process is running
                        restart_attempts["tray_icon"] = 0
                        
                # Check web server
                if "web_server" in self.processes:
                    p = self.processes["web_server"]
                    if p.poll() is not None:
                        restart_attempts["web_server"] += 1
                        if restart_attempts["web_server"] <= max_restart_attempts:
                            logger.warning(f"Web server process exited with code {p.returncode}, restarting... (Attempt {restart_attempts['web_server']}/{max_restart_attempts})")
                            if not self.start_web_server():
                                logger.error("Failed to restart web server process")
                        else:
                            logger.error(f"Web server process has crashed {restart_attempts['web_server']} times. Giving up.")
                    else:
                        # Reset counter if process is running
                        restart_attempts["web_server"] = 0
                
                # Sleep for a while before checking again
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down...")
                self.running = False
                break
                
            except Exception as e:
                logger.error(f"Error in process monitoring: {str(e)}")
                time.sleep(10)  # Wait longer if there's an error
                
    def cleanup(self):
        """Clean up resources and terminate processes"""
        logger.info("Cleaning up resources...")
        
        # Terminate child processes with more aggressive approach
        for name, process in self.processes.items():
            try:
                if process.poll() is None:
                    logger.info(f"Terminating {name} process (PID: {process.pid})")
                    process.terminate()
                    try:
                        # Wait for process to terminate
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # If termination times out, force kill
                        logger.warning(f"{name} process did not terminate gracefully, killing forcefully")
                        if sys.platform == 'win32':
                            subprocess.call(['taskkill', '/F', '/PID', str(process.pid)])
                        else:
                            os.kill(process.pid, signal.SIGKILL)
            except Exception as e:
                logger.error(f"Error terminating {name} process: {str(e)}")
                
        # Remove PID files
        try:
            for pid_file in ["launcher.pid", "trayicon.pid", "webserver.pid"]:
                pid_path = os.path.join(self.paths["temp"], pid_file)
                if os.path.exists(pid_path):
                    os.remove(pid_path)
                    logger.debug(f"Removed {pid_file}")
        except Exception as e:
            logger.error(f"Error removing PID files: {str(e)}")
        
        logger.info("Cleanup complete")
        
    def run(self):
        """Main execution method"""
        try:
            logger.info("Server Manager launcher starting...")
            
            # Start component processes
            if not self.start_processes():
                logger.error("Failed to start required processes, exiting")
                return 1
                
            # Set up signal handlers
            signal.signal(signal.SIGINT, lambda sig, frame: self.handle_shutdown())
            signal.signal(signal.SIGTERM, lambda sig, frame: self.handle_shutdown())
            
            # Monitor processes
            self.monitor_processes()
            
            return 0
            
        except Exception as e:
            logger.error(f"Unhandled exception: {str(e)}")
            return 1
            
        finally:
            self.cleanup()
            
    def handle_shutdown(self):
        """Handle shutdown signal"""
        logger.info("Shutdown signal received")
        self.running = False
        # Make sure we clean up properly
        self.cleanup()
        # Exit immediately to prevent hanging
        logger.info("Launcher exiting due to shutdown signal")
        os._exit(0)  # Force immediate exit

def is_admin():
    """Check if the script is running with administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def main():
    # Check for admin privileges
    if not is_admin():
        logger.error("Administrator privileges required")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        return 1
        
    # Create and run launcher
    launcher = ServerManagerLauncher()
    return launcher.run()

if __name__ == "__main__":
    sys.exit(main())
