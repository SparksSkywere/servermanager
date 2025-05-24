import os
import sys
import winreg
import ctypes
import subprocess
import json
import logging
import shutil
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Installer")

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

class ServerManagerInstaller:
    """Class to handle the installation of Server Manager"""
    def __init__(self):
        self.install_dir = None
        self.steam_cmd_path = None
        self.web_port = 8080
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        
    def setup_directories(self):
        """Create necessary directories for Server Manager"""
        try:
            logger.info("Creating directories...")
            
            # Create main directories
            dirs = [
                self.install_dir,
                os.path.join(self.install_dir, "logs"),
                os.path.join(self.install_dir, "config"),
                os.path.join(self.install_dir, "servers"),
                os.path.join(self.install_dir, "temp"),
                os.path.join(self.install_dir, "scripts"),
                os.path.join(self.install_dir, "modules"),
                os.path.join(self.install_dir, "static"),
                os.path.join(self.install_dir, "templates"),
                os.path.join(self.install_dir, "icons")
            ]
            
            for directory in dirs:
                os.makedirs(directory, exist_ok=True)
                logger.info(f"Created directory: {directory}")
                
            return True
        except Exception as e:
            logger.error(f"Failed to create directories: {str(e)}")
            return False
    
    def write_registry_keys(self):
        """Write registry keys for Server Manager"""
        try:
            logger.info("Writing registry keys...")
            
            # Create or open registry key
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            
            # Write values
            winreg.SetValueEx(key, "Servermanagerdir", 0, winreg.REG_SZ, self.install_dir)
            winreg.SetValueEx(key, "SteamCMDPath", 0, winreg.REG_SZ, self.steam_cmd_path)
            winreg.SetValueEx(key, "WebPort", 0, winreg.REG_DWORD, self.web_port)
            
            # Close key
            winreg.CloseKey(key)
            
            logger.info("Registry keys written successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to write registry keys: {str(e)}")
            return False
    
    def install_required_packages(self):
        """Install required Python packages"""
        try:
            logger.info("Installing required packages...")
            
            # List of required packages
            packages = [
                "flask",
                "psutil",
                "requests",
                "pystray",
                "pillow",
                "pycryptodome",
                "pywin32"
            ]
            
            # Install packages
            for package in packages:
                logger.info(f"Installing {package}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                
            logger.info("All packages installed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to install packages: {str(e)}")
            return False
    
    def copy_files(self):
        """Copy required files to installation directory"""
        try:
            logger.info("Copying files to installation directory...")
            
            # Get current script directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Copy script files
            for script_file in os.listdir(os.path.join(script_dir, "scripts")):
                if script_file.endswith(".py"):
                    source = os.path.join(script_dir, "scripts", script_file)
                    destination = os.path.join(self.install_dir, "scripts", script_file)
                    shutil.copy2(source, destination)
                    logger.info(f"Copied: {script_file}")
            
            # Copy module files
            for module_file in os.listdir(os.path.join(script_dir, "modules")):
                if module_file.endswith(".py"):
                    source = os.path.join(script_dir, "modules", module_file)
                    destination = os.path.join(self.install_dir, "modules", module_file)
                    shutil.copy2(source, destination)
                    logger.info(f"Copied: {module_file}")
            
            # Copy CMD files
            for cmd_file in ["Start-ServerManager.cmd", "Stop-ServerManager.cmd"]:
                source = os.path.join(script_dir, cmd_file)
                destination = os.path.join(self.install_dir, cmd_file)
                shutil.copy2(source, destination)
                logger.info(f"Copied: {cmd_file}")
            
            # Copy static files if they exist
            static_dir = os.path.join(script_dir, "static")
            if os.path.exists(static_dir):
                for item in os.listdir(static_dir):
                    source = os.path.join(static_dir, item)
                    destination = os.path.join(self.install_dir, "static", item)
                    if os.path.isdir(source):
                        shutil.copytree(source, destination, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, destination)
                    logger.info(f"Copied: static/{item}")
            
            # Copy template files if they exist
            templates_dir = os.path.join(script_dir, "templates")
            if os.path.exists(templates_dir):
                for item in os.listdir(templates_dir):
                    source = os.path.join(templates_dir, item)
                    destination = os.path.join(self.install_dir, "templates", item)
                    if os.path.isdir(source):
                        shutil.copytree(source, destination, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, destination)
                    logger.info(f"Copied: templates/{item}")
            
            # Copy icon files if they exist
            icons_dir = os.path.join(script_dir, "icons")
            if os.path.exists(icons_dir):
                for item in os.listdir(icons_dir):
                    source = os.path.join(icons_dir, item)
                    destination = os.path.join(self.install_dir, "icons", item)
                    if os.path.isdir(source):
                        shutil.copytree(source, destination, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, destination)
                    logger.info(f"Copied: icons/{item}")
            
            logger.info("All files copied successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to copy files: {str(e)}")
            return False
    
    def create_shortcuts(self):
        """Create desktop shortcuts"""
        try:
            logger.info("Creating shortcuts...")
            
            # Create Start shortcut
            start_path = os.path.join(self.install_dir, "Start-ServerManager.cmd")
            self.create_shortcut(start_path, "Start Server Manager", "Start Server Manager")
            
            # Create Stop shortcut
            stop_path = os.path.join(self.install_dir, "Stop-ServerManager.cmd")
            self.create_shortcut(stop_path, "Stop Server Manager", "Stop Server Manager")
            
            logger.info("Shortcuts created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create shortcuts: {str(e)}")
            return False
    
    def create_shortcut(self, target_path, shortcut_name, description):
        """Create a Windows shortcut"""
        try:
            import pythoncom
            from win32com.client import Dispatch
            
            # Get desktop path
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            
            # Create shortcut path
            shortcut_path = os.path.join(desktop, f"{shortcut_name}.lnk")
            
            # Create shortcut
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target_path
            shortcut.WorkingDirectory = os.path.dirname(target_path)
            shortcut.Description = description
            shortcut.save()
            
            logger.info(f"Created shortcut: {shortcut_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create shortcut {shortcut_name}: {str(e)}")
            return False
    
    def create_initial_config(self):
        """Create initial configuration files"""
        try:
            logger.info("Creating initial configuration...")
            
            # Create config.json
            config = {
                "version": "0.1",
                "web_port": self.web_port,
                "enable_auto_updates": True,
                "enable_tray_icon": True,
                "check_updates_interval": 3600,  # seconds
                "log_level": "INFO",
                "max_log_size": 10485760,  # 10 MB
                "max_log_files": 10
            }
            
            config_path = os.path.join(self.install_dir, "config", "config.json")
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
                
            logger.info("Initial configuration created")
            return True
        except Exception as e:
            logger.error(f"Failed to create initial configuration: {str(e)}")
            return False
    
    def install(self):
        """Main installation method"""
        logger.info("Starting Server Manager installation...")
        
        # Get installation directory
        self.install_dir = input("Enter installation directory [C:\\ServerManager]: ").strip()
        if not self.install_dir:
            self.install_dir = "C:\\ServerManager"
        
        # Get SteamCMD path
        self.steam_cmd_path = input("Enter SteamCMD directory [C:\\SteamCMD]: ").strip()
        if not self.steam_cmd_path:
            self.steam_cmd_path = "C:\\SteamCMD"
        
        # Get web port
        web_port_input = input("Enter web interface port [8080]: ").strip()
        if web_port_input:
            try:
                self.web_port = int(web_port_input)
            except ValueError:
                logger.warning("Invalid port number, using default: 8080")
        
        # Confirm installation
        print("\nInstallation Summary:")
        print(f"Installation Directory: {self.install_dir}")
        print(f"SteamCMD Directory: {self.steam_cmd_path}")
        print(f"Web Interface Port: {self.web_port}")
        confirm = input("\nProceed with installation? (y/n): ").lower()
        
        if confirm != 'y':
            logger.info("Installation cancelled by user")
            return False
        
        # Set up directories
        if not self.setup_directories():
            logger.error("Failed to set up directories")
            return False
        
        # Install required packages
        if not self.install_required_packages():
            logger.error("Failed to install required packages")
            return False
        
        # Copy files
        if not self.copy_files():
            logger.error("Failed to copy files")
            return False
        
        # Create initial configuration
        if not self.create_initial_config():
            logger.error("Failed to create initial configuration")
            return False
        
        # Write registry keys
        if not self.write_registry_keys():
            logger.error("Failed to write registry keys")
            return False
        
        # Create shortcuts
        if not self.create_shortcuts():
            logger.warning("Failed to create shortcuts, continuing anyway")
        
        logger.info("Server Manager installation completed successfully!")
        
        # Offer to start Server Manager
        start_now = input("Start Server Manager now? (y/n): ").lower()
        if start_now == 'y':
            try:
                subprocess.Popen([os.path.join(self.install_dir, "Start-ServerManager.cmd")])
                logger.info("Server Manager started")
            except Exception as e:
                logger.error(f"Failed to start Server Manager: {str(e)}")
        
        return True

def main():
    # Check for admin privileges
    if not is_admin():
        print("Administrator privileges required. Requesting elevated permissions...")
        run_as_admin()
    
    # Create and run installer
    installer = ServerManagerInstaller()
    return installer.install()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Installation cancelled by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        input("Press Enter to exit...")
    
    sys.exit(0)
