# System tray icon
import os
import sys
import subprocess
import threading
import logging
import winreg
import json
import time
import psutil
import datetime
import socket
import webbrowser
import traceback
import signal
import argparse
import ctypes

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    # Logger not yet available, use subprocess to install packages
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray", "pillow"])
    import pystray
    from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Modules.common import ServerManagerModule, setup_module_logging
from Modules.server_logging import log_dashboard_event

logger = setup_module_logging("TrayIcon")


def is_another_trayicon_running():
    # Check for existing trayicon process
    try:
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'cmdline', 'name']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and proc.info['pid'] != current_pid:
                    cmdline_str = ' '.join(cmdline).lower() if cmdline else ''
                    if 'trayicon.py' in cmdline_str and ('python' in proc.info['name'].lower() or 'pythonw' in proc.info['name'].lower()):
                        logger.warning(f"Found existing trayicon: PID={proc.info['pid']}")
                        return True, proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False, None
    except Exception as e:
        logger.error(f"Trayicon check failed: {e}")
        return False, None


class ServerManagerTrayIcon(ServerManagerModule):
    # - Lives in system tray
    # - Quick access to dashboard, web UI, admin panel
    def __init__(self):
        super().__init__("TrayIcon")
        self.icon = None
        self.server_status = "Unknown"
        self.debug_mode = False
        self.dashboard_process = None
        self.webserver_status = "Disconnected"
        self.offline_mode = False
        self.standalone_mode = False
        self.notifications_enabled = False
        self.admin_dashboard_process = None
        
        parser = argparse.ArgumentParser(description='Server Manager Tray Icon')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        parser.add_argument('--logpath', help='Path to log file')
        parser.add_argument('--standalone', action='store_true', help='Run in standalone mode')
        parser.add_argument('--notifications', action='store_true', help='Enable notification toasts')
        parser.add_argument('--force', action='store_true', help='Force start even if another instance is running')
        args = parser.parse_args()
        
        if not args.force:
            already_running, existing_pid = is_another_trayicon_running()
            if already_running:
                logger.warning(f"Already running (PID: {existing_pid})-exiting. Use --force to start anyway.")
                sys.exit(0)
        
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

    def _find_window_by_title(self, partial_title):
        # Find a window by partial title match
        try:
            import ctypes
            
            # Callback function for EnumWindows
            def enum_callback(hwnd, result_list):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    title = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)
                    if partial_title.lower() in title.value.lower():
                        result_list.append((hwnd, title.value))
                return True
            
            # Enumerate all windows
            result_list = []
            enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            callback = enum_proc(enum_callback)
            
            ctypes.windll.user32.EnumWindows(callback, ctypes.byref(ctypes.c_int(id(result_list))))
            
            # Return the first matching window handle
            if result_list:
                return result_list[0][0]
        except Exception as e:
            logger.warning(f"Error finding window by title: {e}")
        return None

    def configure_file_logging(self, log_path=None):
        # Configure debug mode logging level
        if self.debug_mode:
            logger.setLevel(logging.DEBUG)
            for handler in logger.handlers:
                handler.setLevel(logging.DEBUG)
        logger.debug(f"Logging level configured: {'DEBUG' if self.debug_mode else 'INFO'}")
    
    def create_icon_image(self):
        # Create icon image for the tray
        # First try to use an existing icon file
        icon_path = os.path.join(self.paths["icons"], "servermanager.ico")
        if os.path.exists(icon_path):
            try:
                return Image.open(icon_path)
            except Exception as e:
                logger.error(f"Failed to load icon from {icon_path}: {str(e)}")
        
        # - Fall back to simple icon
        width = 64
        height = 64
        color = (0, 128, 255)  # Blue colour
        
        image = Image.new('RGB', (width, height), color=(0, 0, 0))
        dc = ImageDraw.Draw(image)
        
        # - Draw a simple server icon
        dc.rectangle((10, 10, width-10, height-10), fill=color)
        dc.rectangle((20, 20, width-20, 30), fill=(255, 255, 255))
        dc.rectangle((20, 40, width-20, 50), fill=(255, 255, 255))
        
        return image
    
    def get_running_server_count(self):
        # - Get count of running servers
        try:
            if hasattr(self, 'server_manager') and self.server_manager:
                running_servers = self.server_manager.get_running_servers()
                return len(running_servers) if running_servers else 0
            return 0
        except Exception as e:
            logger.error(f"Error getting running server count: {str(e)}")
            return 0

    def create_menu(self):
        # Create the tray icon menu
        return pystray.Menu(
            pystray.MenuItem(
                f"Running servers ({self.get_running_server_count()})",
                lambda: None,
                enabled=False
            ),
            pystray.MenuItem(
                f"Webserver ({self.webserver_status})",
                lambda: None,
                enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open Admin Dashboard",
                self.open_admin_dashboard
            ),
            pystray.MenuItem(
                "Open Server Dashboard",
                self.open_dashboard
            ),
            pystray.MenuItem(
                "Open Web Dashboard",
                self.open_web_interface
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Restart Servermanager",
                self.restart_servermanager
            ),
            pystray.MenuItem(
                "Exit",
                self.exit_app
            )
        )

    def restart_servermanager(self):
        # Restart the server manager by stopping all processes and restarting them
        logger.info("Restarting Server Manager...")
        
        try:
            # First, try to stop all running servers gracefully
            if hasattr(self, 'server_manager') and self.server_manager:
                try:
                    running_servers = self.server_manager.get_running_servers()
                    for server_name in running_servers:
                        logger.info(f"Stopping server: {server_name}")
                        self.server_manager.stop_server(server_name)
                except Exception as e:
                    logger.error(f"Error stopping servers: {str(e)}")
            
            # Stop webserver if running
            try:
                webserver_pid_file = os.path.join(self.paths["temp"], "webserver.pid")
                if os.path.exists(webserver_pid_file):
                    with open(webserver_pid_file, 'r') as f:
                        pid_info = json.load(f)
                        pid = pid_info.get("ProcessId")
                        if pid and self.is_process_running(pid):
                            logger.info("Stopping webserver...")
                            os.kill(pid, signal.SIGTERM)
                            time.sleep(2)  # Wait for graceful shutdown
            except Exception as e:
                logger.error(f"Error stopping webserver: {str(e)}")
            
            # Stop dashboard if running
            try:
                dashboard_pid_file = os.path.join(self.paths["temp"], "dashboard.pid")
                if os.path.exists(dashboard_pid_file):
                    with open(dashboard_pid_file, 'r') as f:
                        pid_info = json.load(f)
                        pid = pid_info.get("ProcessId")
                        if pid and self.is_process_running(pid):
                            logger.info("Stopping dashboard...")
                            os.kill(pid, signal.SIGTERM)
                            time.sleep(1)
            except Exception as e:
                logger.error(f"Error stopping dashboard: {str(e)}")
            
            # Restart the services
            logger.info("Starting services...")
            
            # Start webserver
            try:
                webserver_script = os.path.join(self.paths["scripts"], "start_webserver.py")
                if os.path.exists(webserver_script):
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = 0  # SW_HIDE
                        subprocess.Popen([sys.executable, webserver_script], 
                                       creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                                       startupinfo=startupinfo,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL)
                    else:
                        subprocess.Popen([sys.executable, webserver_script], 
                                       start_new_session=True)
                    logger.info("Webserver restarted")
            except Exception as e:
                logger.error(f"Error restarting webserver: {str(e)}")
            
            # Show notification
            if self.notifications_enabled and self.icon:
                self.icon.notify("Server Manager restarted", "Server Manager")
                
        except Exception as e:
            logger.error(f"Error during restart: {str(e)}")
            if self.notifications_enabled and self.icon:
                self.icon.notify(f"Restart failed: {str(e)}", "Server Manager Error")

    def update_server_status(self):
        # Update server status in menu
        try:
            # Init server manager if needed
            if not hasattr(self, 'server_manager') or self.server_manager is None:
                try:
                    from Modules.server_manager import ServerManager
                    self.server_manager = ServerManager()
                    logger.info("ServerManager initialised for status updates")
                except Exception as e:
                    logger.error(f"ServerManager init failed: {str(e)}")
                    self.server_status = "Error"
                    return
            
            # Get running servers
            try:
                running_servers = self.server_manager.get_running_servers()
                running_count = len(running_servers) if running_servers else 0
            except Exception as e:
                logger.error(f"Running servers fetch failed: {str(e)}")
                running_count = 0
            
            # Web server status
            self.check_webserver_status()
            
            # Update icon if valid
            if self.icon:
                try:
                    _ = self.icon._icon
                    status_text = f"Running servers ({running_count}) | Webserver ({self.webserver_status})"
                    self.icon.title = f"Server Manager - {status_text}"
                    
                    # Recreate menu with updated status
                    self.icon.menu = self.create_menu()
                    logger.debug(f"Tray icon updated: {status_text}")
                except (AttributeError, RuntimeError, Exception) as icon_error:
                    logger.error(f"Tray icon invalid: {str(icon_error)}")
            else:
                logger.warning("Tray icon is None")
        except Exception as e:
            logger.error(f"Status update failed: {str(e)}")
        
        # Schedule next update
        try:
            # Use a safer threading approach
            timer = threading.Timer(10.0, self.update_server_status)
            timer.daemon = True  # Make sure timer thread doesn't prevent shutdown
            timer.start()
        except Exception as e:
            logger.error(f"Error scheduling next status update: {str(e)}")
            # If we can't schedule the next update, try again in 30 seconds
            try:
                timer = threading.Timer(30.0, self.update_server_status)
                timer.daemon = True
                timer.start()
            except Exception as retry_error:
                logger.error(f"Failed to reschedule status update even with retry: {str(retry_error)}")

    def check_webserver_status(self):
        # Check if the web server is running and update status
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
        # Check if a process with the given PID is running
        try:
            return psutil.pid_exists(pid)
        except:
            return False

    def open_web_interface(self):
        # Open the web interface in a browser, starting the webserver if needed
        logger.info("Opening web interface...")
        
        # Check if we're in offline mode
        if self.offline_mode:
            logger.info("Currently in offline mode")
            if self.icon and self.notifications_enabled:
                self.icon.notify(
                    "Cannot open web interface in offline mode",
                    "Server Manager"
                )
            return
            
        # First, always check current webserver status
        self.check_webserver_status()
        logger.info(f"Current webserver status: {self.webserver_status}")
            
        # Check if web server is running
        if self.webserver_status != "Connected":
            logger.info("Web server not connected, attempting to start...")
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
                
                # Build command (webserver doesn't accept --debug flag)
                cmd = [sys.executable, webserver_script]
                
                # Launch web server process with hidden console
                logger.info(f"Starting web server: {' '.join(cmd)}")
                logger.info(f"Working directory: {self.server_manager_dir}")
                logger.info(f"Using port: {self.web_port}")
                
                if sys.platform == 'win32':
                    # On Windows, use CREATE_NO_WINDOW to hide console
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE
                    
                    proc = subprocess.Popen(
                        cmd,
                        cwd=self.server_manager_dir,  # Set working directory
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
                        cwd=self.server_manager_dir,  # Set working directory
                        start_new_session=True,
                        shell=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE
                    )
                
                logger.info(f"Web server process started with PID: {proc.pid}")
                
                # Wait for web server to start with better timing
                connected = False
                logger.info(f"Waiting for web server to start on port {self.web_port}...")
                for attempt in range(15):  # Increased to 15 seconds
                    time.sleep(1)
                    logger.debug(f"Connection attempt {attempt+1}/15...")
                    if self.is_port_open('localhost', self.web_port):
                        connected = True
                        self.webserver_status = "Connected"
                        logger.info("Web server connected successfully!")
                        break
                
                if not connected:
                    logger.error(f"Failed to connect to web server after 15 seconds")
                    # Try to get some error information from the process
                    try:
                        if proc.poll() is not None:
                            stdout, stderr = proc.communicate(timeout=2)
                            if stderr:
                                logger.error(f"Web server stderr: {stderr.decode(errors='replace')}")
                            if stdout:
                                logger.info(f"Web server stdout: {stdout.decode(errors='replace')}")
                        else:
                            logger.error("Web server process is still running but port is not accessible")
                    except Exception as debug_e:
                        logger.error(f"Failed to get process output: {debug_e}")
                        
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
        # Open the Python dashboard - runs in background thread to avoid blocking trayicon
        try:
            logger.debug("open_dashboard() called")
            # Run the actual launch in a background thread to prevent trayicon from freezing
            launch_thread = threading.Thread(target=self._open_dashboard_async, daemon=True)
            launch_thread.start()
        except Exception as e:
            logger.error(f"Failed to open dashboard: {e}")
            logger.error(traceback.format_exc())
    
    def _open_dashboard_async(self):
        # Async implementation of dashboard launch - runs in background thread
        try:
            logger.debug("Starting dashboard launch...")
            
            if not self.offline_mode and self.webserver_status != "Connected":
                logger.debug("Starting webserver for dashboard API support...")
                webserver_thread = threading.Thread(target=self.start_webserver_for_dashboard, daemon=True)
                webserver_thread.start()
            
            # Check if dashboard is already running
            dashboard_pid_file = os.path.join(self.paths["temp"], "dashboard.pid")
            
            if os.path.exists(dashboard_pid_file):
                try:
                    with open(dashboard_pid_file, 'r') as f:
                        pid_info = json.load(f)
                    
                    pid = pid_info.get("ProcessId")
                    if pid and self.is_process_running(pid):
                        logger.debug(f"Dashboard already running with PID {pid}, bringing to front")
                        try:
                            import ctypes
                            hwnd = self._find_window_by_title("Server Manager Dashboard")
                            if hwnd:
                                ctypes.windll.user32.ShowWindow(hwnd, 9)
                                ctypes.windll.user32.SetForegroundWindow(hwnd)
                                return  # Successfully brought to front
                            else:
                                logger.debug("Could not find dashboard window, starting new instance")
                        except Exception as e:
                            logger.debug(f"Could not bring dashboard window to front: {e}")
                        # Remove the old PID file to avoid conflicts
                        try:
                            os.remove(dashboard_pid_file)
                        except Exception:
                            pass
                    else:
                        logger.debug(f"PID {pid} is not running, will start new dashboard")
                except Exception as e:
                    logger.warning(f"Error checking dashboard PID file: {str(e)}")
            
            # Launch the dashboard script
            dashboard_script = os.path.join(self.paths["scripts"], "..", "Host", "dashboard.py")
            
            if not os.path.exists(dashboard_script):
                # Try alternative path
                dashboard_script = os.path.join(self.paths["scripts"], "dashboard.py")
                
                if not os.path.exists(dashboard_script):
                    # Try another alternative - relative to server_manager_dir
                    dashboard_script = os.path.join(str(self.server_manager_dir or ""), "Host", "dashboard.py")
                    
                    if not os.path.exists(dashboard_script):
                        logger.error("Dashboard script not found in any location!")
                        if self.icon and self.notifications_enabled:
                            self.icon.notify("Dashboard script not found", "Server Manager Error")
                        return
            
            # Normalise the path
            dashboard_script = os.path.normpath(dashboard_script)
            
            # Use pythonw.exe for GUI applications to prevent console window
            python_exe = sys.executable
            if python_exe.lower().endswith("python.exe"):
                pythonw_exe = python_exe[:-4] + "w.exe"  # Replace 'python.exe' with 'pythonw.exe'
                if os.path.exists(pythonw_exe):
                    python_exe = pythonw_exe
            
            # Verify python executable exists
            if not os.path.exists(python_exe):
                logger.error(f"Python executable does not exist: {python_exe}")
                return
            
            # Build command with debug flag if needed
            cmd = [python_exe, dashboard_script]
            if self.debug_mode:
                cmd.append("--debug")
            
            logger.debug(f"Starting dashboard: {' '.join(cmd)}")
            
            if sys.platform == 'win32':
                # For GUI applications like dashboard, hide console window
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE - hide the console window
                
                # Use DETACHED_PROCESS and CREATE_NO_WINDOW to prevent console
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                
                try:
                    self.dashboard_process = subprocess.Popen(
                        cmd, 
                        cwd=self.server_manager_dir,
                        creationflags=creation_flags,
                        startupinfo=startupinfo,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        close_fds=True
                    )
                    logger.info(f"Dashboard started with PID: {self.dashboard_process.pid}")
                        
                except Exception as e:
                    logger.error(f"Failed to create dashboard process: {e}")
                    raise
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
            
            # Quick check if process started successfully (non-blocking)
            time.sleep(0.5)
            
            poll_result = self.dashboard_process.poll()
            if poll_result is not None:
                logger.error(f"Dashboard process exited immediately with return code: {poll_result}")
            
            # Show notification only if enabled
            if self.icon and self.notifications_enabled:
                self.icon.notify("Dashboard opened", "Server Manager")
                
        except Exception as e:
            logger.error(f"Failed to open dashboard: {str(e)}")
            logger.error(traceback.format_exc())
            if self.icon and self.notifications_enabled:
                self.icon.notify(f"Failed to open dashboard: {str(e)}", "Server Manager Error")

    def start_webserver_for_dashboard(self):
        # Start the web server specifically for dashboard API support
        try:
            webserver_script = os.path.join(self.paths["scripts"], "webserver.py")
            if not os.path.exists(webserver_script):
                logger.error(f"Web server script not found: {webserver_script}")
                return False

            # Build command (webserver doesn't accept --debug flag)
            cmd = [sys.executable, webserver_script]

            logger.info(f"Starting web server for dashboard: {' '.join(cmd)}")

            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE

                proc = subprocess.Popen(
                    cmd,
                    cwd=self.server_manager_dir,  # Set working directory
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    startupinfo=startupinfo,
                    shell=False
                    # Don't redirect pipes to prevent blocking
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=self.server_manager_dir,  # Set working directory
                    start_new_session=True,
                    shell=False
                    # Don't redirect pipes to prevent blocking
                )

            # Wait for web server to start (reduced timeout since it's background)
            connected = False
            logger.info(f"Waiting for web server to start on port {self.web_port}...")
            for attempt in range(5):  # Reduced to 5 seconds
                time.sleep(1)
                logger.debug(f"Connection attempt {attempt+1}/5...")
                if self.is_port_open('localhost', self.web_port):
                    connected = True
                    self.webserver_status = "Connected"
                    break
                # Check if process exited
                if proc.poll() is not None:
                    logger.error(f"Web server process exited with code {proc.returncode}")
                    # Can't read output since pipes were removed to prevent blocking
                    break

            if not connected:
                logger.error(f"Failed to connect to web server after 5 seconds")
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
        # Open the admin dashboard for user management
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
                        # Try to bring the existing window to the front
                        try:
                            import ctypes
                            # Find and bring the admin dashboard window to front
                            hwnd = self._find_window_by_title("Admin Dashboard")
                            if hwnd:
                                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                                ctypes.windll.user32.SetForegroundWindow(hwnd)
                        except Exception as e:
                            logger.warning(f"Could not bring admin dashboard window to front: {e}")
                        if self.icon and self.notifications_enabled:
                            self.icon.notify("Admin dashboard already running", "Server Manager")
                        return
                except Exception as e:
                    logger.error(f"Error checking admin dashboard PID file: {str(e)}")
            
            # First, ensure the web server is running for SQL connection
            if not self.offline_mode and self.webserver_status != "Connected":
                logger.info("Web server not running, starting it for admin dashboard SQL support...")
                # Start webserver in background without waiting
                import threading
                webserver_thread = threading.Thread(target=self.start_webserver_for_dashboard, daemon=True)
                webserver_thread.start()
            
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
            # Use pythonw.exe for GUI applications to prevent console window
            python_exe = sys.executable
            if python_exe.lower().endswith("python.exe"):
                pythonw_exe = python_exe[:-4] + "w.exe"
                if os.path.exists(pythonw_exe):
                    python_exe = pythonw_exe
            
            cmd = [python_exe, admin_script]
            if self.debug_mode:
                cmd.append("--debug")
            
            # Launch admin dashboard process - hide console for GUI apps
            logger.info(f"Starting admin dashboard: {' '.join(cmd)}")
            
            if sys.platform == 'win32':
                # For GUI applications like admin dashboard, use CREATE_NO_WINDOW and pythonw.exe
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE - hide console window
                logger.info("Launching admin dashboard with SW_HIDE")
                
                self.admin_dashboard_process = subprocess.Popen(
                    cmd, 
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
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
        # Check if a port is open on the specified host
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
        # Exit the application
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
                # Use CREATE_NO_WINDOW to prevent console popup on Windows
                startupinfo = None
                creationflags = 0
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                subprocess.run([sys.executable, stop_script], timeout=10,
                              startupinfo=startupinfo, creationflags=creationflags)
                logger.info("Executed stop_servermanager.py")
        except Exception as e:
            logger.error(f"Error running stop_servermanager.py: {str(e)}")
        
        # Stop the icon
        if self.icon:
            self.icon.stop()
        
        # Exit the application
        logger.info("Server Manager tray icon terminated")

    def run(self):
        # Run the tray icon application
        try:
            # Create icon image
            image = self.create_icon_image()
            
            # Create and run the tray icon
            self.icon = pystray.Icon("server_manager", image, "Server Manager")
            self.icon.menu = self.create_menu()
            
            # Show notification on startup only if enabled
            def setup(icon):
                try:
                    icon.visible = True
                    if self.notifications_enabled:
                        icon.notify("Server Manager started", "Tray Icon")
                    logger.info("Tray icon is now visible and running")
                    # Start server status update thread after icon is visible
                    self.update_server_status()
                except Exception as setup_error:
                    logger.error(f"Error in tray icon setup: {str(setup_error)}")
            
            # Run the icon
            logger.info("Starting tray icon")
            
            # Prevent immediate exit in standalone mode
            if self.standalone_mode:
                logger.info("Running in standalone mode - tray icon will remain active")
            
            # Run the icon (this is blocking)
            self.icon.run(setup=setup)
            
        except ImportError as e:
            logger.error(f"Required modules not available: {str(e)}")
            print(f"ERROR: Required modules not available. Please install pystray and pillow: pip install pystray pillow", file=sys.stderr)
            return False
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