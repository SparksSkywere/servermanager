# Server Manager startup script with process management, cleanup, and administrative privileges
import os
import subprocess
import sys
import ctypes
import json
import time
import winreg

# Prevent Python from creating __pycache__ directories
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# Import centralized registry constants
from Modules.core.common import REGISTRY_ROOT, REGISTRY_PATH, is_admin, get_server_manager_dir

def check_process_running(pid):
    # Check if a process with given PID is still running
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
    # Clean up PID files for processes that are no longer running
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)
        return
        
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
                        print(f"Cleaned up orphaned PID file: {pid_file_name}")
            except (json.JSONDecodeError, IOError, OSError):
                # If we can't read the file or it's corrupted, remove it
                try:
                    os.remove(pid_file)
                    print(f"Cleaned up corrupted PID file: {pid_file_name}")
                except OSError:
                    pass

def prompt_user_restart():
    # Prompt user if they want to restart after improper shutdown
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
    # Check if an instance of Server Manager is already running
    try:
        # Get server manager directory from registry or use script directory
        server_manager_dir = get_server_manager_dir()
        if not server_manager_dir or not os.path.exists(server_manager_dir):
            server_manager_dir = os.path.dirname(os.path.abspath(__file__))
            
        # Check for launcher PID file
        temp_dir = os.path.join(server_manager_dir, "temp")
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
                        except OSError:
                            pass
                            
            except (json.JSONDecodeError, IOError):
                # Invalid PID file, remove it
                try:
                    os.remove(pid_file)
                except OSError:
                    pass
                
        return False
    except Exception:
        # If there's any error, assume it's not running to be safe
        return False

def check_for_improper_shutdown():
    # Check if there are orphaned PID files indicating improper shutdown
    try:
        # Get server manager directory from registry or use script directory
        server_manager_dir = get_server_manager_dir()
        if not server_manager_dir or not os.path.exists(server_manager_dir):
            server_manager_dir = os.path.dirname(os.path.abspath(__file__))
            
        temp_dir = os.path.join(server_manager_dir, "temp")
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

def ensure_directories_exist(server_manager_dir):
    # Ensure all necessary directories exist for Server Manager
    directories = [
        "logs",
        "temp", 
        "icons",
        "ssl",
        "db",
        "debug",
        "www",
        "api",
        "services",
        "Modules",
        "Host"
    ]
    
    for dir_name in directories:
        dir_path = os.path.join(server_manager_dir, dir_name)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"Created directory: {dir_path}")
        else:
            print(f"Directory already exists: {dir_path}")

# Check for administrator privileges first
if not is_admin():
    if sys.platform == "win32":
        try:
            # Try to elevate to administrator
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{__file__}"', None, 1)
        except Exception as e:
            ctypes.windll.user32.MessageBoxW(0, f"Administrator privileges required.\n\nError: {str(e)}", "Server Manager - Elevation Required", 0x10)
    sys.exit(0)

# Try to get the server manager directory from registry first
server_manager_dir = get_server_manager_dir()

if server_manager_dir and os.path.exists(server_manager_dir):
    # Use the registry path as the script directory
    script_dir = server_manager_dir
    print(f"Using registry path: {server_manager_dir}")
else:
    # Fallback to current script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Registry path not found, using script directory: {script_dir}")

# Ensure all necessary directories exist
ensure_directories_exist(script_dir)

# Temp directory is already ensured above
temp_dir = os.path.join(script_dir, "temp")

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
launcher_path = os.path.join(script_dir, "Modules", "core", "launcher.py")

# Check if the launcher script exists
if not os.path.exists(launcher_path):
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, f"Launcher script not found at:\n{launcher_path}", "Server Manager - Error", 0x10)
    else:
        print(f"Error: Launcher script not found at: {launcher_path}")
    sys.exit(1)

try:
    # Use subprocess with CREATE_NO_WINDOW flag to hide console
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE

    # Run the launcher script with proper working directory and debug flag
    process = subprocess.Popen(
        [sys.executable, launcher_path, "--debug"], 
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        cwd=script_dir,  # Set working directory to the Server Manager root
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stdin=subprocess.DEVNULL
    )
    
    # Give the process more time to start properly
    time.sleep(2.0)
    
    # Check if the process failed to start
    if process.poll() is not None:
        # Process terminated immediately, get error info
        stdout, stderr = process.communicate()
        stdout_text = stdout.decode() if stdout else "No stdout output"
        stderr_text = stderr.decode() if stderr else "No stderr output"
        
        error_msg = f"Failed to start Server Manager launcher.\n\nReturn code: {process.returncode}\n\nStdout:\n{stdout_text}\n\nStderr:\n{stderr_text}"
        
        if sys.platform == "win32":
            # Truncate message if too long for message box
            if len(error_msg) > 1000:
                error_msg = error_msg[:1000] + "...\n\n[Output truncated]"
            ctypes.windll.user32.MessageBoxW(0, error_msg, "Server Manager - Startup Error", 0x10)
        else:
            print(error_msg)
        sys.exit(1)
    else:
        print(f"Server Manager launcher started successfully (PID: {process.pid})")
    
except Exception as e:
    error_msg = f"Failed to start Server Manager launcher.\n\nError: {str(e)}"
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, error_msg, "Server Manager - Startup Error", 0x10)
    else:
        print(error_msg)
    sys.exit(1)
