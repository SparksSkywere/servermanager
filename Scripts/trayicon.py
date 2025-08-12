import os
import sys
import subprocess
import threading
import logging
import winreg
import json
import time
import psutil
import platform
import datetime
import tempfile
import shutil
import socket
import webbrowser
import traceback
import signal
import argparse
import ctypes

# Import required for system tray functionality
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Required packages not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray", "pillow"])
    import pystray
    from PIL import Image, ImageDraw

# Add the parent directory to the path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Modules.common import ServerManagerModule

# Centralized logging
try:
    from Modules.logging import get_component_logger, log_dashboard_event
    logger = get_component_logger("TrayIcon")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("TrayIcon")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("TrayIcon debug mode enabled via environment")

class ServerManagerTrayIcon(ServerManagerModule):
    def __init__(self):
        super().__init__("TrayIcon")
        self.icon = None
        self.server_status = "Unknown"
        self.debug_mode = False
        self.dashboard_process = None
        self.webserver_status = "Disconnected"
        self.offline_mode = False
        self.standalone_mode = False  # New: track if running in standalone mode
        self.notifications_enabled = False  # Add flag to control notifications
        self.admin_dashboard_process = None  # Track admin dashboard process
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Tray Icon')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        parser.add_argument('--logpath', help='Path to log file')
        parser.add_argument('--standalone', action='store_true', help='Run in standalone mode')
        parser.add_argument('--notifications', action='store_true', help='Enable notification toasts')
        args = parser.parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            self.debug_mode = True
            
        # Set standalone mode
        if args.standalone:
            self.standalone_mode = True
            logger.info("Running in standalone mode")
            
        # Set notifications flag
        if args.notifications:
            self.notifications_enabled = True
            logger.info("Notifications enabled")
        
        # Write PID file for tray icon
        self.write_pid_file("trayicon", os.getpid())
        
        if args.logpath:
            self.configure_file_logging(args.logpath)
        else:
            # Set up file logging with default path
            self.configure_file_logging()

    def configure_file_logging(self, log_path=None):
        """Set up logging to file"""
        try:
            if not log_path:
                log_path = os.path.join(self.paths["logs"], "trayicon.log")
                
            # Ensure the directory exists
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            
            # Add file handler to logger
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"File logging configured: {log_path}")
        except Exception as e:
            logger.error(f"Failed to configure file logging: {str(e)}")
    
    def create_icon_image(self):
        """Create icon image for the tray"""
        # First try to use an existing icon file
        icon_path = os.path.join(self.paths["icons"], "servermanager.ico")
        if os.path.exists(icon_path):
            try:
                return Image.open(icon_path)
            except Exception as e:
                logger.error(f"Failed to load icon from {icon_path}: {str(e)}")
        
        # Fall back to creating a simple icon
        width = 64
        height = 64
        color = (0, 128, 255)  # Blue color
        
        image = Image.new('RGB', (width, height), color=(0, 0, 0))
        dc = ImageDraw.Draw(image)
        
        # Draw a simple server icon
        dc.rectangle((10, 10, width-10, height-10), fill=color)
        dc.rectangle((20, 20, width-20, 30), fill=(255, 255, 255))
        dc.rectangle((20, 40, width-20, 50), fill=(255, 255, 255))
        
        return image
    
    def create_menu(self):
        """Create the tray icon menu"""
        return pystray.Menu(
            pystray.MenuItem(
                f"Server Status: {self.server_status}",
                lambda: None,
                enabled=False
            ),
            pystray.MenuItem(
                f"Web Server: {self.webserver_status}",
                lambda: None,
                enabled=False
            ),
            pystray.MenuItem(
                "Open Dashboard",
                self.open_dashboard
            ),
            pystray.MenuItem(
                "Open Web Interface",
                self.open_web_interface
            ),
            pystray.MenuItem(
                "Open Admin Dashboard",
                self.open_admin_dashboard
            ),
            pystray.MenuItem(
                "Exit",
                self.exit_app
            )
        )

    def update_server_status(self):
        """Update server status in the menu"""
        # In a real implementation, this would query the server status
        if self.server_status == "Running":
            self.server_status = "Stopped"
        else:
            self.server_status = "Running"
        
        # Check web server status
        self.check_webserver_status()
        
        if self.icon:
            # Update with status
            status_text = f"Server: {self.server_status} | Web: {self.webserver_status}"
            self.icon.title = f"Server Manager - {status_text}"
            
            # Recreate the entire menu with updated status
            self.icon.menu = self.create_menu()
        
        # Schedule next update
        threading.Timer(10.0, self.update_server_status).start()

    def check_webserver_status(self):
        """Check if the web server is running and update status"""
        if self.offline_mode:
            self.webserver_status = "Offline Mode"
            return
            
        try:
            # Try to read the web server PID file first
            webserver_pid_file = os.path.join(self.paths["temp"], "webserver.pid")
            if os.path.exists(webserver_pid_file):
                try:
                    with open(webserver_pid_file, 'r') as f:
                        pid_info = json.load(f)
                    
                    pid = pid_info.get("ProcessId")
                    port = pid_info.get("Port", self.web_port)
                    
                    # Update web port from PID file if available
                    if port:
                        self.set_config_value("web_port", port)
                    
                    # Check if process is running
                    if pid and self.is_process_running(pid):
                        self.webserver_status = "Connected"
                        return
                except Exception as e:
                    logger.debug(f"Error checking web server PID file: {str(e)}")
            
            # If we get here, try to connect to the port directly
            if self.is_port_open('localhost', self.web_port):
                self.webserver_status = "Connected"
            else:
                self.webserver_status = "Disconnected"
                
        except Exception as e:
            logger.error(f"Error checking web server status: {str(e)}")
            self.webserver_status = "Error"

    def is_process_running(self, pid):
        """Check if a process with the given PID is running"""
        try:
            return psutil.pid_exists(pid)
        except:
            return False

    def open_web_interface(self):
        """Open the web interface in a browser"""
        if self.offline_mode:
            if self.icon and self.notifications_enabled:
                self.icon.notify(
                    "Cannot open web interface in offline mode",
                    "Server Manager"
                )
            return
            
        # Check if web server is running
        if self.webserver_status != "Connected":
            if self.icon and self.notifications_enabled:
                self.icon.notify(
                    "Web server is not connected. Starting web server...",
                    "Server Manager"
                )
                
            # Try to start the web server
            try:
                webserver_script = os.path.join(self.paths["scripts"], "webserver.py")
                if not os.path.exists(webserver_script):
                    logger.error(f"Web server script not found: {webserver_script}")
                    if self.icon and self.notifications_enabled:
                        self.icon.notify(f"Web server script not found: {webserver_script}", "Server Manager Error")
                    return
                
                # Build command with debug flag if needed
                cmd = [sys.executable, webserver_script]
                if self.debug_mode:
                    cmd.append("--debug")
                
                # Launch web server process with hidden console
                logger.info(f"Starting web server: {' '.join(cmd)}")
                
                if sys.platform == 'win32':
                    # On Windows, use CREATE_NO_WINDOW to hide console
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE
                    
                    proc = subprocess.Popen(
                        cmd,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        startupinfo=startupinfo,
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE
                    )
                else:
                    # On Unix, use start_new_session
                    proc = subprocess.Popen(
                        cmd,
                        start_new_session=True,
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE
                    )
                
                # Wait for web server to start
                connected = False
                logger.info(f"Waiting for web server to start on port {self.web_port}...")
                for attempt in range(10):
                    time.sleep(1)
                    logger.debug(f"Connection attempt {attempt+1}/10...")
                    if self.is_port_open('localhost', self.web_port):
                        connected = True
                        self.webserver_status = "Connected"
                        break
                
                if not connected:
                    logger.error(f"Failed to connect to web server after 10 seconds")
                    if self.icon and self.notifications_enabled:
                        self.icon.notify("Failed to start web server", "Server Manager Error")
                    return
                
            except Exception as e:
                logger.error(f"Failed to start web server: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                if self.icon and self.notifications_enabled:
                    self.icon.notify(f"Failed to start web server: {str(e)}", "Server Manager Error")
                return
    
        # Open the web interface in a browser
        try:
            url = f"http://localhost:{self.web_port}"
            logger.info(f"Opening web interface: {url}")
            webbrowser.open(url)
            
            # Show notification only if enabled
            if self.icon and self.notifications_enabled:
                self.icon.notify("Web interface opened in browser", "Server Manager")
                
        except Exception as e:
            logger.error(f"Failed to open web interface: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            if self.icon and self.notifications_enabled:
                self.icon.notify(f"Failed to open web interface: {str(e)}", "Server Manager Error")

    def open_dashboard(self):
        """Open the Python dashboard instead of web dashboard"""
        try:
            # First, ensure the web server is running for API calls
            if not self.offline_mode and self.webserver_status != "Connected":
                logger.info("Web server not running, starting it for dashboard API support...")
                self.start_webserver_for_dashboard()
            
            # Check if dashboard is already running
            dashboard_pid_file = os.path.join(self.paths["temp"], "dashboard.pid")
            if os.path.exists(dashboard_pid_file):
                try:
                    with open(dashboard_pid_file, 'r') as f:
                        pid_info = json.load(f)
                    
                    pid = pid_info.get("ProcessId")
                    if pid and self.is_process_running(pid):
                        logger.info("Dashboard already running, bringing to front")
                        return
                except Exception as e:
                    logger.error(f"Error checking dashboard PID file: {str(e)}")
            
            # Launch the dashboard script
            dashboard_script = os.path.join(self.paths["scripts"], "..", "host", "dashboard.py")
            if not os.path.exists(dashboard_script):
                # Try alternative path
                dashboard_script = os.path.join(self.paths["scripts"], "dashboard.py")
                if not os.path.exists(dashboard_script):
                    logger.error(f"Dashboard script not found: {dashboard_script}")
                    if self.icon and self.notifications_enabled:
                        self.icon.notify("Dashboard script not found", "Server Manager Error")
                    return
            
            # Build command with debug flag if needed
            cmd = [sys.executable, dashboard_script]
            if self.debug_mode:
                cmd.append("--debug")
            
            # Launch dashboard process with hidden console
            logger.info(f"Starting dashboard: {' '.join(cmd)}")
            
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                self.dashboard_process = subprocess.Popen(
                    cmd, 
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    close_fds=True
                )
            else:
                # On Unix, use start_new_session
                self.dashboard_process = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    close_fds=True
                )
            
            logger.info(f"Dashboard started with PID: {self.dashboard_process.pid}")
            
            # Show notification only if enabled
            if self.icon and self.notifications_enabled:
                self.icon.notify("Dashboard opened", "Server Manager")
                
        except Exception as e:
            logger.error(f"Failed to open dashboard: {str(e)}")
            if self.icon and self.notifications_enabled:
                self.icon.notify(f"Failed to open dashboard: {str(e)}", "Server Manager Error")

    def start_webserver_for_dashboard(self):
        """Start the web server specifically for dashboard API support"""
        try:
            webserver_script = os.path.join(self.paths["scripts"], "webserver.py")
            if not os.path.exists(webserver_script):
                logger.error(f"Web server script not found: {webserver_script}")
                return False

            cmd = [sys.executable, webserver_script]
            if self.debug_mode:
                cmd.append("--debug")

            logger.info(f"Starting web server for dashboard: {' '.join(cmd)}")

            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE

                proc = subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    startupinfo=startupinfo,
                    shell=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    shell=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )

            # Wait for web server to start
            connected = False
            logger.info(f"Waiting for web server to start on port {self.web_port}...")
            for attempt in range(20):  # Increased timeout to 20 seconds
                time.sleep(1)
                logger.debug(f"Connection attempt {attempt+1}/20...")
                if self.is_port_open('localhost', self.web_port):
                    connected = True
                    self.webserver_status = "Connected"
                    break
                # Check if process exited
                if proc.poll() is not None:
                    logger.error(f"Web server process exited with code {proc.returncode}")
                    # Read output for debugging
                    try:
                        stdout, stderr = proc.communicate(timeout=2)
                        if stderr:
                            logger.error(f"Web server stderr: {stderr.decode(errors='replace')}")
                        if stdout:
                            logger.info(f"Web server stdout: {stdout.decode(errors='replace')}")
                    except:
                        pass
                    break

            if not connected:
                logger.error(f"Failed to connect to web server after 20 seconds")
                if self.icon and self.notifications_enabled:
                    self.icon.notify("Failed to start web server", "Server Manager Error")
                return False

            logger.info("Web server started successfully for dashboard support")
            return True

        except Exception as e:
            logger.error(f"Failed to start web server for dashboard: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def open_admin_dashboard(self):
        """Open the admin dashboard for user management"""
        try:
            # Check if admin dashboard is already running
            admin_pid_file = os.path.join(self.paths["temp"], "admin_dashboard.pid")
            if os.path.exists(admin_pid_file):
                try:
                    with open(admin_pid_file, 'r') as f:
                        pid_info = json.load(f)
                    
                    pid = pid_info.get("ProcessId")
                    if pid and self.is_process_running(pid):
                        logger.info("Admin dashboard already running, bringing to front")
                        if self.icon and self.notifications_enabled:
                            self.icon.notify("Admin dashboard already running", "Server Manager")
                        return
                except Exception as e:
                    logger.error(f"Error checking admin dashboard PID file: {str(e)}")
            
            # First, ensure the web server is running for SQL connection
            if not self.offline_mode and self.webserver_status != "Connected":
                logger.info("Web server not running, starting it for admin dashboard SQL support...")
                self.start_webserver_for_dashboard()
            
            # Launch the admin dashboard script
            admin_script = os.path.join(self.paths["scripts"], "..", "Host", "admin_dashboard.py")
            if not os.path.exists(admin_script):
                # Try alternative path
                admin_script = os.path.join(self.paths["scripts"], "admin_dashboard.py")
                if not os.path.exists(admin_script):
                    logger.error(f"Admin dashboard script not found: {admin_script}")
                    if self.icon and self.notifications_enabled:
                        self.icon.notify("Admin dashboard script not found", "Server Manager Error")
                    return
            
            # Build command with debug flag if needed
            cmd = [sys.executable, admin_script]
            if self.debug_mode:
                cmd.append("--debug")
            
            # Launch admin dashboard process with hidden console
            logger.info(f"Starting admin dashboard: {' '.join(cmd)}")
            
            if sys.platform == 'win32':
                # On Windows, use CREATE_NO_WINDOW to hide console
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                
                self.admin_dashboard_process = subprocess.Popen(
                    cmd, 
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    startupinfo=startupinfo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    close_fds=True
                )
            else:
                # On Unix, use start_new_session
                self.admin_dashboard_process = subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    close_fds=True
                )
            
            # Write PID file for admin dashboard
            try:
                pid_info = {
                    "ProcessId": self.admin_dashboard_process.pid,
                    "StartTime": datetime.datetime.now().isoformat(),
                    "ProcessType": "admin_dashboard"
                }
                
                with open(admin_pid_file, 'w') as f:
                    json.dump(pid_info, f)
                    
                logger.debug(f"Admin dashboard PID file created: {admin_pid_file}")
            except Exception as e:
                logger.error(f"Failed to write admin dashboard PID file: {str(e)}")
            
            logger.info(f"Admin dashboard started with PID: {self.admin_dashboard_process.pid}")
            
            # Show notification only if enabled
            if self.icon and self.notifications_enabled:
                self.icon.notify("Admin dashboard opened", "Server Manager")
                
        except Exception as e:
            logger.error(f"Failed to open admin dashboard: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            if self.icon and self.notifications_enabled:
                self.icon.notify(f"Failed to open admin dashboard: {str(e)}", "Server Manager Error")

    def is_port_open(self, host, port, timeout=1):
        """Check if a port is open on the specified host"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            logger.debug(f"Port {port} check result: {result} (0 means open)")
            return result == 0
        except Exception as e:
            logger.error(f"Error checking port {port}: {str(e)}")
            return False
    
    def exit_app(self):
        """Exit the application"""
        logger.info("Exiting application")
        
        # First, attempt to stop the launcher process
        try:
            launcher_pid_file = os.path.join(self.paths["temp"], "launcher.pid")
            if os.path.exists(launcher_pid_file):
                with open(launcher_pid_file, 'r') as f:
                    pid_info = json.load(f)
                
                launcher_pid = pid_info.get("ProcessId")
                if launcher_pid and self.is_process_running(launcher_pid):
                    try:
                        launcher_process = psutil.Process(launcher_pid)
                        launcher_process.terminate()
                        logger.info(f"Terminated launcher process with PID {launcher_pid}")
                    except Exception as e:
                        logger.error(f"Error terminating launcher process: {str(e)}")
        except Exception as e:
            logger.error(f"Error accessing launcher PID file: {str(e)}")
        
        # Remove PID file
        try:
            pid_file = os.path.join(self.paths["temp"], "trayicon.pid")
            if os.path.exists(pid_file):
                os.remove(pid_file)
                logger.debug("Removed tray icon PID file")
        except Exception as e:
            logger.error(f"Error removing PID file: {str(e)}")
        
        # Stop dashboard if we started it
        if self.dashboard_process and self.dashboard_process.poll() is None:
            try:
                self.dashboard_process.terminate()
                logger.info("Terminated dashboard process")
            except Exception as e:
                logger.error(f"Error terminating dashboard process: {str(e)}")
        
        # Stop admin dashboard if we started it
        if self.admin_dashboard_process and self.admin_dashboard_process.poll() is None:
            try:
                self.admin_dashboard_process.terminate()
                logger.info("Terminated admin dashboard process")
            except Exception as e:
                logger.error(f"Error terminating admin dashboard process: {str(e)}")
        
        # Also try to find and close other dashboard instances by PID file
        try:
            dashboard_pid_file = os.path.join(self.paths["temp"], "dashboard.pid")
            if os.path.exists(dashboard_pid_file):
                with open(dashboard_pid_file, 'r') as f:
                    pid_info = json.load(f)
                
                dashboard_pid = pid_info.get("ProcessId")
                if dashboard_pid and self.is_process_running(dashboard_pid):
                    try:
                        dashboard_process = psutil.Process(dashboard_pid)
                        dashboard_process.terminate()
                        logger.info(f"Terminated existing dashboard process with PID {dashboard_pid}")
                    except Exception as e:
                        logger.error(f"Error terminating existing dashboard: {str(e)}")
                
                # Remove the PID file
                os.remove(dashboard_pid_file)
        except Exception as e:
            logger.error(f"Error terminating existing dashboard: {str(e)}")
        
        # Also try to find and close admin dashboard instances by PID file
        try:
            admin_pid_file = os.path.join(self.paths["temp"], "admin_dashboard.pid")
            if os.path.exists(admin_pid_file):
                with open(admin_pid_file, 'r') as f:
                    pid_info = json.load(f)
                
                admin_pid = pid_info.get("ProcessId")
                if admin_pid and self.is_process_running(admin_pid):
                    try:
                        admin_process = psutil.Process(admin_pid)
                        admin_process.terminate()
                        logger.info(f"Terminated existing admin dashboard process with PID {admin_pid}")
                    except Exception as e:
                        logger.error(f"Error terminating existing admin dashboard: {str(e)}")
                
                # Remove the PID file
                os.remove(admin_pid_file)
        except Exception as e:
            logger.error(f"Error terminating existing admin dashboard: {str(e)}")
        
        # As a final failsafe, call the stop_servermanager script to ensure all processes are terminated
        try:
            stop_script = os.path.join(self.paths["scripts"], "stop_servermanager.py")
            if os.path.exists(stop_script):
                subprocess.run([sys.executable, stop_script], timeout=10)
                logger.info("Executed stop_servermanager.py")
        except Exception as e:
            logger.error(f"Error running stop_servermanager.py: {str(e)}")
        
        # Stop the icon
        if self.icon:
            self.icon.stop()
        
        # Exit the application
        logger.info("Server Manager tray icon terminated")

    def run(self):
        """Run the tray icon application"""
        try:
            # Create icon image
            image = self.create_icon_image()
            
            # Create and run the tray icon
            self.icon = pystray.Icon("server_manager", image, "Server Manager")
            self.icon.menu = self.create_menu()
            
            # Show notification on startup only if enabled
            def setup(icon):
                icon.visible = True
                if self.notifications_enabled:
                    icon.notify("Server Manager started", "Tray Icon")
                logger.info("Tray icon is now visible and running")
                # Start server status update thread after icon is visible
                self.update_server_status()
            
            # Run the icon
            logger.info("Starting tray icon")
            
            # Prevent immediate exit in standalone mode
            if self.standalone_mode:
                logger.info("Running in standalone mode - tray icon will remain active")
            
            # Run the icon (this is blocking)
            self.icon.run(setup=setup)
            
        except Exception as e:
            logger.error(f"Error running tray icon: {str(e)}")
            # Print to stderr for immediate visibility
            print(f"ERROR: {str(e)}", file=sys.stderr)
            return False
        
        return True

def main():
    try:
        # Create and run tray icon
        tray_icon = ServerManagerTrayIcon()
        result = tray_icon.run()
        
        if not result:
            logger.error("Tray icon failed to run properly")
            return 1
            
        logger.info("Tray icon exited normally")
        return 0
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        # Print to stderr for immediate visibility
        print(f"CRITICAL ERROR: {str(e)}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    # Capture the exit code
    exit_code = main()
    
    # Log before exiting
    logger.info(f"Exiting with code {exit_code}")
    
    # Exit with the appropriate code
    sys.exit(exit_code)