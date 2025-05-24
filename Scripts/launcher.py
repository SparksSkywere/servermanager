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
                
            # Start tray icon process
            tray_process = subprocess.Popen(
                [sys.executable, tray_script],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            self.processes["tray_icon"] = tray_process
            self.write_pid_file("trayicon", tray_process.pid)
            
            logger.info(f"Tray icon process started (PID: {tray_process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start tray icon: {str(e)}")
            return False
            
    def start_web_server(self):
        """Start the web server process"""
        try:
            web_script = os.path.join(self.paths["scripts"], "webserver.py")
            
            if not os.path.exists(web_script):
                logger.error(f"Web server script not found: {web_script}")
                return False
                
            # Start web server process
            web_process = subprocess.Popen(
                [sys.executable, web_script],
                creationflags=subprocess.CREATE_NO_WINDOW
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
        while self.running:
            try:
                # Check tray icon
                if "tray_icon" in self.processes:
                    p = self.processes["tray_icon"]
                    if p.poll() is not None:
                        logger.warning(f"Tray icon process exited with code {p.returncode}, restarting...")
                        self.start_tray_icon()
                        
                # Check web server
                if "web_server" in self.processes:
                    p = self.processes["web_server"]
                    if p.poll() is not None:
                        logger.warning(f"Web server process exited with code {p.returncode}, restarting...")
                        self.start_web_server()
                
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
        
        # Terminate child processes
        for name, process in self.processes.items():
            try:
                if process.poll() is None:
                    logger.info(f"Terminating {name} process (PID: {process.pid})")
                    process.terminate()
                    process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error terminating {name} process: {str(e)}")
                
        # Remove PID files
        try:
            for pid_file in ["launcher.pid", "trayicon.pid", "webserver.pid"]:
                pid_path = os.path.join(self.paths["temp"], pid_file)
                if os.path.exists(pid_path):
                    os.remove(pid_path)
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
