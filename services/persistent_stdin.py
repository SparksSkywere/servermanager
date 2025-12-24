# -*- coding: utf-8 -*-
# pyright: reportArgumentType=false
# Persistent stdin pipe for server processes
# - Named pipe for stdin access

import os
import sys
import time
import json
import threading
import logging
from pathlib import Path
from typing import Optional, Tuple

# Windows named pipe support
_AVAILABLE = False
if sys.platform == 'win32':
    try:
        import win32pipe
        import win32file
        import win32security
        import pywintypes
        import msvcrt
        _AVAILABLE = True
    except ImportError:
        pass

LOG_DIR = Path(__file__).parent.parent / "logs" / "services"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "persistent_stdin.log"),
    ]
)
logger = logging.getLogger("PersistentStdin")


def get_stdin_pipe_name(server_name: str) -> str:
    # Named pipe path for server stdin
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
    return f"\\\\.\\pipe\\ServerManager_stdin_{safe_name}"


def get_stdin_info_file(server_name: str) -> Path:
    # Stdin pipe info file path
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)
    temp_dir = Path(__file__).parent.parent / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"stdin_{safe_name}.json"


class PersistentStdinPipe:
    # Named pipe for stdin forwarding to server
    
    def __init__(self, server_name: str):
        self.server_name = server_name
        self.pipe_name = get_stdin_pipe_name(server_name)
        self.pipe_handle = None
        self.read_handle = None  # Handle for subprocess stdin
        self.listener_thread = None
        self.stop_event = threading.Event()
        self.server_stdin = None  # Actual stdin target
        self._lock = threading.Lock()
    
    def create_pipe_for_subprocess(self) -> Optional[int]:
        # Create pipe, return fd for subprocess.Popen stdin
        if not _AVAILABLE:
            logger.error("Named pipes not available")
            return None
        
        try:
            # Create security attributes that allow access from any process
            sd = win32security.SECURITY_DESCRIPTOR()
            sd.SetSecurityDescriptorDacl(1, None, 0)  # Null DACL = everyone has access
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.SECURITY_DESCRIPTOR = sd
            sa.bInheritHandle = True  # Allow handle inheritance
            
            # Create the named pipe in duplex mode
            self.pipe_handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                65536,  # Out buffer
                65536,  # In buffer
                0,      # Default timeout
                sa
            )
            
            if self.pipe_handle == win32file.INVALID_HANDLE_VALUE:
                logger.error(f"Failed to create named pipe for {self.server_name}")
                return None
            
            logger.info(f"Created stdin pipe: {self.pipe_name}")
            
            # Save pipe info
            info = {
                'server_name': self.server_name,
                'pipe_name': self.pipe_name,
                'created_at': time.time()
            }
            get_stdin_info_file(self.server_name).write_text(json.dumps(info, indent=2))
            
            # Open the pipe for reading (this is what the subprocess will use)
            self.read_handle = win32file.CreateFile(
                self.pipe_name,
                win32file.GENERIC_READ,
                win32file.FILE_SHARE_WRITE,
                sa,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            
            # Convert to file descriptor for subprocess
            fd = msvcrt.open_osfhandle(int(self.read_handle), os.O_RDONLY)
            return fd
            
        except Exception as e:
            logger.error(f"Error creating stdin pipe: {e}", exc_info=True)
            self.cleanup()
            return None
    
    def cleanup(self):
        """Clean up pipe handles."""
        try:
            if self.pipe_handle:
                win32file.CloseHandle(self.pipe_handle)
                self.pipe_handle = None
        except:
            pass
        
        try:
            info_file = get_stdin_info_file(self.server_name)
            if info_file.exists():
                info_file.unlink()
        except:
            pass


def send_command_to_stdin_pipe(server_name: str, command: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """
    Send a command to a server via its persistent stdin pipe.
    
    Args:
        server_name: The name of the server
        command: The command to send
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (success, message)
    """
    if not _AVAILABLE:
        return False, "Named pipes not available"
    
    pipe_name = get_stdin_pipe_name(server_name)
    
    # Check if pipe info exists
    info_file = get_stdin_info_file(server_name)
    if not info_file.exists():
        return False, f"No stdin pipe configured for {server_name}"
    
    try:
        # Try to connect to the pipe and write
        handle = win32file.CreateFile(
            pipe_name,
            win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None
        )
        
        try:
            # Write command with newline
            data = (command + "\n").encode('utf-8')
            win32file.WriteFile(handle, data)
            logger.info(f"Sent command to {server_name} via stdin pipe: {command}")
            return True, f"Command sent: {command}"
        finally:
            win32file.CloseHandle(handle)
            
    except pywintypes.error as e:
        if e.winerror == 2:  # ERROR_FILE_NOT_FOUND
            return False, f"Stdin pipe not available for {server_name}"
        elif e.winerror == 231:  # ERROR_PIPE_BUSY
            return False, f"Stdin pipe is busy for {server_name}"
        else:
            return False, f"Pipe error: {e}"
    except Exception as e:
        return False, str(e)


def is_stdin_pipe_available(server_name: str) -> bool:
    """Check if a stdin pipe is available for the server."""
    info_file = get_stdin_info_file(server_name)
    if not info_file.exists():
        return False
    
    # Try to open the pipe briefly to verify it exists
    pipe_name = get_stdin_pipe_name(server_name)
    try:
        handle = win32file.CreateFile(
            pipe_name,
            win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_OVERLAPPED,
            None
        )
        win32file.CloseHandle(handle)
        return True
    except:
        return False
