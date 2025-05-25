import os
import subprocess
import sys
import ctypes
import json
import time

def is_already_running():
    """Check if an instance of Server Manager is already running"""
    try:
        # Check for launcher PID file
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        pid_file = os.path.join(temp_dir, "launcher.pid")
        
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid_data = json.load(f)
                    pid = pid_data.get("ProcessId")
                    
                    if pid:
                        # Check if process is still running
                        if sys.platform == "win32":
                            # Windows method to check if process exists
                            PROCESS_QUERY_INFORMATION = 0x0400
                            process_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                            if process_handle:
                                ctypes.windll.kernel32.CloseHandle(process_handle)
                                return True
                        else:
                            # Unix method to check if process exists
                            try:
                                os.kill(pid, 0)  # Signal 0 just checks if process exists
                                return True
                            except OSError:
                                pass
            except (json.JSONDecodeError, IOError):
                # Invalid PID file, can be ignored
                pass
                
        return False
    except Exception:
        # If there's any error, assume it's not running to be safe
        return False

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Check if already running
if is_already_running():
    # Show a message box that the application is already running
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, "Server Manager is already running.", "Server Manager", 0x10)
    sys.exit(0)

# Make sure temp directory exists
temp_dir = os.path.join(script_dir, "temp")
os.makedirs(temp_dir, exist_ok=True)

# Launch the Python launcher script
launcher_path = os.path.join(script_dir, "scripts", "launcher.py")

# Use subprocess with CREATE_NO_WINDOW flag to hide console
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = 0  # SW_HIDE

# Run the launcher script
subprocess.Popen([sys.executable, launcher_path], startupinfo=startupinfo)
