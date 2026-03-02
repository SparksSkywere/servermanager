# -*- coding: utf-8 -*-
# pyright: reportArgumentType=false
# Stdin relay background process
import os
import sys
import time
import threading
import json
import subprocess
from pathlib import Path
from typing import Any

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_component_logger
logger = get_component_logger("StdinRelay")

# Windows named pipe support - declare module-level placeholders for type checking
win32pipe: Any = None
win32file: Any = None
pywintypes: Any = None
win32security: Any = None
win32api: Any = None

_NAMED_PIPES_AVAILABLE = False
if sys.platform == 'win32':
    try:
        import win32pipe as _win32pipe
        import win32file as _win32file
        import pywintypes as _pywintypes
        import win32security as _win32security
        import win32api as _win32api
        win32pipe = _win32pipe
        win32file = _win32file
        pywintypes = _pywintypes
        win32security = _win32security
        win32api = _win32api
        _NAMED_PIPES_AVAILABLE = True
    except ImportError:
        logger.warning("pywin32 not available - stdin relay cannot function")

def sanitise_pipe_name(server_name: str) -> str:
    # Valid Windows pipe name from server name
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
    return f"\\\\.\\pipe\\ServerManager_stdin_{safe_name}"

def get_relay_pid_file(server_name: str) -> Path:
    # Relay PID file path
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
    temp_dir = Path(__file__).parent.parent / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"relay_{safe_name}.pid"

def cleanup_existing_relays(server_name: str):
    # Clean up any existing relay processes and pipes for a server
    try:
        import psutil
        
        pipe_name = sanitise_pipe_name(server_name)
        logger.info(f"Starting cleanup for {server_name}, pipe: {pipe_name}")
        
        # Try to find and kill any existing relay processes for this server
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.pid == os.getpid():  # Skip self
                    continue
                    
                cmdline = " ".join(proc.info['cmdline'] or [])
                if "stdin_relay.py" in cmdline and server_name in cmdline:
                    logger.info(f"Found existing relay process {proc.pid} for {server_name}, terminating")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                        logger.debug(f"Terminated relay process {proc.pid}")
                    except psutil.TimeoutExpired:
                        proc.kill()
                        logger.warning(f"Force killed relay process {proc.pid}")
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        # Try to connect to and close any existing pipe
        try:
            # Try to connect to the pipe and send a close command
            result, data = win32pipe.CallNamedPipe(pipe_name, b"close", 1024, 0)
            logger.debug(f"Sent close command to existing pipe for {server_name}")
        except Exception as e:
            logger.debug(f"No existing pipe to close for {server_name}: {e}")
            
        # Try to create a pipe with the same name to clear any stale state
        try:
            # Create pipe, immediately close it to clear any stale state
            pipe_handle = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,  # Allow unlimited instances
                1024,  # Out buffer size
                1024,  # In buffer size
                0,  # Default timeout
                None  # Security attributes
            )
            if pipe_handle and pipe_handle != win32file.INVALID_HANDLE_VALUE:
                win32file.CloseHandle(pipe_handle)
                logger.debug(f"Created and closed dummy pipe to clear stale state for {server_name}")
        except Exception as e:
            logger.debug(f"Could not create dummy pipe for cleanup: {e}")
            
        # Wait a bit for cleanup to take effect
        time.sleep(0.5)
            
        logger.info(f"Completed cleanup for {server_name}")
        
    except Exception as e:
        logger.error(f"Error cleaning up existing relays for {server_name}: {e}")

def is_relay_running(server_name: str) -> bool:
    # Check relay availability via pipe test
    info_file = get_relay_pid_file(server_name).with_suffix('.json')
    if not info_file.exists():
        return False
    
    try:
        info = json.loads(info_file.read_text())
        server_pid = info.get('server_pid')
        dashboard_pid = info.get('dashboard_pid')
        
        # Check if server still running
        import psutil
        if not server_pid or not psutil.pid_exists(server_pid):
            # Server gone, clean up
            try:
                info_file.unlink()
            except OSError:
                pass
            return False
        
        # Check if the dashboard that owns the relay is still running
        if dashboard_pid and psutil.pid_exists(dashboard_pid):
            # The original dashboard is still running, relay should be active
            return True
        
        # Dashboard is gone but server is running - relay is dead
        return False
        
    except Exception as e:
        logger.debug(f"Error checking relay status: {e}")
        return False

def start_relay_for_server(server_name: str, server_process: subprocess.Popen, server_pid: int) -> bool:
    # Start a persistent stdin relay process for a server
    if not _NAMED_PIPES_AVAILABLE:
        logger.error("Named pipes not available - cannot start stdin relay")
        return False
    
    if is_relay_running(server_name):
        logger.info(f"Relay already running for {server_name}")
        return True
    
    # Clean up any existing relay processes for this server
    cleanup_existing_relays(server_name)
    
    # Give cleanup time to work
    time.sleep(1)
    
    # Clean up any stale relay files before starting
    relay_info_file = get_relay_pid_file(server_name).with_suffix('.json')
    if relay_info_file.exists():
        try:
            relay_info_file.unlink()
            logger.debug(f"Removed stale relay info file for {server_name}")
        except OSError:
            pass
    
    # Start a separate relay process that will survive dashboard restarts
    # We use pythonw.exe to run without a console window
    try:
        script_path = Path(__file__).resolve()
        python_exe = sys.executable
        
        # Use pythonw for background execution if available
        if python_exe.endswith('python.exe'):
            pythonw = python_exe.replace('python.exe', 'pythonw.exe')
            if Path(pythonw).exists():
                python_exe = pythonw
        
        # Pass stdin handle info via environment or temp file
        # Since we can't pass the stdin handle directly, we'll use a hybrid approach:
        # The relay process will create a named pipe, and we'll copy stdin data to it
        
        # For now, start the in-process relay thread AND spawn a persistent watcher
        # The thread handles stdin, the watcher provides reconnection capability
        
        relay_thread = threading.Thread(
            target=_run_relay_thread,
            args=(server_name, server_process, server_pid),
            daemon=False,  # Non-daemon so it survives longer
            name=f"StdinRelay-{server_name}"
        )
        relay_thread.start()
        
        # Write relay info so reattached dashboards know about it
        relay_info_file = get_relay_pid_file(server_name).with_suffix('.json')
        relay_info = {
            'server_name': server_name,
            'server_pid': server_pid,
            'pipe_name': sanitise_pipe_name(server_name),
            'started_at': time.time(),
            'dashboard_pid': os.getpid()
        }
        relay_info_file.write_text(json.dumps(relay_info, indent=2))
        
        logger.info(f"Started stdin relay for {server_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start relay process: {e}", exc_info=True)
        return False

def _run_relay_thread(server_name: str, server_process: subprocess.Popen, server_pid: int):
    # Stdin relay thread
    # - Listens on named pipe, forwards to server stdin
    import psutil
    
    pipe_name = sanitise_pipe_name(server_name)
    logger.info(f"Starting stdin relay for {server_name} on pipe {pipe_name}")
    
    # Create security attributes for the pipe (allow all access)
    try:
        # Create a security descriptor that allows everyone to connect
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorDacl(1, None, 0)  # Null DACL = everyone has access
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        sa.bInheritHandle = False
    except Exception as e:
        logger.warning(f"Could not create security attributes: {e}")
        sa = None
    
    while True:
        try:
            # Check if server is still running
            if not psutil.pid_exists(server_pid):
                logger.info(f"Server {server_name} (PID {server_pid}) has exited, stopping relay")
                break
            
            # Check if stdin is still available
            if not hasattr(server_process, 'stdin') or server_process.stdin is None or server_process.stdin.closed:
                logger.warning(f"Server {server_name} stdin no longer available, stopping relay")
                break
            
            # Create/recreate the named pipe
            logger.debug(f"Creating named pipe {pipe_name}")
            try:
                pipe = win32pipe.CreateNamedPipe(
                    pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,  # Allow unlimited instances
                    65536,  # Out buffer size
                    65536,  # In buffer size
                    0,  # Default timeout
                    sa  # Security attributes
                )
            except pywintypes.error as e:
                if e.args[0] == 231:  # ERROR_PIPE_BUSY - All pipe instances are busy
                    logger.warning(f"Pipe {pipe_name} is busy, waiting for it to become available")
                    # Wait for the pipe to become available
                    if win32pipe.WaitNamedPipe(pipe_name, 5000):  # Wait up to 5 seconds
                        logger.info(f"Pipe {pipe_name} became available, retrying creation")
                        continue  # Retry the loop
                    else:
                        logger.error(f"Pipe {pipe_name} remained busy after waiting")
                        time.sleep(1)
                        continue
                else:
                    logger.error(f"Failed to create named pipe for {server_name}, error: {e}")
                    time.sleep(1)
                    continue
            
            if pipe == win32file.INVALID_HANDLE_VALUE:
                error_code = win32api.GetLastError()
                logger.error(f"Failed to create named pipe for {server_name}, error code: {error_code}")
                time.sleep(1)
                continue
            
            logger.debug(f"Waiting for client connection on {pipe_name}")
            
            # Wait for client connection (this blocks)
            try:
                win32pipe.ConnectNamedPipe(pipe, None)
                logger.info(f"Client connected to stdin relay for {server_name}")
            except pywintypes.error as e:
                if e.args[0] == 535:  # ERROR_PIPE_CONNECTED - client already connected
                    pass
                else:
                    logger.error(f"Error connecting pipe: {e}")
                    win32file.CloseHandle(pipe)
                    time.sleep(0.5)
                    continue
            
            # Read and process commands until client disconnects or server exits
            while True:
                # Check if server is still running
                if not psutil.pid_exists(server_pid):
                    logger.info(f"Server exited, closing relay pipe")
                    break
                
                try:
                    # Read command from pipe
                    result, data = win32file.ReadFile(pipe, 65536)
                    if result != 0:
                        logger.debug(f"ReadFile returned {result}")
                        break
                    
                    # Handle both bytes and str (pywin32 may return either)
                    if isinstance(data, bytes):
                        command = data.decode('utf-8').strip()
                    else:
                        command = str(data).strip()
                    if command:
                        logger.debug(f"Received command for {server_name}: {command}")
                        
                        # Forward to server stdin
                        try:
                            command_with_newline = f"{command}\n"
                            try:
                                server_process.stdin.write(command_with_newline)
                            except TypeError:
                                server_process.stdin.write(command_with_newline.encode('utf-8'))
                            server_process.stdin.flush()
                            
                            # Send acknowledgment back to client
                            response = json.dumps({"status": "ok", "command": command}).encode('utf-8')
                            win32file.WriteFile(pipe, response)
                            
                            logger.info(f"Command sent to {server_name}: {command}")
                        except (OSError, ValueError, BrokenPipeError) as e:
                            logger.error(f"Error sending command to server: {e}")
                            response = json.dumps({"status": "error", "message": str(e)}).encode('utf-8')
                            win32file.WriteFile(pipe, response)
                            break
                            
                except pywintypes.error as e:
                    if e.args[0] == 109:  # ERROR_BROKEN_PIPE - client disconnected
                        logger.debug(f"Client disconnected from {server_name} relay")
                        break
                    elif e.args[0] == 232:  # ERROR_NO_DATA - pipe closing
                        logger.debug(f"Pipe closing for {server_name}")
                        break
                    else:
                        logger.error(f"Pipe error: {e}")
                        break
            
            # Disconnect and close pipe
            try:
                win32pipe.DisconnectNamedPipe(pipe)
            except (pywintypes.error, OSError):
                pass
            win32file.CloseHandle(pipe)
            
        except Exception as e:
            logger.error(f"Error in stdin relay for {server_name}: {e}", exc_info=True)
            time.sleep(1)
    
    logger.info(f"Stdin relay for {server_name} shutting down")

def send_command_via_relay(server_name: str, command: str, timeout: float = 5.0) -> tuple[bool, str]:
    # Send a command to a server via its stdin relay pipe
    # Args: server_name - The name of the server, command - The command to send, timeout - Timeout in seconds
    # Returns: Tuple of (success, message)
    if not _NAMED_PIPES_AVAILABLE:
        return False, "Named pipes not available"
    
    pipe_name = sanitise_pipe_name(server_name)
    
    try:
        # Connect to existing relay pipe
        logger.debug(f"Connecting to relay pipe {pipe_name}")
        
        # Wait for pipe to be available
        start_time = time.time()
        pipe = None
        
        while time.time() - start_time < timeout:
            try:
                pipe = win32file.CreateFile(
                    pipe_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,  # No sharing
                    None,  # Default security
                    win32file.OPEN_EXISTING,
                    0,  # Default attributes
                    None  # No template
                )
                break
            except pywintypes.error as e:
                if e.args[0] == 2:  # ERROR_FILE_NOT_FOUND - pipe doesn't exist
                    return False, f"No stdin relay running for {server_name}"
                elif e.args[0] == 231:  # ERROR_PIPE_BUSY - another client connected
                    time.sleep(0.1)
                    continue
                else:
                    return False, f"Failed to connect to relay pipe: {e}"
        
        if pipe is None:
            return False, f"Timeout connecting to relay pipe for {server_name}"
        
        try:
            # Set pipe to message mode
            win32pipe.SetNamedPipeHandleState(pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            
            # Send command
            command_data = command.encode('utf-8')
            win32file.WriteFile(pipe, command_data)
            
            # Read response
            result, response_data = win32file.ReadFile(pipe, 65536)
            # Handle both bytes and str (pywin32 may return either)
            if isinstance(response_data, bytes):
                response = json.loads(response_data.decode('utf-8'))
            else:
                response = json.loads(str(response_data))
            
            if response.get("status") == "ok":
                return True, f"Command sent: {response.get('command', command)}"
            else:
                return False, response.get("message", "Unknown error")
                
        finally:
            win32file.CloseHandle(pipe)
            
    except Exception as e:
        logger.error(f"Error sending command via relay: {e}", exc_info=True)
        return False, str(e)

# Standalone execution for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Stdin Relay Service")
    parser.add_argument("action", choices=["test", "send"], help="Action to perform")
    parser.add_argument("--server", required=True, help="Server name")
    parser.add_argument("--command", help="Command to send (for 'send' action)")
    
    args = parser.parse_args()
    
    if args.action == "test":
        if is_relay_running(args.server):
            print(f"Relay is running for {args.server}")
        else:
            print(f"No relay running for {args.server}")
    
    elif args.action == "send":
        if not args.command:
            print("--command is required for 'send' action")
            sys.exit(1)
        
        success, message = send_command_via_relay(args.server, args.command)
        print(f"{'Success' if success else 'Failed'}: {message}")
        sys.exit(0 if success else 1)
