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
import socket

# Add the parent directory to the path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Modules.common import ServerManagerModule

# Centralized logging (fallback to basic if module import fails)
try:
    from Modules.logging import get_component_logger, log_dashboard_event
    logger = get_component_logger("Launcher")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Launcher")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Launcher debug mode enabled via environment")

class ServerManagerLauncher(ServerManagerModule):
    def __init__(self):
        super().__init__("Launcher")
        self.processes = {}
        self.running = True
        self.is_service = False
        self.cluster_role = "Unknown"
        self.host_address = None
        
        # Detect cluster role (Host or Subhost)
        self.detect_cluster_role()
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Launcher')
        parser.add_argument('--service', action='store_true', help='Run as a service')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        parser.add_argument('--force', action='store_true', help='Force start even if another instance is detected')
        args = parser.parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            
        self.is_service = args.service
        self.force_start = args.force
        
        # Set up file logging
        log_file = os.path.join(self.paths["logs"], "launcher.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        
        # Log cluster role information
        logger.info(f"Cluster role detected: {self.cluster_role}")
        if self.host_address:
            logger.info(f"Host address: {self.host_address}")
        
        # Write PID file for launcher
        self.write_pid_file("launcher", os.getpid())
        
        # Check for existing instance
        if not self.force_start and self.check_existing_instance():
            logger.warning("Another instance of Server Manager is already running. Exiting.")
            sys.exit(0)
    
    def detect_cluster_role(self):
        """Detect whether this instance is a Host or Subhost"""
        try:
            from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
            self.cluster_role = winreg.QueryValueEx(key, "HostType")[0]
            try:
                self.host_address = winreg.QueryValueEx(key, "HostAddress")[0]
            except Exception:
                self.host_address = None
            winreg.CloseKey(key)
        except Exception as e:
            logger.warning(f"Could not detect cluster role from registry: {e}")
            self.cluster_role = "Unknown"
            self.host_address = None
        
    def check_existing_instance(self):
        """Check if another instance of Server Manager is already running"""
        try:
            if not self.paths or not self.paths.get("temp"):
                # If paths aren't initialized, we can't check
                return False
                
            # Check for existing PID files
            for process_type in ["launcher", "trayicon", "webserver"]:
                pid_file = os.path.join(self.paths["temp"], f"{process_type}.pid")
                
                if os.path.exists(pid_file):
                    try:
                        with open(pid_file, 'r') as f:
                            pid_data = json.load(f)
                            pid = pid_data.get("ProcessId")
                            
                            if pid and pid != os.getpid():  # Make sure it's not our PID
                                # Check if process is still running
                                if sys.platform == "win32":
                                    # Windows method
                                    PROCESS_QUERY_INFORMATION = 0x0400
                                    process_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                                    if process_handle:
                                        ctypes.windll.kernel32.CloseHandle(process_handle)
                                        logger.warning(f"Found existing {process_type} process with PID {pid}")
                                        return True
                                else:
                                    # Unix method
                                    try:
                                        os.kill(pid, 0)  # Signal 0 just checks if process exists
                                        logger.warning(f"Found existing {process_type} process with PID {pid}")
                                        return True
                                    except OSError:
                                        # Process not running, clean up stale PID file
                                        os.remove(pid_file)
                    except (json.JSONDecodeError, IOError) as e:
                        # Invalid PID file, remove it
                        logger.warning(f"Invalid PID file for {process_type}: {str(e)}")
                        try:
                            os.remove(pid_file)
                        except:
                            pass
            
            return False
        except Exception as e:
            logger.error(f"Error checking for existing instances: {str(e)}")
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

            # Add the server manager directory to PYTHONPATH for module imports
            env = os.environ.copy()
            pythonpath = env.get('PYTHONPATH', '')
            if pythonpath:
                env['PYTHONPATH'] = f"{self.server_manager_dir or ''};{pythonpath}"
            else:
                env['PYTHONPATH'] = self.server_manager_dir or ''
                
            # Start web server process using direct Python execution (no batch file)
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE - completely hidden
                
                # Use direct Python execution for better reliability and no console windows
                logger.info("Starting web server directly with Python")
                web_process = subprocess.Popen(
                    [sys.executable, web_script],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    startupinfo=startupinfo,
                    shell=False,
                    env=env,
                    cwd=self.server_manager_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
            else:
                # On Unix-based systems
                web_process = subprocess.Popen(
                    [sys.executable, web_script],
                    start_new_session=True,
                    shell=False,
                    env=env,
                    cwd=self.server_manager_dir  # Explicit working directory
                )
            
            # Wait longer to see if the process exits immediately
            time.sleep(5)
            if web_process.poll() is not None:
                exit_code = web_process.returncode
                logger.error(f"Web server process exited immediately with code {exit_code}")
                # Since we're not capturing stdout/stderr, we can't show detailed error info
                # but the process started and exited, which indicates a runtime error
                return False
            
            self.processes["web_server"] = web_process
            self.write_pid_file("webserver", web_process.pid)
            
            # Check if the web server is actually listening on the port
            web_port = 8080  # Default port
            try:
                from Modules.common import REGISTRY_ROOT
                # Try to get the port from registry
                key = winreg.OpenKey(REGISTRY_ROOT, self.registry_path)
                web_port = int(winreg.QueryValueEx(key, "WebPort")[0])
                winreg.CloseKey(key)
            except:
                logger.warning("Could not get web port from registry, using default 8080")
            
            logger.info(f"Checking if web server is listening on port {web_port}...")
            for attempt in range(15):  # Increased timeout
                time.sleep(2)
                if self.is_port_open('localhost', web_port):
                    logger.info(f"Web server successfully started and listening on port {web_port}")
                    return True
                logger.debug(f"Attempt {attempt+1}/15: Web server not yet listening")
                
                # Check if process is still running
                if web_process.poll() is not None:
                    logger.error(f"Web server process died during startup with exit code {web_process.returncode}")
                    try:
                        stdout, stderr = web_process.communicate(timeout=2)
                        if stdout:
                            logger.error(f"Web server stdout: {stdout.decode('utf-8', errors='replace')}")
                        if stderr:
                            logger.error(f"Web server stderr: {stderr.decode('utf-8', errors='replace')}")
                    except subprocess.TimeoutExpired:
                        logger.error("Could not get web server output (timeout)")
                    return False
            
            # Final check: if still not listening, try to capture any error output
            if not self.is_port_open('localhost', web_port):
                logger.warning(f"Web server process started (PID: {web_process.pid}) but not listening on port {web_port}")
                # Since we're not capturing output, we can't get detailed error info
                # but we can try to terminate the non-responsive process
                try:
                    if web_process.poll() is None:  # Process still running
                        logger.warning("Terminating unresponsive web server process")
                        web_process.terminate()
                        time.sleep(2)
                        if web_process.poll() is None:
                            web_process.kill()  # Force kill if terminate didn't work
                except Exception as e:
                    logger.error(f"Error terminating web server process: {e}")
            else:
                logger.info(f"Web server successfully started and listening on port {web_port}")
                return True
            
            return True  # Return True anyway to keep the process managed if it didn't crash immediately
            
        except Exception as e:
            logger.error(f"Failed to start web server: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def start_subhost_dashboard(self):
        """Start the subhost dashboard for connecting to a host server"""
        try:
            subhost_script = os.path.join(self.paths["project_root"], "Subhost", "dashboard.py")
            
            if not os.path.exists(subhost_script):
                logger.error(f"Subhost dashboard script not found: {subhost_script}")
                return False
                
            python_exe = sys.executable
            if not os.path.exists(python_exe):
                logger.error(f"Python executable not found: {python_exe}")
                return False
                
            logger.info(f"Starting subhost dashboard...")
            logger.debug(f"Using Python executable: {python_exe}")
            logger.debug(f"Subhost script path: {subhost_script}")
            
            # Set environment variables for subhost
            env = os.environ.copy()
            if self.host_address:
                env["CLUSTER_HOST_URL"] = f"http://{self.host_address}:5001"
                logger.info(f"Connecting to host at: {self.host_address}")
            
            # Start subhost dashboard process
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                subhost_process = subprocess.Popen(
                    [python_exe, subhost_script],
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    env=env
                )
            else:
                # On Unix-based systems
                subhost_process = subprocess.Popen(
                    [python_exe, subhost_script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    env=env
                )
            
            # Store process for monitoring
            self.processes["subhost_dashboard"] = subhost_process
            self.write_pid_file("subhost_dashboard", subhost_process.pid)
            
            logger.info(f"Subhost dashboard started with PID: {subhost_process.pid}")
            
            # Wait a moment and check if it started successfully
            time.sleep(2)
            
            # Check if it's listening on port 5002 (default subhost port)
            for attempt in range(15):  # Check for 15 seconds
                time.sleep(1)
                if self.is_port_open('localhost', 5002):
                    logger.info(f"Subhost dashboard successfully started and listening on port 5002")
                    return True
                logger.debug(f"Attempt {attempt+1}/15: Subhost dashboard not yet listening")
                # Check if process is still running
                if subhost_process.poll() is not None:
                    logger.error(f"Subhost dashboard process died during startup with exit code {subhost_process.returncode}")
                    return False
            
            logger.warning(f"Subhost dashboard process started (PID: {subhost_process.pid}) but not listening on port 5002")
            return True  # Return True anyway to keep the process managed
            
        except Exception as e:
            logger.error(f"Failed to start subhost dashboard: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def is_port_open(self, host, port, timeout=1):
        """Check if a port is open on the specified host"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False
    
    def check_dependencies(self):
        """Check if required dependencies are installed"""
        try:
            logger.info("Checking for required dependencies...")
            
            # Check if Flask is installed
            try:
                import flask
                logger.info("Flask is installed")
            except ImportError:
                logger.error("Flask is not installed")
                return False
                
            # Check if Flask-CORS is installed
            try:
                import flask_cors
                logger.info("Flask-CORS is installed")
            except ImportError:
                logger.warning("Flask-CORS is not installed - some features may not work")
                
            # Check other important dependencies
            for module in ["pystray", "PIL"]:
                try:
                    __import__(module)
                    logger.info(f"{module} is installed")
                except ImportError:
                    logger.error(f"{module} is not installed")
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Error checking dependencies: {e}")
            return False

    def install_dependencies(self):
        """Install missing dependencies"""
        try:
            if not self.server_manager_dir:
                logger.error("Server manager directory not set")
                return False
                
            setup_script = os.path.join(self.server_manager_dir, "setup.py")
            
            if not os.path.exists(setup_script):
                logger.error(f"Setup script not found: {setup_script}")
                return False
                
            logger.info("Running setup script to install dependencies...")
            
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                result = subprocess.run(
                    [sys.executable, setup_script, "--no-admin-check"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    startupinfo=startupinfo,
                    capture_output=True,
                    text=True
                )
            else:
                result = subprocess.run(
                    [sys.executable, setup_script, "--no-admin-check"],
                    capture_output=True,
                    text=True
                )
                
            if result.returncode != 0:
                logger.error(f"Failed to install dependencies: {result.stderr}")
                return False
                
            logger.info("Dependencies installed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error installing dependencies: {e}")
            return False

    def start_processes(self):
        """Start all server manager component processes based on cluster role"""
        try:
            # Check and install dependencies first
            if not self.check_dependencies():
                logger.warning("Some dependencies are missing, attempting to install...")
                if not self.install_dependencies():
                    logger.error("Failed to install dependencies, some components may not work")
            
            logger.info(f"Starting processes for cluster role: {self.cluster_role}")
            
            # Start components based on cluster role
            if self.cluster_role == "Host":
                # Host should run all components
                logger.info("Starting as Host - launching all components")
                
                # Start tray icon (only if not running as service)
                if not self.is_service:
                    if not self.start_tray_icon():
                        logger.warning("Failed to start tray icon, continuing anyway")
                else:
                    logger.info("Running as service - skipping tray icon")
                    
                # Start web server
                if not self.start_web_server():
                    logger.warning("Failed to start web server, continuing anyway")
                    
            elif self.cluster_role == "Subhost":
                # Subhost should only run minimal components and connect to host
                logger.info("Starting as Subhost - launching minimal components")
                
                # Start tray icon (only if not running as service)
                if not self.is_service:
                    if not self.start_tray_icon():
                        logger.warning("Failed to start tray icon, continuing anyway")
                else:
                    logger.info("Running as service - skipping tray icon")
                
                # Start subhost dashboard instead of main web server
                if not self.start_subhost_dashboard():
                    logger.warning("Failed to start subhost dashboard, continuing anyway")
                    
            else:
                # Unknown role - start minimal components
                logger.warning(f"Unknown cluster role '{self.cluster_role}' - starting minimal components")
                
                # Start tray icon (only if not running as service)
                if not self.is_service:
                    if not self.start_tray_icon():
                        logger.warning("Failed to start tray icon, continuing anyway")
                        
                # Start web server as fallback
                if not self.start_web_server():
                    logger.warning("Failed to start web server, continuing anyway")
                
            logger.info("All processes started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start processes: {str(e)}")
            return False
            
    def monitor_processes(self):
        """Monitor and restart processes if they crash"""
        restart_attempts = {"tray_icon": 0, "web_server": 0, "subhost_dashboard": 0}
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

                # Check subhost dashboard
                if "subhost_dashboard" in self.processes:
                    p = self.processes["subhost_dashboard"]
                    if p.poll() is not None:
                        restart_attempts["subhost_dashboard"] += 1
                        if restart_attempts["subhost_dashboard"] <= max_restart_attempts:
                            logger.warning(f"Subhost dashboard process exited with code {p.returncode}, restarting... (Attempt {restart_attempts['subhost_dashboard']}/{max_restart_attempts})")
                            if not self.start_subhost_dashboard():
                                logger.error("Failed to restart subhost dashboard process")
                        else:
                            logger.error(f"Subhost dashboard process has crashed {restart_attempts['subhost_dashboard']} times. Giving up.")
                    else:
                        # Reset counter if process is running
                        restart_attempts["subhost_dashboard"] = 0
                
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
