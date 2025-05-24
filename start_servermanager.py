import os
import sys
import subprocess
import winreg
import ctypes

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

def main():
    try:
        # Check if running as admin
        if not is_admin():
            print("Requesting administrative privileges...")
            run_as_admin()
        
        print("Starting Server Manager service...")
        
        # Try to start the service if it exists
        try:
            result = subprocess.run(["sc", "query", "ServerManagerService"], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE,
                                   text=True)
            
            if "RUNNING" in result.stdout:
                print("Server Manager service is already running.")
                return 0
            
            # Start the service
            subprocess.run(["sc", "start", "ServerManagerService"], check=True)
            print("Server Manager service started successfully.")
            return 0
        except subprocess.CalledProcessError:
            # If service doesn't exist, try alternative method
            pass
        
        # Service doesn't exist or couldn't be started, use alternative method
        try:
            # Get installation directory from registry
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\Servermanager")
            server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            if not server_manager_dir:
                raise Exception("Server Manager directory not found in registry")
            
            # Run the launcher script directly
            launcher_script = os.path.join(server_manager_dir, "scripts", "launcher.py")
            if os.path.exists(launcher_script):
                print(f"Starting Server Manager using launcher script: {launcher_script}")
                subprocess.Popen([sys.executable, launcher_script])
                print("Server Manager started successfully.")
                return 0
            else:
                raise Exception(f"Launcher script not found at: {launcher_script}")
        except Exception as e:
            print(f"Failed to start Server Manager: {str(e)}")
            return 1
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
