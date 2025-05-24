import os
import sys
import subprocess
import logging
import winreg
import webbrowser
import signal
import argparse
from pathlib import Path
from datetime import datetime
import threading
import json

# Import required for system tray functionality
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Required packages not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray", "pillow"])
    import pystray
    from PIL import Image, ImageDraw

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("TrayIcon")

class ServerManagerTrayIcon:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.icon = None
        self.web_port = 8080
        self.server_status = "Unknown"
        self.debug_mode = False
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Tray Icon')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        parser.add_argument('--logpath', help='Path to log file')
        args = parser.parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            self.debug_mode = True
        
        # Initialize and start the tray icon
        self.initialize()
        if args.logpath:
            self.configure_file_logging(args.logpath)
        
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
    
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            self.web_port = int(winreg.QueryValueEx(key, "WebPort")[0])
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "icons": os.path.join(self.server_manager_dir, "icons")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Write PID file
            self.write_pid_file("trayicon", os.getpid())
            
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
        dc.rectangle([(10, 10), (width-10, height-10)], fill=color)
        dc.rectangle([(20, 20), (width-20, 30)], fill=(255, 255, 255))
        dc.rectangle([(20, 40), (width-20, 50)], fill=(255, 255, 255))
        
        return image
    
    def create_menu(self, icon):
        """Create the tray icon menu"""
        return pystray.Menu(
            pystray.MenuItem(
                "Server Status",
                lambda: None,
                enabled=False
            ),
            pystray.MenuItem(
                "Open Dashboard",
                self.open_dashboard
            ),
            pystray.MenuItem(
                "Toggle Debug Mode",
                self.toggle_debug_mode
            ),
            pystray.MenuItem(
                "Exit",
                self.exit_app
            )
        )
    
    def update_server_status(self):
        """Update server status in the menu"""
        # This would normally check the actual server status
        # For now, we'll just toggle between running and stopped
        threading.Timer(10.0, self.update_server_status).start()
        
        # In a real implementation, this would query the server status
        if self.server_status == "Running":
            self.server_status = "Stopped"
        else:
            self.server_status = "Running"
            
        if self.icon:
            self.icon.title = f"Server Manager - {self.server_status}"
    
    def open_dashboard(self):
        """Open the web dashboard in a browser"""
        try:
            url = f"http://localhost:{self.web_port}"
            webbrowser.open(url)
            logger.info(f"Opening dashboard: {url}")
        except Exception as e:
            logger.error(f"Failed to open dashboard: {str(e)}")
    
    def toggle_debug_mode(self):
        """Toggle debug mode"""
        self.debug_mode = not self.debug_mode
        
        if self.debug_mode:
            logger.setLevel(logging.DEBUG)
            logger.debug("Debug mode enabled")
        else:
            logger.setLevel(logging.INFO)
            logger.info("Debug mode disabled")
            
        # Show notification
        if self.icon:
            self.icon.notify(
                f"Debug mode {'enabled' if self.debug_mode else 'disabled'}",
                "Server Manager"
            )
    
    def exit_app(self):
        """Exit the application"""
        logger.info("Exiting application")
        
        # Remove PID file
        try:
            pid_file = os.path.join(self.paths["temp"], "trayicon.pid")
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except Exception as e:
            logger.error(f"Error removing PID file: {str(e)}")
        
        # Stop the icon
        if self.icon:
            self.icon.stop()
            
        # Stop all related processes
        try:
            stop_script = os.path.join(self.paths["scripts"], "stop_servermanager.py")
            if os.path.exists(stop_script):
                subprocess.Popen([sys.executable, stop_script])
        except Exception as e:
            logger.error(f"Error stopping server manager: {str(e)}")
    
    def run(self):
        """Run the tray icon application"""
        try:
            # Create icon image
            image = self.create_icon_image()
            
            # Create and run the tray icon
            self.icon = pystray.Icon("server_manager", image, "Server Manager")
            self.icon.menu = self.create_menu(self.icon)
            
            # Start server status update thread
            self.update_server_status()
            
            # Show notification on startup
            def setup(icon):
                icon.visible = True
                icon.notify(
                    "Server Manager is now running in the system tray",
                    "Server Manager"
                )
            
            # Run the icon
            logger.info("Starting tray icon")
            self.icon.run(setup=setup)
            
        except Exception as e:
            logger.error(f"Error running tray icon: {str(e)}")
            return False
            
        return True

def main():
    try:
        # Create and run tray icon
        tray_icon = ServerManagerTrayIcon()
        tray_icon.run()
        return 0
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
