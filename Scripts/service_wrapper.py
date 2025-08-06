#!/usr/bin/env python3
import os
import sys
import time
import logging
import servicemanager
import socket
import json
import traceback
from pathlib import Path

# Add the parent directory to the path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import win32serviceutil
    import win32service
    import win32event
    import win32api
except ImportError:
    print("Error: pywin32 is required for Windows service functionality")
    print("Install with: pip install pywin32")
    sys.exit(1)

# Import our launcher
from Scripts.launcher import ServerManagerLauncher

class ServerManagerService(win32serviceutil.ServiceFramework):
    """Windows Service for Server Manager"""
    
    _svc_name_ = "ServerManagerService"
    _svc_display_name_ = "Server Manager Service"
    _svc_description_ = "Manages game servers and provides web dashboard interface"
    _svc_deps_ = None  # sequence of service names on which this depends
    _exe_name_ = None  # Default to PythonService.exe
    _exe_args_ = None  # Default to no arguments
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.launcher = None
        self.running = False
        
        # Set up logging for service
        self.setup_service_logging()
        
    def setup_service_logging(self):
        """Configure logging for the service"""
        try:
            # Get server manager directory from registry
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\Servermanager")
            server_manager_dir = winreg.QueryValueEx(key, "ServerManagerPath")[0]
            winreg.CloseKey(key)
            
            # Create logs directory if it doesn't exist
            logs_dir = os.path.join(server_manager_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            
            # Configure logging
            log_file = os.path.join(logs_dir, "service.log")
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file),
                    logging.StreamHandler()
                ]
            )
            
            self.logger = logging.getLogger("ServerManagerService")
            self.logger.info("Service logging initialized")
            
        except Exception as e:
            # Fallback logging if registry read fails
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger("ServerManagerService")
            self.logger.error(f"Failed to setup service logging: {e}")
    
    def SvcStop(self):
        """Called when the service is asked to stop"""
        self.logger.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.running = False
        
        # Stop the launcher
        if self.launcher:
            try:
                self.launcher.cleanup()
            except Exception as e:
                self.logger.error(f"Error stopping launcher: {e}")
    
    def SvcDoRun(self):
        """Called when the service is started"""
        try:
            self.logger.info("Server Manager Service starting...")
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            
            self.running = True
            self.main_loop()
            
        except Exception as e:
            self.logger.error(f"Service error: {e}")
            self.logger.error(traceback.format_exc())
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_ERROR_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, f'Error: {e}')
            )
    
    def main_loop(self):
        """Main service loop"""
        try:
            # Initialize and start the launcher in service mode
            self.launcher = ServerManagerLauncher()
            self.launcher.is_service = True
            
            self.logger.info("Starting Server Manager launcher...")
            
            # Start the launcher in a separate thread
            import threading
            launcher_thread = threading.Thread(target=self.launcher.run)
            launcher_thread.daemon = True
            launcher_thread.start()
            
            self.logger.info("Server Manager Service started successfully")
            
            # Wait for stop signal
            while self.running:
                # Wait for stop event or timeout every 30 seconds
                rc = win32event.WaitForSingleObject(self.hWaitStop, 30000)
                if rc == win32event.WAIT_OBJECT_0:
                    # Stop event was signaled
                    break
                elif rc == win32event.WAIT_TIMEOUT:
                    # Timeout - check if launcher is still running
                    if not launcher_thread.is_alive():
                        self.logger.warning("Launcher thread died, restarting...")
                        launcher_thread = threading.Thread(target=self.launcher.run)
                        launcher_thread.daemon = True
                        launcher_thread.start()
            
            self.logger.info("Server Manager Service stopping...")
            
        except Exception as e:
            self.logger.error(f"Main loop error: {e}")
            self.logger.error(traceback.format_exc())
            raise

def install_service():
    """Install the service"""
    try:
        # Install the service
        win32serviceutil.InstallService(
            ServerManagerService,
            ServerManagerService._svc_name_,
            ServerManagerService._svc_display_name_,
            startType=win32service.SERVICE_AUTO_START,
            description=ServerManagerService._svc_description_
        )
        
        print(f"Service '{ServerManagerService._svc_display_name_}' installed successfully")
        return True
        
    except Exception as e:
        print(f"Failed to install service: {e}")
        return False

def uninstall_service():
    """Uninstall the service"""
    try:
        win32serviceutil.RemoveService(ServerManagerService._svc_name_)
        print(f"Service '{ServerManagerService._svc_display_name_}' uninstalled successfully")
        return True
        
    except Exception as e:
        print(f"Failed to uninstall service: {e}")
        return False

def start_service():
    """Start the service"""
    try:
        win32serviceutil.StartService(ServerManagerService._svc_name_)
        print(f"Service '{ServerManagerService._svc_display_name_}' started successfully")
        return True
        
    except Exception as e:
        print(f"Failed to start service: {e}")
        return False

def stop_service():
    """Stop the service"""
    try:
        win32serviceutil.StopService(ServerManagerService._svc_name_)
        print(f"Service '{ServerManagerService._svc_display_name_}' stopped successfully")
        return True
        
    except Exception as e:
        print(f"Failed to stop service: {e}")
        return False

def main():
    """Main entry point"""
    if len(sys.argv) == 1:
        # No arguments - run as service
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ServerManagerService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Handle command line arguments
        command = sys.argv[1].lower()
        
        if command == 'install':
            install_service()
        elif command == 'uninstall' or command == 'remove':
            uninstall_service()
        elif command == 'start':
            start_service()
        elif command == 'stop':
            stop_service()
        elif command == 'restart':
            stop_service()
            time.sleep(2)
            start_service()
        elif command == 'debug':
            # Run in debug mode (not as service)
            launcher = ServerManagerLauncher()
            launcher.is_service = False
            launcher.run()
        else:
            print("Usage:")
            print("  service_wrapper.py install     - Install the service")
            print("  service_wrapper.py uninstall   - Uninstall the service")
            print("  service_wrapper.py start       - Start the service")
            print("  service_wrapper.py stop        - Stop the service")
            print("  service_wrapper.py restart     - Restart the service")
            print("  service_wrapper.py debug       - Run in debug mode (not as service)")

if __name__ == '__main__':
    main()
