import os
import sys
import subprocess
import winreg
import ctypes
import psutil
import time

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
        
        print("Stopping Server Manager service...")
        
        # Try to stop the service if it exists
        try:
            result = subprocess.run(["sc", "query", "ServerManagerService"], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE,
                                   text=True)
            
            if "RUNNING" in result.stdout:
                # Stop the service
                subprocess.run(["sc", "stop", "ServerManagerService"], check=True)
                print("Server Manager service stopped successfully.")
                return 0
            else:
                print("Server Manager service is not running.")
        except subprocess.CalledProcessError:
            # If service doesn't exist, try alternative method
            pass
        
        # Service doesn't exist or couldn't be stopped, use alternative method
        try:
            # Get installation directory from registry
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\Servermanager")
            server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            if not server_manager_dir:
                raise Exception("Server Manager directory not found in registry")
            
            # Kill any processes related to Server Manager
            killed = False
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline'] if proc.info['cmdline'] else []
                    cmdline_str = ' '.join(cmdline).lower()
                    
                    if ("servermanager" in cmdline_str or 
                        (server_manager_dir.lower() in cmdline_str and "python" in proc.info['name'].lower())):
                        print(f"Stopping process: {proc.info['name']} (PID: {proc.info['pid']})")
                        proc.kill()
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            if killed:
                print("Server Manager processes stopped successfully.")
                return 0
            else:
                print("No running Server Manager processes found.")
                return 0
        except Exception as e:
            print(f"Failed to stop Server Manager: {str(e)}")
            return 1
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
