import os
import sys
import shutil
import subprocess
import winreg
import ctypes
import traceback
import psutil
import tkinter as tk
from tkinter import messagebox
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

def remove_directory_forcefully(path):
    """Remove a directory forcefully, dealing with permission issues"""
    print(f"Attempting to remove directory: {path}")
    
    if not os.path.exists(path):
        print(f"Directory does not exist: {path}")
        return
    
    # Kill any processes that might be locking the directory
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if proc.info['exe'] and path.lower() in proc.info['exe'].lower():
                print(f"Stopping process: {proc.info['name']}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    # Take ownership and grant permissions (Windows only)
    try:
        subprocess.run(["takeown", "/f", path, "/r", "/d", "y"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["icacls", path, "/grant", "administrators:F", "/t"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print(f"Error taking ownership: {str(e)}")
    
    # Try different removal methods
    try:
        # Method 1: Direct removal
        shutil.rmtree(path, ignore_errors=True)
    except Exception as e1:
        print(f"Standard removal failed: {str(e1)}")
        try:
            # Method 2: CMD
            subprocess.run(["cmd", "/c", f"rd /s /q \"{path}\""], check=False)
        except Exception as e2:
            print(f"CMD removal failed: {str(e2)}")
            try:
                # Method 3: Robocopy (empty dir trick)
                empty_dir = os.path.join(os.environ["TEMP"], "empty")
                os.makedirs(empty_dir, exist_ok=True)
                subprocess.run([
                    "robocopy", empty_dir, path, "/PURGE", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP"
                ], check=False)
                shutil.rmtree(empty_dir, ignore_errors=True)
                os.rmdir(path)
            except Exception as e3:
                print(f"Robocopy removal failed: {str(e3)}")

def stop_service(service_name="ServerManagerService"):
    """Stop a Windows service"""
    try:
        # First check if service exists
        output = subprocess.run(["sc", "query", service_name], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE,
                               text=True)
        
        if "RUNNING" in output.stdout:
            print(f"Stopping service: {service_name}")
            subprocess.run(["sc", "stop", service_name], check=False)
            time.sleep(2)  # Wait for service to stop
            
        # Delete the service
        subprocess.run(["sc", "delete", service_name], check=False)
        print(f"Service {service_name} deleted")
    except Exception as e:
        print(f"Error managing service: {str(e)}")

def remove_firewall_rules(prefix="ServerManager_"):
    """Remove firewall rules with a specific prefix"""
    try:
        # Get all firewall rules
        output = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all"], 
                               stdout=subprocess.PIPE, 
                               text=True)
        
        # Find rules with our prefix
        import re
        rules = re.findall(rf"Rule Name:\s+({prefix}[^\n]+)", output.stdout)
        
        # Delete each rule
        for rule in rules:
            print(f"Removing firewall rule: {rule}")
            subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule}"], check=False)
    except Exception as e:
        print(f"Error removing firewall rules: {str(e)}")

def main():
    """Main uninstallation function"""
    try:
        # Check if running as admin
        if not is_admin():
            print("Requesting administrative privileges...")
            run_as_admin()
        
        # Stop the service if it exists
        stop_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "stop_servermanager.py")
        if os.path.exists(stop_script):
            print("Stopping Server Manager service...")
            subprocess.run([sys.executable, stop_script], check=False)
            time.sleep(2)
        
        # Get the installation path from registry
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\servermanager")
            steam_cmd_path = winreg.QueryValueEx(key, "SteamCMDPath")[0]
            winreg.CloseKey(key)
            
            if not steam_cmd_path:
                raise Exception("SteamCMDPath not found")
        except Exception as e:
            print(f"Installation not found or registry key missing: {str(e)}")
            return 1
        
        # Confirm uninstallation
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        
        result = messagebox.askyesno(
            "Uninstall Confirmation",
            f"Do you want to uninstall Server Manager?\nSteamCMD directory: {steam_cmd_path}"
        )
        
        if not result:
            return 0
        
        # Additional confirmation for SteamCMD
        remove_steam_cmd = messagebox.askyesno(
            "Remove SteamCMD",
            "Do you also want to remove SteamCMD and all game servers?"
        )
        
        print("Starting uninstallation...")
        
        # Stop related processes
        print("Stopping related processes...")
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if ("steam" in proc.info['name'].lower() or 
                    "servermanager" in proc.info['name'].lower()):
                    print(f"Stopping process: {proc.info['name']}")
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Remove services
        print("Removing services...")
        stop_service("ServerManagerService")
        
        # Remove firewall rules
        print("Removing firewall rules...")
        remove_firewall_rules()
        
        # Remove scheduled tasks
        print("Removing scheduled tasks...")
        subprocess.run(["schtasks", "/delete", "/tn", "ServerManager\\*", "/f"], check=False)
        
        # Remove program data
        program_data_paths = [
            r"C:\ProgramData\ServerManager",
            os.path.join(os.environ["LOCALAPPDATA"], "ServerManager"),
            os.path.join(os.environ["APPDATA"], "ServerManager")
        ]
        
        for path in program_data_paths:
            remove_directory_forcefully(path)
        
        # Remove registry keys
        print("Removing registry keys...")
        try:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\servermanager")
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries")
        except Exception as e:
            print(f"Error removing registry keys: {str(e)}")
        
        # Remove installation directory
        if remove_steam_cmd:
            print("Removing SteamCMD directory...")
            remove_directory_forcefully(steam_cmd_path)
        else:
            print("Removing Server Manager components...")
            remove_directory_forcefully(os.path.join(steam_cmd_path, "servermanager"))
        
        print("\nUninstallation completed!")
        if not remove_steam_cmd:
            print(f"SteamCMD remains at: {steam_cmd_path}")
        
        input("Press Enter to exit")
        return 0
    except Exception as e:
        print(f"Uninstallation failed: {str(e)}")
        traceback.print_exc()
        input("Press Enter to exit")
        return 1

if __name__ == "__main__":
    sys.exit(main())
