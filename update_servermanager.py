import os
import sys
import winreg
import ctypes
import subprocess
import logging
import json
import shutil
import requests
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Updater")

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

class ServerManagerUpdater:
    """Class to handle the updating of Server Manager"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.update_source = "https://example.com/servermanager/latest"  # Replace with actual update URL
        self.current_version = "0.1"
        self.latest_version = None
        self.update_available = False
        self.backup_dir = None
        
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
            
            # Check for current version
            config_file = os.path.join(self.server_manager_dir, "config", "config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    if "version" in config:
                        self.current_version = config["version"]
            
            logger.info(f"Current version: {self.current_version}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize from registry: {str(e)}")
            return False
    
    def check_for_updates(self):
        """Check if updates are available"""
        try:
            logger.info("Checking for updates...")
            
            # This is a placeholder. In a real implementation, you would
            # make an HTTP request to your update server to check for the latest version
            try:
                # Example HTTP request to get version information
                response = requests.get(f"{self.update_source}/version.json", timeout=10)
                if response.status_code == 200:
                    version_info = response.json()
                    self.latest_version = version_info.get("version")
                    
                    # Compare versions
                    if self.latest_version and self.latest_version != self.current_version:
                        self.update_available = True
                        logger.info(f"Update available: {self.latest_version}")
                        return True
                    else:
                        logger.info("No updates available")
                        return False
                else:
                    logger.error(f"Failed to check for updates: HTTP {response.status_code}")
                    return False
            except requests.RequestException as e:
                logger.error(f"Failed to check for updates: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking for updates: {str(e)}")
            return False
    
    def backup_current_installation(self):
        """Create a backup of the current installation"""
        try:
            logger.info("Creating backup of current installation...")
            
            # Create backup directory with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_dir = os.path.join(self.server_manager_dir, "backups", f"backup_{timestamp}")
            os.makedirs(self.backup_dir, exist_ok=True)
            
            # Directories to backup
            dirs_to_backup = ["scripts", "modules", "static", "templates", "icons"]
            
            # Backup each directory
            for directory in dirs_to_backup:
                source_dir = os.path.join(self.server_manager_dir, directory)
                if os.path.exists(source_dir):
                    dest_dir = os.path.join(self.backup_dir, directory)
                    shutil.copytree(source_dir, dest_dir)
                    logger.info(f"Backed up {directory}")
            
            # Backup configuration
            config_dir = os.path.join(self.server_manager_dir, "config")
            if os.path.exists(config_dir):
                dest_config = os.path.join(self.backup_dir, "config")
                shutil.copytree(config_dir, dest_config)
                logger.info("Backed up configuration")
            
            # Backup CMD files
            for cmd_file in ["Start-ServerManager.cmd", "Stop-ServerManager.cmd"]:
                source_file = os.path.join(self.server_manager_dir, cmd_file)
                if os.path.exists(source_file):
                    shutil.copy2(source_file, os.path.join(self.backup_dir, cmd_file))
                    logger.info(f"Backed up {cmd_file}")
            
            logger.info(f"Backup created at {self.backup_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to create backup: {str(e)}")
            return False
    
    def download_update(self):
        """Download the update package"""
        try:
            logger.info("Downloading update package...")
            
            # Create temporary directory for download
            temp_dir = tempfile.mkdtemp()
            update_zip = os.path.join(temp_dir, "update.zip")
            
            # Download update package
            try:
                response = requests.get(f"{self.update_source}/update_{self.latest_version}.zip", 
                                        stream=True, timeout=300)
                
                if response.status_code == 200:
                    # Save the download
                    with open(update_zip, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    logger.info("Update package downloaded successfully")
                    
                    # Extract the update
                    with zipfile.ZipFile(update_zip, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    logger.info("Update package extracted")
                    
                    # Return the path to the extracted update
                    return os.path.join(temp_dir, "update")
                else:
                    logger.error(f"Failed to download update: HTTP {response.status_code}")
                    return None
            except requests.RequestException as e:
                logger.error(f"Failed to download update: {str(e)}")
                return None
                
        except Exception as e:
            logger.error(f"Error downloading update: {str(e)}")
            return None
    
    def apply_update(self, update_dir):
        """Apply the downloaded update to the installation"""
        try:
            logger.info("Applying update...")
            
            if not update_dir or not os.path.exists(update_dir):
                logger.error("Update directory not found")
                return False
            
            # Directories to update
            dirs_to_update = ["scripts", "modules", "static", "templates", "icons"]
            
            # Update each directory
            for directory in dirs_to_update:
                source_dir = os.path.join(update_dir, directory)
                if os.path.exists(source_dir):
                    dest_dir = os.path.join(self.server_manager_dir, directory)
                    
                    # Remove existing directory if it exists
                    if os.path.exists(dest_dir):
                        shutil.rmtree(dest_dir)
                    
                    # Copy new directory
                    shutil.copytree(source_dir, dest_dir)
                    logger.info(f"Updated {directory}")
            
            # Update CMD files
            for cmd_file in ["Start-ServerManager.cmd", "Stop-ServerManager.cmd"]:
                source_file = os.path.join(update_dir, cmd_file)
                if os.path.exists(source_file):
                    dest_file = os.path.join(self.server_manager_dir, cmd_file)
                    if os.path.exists(dest_file):
                        os.remove(dest_file)
                    shutil.copy2(source_file, dest_file)
                    logger.info(f"Updated {cmd_file}")
            
            # Update version in config
            config_file = os.path.join(self.server_manager_dir, "config", "config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                config["version"] = self.latest_version
                
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
                
                logger.info(f"Updated version in config to {self.latest_version}")
            
            logger.info("Update applied successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to apply update: {str(e)}")
            return False
    
    def restore_backup(self):
        """Restore from backup in case of update failure"""
        try:
            logger.info("Restoring from backup...")
            
            if not self.backup_dir or not os.path.exists(self.backup_dir):
                logger.error("Backup directory not found")
                return False
            
            # Directories to restore
            dirs_to_restore = ["scripts", "modules", "static", "templates", "icons"]
            
            # Restore each directory
            for directory in dirs_to_restore:
                source_dir = os.path.join(self.backup_dir, directory)
                if os.path.exists(source_dir):
                    dest_dir = os.path.join(self.server_manager_dir, directory)
                    
                    # Remove existing directory if it exists
                    if os.path.exists(dest_dir):
                        shutil.rmtree(dest_dir)
                    
                    # Copy from backup
                    shutil.copytree(source_dir, dest_dir)
                    logger.info(f"Restored {directory}")
            
            # Restore config
            backup_config = os.path.join(self.backup_dir, "config")
            if os.path.exists(backup_config):
                dest_config = os.path.join(self.server_manager_dir, "config")
                
                # Remove existing config if it exists
                if os.path.exists(dest_config):
                    shutil.rmtree(dest_config)
                
                # Copy from backup
                shutil.copytree(backup_config, dest_config)
                logger.info("Restored configuration")
            
            # Restore CMD files
            for cmd_file in ["Start-ServerManager.cmd", "Stop-ServerManager.cmd"]:
                source_file = os.path.join(self.backup_dir, cmd_file)
                if os.path.exists(source_file):
                    dest_file = os.path.join(self.server_manager_dir, cmd_file)
                    if os.path.exists(dest_file):
                        os.remove(dest_file)
                    shutil.copy2(source_file, dest_file)
                    logger.info(f"Restored {cmd_file}")
            
            logger.info("Restoration complete")
            return True
        except Exception as e:
            logger.error(f"Failed to restore from backup: {str(e)}")
            return False
    
    def restart_server_manager(self):
        """Restart Server Manager after update"""
        try:
            logger.info("Restarting Server Manager...")
            
            # Stop Server Manager
            stop_cmd = os.path.join(self.server_manager_dir, "Stop-ServerManager.cmd")
            if os.path.exists(stop_cmd):
                subprocess.call([stop_cmd])
                logger.info("Server Manager stopped")
            
            # Wait a moment
            import time
            time.sleep(5)
            
            # Start Server Manager
            start_cmd = os.path.join(self.server_manager_dir, "Start-ServerManager.cmd")
            if os.path.exists(start_cmd):
                subprocess.Popen([start_cmd])
                logger.info("Server Manager started")
                return True
            else:
                logger.error("Start script not found")
                return False
                
        except Exception as e:
            logger.error(f"Failed to restart Server Manager: {str(e)}")
            return False
    
    def update(self):
        """Main update method"""
        logger.info("Starting Server Manager update process...")
        
        # Check if update available
        if not self.check_for_updates():
            logger.info("No updates available. Current version is up to date.")
            return True
        
        # Create backup
        if not self.backup_current_installation():
            logger.error("Failed to create backup, aborting update")
            return False
        
        # Download update
        update_dir = self.download_update()
        if not update_dir:
            logger.error("Failed to download update, aborting")
            return False
        
        # Apply update
        if not self.apply_update(update_dir):
            logger.error("Failed to apply update, attempting to restore from backup")
            self.restore_backup()
            return False
        
        # Restart Server Manager
        if not self.restart_server_manager():
            logger.warning("Failed to restart Server Manager, please restart manually")
        
        logger.info(f"Server Manager successfully updated to version {self.latest_version}")
        return True

def main():
    # Check for admin privileges
    if not is_admin():
        print("Administrator privileges required. Requesting elevated permissions...")
        run_as_admin()
    
    # Create and run updater
    updater = ServerManagerUpdater()
    result = updater.update()
    
    if result:
        logger.info("Update process completed successfully")
    else:
        logger.error("Update process failed")
    
    return 0 if result else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Update cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        sys.exit(1)
