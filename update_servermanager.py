import os
import sys
import subprocess
import winreg
import ctypes
import traceback
from datetime import datetime

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

def update_git_repo(repo_url, destination):
    """Update (pull) or clone Git repository"""
    print(f"Updating Git repository at {destination}")
    try:
        # Check if git command is available
        subprocess.run(["git", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Check if destination is a git repository
        if os.path.exists(os.path.join(destination, ".git")):
            print("Existing Git repository found.")
            
            # Save current directory to return to it later
            original_dir = os.getcwd()
            
            try:
                # Change to the repository directory
                os.chdir(destination)
                
                # Fetch updates
                print("Fetching updates...")
                subprocess.run(["git", "fetch", "origin"], check=True)
                
                # Get current branch name
                result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                                       check=True, stdout=subprocess.PIPE, text=True)
                current_branch = result.stdout.strip()
                
                # Reset to origin
                print("Resetting to latest version...")
                subprocess.run(["git", "reset", "--hard", f"origin/{current_branch}"], check=True)
                
                print("Git repository updated successfully.")
            finally:
                # Return to original directory
                os.chdir(original_dir)
        else:
            print("No Git repository found. Please run the installer first.")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to update Git repository: {str(e)}")
        raise

def main():
    """Main update function"""
    try:
        # Check if running as admin
        if not is_admin():
            print("Requesting administrative privileges...")
            run_as_admin()
        
        # Get installation directory from registry
        registry_path = r"Software\SkywereIndustries\Servermanager"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
            server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            if not server_manager_dir:
                raise Exception("Server Manager directory not found in registry")
        except Exception as e:
            print(f"Error accessing registry: {str(e)}")
            raise Exception("Server Manager is not installed. Please run the installer first.")
        
        git_repo_url = "https://github.com/SparksSkywere/servermanager.git"
        
        # Update repository
        update_git_repo(git_repo_url, server_manager_dir)
        
        # Update last update time in registry
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "LastUpdate", 0, winreg.REG_SZ, datetime.now().isoformat())
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Warning: Could not update registry: {str(e)}")
        
        # Inform user that they may need to restart Server Manager
        print("Update completed successfully. You may need to restart Server Manager.")
        print("Use stop_servermanager.py and start_servermanager.py to restart the service.")
        
        return 0
    except Exception as e:
        print(f"Update failed: {str(e)}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
