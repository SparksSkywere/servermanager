import os
import sys
import winreg
import ctypes
import subprocess
import logging
import shutil
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Uninstaller")

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

class ServerManagerUninstaller:
    """Class to handle the uninstallation of Server Manager"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.remove_data = False
        
        # Initialize from registry
        self.initialize_from_registry()
    
    def initialize_from_registry(self):
        """Get server manager directory from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            logger.info(f"Server Manager directory: {self.server_manager_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize from registry: {str(e)}")
            return False
    
    def stop_services(self):
        """Stop all Server Manager services"""
        try:
            logger.info("Stopping Server Manager services...")
            
            # Run the stop script if it exists
            stop_script = os.path.join(self.server_manager_dir, "Stop-ServerManager.cmd")
            if os.path.exists(stop_script):
                subprocess.call([stop_script])
                logger.info("Services stopped")
            else:
                logger.warning("Stop script not found, attempting manual shutdown")
                
                # Try to stop processes directly
                try:
                    # Import needed here to avoid errors if not available
                    import psutil
                    
                    # Look for processes
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        try:
                            # Check for Python processes related to Server Manager
                            if proc.info['name'] == 'python.exe' or proc.info['name'] == 'pythonw.exe':
                                cmdline = proc.info['cmdline']
                                if cmdline and any('servermanager' in str(cmd).lower() for cmd in cmdline):
                                    proc.terminate()
                                    logger.info(f"Terminated process: {proc.info['pid']}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            pass
                except ImportError:
                    logger.warning("psutil not available, cannot stop processes manually")
            
            # Wait a moment to ensure processes are stopped
            import time
            time.sleep(3)
            
            return True
        except Exception as e:
            logger.error(f"Failed to stop services: {str(e)}")
            return False
    
    def remove_registry_keys(self):
        """Remove registry keys for Server Manager"""
        try:
            logger.info("Removing registry keys...")
            
            try:
                # Delete registry key and all values
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
                logger.info("Registry keys removed")
            except WindowsError as e:
                if e.winerror == 2:  # Key not found
                    logger.warning("Registry key not found, already removed")
                else:
                    raise
            
            return True
        except Exception as e:
            logger.error(f"Failed to remove registry keys: {str(e)}")
            return False
    
    def remove_shortcuts(self):
        """Remove desktop shortcuts"""
        try:
            logger.info("Removing shortcuts...")
            
            # Get desktop path
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            
            # Shortcut names to remove
            shortcut_names = ["Start Server Manager.lnk", "Stop Server Manager.lnk"]
            
            # Remove shortcuts
            for shortcut in shortcut_names:
                shortcut_path = os.path.join(desktop, shortcut)
                if os.path.exists(shortcut_path):
                    os.remove(shortcut_path)
                    logger.info(f"Removed shortcut: {shortcut}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to remove shortcuts: {str(e)}")
            return False
    
    def remove_installation(self):
        """Remove Server Manager installation"""
        try:
            logger.info("Removing installation files...")
            
            if not self.server_manager_dir or not os.path.exists(self.server_manager_dir):
                logger.warning("Installation directory not found or already removed")
                return True
            
            # If not removing data, back up servers and configuration
            if not self.remove_data:
                logger.info("Backing up servers and configuration...")
                
                # Create backup directory
                backup_dir = os.path.join(os.path.dirname(self.server_manager_dir), "ServerManagerBackup")
                os.makedirs(backup_dir, exist_ok=True)
                
                # Backup servers directory
                servers_dir = os.path.join(self.server_manager_dir, "servers")
                if os.path.exists(servers_dir):
                    shutil.copytree(servers_dir, os.path.join(backup_dir, "servers"), dirs_exist_ok=True)
                    logger.info("Servers directory backed up")
                
                # Backup config directory
                config_dir = os.path.join(self.server_manager_dir, "config")
                if os.path.exists(config_dir):
                    shutil.copytree(config_dir, os.path.join(backup_dir, "config"), dirs_exist_ok=True)
                    logger.info("Configuration directory backed up")
                
                logger.info(f"Backups saved to: {backup_dir}")
            
            # Remove the installation directory
            shutil.rmtree(self.server_manager_dir, ignore_errors=True)
            logger.info("Installation directory removed")
            
            return True
        except Exception as e:
            logger.error(f"Failed to remove installation: {str(e)}")
            return False
    
    def uninstall(self):
        """Main uninstallation method"""
        logger.info("Starting Server Manager uninstallation...")
        
        # Confirm uninstallation
        print("This will uninstall Server Manager from your system.")
        confirm = input("Are you sure you want to continue? (y/n): ").lower()
        
        if confirm != 'y':
            logger.info("Uninstallation cancelled by user")
            return False
        
        # Confirm data removal
        remove_data = input("Do you want to remove all server data and configuration? (y/n): ").lower()
        self.remove_data = (remove_data == 'y')
        
        if not self.remove_data:
            print("Server data and configuration will be backed up before removal.")
        
        # Stop services
        if not self.stop_services():
            logger.warning("Failed to stop all services, continuing anyway")
        
        # Remove registry keys
        if not self.remove_registry_keys():
            logger.warning("Failed to remove registry keys, continuing anyway")
        
        # Remove shortcuts
        if not self.remove_shortcuts():
            logger.warning("Failed to remove shortcuts, continuing anyway")
        
        # Remove installation
        if not self.remove_installation():
            logger.error("Failed to remove installation")
            return False
        
        logger.info("Server Manager uninstallation completed successfully!")
        
        if not self.remove_data:
            backup_dir = os.path.join(os.path.dirname(self.server_manager_dir), "ServerManagerBackup")
            print(f"\nYour server data and configuration have been backed up to: {backup_dir}")
        
        return True

def main():
    # Check for admin privileges
    if not is_admin():
        print("Administrator privileges required. Requesting elevated permissions...")
        run_as_admin()
    
    # Create and run uninstaller
    uninstaller = ServerManagerUninstaller()
    result = uninstaller.uninstall()
    
    if result:
        print("\nUninstallation completed successfully.")
    else:
        print("\nUninstallation failed or was cancelled.")
    
    input("Press Enter to exit...")
    return 0 if result else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Uninstallation cancelled by user")
        print("\nUninstallation cancelled.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        print(f"\nAn error occurred: {str(e)}")
        input("Press Enter to exit...")
        sys.exit(1)
