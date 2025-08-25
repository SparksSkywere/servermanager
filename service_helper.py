#!/usr/bin/env python3
import os
import sys
import subprocess
import argparse
import winreg

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

def get_server_manager_dir():
    """Get Server Manager directory from registry"""
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "ServerManagerPath")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        print(f"Error reading registry: {e}")
        return None

def check_admin():
    """Check if script is running with admin privileges"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    """Re-run script with admin privileges"""
    try:
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        return True
    except:
        return False

def install_service():
    """Install the Server Manager service"""
    if not check_admin():
        print("Admin privileges required for service installation.")
        if input("Restart with admin privileges? (y/n): ").lower() == 'y':
            return run_as_admin()
        return False
    
    server_manager_dir = get_server_manager_dir()
    if not server_manager_dir:
        print("Server Manager installation not found in registry.")
        return False
    
    service_wrapper_path = os.path.join(server_manager_dir, "Modules", "service_wrapper.py")
    if not os.path.exists(service_wrapper_path):
        print(f"Service wrapper not found: {service_wrapper_path}")
        return False
    
    try:
        print("Installing Server Manager Windows Service...")
        
        # Install pywin32 if needed
        print("Ensuring pywin32 is installed...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pywin32"], 
                      check=True, capture_output=True)
        
        # Install the service
        result = subprocess.run([sys.executable, service_wrapper_path, "install"], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Service installed successfully!")
            
            # Start the service
            print("Starting service...")
            start_result = subprocess.run([sys.executable, service_wrapper_path, "start"], 
                                        capture_output=True, text=True)
            
            if start_result.returncode == 0:
                print("Service started successfully!")
                print("Server Manager will now start automatically with Windows.")
                return True
            else:
                print(f"Service installed but failed to start: {start_result.stderr}")
                return False
        else:
            print(f"Service installation failed: {result.stderr}")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"Error during service installation: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

def uninstall_service():
    """Uninstall the Server Manager service"""
    if not check_admin():
        print("Admin privileges required for service uninstallation.")
        if input("Restart with admin privileges? (y/n): ").lower() == 'y':
            return run_as_admin()
        return False
    
    server_manager_dir = get_server_manager_dir()
    if not server_manager_dir:
        print("Server Manager installation not found in registry.")
        return False
    
    service_wrapper_path = os.path.join(server_manager_dir, "Modules", "service_wrapper.py")
    if not os.path.exists(service_wrapper_path):
        print(f"Service wrapper not found: {service_wrapper_path}")
        return False
    
    try:
        print("Uninstalling Server Manager Windows Service...")
        
        # Stop the service first
        print("Stopping service...")
        subprocess.run([sys.executable, service_wrapper_path, "stop"], 
                      capture_output=True, text=True)
        
        # Uninstall the service
        result = subprocess.run([sys.executable, service_wrapper_path, "uninstall"], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Service uninstalled successfully!")
            return True
        else:
            print(f"Service uninstallation failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error during service uninstallation: {e}")
        return False

def service_status():
    """Check service status"""
    try:
        result = subprocess.run(['sc', 'query', 'ServerManagerService'], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            if "RUNNING" in result.stdout:
                print("Server Manager Service: RUNNING")
            elif "STOPPED" in result.stdout:
                print("Server Manager Service: STOPPED")
            else:
                print("Server Manager Service: UNKNOWN STATE")
                print(result.stdout)
        else:
            print("Server Manager Service: NOT INSTALLED")
    except Exception as e:
        print(f"Error checking service status: {e}")

def start_stop_service(action):
    """Start or stop the service"""
    if not check_admin():
        print(f"Admin privileges required to {action} service.")
        if input("Restart with admin privileges? (y/n): ").lower() == 'y':
            return run_as_admin()
        return False
    
    server_manager_dir = get_server_manager_dir()
    if not server_manager_dir:
        print("Server Manager installation not found in registry.")
        return False
    
    service_wrapper_path = os.path.join(server_manager_dir, "Modules", "service_wrapper.py")
    if not os.path.exists(service_wrapper_path):
        print(f"Service wrapper not found: {service_wrapper_path}")
        return False
    
    try:
        print(f"{action.capitalize()}ing Server Manager service...")
        result = subprocess.run([sys.executable, service_wrapper_path, action], 
                               capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"Service {action}ed successfully!")
            return True
        else:
            print(f"Failed to {action} service: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error {action}ing service: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Server Manager Service Helper')
    parser.add_argument('action', choices=['install', 'uninstall', 'start', 'stop', 'restart', 'status'],
                       help='Action to perform')
    
    args = parser.parse_args()
    
    print("Server Manager Service Helper")
    print("=" * 40)
    
    if args.action == 'install':
        success = install_service()
    elif args.action == 'uninstall':
        success = uninstall_service()
    elif args.action == 'start':
        success = start_stop_service('start')
    elif args.action == 'stop':
        success = start_stop_service('stop')
    elif args.action == 'restart':
        success = start_stop_service('stop')
        if success:
            import time
            time.sleep(2)
            success = start_stop_service('start')
    elif args.action == 'status':
        service_status()
        success = True
    
    if args.action != 'status':
        input("\nPress Enter to exit...")
    
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())
