import os
import subprocess
import sys
import ctypes
import json
import time

def check_process_running(pid):
    """Check if a process with given PID is still running"""
    if not pid:
        return False
        
    try:
        if sys.platform == "win32":
            # Windows method to check if process exists
            PROCESS_QUERY_INFORMATION = 0x0400
            process_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if process_handle:
                ctypes.windll.kernel32.CloseHandle(process_handle)
                return True
            return False
        else:
            # Unix method to check if process exists
            try:
                os.kill(pid, 0)  # Signal 0 just checks if process exists
                return True
            except OSError:
                return False
    except Exception:
        return False

def cleanup_orphaned_pid_files(temp_dir):
    """Clean up PID files for processes that are no longer running"""
    pid_files = ["launcher.pid", "trayicon.pid", "webserver.pid"]
    
    for pid_file_name in pid_files:
        pid_file = os.path.join(temp_dir, pid_file_name)
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid_data = json.load(f)
                    pid = pid_data.get("ProcessId")
                    
                    # If process is not running, remove the PID file
                    if not check_process_running(pid):
                        os.remove(pid_file)
            except (json.JSONDecodeError, IOError, OSError):
                # If we can't read the file or it's corrupted, remove it
                try:
                    os.remove(pid_file)
                except:
                    pass

def prompt_user_restart():
    """Prompt user if they want to restart after improper shutdown"""
    if sys.platform == "win32":
        # MB_YESNO = 0x4, MB_ICONQUESTION = 0x20, MB_DEFBUTTON1 = 0x0
        result = ctypes.windll.user32.MessageBoxW(
            0, 
            "Server Manager did not close properly. Would you like to restart it?\n\nClick 'Yes' to restart or 'No' to cancel.",
            "Server Manager - Restart Required", 
            0x4 | 0x20 | 0x0
        )
        return result == 6  # IDYES = 6
    else:
        # For non-Windows systems, default to yes
        print("Server Manager did not close properly. Restarting...")
        return True

def is_already_running():
    """Check if an instance of Server Manager is already running"""
    try:
        # Check for launcher PID file
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        pid_file = os.path.join(temp_dir, "launcher.pid")
        
        # First, clean up any orphaned PID files
        cleanup_orphaned_pid_files(temp_dir)
        
        # Check if the main launcher PID file exists after cleanup
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid_data = json.load(f)
                    pid = pid_data.get("ProcessId")
                    
                    if pid and check_process_running(pid):
                        return True
                    else:
                        # Process not running, remove stale PID file
                        try:
                            os.remove(pid_file)
                        except:
                            pass
                            
            except (json.JSONDecodeError, IOError):
                # Invalid PID file, remove it
                try:
                    os.remove(pid_file)
                except:
                    pass
                
        return False
    except Exception:
        # If there's any error, assume it's not running to be safe
        return False

def check_for_improper_shutdown():
    """Check if there are orphaned PID files indicating improper shutdown"""
    try:
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        pid_files = ["launcher.pid", "trayicon.pid", "webserver.pid"]
        
        orphaned_files = []
        for pid_file_name in pid_files:
            pid_file = os.path.join(temp_dir, pid_file_name)
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid_data = json.load(f)
                        pid = pid_data.get("ProcessId")
                        
                        # If PID file exists but process is not running
                        if not check_process_running(pid):
                            orphaned_files.append(pid_file_name)
                            
                except (json.JSONDecodeError, IOError):
                    # Corrupted PID file also indicates improper shutdown
                    orphaned_files.append(pid_file_name)
        
        return len(orphaned_files) > 0
        
    except Exception:
        return False

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Make sure temp directory exists
temp_dir = os.path.join(script_dir, "temp")
os.makedirs(temp_dir, exist_ok=True)

# Check for improper shutdown first
if check_for_improper_shutdown():
    if not prompt_user_restart():
        # User chose not to restart
        sys.exit(0)
    else:
        # User chose to restart, clean up orphaned files
        cleanup_orphaned_pid_files(temp_dir)

# Check if already running (after potential cleanup)
if is_already_running():
    # Show a message box that the application is already running
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, "Server Manager is already running.", "Server Manager", 0x10)
    sys.exit(0)

# Launch the Python launcher script
launcher_path = os.path.join(script_dir, "scripts", "launcher.py")

# Use subprocess with CREATE_NO_WINDOW flag to hide console
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = 0  # SW_HIDE

# Run the launcher script
subprocess.Popen([sys.executable, launcher_path], startupinfo=startupinfo)
