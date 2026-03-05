# -*- coding: utf-8 -*-
# pyright: reportArgumentType=false
# Persistent stdin pipe for server processes
import os
import sys
from pathlib import Path
from typing import Tuple, Any

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Windows named pipe support - declare module-level placeholders for type checking
win32pipe: Any = None
win32file: Any = None
win32security: Any = None
pywintypes: Any = None

_AVAILABLE = False
if sys.platform == 'win32':
    try:
        import win32pipe as _win32pipe
        import win32file as _win32file
        import win32security as _win32security
        import pywintypes as _pywintypes
        win32pipe = _win32pipe
        win32file = _win32file
        win32security = _win32security
        pywintypes = _pywintypes
        _AVAILABLE = True
    except ImportError:
        pass

from Modules.server_logging import get_component_logger
logger = get_component_logger("PersistentStdin")

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

def send_command_to_stdin_pipe(server_name: str, command: str, timeout: float = 5.0) -> Tuple[bool, str]:
    # Send a command to a server via its persistent stdin pipe
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
        if e.winerror == 2:
            return False, f"Stdin pipe not available for {server_name}"
        elif e.winerror == 231:
            return False, f"Stdin pipe is busy for {server_name}"
        else:
            return False, f"Pipe error: {e}"
    except Exception as e:
        return False, str(e)

def is_stdin_pipe_available(server_name: str) -> bool:
    # Check if a stdin pipe is available for the server
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
    except (pywintypes.error, OSError):
        return False