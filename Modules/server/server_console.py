# Server console interface
# -*- coding: utf-8 -*-
# pyright: reportArgumentType=false
import os
import sys
import subprocess
import threading
import time
import queue
import logging
import signal
import glob
import select
import json
import ssl
import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import psutil
from typing import Any
import urllib.request
import urllib.parse
import urllib.error

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path
setup_module_path()

# Windows named pipe support - declare module-level placeholders for type checking
win32pipe: Any = None
win32file: Any = None
pywintypes: Any = None

_NAMED_PIPES_AVAILABLE = False
_WIN32_CONSOLE_AVAILABLE = False

# Windows console API support - declare module-level placeholders
ctypes: Any = None
wintypes: Any = None
kernel32: Any = None
ATTACH_PARENT_PROCESS = -1
STD_INPUT_HANDLE = -10

if sys.platform == 'win32':
    try:
        import win32pipe as _win32pipe
        import win32file as _win32file
        import pywintypes as _pywintypes
        win32pipe = _win32pipe
        win32file = _win32file
        pywintypes = _pywintypes
        _NAMED_PIPES_AVAILABLE = True
    except ImportError:
        pass

    # Console API for attached process input
    try:
        import ctypes as _ctypes
        from ctypes import wintypes as _wintypes
        ctypes = _ctypes
        wintypes = _wintypes

        kernel32 = ctypes.windll.kernel32

        kernel32.AttachConsole.argtypes = [wintypes.DWORD]
        kernel32.AttachConsole.restype = wintypes.BOOL
        kernel32.FreeConsole.argtypes = []
        kernel32.FreeConsole.restype = wintypes.BOOL
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.WriteConsoleInputW.restype = wintypes.BOOL

        _WIN32_CONSOLE_AVAILABLE = True
    except Exception:
        pass

from Modules.core.common import setup_module_logging, send_command_to_server
from Modules.ui.color_palettes import get_palette
from Modules.ui.theme import get_theme_preference

# Import shared server operations from dashboard_functions
try:
    from Host.dashboard_functions import start_server_operation, stop_server_operation
    _DASHBOARD_FUNCTIONS_AVAILABLE = True
except ImportError:
    start_server_operation = None
    stop_server_operation = None
    _DASHBOARD_FUNCTIONS_AVAILABLE = False

# File-based command queue - declare placeholders for type checking
is_relay_active: Any = None
start_command_relay: Any = None
_COMMAND_QUEUE_AVAILABLE = False
try:
    from services.command_queue import is_relay_active as _is_relay_active
    from services.command_queue import start_command_relay as _start_command_relay
    is_relay_active = _is_relay_active
    start_command_relay = _start_command_relay
    _COMMAND_QUEUE_AVAILABLE = True
except ImportError:
    pass

logger: logging.Logger = setup_module_logging("ServerConsole")


class _ConsoleCrashTracer:
    # Temporary crash tracer is disabled after stability fixes.
    def record(self, event, server_name=None, **fields):
        return

    def dump_recent(self, reason, logger_obj):
        return


_CRASH_TRACER = _ConsoleCrashTracer()

# Real-time console class
class RealTimeConsole:
    # Real-time console for individual server process

    def __init__(self, server_name, server_config, server_manager=None, console_manager=None):
        self.server_name = server_name
        self.server_config = server_config
        self.server_manager = server_manager
        self.console_manager = console_manager
        self.process = None
        self.is_active = False
        self.window = None
        self.text_widget = None
        self.command_entry = None
        self.output_thread = None
        self.error_thread = None
        self.input_thread = None
        self.log_monitor_thread = None
        self.state_save_thread = None
        self.stop_event = threading.Event()

        # Command handling
        self.command_queue = queue.Queue()
        self.command_history = []
        self.history_index = -1

        # Output buffering
        self.output_buffer = []
        self.buffer_lock = threading.Lock()
        self.max_buffer_size = 2000
        self._last_output_text = None
        self._last_output_type = None
        self._last_output_time = 0.0
        self._duplicate_output_window = 1.0

        # Rate limiting for GUI updates
        self.last_gui_update = 0
        self.gui_update_interval = 0.05
        self.pending_gui_updates = []
        self.gui_update_lock = threading.Lock()

        # Flush thread for periodic GUI updates
        self.flush_thread = None

        # Auto-scroll control
        self.auto_scroll_enabled = True
        self.scroll_pause_btn = None

        # Log file handles and monitoring
        self.stdout_log = None
        self.stderr_log = None
        self.server_log_paths = []
        self.log_file_positions = {}
        self._force_log_refresh = threading.Event()

        # State persistence for crash recovery
        self._last_state_save_count = 0
        self._state_save_interval = 3
        self._db_save_pending = False

        # Named pipe for IPC command sending (Windows only)
        self._pipe_name = self._get_pipe_name()
        self._pipe_handle = None
        self._pipe_listener_thread = None
        self._pipe_server_active = False
        self._is_reattached = False

        # GUI status update control
        self.status_updates_active = True

        # HTTPS/Web API support for secured consoles
        self.use_https_console = False
        self.web_api_url = "https://127.0.0.1:8080"
        self.auth_token = None
        self.last_console_update = 0
        self.api_poll_interval = 1.0
        self.api_poll_thread = None

    def _authenticate_api(self):
        # Authenticate with the webserver API to get a token
        try:
            # Try to get credentials from environment or use default
            username = os.getenv('SERVER_MANAGER_USER', 'admin')
            password = os.getenv('SERVER_MANAGER_PASS', 'admin')

            auth_url = f"{self.web_api_url}/api/auth/login"
            auth_data = json.dumps({
                'username': username,
                'password': password
            }).encode('utf-8')

            # Create request with SSL context - using CERT_REQUIRED for security
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED

            req = urllib.request.Request(auth_url, data=auth_data, method='POST')
            req.add_header('Content-Type', 'application/json')

            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                if response.getcode() == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if 'token' in data:
                        self.auth_token = data['token']
                        logger.debug(f"Successfully authenticated with webserver API for {self.server_name}")
                        return True
                    else:
                        logger.error(f"Authentication failed: {data}")
                else:
                    logger.error(f"Authentication HTTP error: {response.getcode()}")

        except Exception as e:
            logger.error(f"Error authenticating with webserver API: {e}")

        return False

    def _start_api_poll_thread(self):
        # Start HTTPS API polling thread for secured console updates
        try:
            if self.api_poll_thread and self.api_poll_thread.is_alive():
                return

            self.api_poll_thread = threading.Thread(
                target=self._api_poll_loop,
                daemon=True,
                name=f"Console-API-{self.server_name}"
            )
            self.api_poll_thread.start()
            logger.debug(f"Started HTTPS API polling thread for {self.server_name}")
        except Exception as e:
            logger.error(f"Error starting API poll thread for {self.server_name}: {e}")

    def _api_poll_loop(self):
        # Poll the HTTPS API for console updates
        try:
            while self.is_active and not self.stop_event.is_set():
                try:
                    self._poll_console_api()
                    time.sleep(self.api_poll_interval)
                except Exception as e:
                    logger.debug(f"API poll error for {self.server_name}: {e}")
                    time.sleep(2)
        except Exception as e:
            logger.error(f"Fatal API poll error for {self.server_name}: {e}")

    def _poll_console_api(self):
        # Poll the HTTPS API for new console output
        try:
            if not self.auth_token:
                # Try to get token from environment or config
                self.auth_token = os.getenv('SERVER_MANAGER_TOKEN')
                if not self.auth_token and self.server_config:
                    # Try to authenticate
                    self._authenticate_api()
                if not self.auth_token:
                    return

            # Build API URL
            api_url = f"{self.web_api_url}/api/servers/{urllib.parse.quote(self.server_name)}/console?lines=50"

            # Create request with SSL context - using CERT_REQUIRED for security
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED

            req = urllib.request.Request(api_url)
            req.add_header('Authorization', f'Bearer {self.auth_token}')
            req.add_header('Content-Type', 'application/json')

            with urllib.request.urlopen(req, context=context, timeout=5) as response:
                if response.getcode() == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('output'):
                        # Process new output lines
                        current_time = time.time()
                        for line_data in data['output']:
                            line_text = line_data.get('text', '').strip()
                            if line_text:
                                # Add to buffer if not already present (avoid duplicates)
                                with self.buffer_lock:
                                    # Check if this line is already in recent buffer
                                    recent_lines = [entry['text'] for entry in self.output_buffer[-10:]]
                                    if line_text not in recent_lines:
                                        self._add_output(line_text, "stdout")

                        self.last_console_update = current_time
                elif response.getcode() == 401:
                    # Token expired, try to re-authenticate
                    self.auth_token = None
                    logger.debug(f"API auth failed for {self.server_name}, will retry")

        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.auth_token = None
            logger.debug(f"HTTP error polling console API for {self.server_name}: {e.code}")
        except Exception as e:
            logger.debug(f"Error polling console API for {self.server_name}: {e}")

    def _send_command_via_api(self, command):
        # Send command via HTTPS API
        try:
            if not self.auth_token:
                self._authenticate_api()
                if not self.auth_token:
                    self._add_output("[ERROR] Cannot send command - authentication failed", "error")
                    return False

            # Build API URL
            api_url = f"{self.web_api_url}/api/servers/{urllib.parse.quote(self.server_name)}/console"
            command_data = json.dumps({'command': command}).encode('utf-8')

            # Create request with SSL context - using CERT_REQUIRED for security
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED

            req = urllib.request.Request(api_url, data=command_data, method='POST')
            req.add_header('Authorization', f'Bearer {self.auth_token}')
            req.add_header('Content-Type', 'application/json')

            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                if response.getcode() == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('success'):
                        self._add_output(f"> {command}", "command")
                        if command not in self.command_history:
                            self.command_history.append(command)
                            if len(self.command_history) > 50:
                                self.command_history.pop(0)
                        return True
                    else:
                        error_msg = data.get('error', 'Unknown error')
                        self._add_output(f"[ERROR] Command failed: {error_msg}", "error")
                        return False
                else:
                    self._add_output(f"[ERROR] Command failed with HTTP {response.getcode()}", "error")
                    return False

        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.auth_token = None
                self._add_output("[ERROR] Authentication failed - please restart console", "error")
            else:
                self._add_output(f"[ERROR] HTTP error: {e.code}", "error")
            return False
        except Exception as e:
            logger.error(f"Error sending command via API for {self.server_name}: {e}")
            self._add_output(f"[ERROR] Failed to send command: {str(e)}", "error")
            return False

    def _start_flush_thread(self):
        # Start the GUI update flush thread
        try:
            if self.flush_thread and self.flush_thread.is_alive():
                return

            self.flush_thread = threading.Thread(
                target=self._flush_thread_loop,
                daemon=True,
                name=f"Console-{self.server_name}-Flush"
            )
            self.flush_thread.start()
            logger.debug(f"Started flush thread for {self.server_name}")
        except Exception as e:
            logger.error(f"Error starting flush thread for {self.server_name}: {e}")

    def _flush_thread_loop(self):
        # Periodic flush thread to ensure pending GUI updates are processed
        try:
            while self.is_active and not self.stop_event.is_set():
                try:
                    # Process any pending batch updates that weren't handled immediately
                    self._process_pending_batch_updates()
                    time.sleep(0.5)
                except Exception as e:
                    logger.debug(f"Flush thread error: {e}")
                    time.sleep(1)
        except Exception as e:
            logger.error(f"Fatal flush thread error for {self.server_name}: {e}")
        finally:
            logger.debug(f"Flush thread ended for {self.server_name}")

    def _get_pipe_name(self):
        # Get the named pipe name for this server (Windows only)
        try:
            # Sanitise server name for pipe name
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in self.server_name)
            return f"\\\\.\\pipe\\ServerManager_{safe_name}_Console"
        except Exception as e:
            logger.error(f"Error getting pipe name for {self.server_name}: {e}")
            return None

    def save_console_state(self):
        # Save current console state to database for web console access and crash recovery
        try:
            with self.buffer_lock:
                current_count = len(self.output_buffer)
                if current_count == 0:
                    return True

                # Import console database functions
                try:
                    from Modules.Database.console_database import save_console_state_db
                    process_id = self.process.pid if self.process and hasattr(self.process, 'pid') else None
                    success = save_console_state_db(
                        server_name=self.server_name,
                        output_buffer=self.output_buffer[-self.max_buffer_size:],
                        command_history=self.command_history[-100:],
                        process_id=process_id,
                        is_active=self.is_active
                    )
                    if success:
                        self._last_state_save_count = current_count
                        logger.debug(f"Saved console state for {self.server_name} ({current_count} entries)")
                        return True
                    return False
                except ImportError:
                    logger.warning("Console database not available, cannot save state")
                    return False
        except Exception as e:
            logger.error(f"Error saving console state for {self.server_name}: {e}")
            return False

    def load_console_state(self):
        # Load console state from database (for crash recovery)
        try:
            # Try database first
            try:
                from Modules.Database.console_database import load_console_state_db
                output_buffer, command_history = load_console_state_db(self.server_name, max_age_seconds=3600)
                if output_buffer is not None:
                    # Load command history
                    self.command_history = command_history or []

                    # Load output buffer
                    with self.buffer_lock:
                        # Clear existing buffer and load saved state
                        self.output_buffer = output_buffer
                        self._last_state_save_count = len(self.output_buffer)

                    logger.debug(f"Loaded console state for {self.server_name} from database ({len(output_buffer)} entries)")
                    return True
            except ImportError:
                logger.warning("Console database not available, no state loading possible")
                return False

        except Exception as e:
            logger.error(f"Error loading console state for {self.server_name}: {e}")
            return False

    def _start_state_save_thread(self):
        # Start periodic state saving thread
        try:
            if self.state_save_thread and self.state_save_thread.is_alive():
                return

            self.state_save_thread = threading.Thread(
                target=self._periodic_state_save,
                daemon=True,
                name=f"Console-{self.server_name}-StateSave"
            )
            self.state_save_thread.start()
            logger.debug(f"Started state save thread for {self.server_name}")
        except Exception as e:
            logger.error(f"Error starting state save thread for {self.server_name}: {e}")

    def _periodic_state_save(self):
        # Periodically save console state to database for web console access
        try:
            while self.is_active and not self.stop_event.is_set():
                # Wait for the save interval
                if self.stop_event.wait(timeout=self._state_save_interval):
                    break

                # Save state only if there are pending changes
                if self.is_active and self._db_save_pending:
                    self._db_save_pending = False
                    self.save_console_state()

        except Exception as e:
            logger.error(f"Error in periodic state save for {self.server_name}: {e}")

    def clear_console_state(self):
        # Remove the console state from database (called when server is properly stopped)
        try:
            # Try database first
            try:
                from Modules.Database.console_database import clear_console_state_db
                clear_console_state_db(self.server_name)
                logger.debug(f"Cleared console state from database for {self.server_name}")
            except ImportError:
                logger.warning("Console database not available, cannot clear state")
        except Exception as e:
            logger.error(f"Error clearing console state for {self.server_name}: {e}")

    def _clear_pending_command_queue(self):
        # Drop queued stdin commands so old stop/automation commands can't leak into next session.
        try:
            while True:
                self.command_queue.get_nowait()
        except queue.Empty:
            pass
        except Exception as e:
            logger.debug(f"Error clearing command queue for {self.server_name}: {e}")

    def cleanup_on_server_stop(self):
        # Clean up console when server is properly stopped (not crashed)
        try:
            self.is_active = False
            self.status_updates_active = False
            self._status_update_scheduled = False
            pid = self.process.pid if self.process and hasattr(self.process, 'pid') else 'Unknown'

            # Clear the console state file - we don't want to restore old state
            self.clear_console_state()

            # Clear the output buffer
            with self.buffer_lock:
                self.output_buffer.clear()

            # Clear command history
            self.command_history.clear()

            # Clear queued commands that may be stale after process stop.
            self._clear_pending_command_queue()

            # Close log files
            self._close_log_files()

            # Stop monitoring threads
            self.stop_event.set()

            # Stop named pipe server
            self._stop_pipe_server()

            # Clear process reference
            self.process = None

            logger.debug(f"Cleaned up console for {self.server_name} (PID: {pid}) after server stop")

        except Exception as e:
            logger.error(f"Error cleaning up console on stop for {self.server_name}: {e}")

    def _start_pipe_server(self):
        # Start named pipe server for IPC command input (Windows only)
        if not _NAMED_PIPES_AVAILABLE or not self._pipe_name:
            return False

        try:
            if self._pipe_server_active:
                return True

            self._pipe_server_active = True
            self._pipe_listener_thread = threading.Thread(
                target=self._pipe_server_loop,
                daemon=True,
                name=f"Console-{self.server_name}-PipeServer"
            )
            self._pipe_listener_thread.start()
            logger.debug(f"Started named pipe server for {self.server_name}: {self._pipe_name}")
            return True
        except Exception as e:
            logger.error(f"Error starting pipe server for {self.server_name}: {e}")
            return False

    def _stop_pipe_server(self):
        # Stop named pipe server
        try:
            self._pipe_server_active = False
            if self._pipe_handle:
                try:
                    win32file.CloseHandle(self._pipe_handle)
                except (pywintypes.error, OSError):
                    pass
                self._pipe_handle = None
            logger.debug(f"Stopped named pipe server for {self.server_name}")
        except Exception as e:
            logger.debug(f"Error stopping pipe server for {self.server_name}: {e}")

    def _pipe_server_loop(self):
        # Named pipe server loop - listens for commands and forwards to process stdin
        if not _NAMED_PIPES_AVAILABLE:
            return

        try:
            while self._pipe_server_active and self.is_active and not self.stop_event.is_set():
                try:
                    # Create named pipe server
                    pipe_name = self._pipe_name if self._pipe_name else f"\\\\.\\pipe\\servermanager_{self.server_name}"
                    self._pipe_handle = win32pipe.CreateNamedPipe(
                        pipe_name,
                        win32pipe.PIPE_ACCESS_INBOUND,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        1,
                        4096,
                        4096,
                        0,
                        None
                    )

                    if self._pipe_handle == win32file.INVALID_HANDLE_VALUE:
                        logger.error(f"Failed to create named pipe for {self.server_name}")
                        time.sleep(1)
                        continue

                    logger.debug(f"Waiting for pipe connection on {self._pipe_name}")

                    # Wait for client connection (with timeout check)
                    try:
                        win32pipe.ConnectNamedPipe(self._pipe_handle, None)
                    except pywintypes.error as e:
                        if e.winerror == 535:
                            pass
                        else:
                            raise

                    # Read commands from pipe
                    while self._pipe_server_active and self.is_active:
                        try:
                            result, data = win32file.ReadFile(self._pipe_handle, 4096)
                            if result == 0 and data:
                                # data is bytes from ReadFile
                                command = data.decode('utf-8').strip() if isinstance(data, bytes) else str(data).strip()
                                if command:
                                    logger.debug(f"Received pipe command for {self.server_name}: {command}")
                                    # Forward command to process via command queue
                                    self.command_queue.put(command)
                        except pywintypes.error as e:
                            if e.winerror == 109:
                                break
                            elif e.winerror == 232:
                                time.sleep(0.1)
                                continue
                            else:
                                raise

                    # Close this instance of the pipe
                    try:
                        win32pipe.DisconnectNamedPipe(self._pipe_handle)
                        win32file.CloseHandle(self._pipe_handle)
                    except (pywintypes.error, OSError):
                        pass
                    self._pipe_handle = None

                except pywintypes.error as e:
                    if e.winerror == 231:
                        time.sleep(0.1)
                        continue
                    logger.debug(f"Pipe server error for {self.server_name}: {e}")
                    time.sleep(1)
                except Exception as e:
                    logger.debug(f"Pipe server loop error for {self.server_name}: {e}")
                    time.sleep(1)

        except Exception as e:
            logger.error(f"Fatal pipe server error for {self.server_name}: {e}")
        finally:
            self._pipe_server_active = False
            if self._pipe_handle:
                try:
                    win32file.CloseHandle(self._pipe_handle)
                except (pywintypes.error, OSError):
                    pass
                self._pipe_handle = None

    def _send_command_via_pipe(self, command):
        # Send command to server via named pipe (for reattached consoles)
        if not _NAMED_PIPES_AVAILABLE or not self._pipe_name:
            return False

        try:
            # Connect to named pipe as client
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )

            try:
                # Set pipe mode to message (handle type is compatible at runtime)
                win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)  # type: ignore[arg-type]

                # Write command
                data = (command + "\n").encode('utf-8')
                win32file.WriteFile(handle, data)  # type: ignore[arg-type]

                logger.debug(f"Sent command via pipe to {self.server_name}: {command}")
                return True
            finally:
                win32file.CloseHandle(handle)  # type: ignore[arg-type]

        except pywintypes.error as e:
            if e.winerror == 2:
                logger.debug(f"Named pipe not available for {self.server_name}, will try alternative method")
            else:
                logger.error(f"Error sending command via pipe to {self.server_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending command via pipe to {self.server_name}: {e}")
            return False

    def _send_command_via_console_api(self, command):
        # Send command to reattached process via Windows Console API (AttachConsole)
        if not _WIN32_CONSOLE_AVAILABLE:
            return False

        if not self.process:
            return False

        try:
            pid = self.process.pid if hasattr(self.process, 'pid') else None
            if not pid:
                return False

            # Detach from our current console first
            kernel32.FreeConsole()

            # Attach to the target process's console
            if not kernel32.AttachConsole(pid):
                logger.debug(f"Could not attach to console of PID {pid}")
                # Reattach to our parent's console
                kernel32.AttachConsole(ATTACH_PARENT_PROCESS)
                return False

            try:
                # Get the input handle for the attached console
                stdin_handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)

                if stdin_handle == -1 or stdin_handle == 0:
                    logger.debug(f"Could not get stdin handle for PID {pid}")
                    return False

                # Create INPUT_RECORD structures for each character and simulates keyboard input to the console
                command_with_enter = command + "\r\n"

                # Define INPUT_RECORD structure
                class KEY_EVENT_RECORD(ctypes.Structure):
                    _fields_ = [
                        ("bKeyDown", wintypes.BOOL),
                        ("wRepeatCount", wintypes.WORD),
                        ("wVirtualKeyCode", wintypes.WORD),
                        ("wVirtualScanCode", wintypes.WORD),
                        ("uChar", wintypes.WCHAR),
                        ("dwControlKeyState", wintypes.DWORD),
                    ]

                class INPUT_RECORD(ctypes.Structure):
                    _fields_ = [
                        ("EventType", wintypes.WORD),
                        ("Event", KEY_EVENT_RECORD),
                    ]

                KEY_EVENT = 0x0001

                # Write each character as a key event
                for char in command_with_enter:
                    # Key down event
                    input_record = INPUT_RECORD()
                    input_record.EventType = KEY_EVENT
                    input_record.Event.bKeyDown = True
                    input_record.Event.wRepeatCount = 1
                    input_record.Event.uChar = char
                    input_record.Event.wVirtualKeyCode = 0
                    input_record.Event.wVirtualScanCode = 0
                    input_record.Event.dwControlKeyState = 0

                    written = wintypes.DWORD()
                    kernel32.WriteConsoleInputW(stdin_handle, ctypes.byref(input_record), 1, ctypes.byref(written))

                    # Key up event
                    input_record.Event.bKeyDown = False
                    kernel32.WriteConsoleInputW(stdin_handle, ctypes.byref(input_record), 1, ctypes.byref(written))

                logger.debug(f"Sent command via Console API to {self.server_name}: {command}")
                return True

            finally:
                # Detach from target console and reattach to parent
                kernel32.FreeConsole()
                kernel32.AttachConsole(ATTACH_PARENT_PROCESS)

        except Exception as e:
            logger.error(f"Error sending command via Console API to {self.server_name}: {e}")
            # Try to reattach to parent console
            try:
                kernel32.FreeConsole()
                kernel32.AttachConsole(ATTACH_PARENT_PROCESS)
            except (OSError, AttributeError):
                pass
            return False

    def attach_to_process(self, process):
        # Attach console to an existing process object (subprocess.Popen or psutil.Process)
        try:
            logger.debug(f"Attempting to attach console to process for {self.server_name}")
            if not process:
                logger.error(f"Cannot attach console to {self.server_name}: No process provided")
                return False

            # Detect if this is a reattachment (psutil.Process) vs original start (subprocess.Popen)
            if hasattr(process, 'poll'):
                # This is a subprocess.Popen object (original start) - we have stdin access
                self._is_reattached = False
                logger.debug(f"Attaching to original Popen process for {self.server_name}")

                # Start command queue relay if not already running
                if _COMMAND_QUEUE_AVAILABLE and not is_relay_active(self.server_name):
                    try:
                        from services.command_queue import start_command_relay
                        start_command_relay(self.server_name, process)
                        logger.debug(f"Started command queue relay for {self.server_name}")
                    except Exception as e:
                        logger.warning(f"Could not start command queue relay: {e}")
            else:
                # This is a psutil.Process object (reattachment) - no stdin access
                self._is_reattached = True
                logger.debug(f"Reattaching to existing process for {self.server_name} (no stdin)")

            self.process = process
            self.is_active = True
            self.stop_event.clear()
            self._clear_pending_command_queue()

            # Start periodic GUI update flush thread
            self._start_flush_thread()

            # Open log files if specified
            self._open_log_files()

            # Try to load saved console state first (for crash recovery)
            state_loaded = self.load_console_state()

            # If no saved state, load historical output from log files
            if not state_loaded:
                self._load_historical_output()
            else:
                # State was loaded - add a reconnection message
                self._add_output(f"=== Console state restored from previous session ===", "system")

            # Add session start message
            pid = process.pid if hasattr(process, 'pid') else 'Unknown'
            self._add_output(f"=== Console attached to {self.server_name} (PID: {pid}) ===", "system")

            # Start monitoring threads (only if process has stdout/stderr)
            self._start_monitoring_threads()

            # Start periodic state saving for crash recovery
            self._start_state_save_thread()

            # Start named pipe server for IPC (if this is original start with stdin)
            if not self._is_reattached and _NAMED_PIPES_AVAILABLE:
                self._start_pipe_server()
            elif self._is_reattached:
                # Inform user about command input capabilities for reattached servers
                if _COMMAND_QUEUE_AVAILABLE and is_relay_active(self.server_name):
                    self._add_output(f"=== Console reattached - command input available via shared dispatcher ===", "system")
                else:
                    self._add_output(f"=== Console reattached - attempting shared command dispatcher ===", "system")

            logger.debug(f"Console attached to {self.server_name} (PID: {pid}, reattached={self._is_reattached})")

            # Schedule UI refresh on main thread if window exists
            if self.window:
                try:
                    self.window.after(100, self._refresh_console_state)
                except tk.TclError:
                    pass

            return True

        except Exception as e:
            logger.error(f"Error attaching console to {self.server_name}: {e}")
            return False

    def _quick_attach_to_process(self, process):
        # Quick attach to process - skips slow historical output loading
        try:
            logger.debug(f"Quick attaching console to process for {self.server_name}")
            if not process:
                return False

            # Detect if this is a reattachment
            if hasattr(process, 'poll'):
                self._is_reattached = False
            else:
                self._is_reattached = True

            # Load existing console state for reattached consoles
            if self._is_reattached:
                self.load_console_state()

            self.process = process
            self.is_active = True
            self.stop_event.clear()
            self._clear_pending_command_queue()

            # Start flush thread for GUI updates
            self._start_flush_thread()

            # Add session start message (will show when window opens)
            pid = process.pid if hasattr(process, 'pid') else 'Unknown'
            self._add_output(f"=== Console attached to {self.server_name} (PID: {pid}) ===", "system")

            # Start monitoring threads
            self._start_monitoring_threads()

            # Start state save thread
            self._start_state_save_thread()

            logger.debug(f"Quick attach complete for {self.server_name} (PID: {pid})")
            return True

        except Exception as e:
            logger.error(f"Error in quick attach for {self.server_name}: {e}")
            # Reset state on failure
            self.process = None
            self.is_active = False
            self.stop_event.set()
            return False

    def _open_log_files(self):
        # Open log files for writing
        try:
            stdout_path = self.server_config.get('LogStdout')
            stderr_path = self.server_config.get('LogStderr')

            if stdout_path:
                self.stdout_log = open(stdout_path, 'a', encoding='utf-8', buffering=1)
            if stderr_path:
                self.stderr_log = open(stderr_path, 'a', encoding='utf-8', buffering=1)

        except Exception as e:
            logger.error(f"Error opening log files for {self.server_name}: {e}")

    def _close_log_files(self):
        # Close log files
        try:
            if self.stdout_log:
                self.stdout_log.close()
                self.stdout_log = None
            if self.stderr_log:
                self.stderr_log.close()
                self.stderr_log = None
        except Exception as e:
            logger.error(f"Error closing log files for {self.server_name}: {e}")

    def _handle_process_termination(self):
        # Handle when the attached process has ended
        try:
            if self.is_active:
                self.is_active = False
                pid = self.process.pid if self.process and hasattr(self.process, 'pid') else 'Unknown'
                self._add_output(f"=== Process {self.server_name} (PID: {pid}) has ended ===", "system")
                logger.debug(f"Process {self.server_name} (PID: {pid}) has ended")

                # Save final console state before cleanup
                self.save_console_state()

                # Close log files
                self._close_log_files()

                # Stop monitoring threads
                self.stop_event.set()

        except Exception as e:
            logger.error(f"Error handling process termination for {self.server_name}: {e}")

    def _is_process_running(self):
        # Check if the attached process is still running
        try:
            if not self.process:
                return False

            # For subprocess.Popen objects
            if hasattr(self.process, 'poll'):
                try:
                    return self.process.poll() is None
                except (OSError, AttributeError):
                    # Process object became invalid
                    return False
            # For psutil.Process objects
            elif hasattr(self.process, 'is_running'):
                try:
                    return self.process.is_running()
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    # Process no longer exists or access denied
                    return False
            else:
                # Fallback - try to get process info
                try:
                    pid = self.process.pid
                    if pid:
                        # Quick check if process exists
                        os.kill(pid, 0)
                        return True
                except (OSError, AttributeError, ProcessLookupError):
                    return False
        except Exception as e:
            logger.debug(f"Error checking if process is running: {e}")
            return False

    def _start_monitoring_threads(self):
        # Start all monitoring threads
        try:
            if self.use_https_console:
                # Use HTTPS API polling for secured console updates
                logger.debug(f"Starting HTTPS API polling for secured console: {self.server_name}")
                self._start_api_poll_thread()
                return

            # Direct stream monitoring is only valid for live subprocess.Popen objects
            # that expose stdio streams. Reattached psutil processes should rely on
            # log monitoring / API polling instead.
            has_stdout_stream = (
                self.process and hasattr(self.process, 'stdout') and self.process.stdout is not None
            )
            has_stderr_stream = (
                self.process and hasattr(self.process, 'stderr') and self.process.stderr is not None
            )
            has_stdin_stream = (
                self.process and hasattr(self.process, 'stdin') and self.process.stdin is not None
            )

            if has_stdout_stream:
                self.output_thread = threading.Thread(
                    target=self._monitor_stdout,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stdout"
                )
                self.output_thread.start()

            # Start stderr monitoring (only if not redirected to stdout and has stderr)
            if has_stderr_stream and has_stdout_stream and self.process.stderr != self.process.stdout:
                self.error_thread = threading.Thread(
                    target=self._monitor_stderr,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stderr"
                )
                self.error_thread.start()

            # Start command input handler (only if process has stdin)
            if has_stdin_stream:
                self.input_thread = threading.Thread(
                    target=self._handle_commands,
                    daemon=True,
                    name=f"Console-{self.server_name}-Input"
                )
                self.input_thread.start()

            # Start log file monitoring for additional output capture.
            executable_path = str(self.server_config.get('ExecutablePath', '') or '').lower()
            is_wrapper_script = executable_path.endswith(('.bat', '.cmd', '.ps1', '.sh'))

            if self._is_reattached or is_wrapper_script or not has_stdout_stream:
                self._discover_server_logs()
                if self.server_log_paths:
                    self.log_monitor_thread = threading.Thread(
                        target=self._monitor_log_files,
                        daemon=True,
                        name=f"Console-{self.server_name}-LogMonitor"
                    )
                    self.log_monitor_thread.start()
                else:
                    self._add_output("No log files found for live output monitoring. Server may not be producing output.", "system")

        except Exception as e:
            logger.error(f"Error starting monitoring threads for {self.server_name}: {e}")

    def _monitor_stdout(self):
        # Monitor stdout from server process
        try:
            logger.debug(f"Started stdout monitoring for {self.server_name}")

            lines_processed = 0
            last_throttle_check = time.time()

            while self.is_active and not self.stop_event.is_set():
                try:
                    if (self.process and hasattr(self.process, 'stdout') and
                        self.process.stdout and not self.process.stdout.closed):
                        # On Windows, use non-blocking read with polling
                        if sys.platform == 'win32':
                            try:
                                # Use readline with a small timeout
                                line = self.process.stdout.readline()
                                if line:
                                    line = line.strip()
                                    if line:
                                        self._add_output(line, "stdout")
                                        if self.stdout_log:
                                            self.stdout_log.write(f"{datetime.datetime.now().isoformat()} {line}\n")
                                            self.stdout_log.flush()

                                        lines_processed += 1
                                elif not self._is_process_running():
                                    # Process has ended
                                    self._handle_process_termination()
                                    break
                                else:
                                    # Small sleep to prevent excessive CPU usage
                                    time.sleep(0.01)
                            except (OSError, ValueError, AttributeError) as e:
                                # Process stdout became invalid
                                logger.debug(f"Stdout became invalid for {self.server_name}: {e}")
                                self._handle_process_termination()
                                break

                        # Throttle processing if too many lines are being processed rapidly
                        current_time = time.time()
                        if current_time - last_throttle_check >= 1.0:
                            if lines_processed > 100:
                                logger.debug(f"High output detected for {self.server_name} ({lines_processed} lines/sec), throttling")
                                time.sleep(0.1)  # Add extra delay
                            lines_processed = 0
                            last_throttle_check = current_time

                    else:
                        # Unix systems - use select for non-blocking reads
                        try:
                            if self.process and hasattr(self.process, 'stdout') and self.process.stdout:
                                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                                if ready:
                                    line = self.process.stdout.readline()
                                    if line:
                                        line = line.strip()
                                        if line:
                                            self._add_output(line, "stdout")
                                            if self.stdout_log:
                                                self.stdout_log.write(f"{datetime.datetime.now().isoformat()} {line}\n")
                                                self.stdout_log.flush()

                                            lines_processed += 1
                            else:
                                # No stdout stream available; only treat as ended when the process is
                                # actually no longer running.
                                if not self._is_process_running():
                                    self._handle_process_termination()
                                    break
                                time.sleep(0.1)
                        except (OSError, ValueError, AttributeError, select.error) as e:
                            # Process stdout became invalid or select failed
                            logger.debug(f"Stdout monitoring failed for {self.server_name}: {e}")
                            if not self._is_process_running():
                                self._handle_process_termination()
                                break
                            time.sleep(0.1)

                except Exception as e:
                    logger.debug(f"Stdout monitoring error for {self.server_name}: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logger.error(f"Fatal stdout monitoring error for {self.server_name}: {e}")
        finally:
            logger.debug(f"Stdout monitoring ended for {self.server_name}")

    def _monitor_stderr(self):
        # Monitor stderr from server process
        try:
            logger.debug(f"Started stderr monitoring for {self.server_name}")

            lines_processed = 0
            last_throttle_check = time.time()

            while self.is_active and not self.stop_event.is_set():
                try:
                    if (self.process and hasattr(self.process, 'stderr') and
                        self.process.stderr and not self.process.stderr.closed and
                        self.process.stderr != self.process.stdout):
                        # Use select/poll for non-blocking reads if available
                        try:
                            if hasattr(select, 'select'):
                                ready, _, _ = select.select([self.process.stderr], [], [], 0.1)
                                if ready:
                                    line = self.process.stderr.readline()
                                    if line:
                                        line = line.strip()
                                        if line:
                                            self._add_output(line, "stderr")
                                            if self.stderr_log:
                                                self.stderr_log.write(f"{datetime.datetime.now().isoformat()} {line}\n")
                                                self.stderr_log.flush()

                                            lines_processed += 1

                                            # Throttle processing if too many lines are being processed rapidly
                                            current_time = time.time()
                                            if current_time - last_throttle_check >= 1.0:
                                                if lines_processed > 100:
                                                    logger.debug(f"High stderr output detected for {self.server_name} ({lines_processed} lines/sec), throttling")
                                                    time.sleep(0.1)
                                                lines_processed = 0
                                                last_throttle_check = current_time

                                else:
                                    # Check if process ended
                                    if not self._is_process_running():
                                        self._handle_process_termination()
                                        break
                            else:
                                # Fallback for Windows
                                line = self.process.stderr.readline()
                                if line:
                                    line = line.strip()
                                    if line:
                                        self._add_output(line, "stderr")
                                        if self.stderr_log:
                                            self.stderr_log.write(f"{datetime.datetime.now().isoformat()} {line}\n")
                                            self.stderr_log.flush()

                                        lines_processed += 1

                                        # Throttle processing if too many lines are being processed rapidly
                                        current_time = time.time()
                                        if current_time - last_throttle_check >= 1.0:
                                            if lines_processed > 100:
                                                logger.debug(f"High stderr output detected for {self.server_name} ({lines_processed} lines/sec), throttling")
                                                time.sleep(0.1)
                                            lines_processed = 0
                                            last_throttle_check = current_time

                                elif not self._is_process_running():
                                    self._handle_process_termination()
                                    break
                                else:
                                    time.sleep(0.05)
                        except (OSError, ValueError, AttributeError, select.error) as e:
                            # Process stderr became invalid or select failed
                            logger.debug(f"Stderr monitoring failed for {self.server_name}: {e}")
                            self._handle_process_termination()
                            break
                    else:
                        # Check if process ended
                        if not self._is_process_running():
                            self._handle_process_termination()
                            break
                        time.sleep(0.1)

                except Exception as e:
                    logger.debug(f"Stderr monitoring error for {self.server_name}: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logger.error(f"Fatal stderr monitoring error for {self.server_name}: {e}")
        finally:
            logger.debug(f"Stderr monitoring ended for {self.server_name}")

    def _handle_commands(self):
        # Handle command input to server process
        try:
            logger.debug(f"Starting command handler for {self.server_name}")

            while self.is_active and not self.stop_event.is_set():
                try:
                    # Wait for command with timeout
                    command = self.command_queue.get(timeout=1.0)
                    logger.debug(f"Retrieved command from queue for {self.server_name}: '{command}'")

                    if (command and self.process and hasattr(self.process, 'stdin') and
                        self.process.stdin and not self.process.stdin.closed):
                        try:
                            # Send command to process
                            command_with_newline = f"{command}\n"
                            logger.debug(f"Sending to {self.server_name}: '{command_with_newline.strip()}'")

                            # Write command (encode to bytes if needed)
                            try:
                                self.process.stdin.write(command_with_newline)
                            except TypeError:
                                # If stdin expects bytes, encode the string
                                self.process.stdin.write(command_with_newline.encode('utf-8'))
                            self.process.stdin.flush()

                            # Show command in console
                            self._add_output(f"> {command}", "command")

                            # Add to history
                            if command not in self.command_history:
                                self.command_history.append(command)
                                if len(self.command_history) > 50:
                                    self.command_history.pop(0)

                            logger.debug(f"Command sent successfully to {self.server_name}: {command}")
                        except (OSError, ValueError, BrokenPipeError) as e:
                            logger.error(f"Error sending command '{command}' to {self.server_name}: {e}")
                            # Process stdin became invalid, terminate
                            self._handle_process_termination()
                            break
                    else:
                        logger.warning(f"Cannot send command to {self.server_name}: process or stdin not available (process={self.process is not None}, has_stdin={hasattr(self.process, 'stdin') if self.process else False}, stdin_closed={self.process.stdin.closed if self.process and hasattr(self.process, 'stdin') and self.process.stdin else 'N/A'})")

                    self.command_queue.task_done()

                except queue.Empty:
                    continue
                except Exception as e:
                    logger.debug(f"Command handling error for {self.server_name}: {e}")

        except Exception as e:
            logger.error(f"Fatal command handling error for {self.server_name}: {e}")
        finally:
            logger.debug(f"Command handler ended for {self.server_name}")

    def _discover_server_logs(self):
        # Discover additional log files that the server might write to
        try:
            # First, add the log files specified in the server config
            stdout_path = self.server_config.get('LogStdout')
            stderr_path = self.server_config.get('LogStderr')

            # For reattached consoles, monitor config log files since we don't have stdout
            if self._is_reattached:
                if stdout_path and os.path.exists(stdout_path):
                    self.server_log_paths.append(stdout_path)
                    logger.debug(f"Added config stdout log for reattached console: {stdout_path}")
                if stderr_path and os.path.exists(stderr_path) and stderr_path != stdout_path:
                    self.server_log_paths.append(stderr_path)
                    logger.debug(f"Added config stderr log for reattached console: {stderr_path}")

            # Then discover additional log files in the install directory
            install_dir = self.server_config.get('InstallDir', '')
            if not install_dir or not os.path.exists(install_dir):
                return

            # Common server log file patterns
            log_patterns = [
                'logs/*.log',
                'logs/*.txt',
                'Logs/*.log',
                'Logs/*.txt',
                '*.log',
                '*.txt',
                'console.log',
                'console.txt',
                'server.log',
                'server.txt',
                'output.log',
                'output.txt',
                'srcds.log',
                'debug.log',
                'debug.txt',
                'l4d2/logs/*.log',
                'left4dead2/logs/*.log',
                'addons/sourcemod/logs/*.log',
                'VintageStoryData/Logs/*.log',
                'VintageStoryData/Logs/*.txt',
            ]

            for pattern in log_patterns:
                full_pattern = os.path.join(install_dir, pattern)
                for log_file in glob.glob(full_pattern):
                    if os.path.isfile(log_file) and log_file not in self.server_log_paths:
                        # Skip config log files to avoid duplication (already added above for reattached)
                        if log_file == stdout_path or log_file == stderr_path:
                            continue
                        self.server_log_paths.append(log_file)
                        logger.debug(f"Found server log file: {log_file}")

            # Special handling for Vintage Story - check data path directory
            try:
                command = self.server_config.get('Command', '')
                if 'Vintagestory' in command.lower() or 'vintagestory' in command:
                    # Parse --dataPath from command
                    import re
                    data_path_match = re.search(r'--dataPath\s+["\']?([^"\s]+)["\']?', command)
                    if data_path_match:
                        data_path = data_path_match.group(1)
                        if os.path.exists(data_path):
                            vs_log_patterns = [
                                'VintageStoryData/Logs/*.log',
                                'VintageStoryData/Logs/*.txt',
                                'logs/*.log',
                                'logs/*.txt'
                            ]
                            for pattern in vs_log_patterns:
                                full_pattern = os.path.join(data_path, pattern)
                                for log_file in glob.glob(full_pattern):
                                    if os.path.isfile(log_file) and log_file not in self.server_log_paths:
                                        self.server_log_paths.append(log_file)
                                        logger.debug(f"Found Vintage Story log file: {log_file}")
            except Exception as e:
                logger.debug(f"Error checking Vintage Story data path: {e}")

        except Exception as e:
            logger.debug(f"Error discovering server logs: {e}")

    def _monitor_log_files(self):
        # Monitor additional server log files for output
        try:
            logger.debug(f"Started log file monitoring for {self.server_name}")

            while self.is_active and not self.stop_event.is_set():
                try:
                    # For subprocess.Popen objects, stop monitoring if process has ended
                    if hasattr(self.process, 'poll') and not self._is_process_running():
                        logger.debug(f"Process {self.server_name} has ended, stopping log file monitoring")
                        self._handle_process_termination()
                        break

                    # Process log files efficiently - batch file operations
                    log_files_to_check = []
                    for log_file in self.server_log_paths:
                        try:
                            if os.path.exists(log_file):
                                current_size = os.path.getsize(log_file)
                                last_pos = self.log_file_positions.get(log_file, 0)

                                # For reattached consoles, start from the end
                                if self._is_reattached and log_file not in self.log_file_positions:
                                    last_pos = current_size
                                    self.log_file_positions[log_file] = last_pos

                                # Only check files that have grown
                                if current_size > last_pos:
                                    log_files_to_check.append((log_file, current_size, last_pos))
                        except Exception as e:
                            logger.debug(f"Error checking log file {log_file}: {e}")

                    # Now read the files that need updating
                    for log_file, current_size, last_pos in log_files_to_check:
                        try:
                            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                                f.seek(last_pos)
                                content = f.read()

                                if content:
                                    # Split into lines, handling potential partial last line
                                    lines = content.splitlines()
                                    new_lines = []
                                    for line in lines:
                                        line = line.strip()
                                        if line and not self._is_old_log_entry(line):
                                            new_lines.append(line)

                                    # Only add lines if we have new content
                                    if new_lines:
                                        for line in new_lines:
                                            # Don't prefix with [LOG] if it's already a real-time console output
                                            if any(marker in line for marker in ['Setting breakpad', 'SteamInternal_', 'Looking up breakpad', 'Calling BreakpadMiniDumpSystemInit', 'Using breakpad']):
                                                # Skip these repetitive startup messages
                                                continue
                                            elif line.startswith('---') or 'Command:' in line:
                                                # Skip historical startup entries
                                                continue
                                            else:
                                                self._add_output(line, "stdout")

                                # Update position to current file size
                                self.log_file_positions[log_file] = current_size
                        except Exception as e:
                            logger.debug(f"Error reading log file {log_file}: {e}")

                    # Wait briefly before next check to avoid excessive CPU usage
                    time.sleep(0.05)

                except Exception as e:
                    logger.debug(f"Log file monitoring error: {e}")
                    time.sleep(1)

        except Exception as e:
            logger.error(f"Fatal log file monitoring error: {e}")
        finally:
            logger.debug(f"Log file monitoring ended for {self.server_name}")

    def _is_old_log_entry(self, line):
        # Check if a log entry is from an old session
        try:
            # Skip historical server start entries
            if '--- Server started at' in line:
                return True
            if 'Command:' in line:
                return True
            # Skip repetitive breakpad messages
            if any(marker in line for marker in [
                'Setting breakpad minidump AppID',
                'SteamInternal_SetMinidumpSteamID',
                'Looking up breakpad interfaces',
                'Calling BreakpadMiniDumpSystemInit',
                'Using breakpad crash handler',
                'Forcing breakpad minidump interfaces'
            ]):
                return True
            return False
        except Exception:
            return False

    def _add_output(self, text, msg_type="info"):
        # Add output to buffer and update GUI immediately for instant feedback
        try:
            now = time.time()
            raw_text = str(text).strip()

            # Check if text already has a timestamp prefix (e.g., [HH:MM:SS] or [DDMMMYYYY HH:MM:SS.mmm])
            import re
            timestamp_pattern = r'^\[\d{2}:\d{2}:\d{2}\]|\[\d{2}\w{3}\d{4} \d{2}:\d{2}:\d{2}\.\d{3}\]'
            if re.match(timestamp_pattern, raw_text):
                # Text already has timestamp, use as-is
                formatted_text = raw_text
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            else:
                # Add timestamp prefix
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                formatted_text = f"[{timestamp}] {raw_text}"

            with self.buffer_lock:
                # Avoid duplicate lines from overlapping stream/log monitoring sources.
                if (
                    raw_text
                    and raw_text == self._last_output_text
                    and msg_type == self._last_output_type
                    and (now - self._last_output_time) <= self._duplicate_output_window
                ):
                    return

                self._last_output_text = raw_text
                self._last_output_type = msg_type
                self._last_output_time = now

                self.output_buffer.append({
                    'text': formatted_text,
                    'type': msg_type,
                    'timestamp': timestamp
                })

                # Maintain buffer size
                if len(self.output_buffer) > self.max_buffer_size:
                    self.output_buffer.pop(0)

            # Update GUI immediately for instant feedback (but rate-limited)
            self._update_gui_immediately(formatted_text, msg_type)

            # Mark that DB save is needed (will be picked up by periodic save thread)
            self._db_save_pending = True

        except Exception as e:
            logger.debug(f"Error adding output for {self.server_name}: {e}")

    def _update_gui_immediately(self, text, msg_type):
        # Update GUI immediately with rate limiting to prevent excessive updates
        try:
            # Tkinter APIs are not thread-safe; background threads should only queue updates.
            if threading.current_thread() != threading.main_thread():
                with self.gui_update_lock:
                    self.pending_gui_updates.append((text, msg_type))
                return

            current_time = time.time()

            # Rate limit GUI updates to prevent excessive refreshes (max 20 per second)
            if current_time - self.last_gui_update < 0.05:
                # Too soon, add to pending updates for batch processing
                with self.gui_update_lock:
                    self.pending_gui_updates.append((text, msg_type))
                return

            self.last_gui_update = current_time

            # Check if GUI updates are still active
            if not self.status_updates_active:
                return

            # Schedule immediate GUI update on main thread
            if self.window:
                try:
                    self.window.after(0, lambda: self._do_gui_update(text, msg_type))
                except tk.TclError:
                    # Window was destroyed
                    pass

        except Exception as e:
            logger.debug(f"Error scheduling immediate GUI update: {e}")

    def _do_gui_update(self, text, msg_type):
        # Perform the actual GUI update on the main thread
        try:
            if not self.status_updates_active or not self.text_widget or not self.window or not self.window.winfo_exists():
                return

            self.text_widget.config(state=tk.NORMAL)

            # Insert new text at the end
            self.text_widget.insert(tk.END, text + "\n", msg_type)

            # Efficient line limiting - only check and trim when we have too many lines
            lines = int(self.text_widget.index('end-1c').split('.')[0])
            if lines > 1000:
                # Remove oldest lines in chunks for better performance
                self.text_widget.delete(1.0, f"{lines-1000}.0")

            # Auto-scroll to bottom only if user is already at bottom, this prevents jumping when user is scrolling up to read old messages
            if self._is_at_bottom():
                self.text_widget.see(tk.END)

            self.text_widget.config(state=tk.DISABLED)

            # Force UI refresh
            try:
                self.text_widget.update_idletasks()
                self.window.update_idletasks()
            except tk.TclError:
                pass

        except tk.TclError:
            pass  # Window was destroyed
        except Exception as e:
            logger.debug(f"Error in immediate GUI update: {e}")

    def _process_pending_batch_updates(self):
        # Process any pending updates that accumulated during rate limiting
        try:
            # This method must only touch Tk widgets on the main thread.
            if threading.current_thread() != threading.main_thread():
                return

            with self.gui_update_lock:
                if not self.pending_gui_updates:
                    return
                updates = self.pending_gui_updates.copy()
                self.pending_gui_updates.clear()

            # Schedule batch update on main thread
            if self.window and updates:
                self.window.after(0, lambda: self._do_batch_gui_update(updates))

        except Exception as e:
            logger.debug(f"Error processing pending batch updates: {e}")

    def _do_batch_gui_update(self, updates):
        # Perform batch GUI update on the main thread
        try:
            if not self.text_widget or not self.window or not self.window.winfo_exists():
                return

            self.text_widget.config(state=tk.NORMAL)

            # Insert all pending updates
            for text, msg_type in updates:
                self.text_widget.insert(tk.END, text + "\n", msg_type)

            # Efficient line limiting
            lines = int(self.text_widget.index('end-1c').split('.')[0])
            if lines > 1000:
                self.text_widget.delete(1.0, f"{lines-1000}.0")

            # Auto-scroll to bottom only if user is already at bottom
            if self._is_at_bottom():
                self.text_widget.see(tk.END)

            self.text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass
        except Exception as e:
            logger.debug(f"Error in batch GUI update: {e}")

    def _is_at_bottom(self):
        # Check if auto-scroll is enabled (respects pause button) returns True if we should auto-scroll to bottom
        return self.auto_scroll_enabled

    def _toggle_scroll_pause(self):
        # Toggle auto-scroll pause state
        self.auto_scroll_enabled = not self.auto_scroll_enabled

        # Update button text
        if self.scroll_pause_btn:
            if self.auto_scroll_enabled:
                self.scroll_pause_btn.config(text="Pause Scroll")
                # Jump to bottom when resuming
                if self.text_widget:
                    try:
                        self.text_widget.see(tk.END)
                    except tk.TclError:
                        pass
            else:
                self.scroll_pause_btn.config(text="Resume Scroll")

    def _bind_scroll_controls(self):
        # Ensure scrolling works after console window recreation.
        try:
            if not self.text_widget:
                return

            def _on_mousewheel(event):
                try:
                    if event.delta:
                        self.text_widget.yview_scroll(int(-event.delta / 120), "units")
                    else:
                        # X11 fallback
                        if getattr(event, 'num', None) == 4:
                            self.text_widget.yview_scroll(-1, "units")
                        elif getattr(event, 'num', None) == 5:
                            self.text_widget.yview_scroll(1, "units")
                except tk.TclError:
                    pass
                return "break"

            self.text_widget.bind("<MouseWheel>", _on_mousewheel)
            self.text_widget.bind("<Button-4>", _on_mousewheel)
            self.text_widget.bind("<Button-5>", _on_mousewheel)

            # Keep scrollbar wheel behavior when pointer is over the scrollbar itself.
            try:
                if hasattr(self.text_widget, 'vbar'):
                    self.text_widget.vbar.bind("<MouseWheel>", _on_mousewheel)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Error binding scroll controls for {self.server_name}: {e}")

    def _get_status_text(self):
        # Get status text for the console
        try:
            if self.process and self._is_process_running():
                pid = self.process.pid if hasattr(self.process, 'pid') else 'Unknown'
                return f"Status: Running (PID: {pid})"
            else:
                return "Status: Stopped (Read-only mode)"
        except Exception as e:
            logger.debug(f"Error getting status text: {e}")
            return "Status: Unknown"

    def _start_status_updates(self):
        # Start periodic status updates and GUI refresh on the Tk event loop
        try:
            if getattr(self, '_status_update_scheduled', False):
                return
            self._status_update_scheduled = True
            _CRASH_TRACER.record("status_updates_start", self.server_name)

            def status_tick():
                try:
                    if not self.status_updates_active:
                        self._status_update_scheduled = False
                        _CRASH_TRACER.record("status_updates_stop_inactive", self.server_name)
                        return

                    _CRASH_TRACER.record("status_tick", self.server_name, has_window=bool(self.window), has_process=bool(self.process))
                    self._schedule_status_update()

                    if self.window:
                        self.window.after(2000, status_tick)
                    else:
                        self._status_update_scheduled = False
                        _CRASH_TRACER.record("status_updates_stop_no_window", self.server_name)
                except tk.TclError:
                    self._status_update_scheduled = False
                    _CRASH_TRACER.record("status_tick_tclerror", self.server_name)
                except Exception as e:
                    logger.debug(f"Error in status tick for {self.server_name}: {e}")
                    self._status_update_scheduled = False
                    _CRASH_TRACER.record("status_tick_error", self.server_name, error=str(e))
                    _CRASH_TRACER.dump_recent("status_tick_exception", logger)

            if self.window:
                self.window.after(2000, status_tick)
            else:
                self._status_update_scheduled = False

        except Exception as e:
            logger.debug(f"Error starting status updates: {e}")
            self._status_update_scheduled = False
            _CRASH_TRACER.record("status_updates_start_error", self.server_name, error=str(e))

    def _schedule_status_update(self):
        # Schedule the actual update
        try:
            self._update_status_once()
        except Exception as e:
            logger.debug(f"Error in scheduled status update: {e}")

    def _update_status_once(self):
        # Perform one status update
        try:
            if not self.status_updates_active or not self.window or not self.window.winfo_exists():
                return

            if hasattr(self, 'status_label'):
                self.status_label.config(text=self._get_status_text())

                # Enable/disable command input based on process status
                is_running = self.process and self._is_process_running()
                if hasattr(self, 'command_entry') and self.command_entry:
                    self.command_entry.config(state=tk.NORMAL if is_running else tk.DISABLED)

                # Refresh GUI with any pending buffer content
                self._refresh_gui_from_buffer()

        except tk.TclError:
            pass
        except Exception as e:
            logger.debug(f"Error updating status: {e}")

    def _refresh_console_state(self):
        # Refresh console UI state after start/stop operations
        try:
            if not self.window or not self.window.winfo_exists():
                return

            # Update status label
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.config(text=self._get_status_text())

            # Update command entry state based on process status
            is_running = self.process and self._is_process_running()
            if hasattr(self, 'command_entry') and self.command_entry:
                self.command_entry.config(state=tk.NORMAL if is_running else tk.DISABLED)

            logger.debug(f"Console state refreshed for {self.server_name}, running={is_running}")

        except Exception as e:
            logger.debug(f"Error refreshing console state: {e}")

    def _refresh_gui_from_buffer(self):
        # Refresh GUI with any new content from buffer - MUST be called from main thread
        try:
            if not self.text_widget or not self.window or not self.window.winfo_exists():
                return

            # Check for pending updates
            with self.gui_update_lock:
                if not self.pending_gui_updates:
                    return
                updates = self.pending_gui_updates.copy()
                self.pending_gui_updates.clear()

            # Apply updates
            self.text_widget.config(state=tk.NORMAL)
            for text, msg_type in updates:
                self.text_widget.insert(tk.END, text + "\n", msg_type)

            # Limit lines
            lines = int(self.text_widget.index('end-1c').split('.')[0])
            if lines > 1000:
                self.text_widget.delete(1.0, f"{lines-1000}.0")

            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass
        except Exception as e:
            logger.debug(f"Error refreshing GUI: {e}")

    def send_command(self, command):
        # Send command to server process
        try:
            logger.debug(f"send_command called for {self.server_name} with command: '{command}'")
            if not self.is_active:
                logger.debug(f"Console not active for {self.server_name}")
                return False
            if not command.strip():
                logger.debug(f"Empty command for {self.server_name}")
                return False

            command = command.strip()

            # Use HTTPS API for secured console commands
            if self.use_https_console:
                return self._send_command_via_api(command)

            # Helper to handle successful command send
            def on_command_sent():
                self._add_output(f"> {command}", "command")
                if command not in self.command_history:
                    self.command_history.append(command)
                    if len(self.command_history) > 50:
                        self.command_history.pop(0)
                # Trigger immediate log file refresh to show response faster
                if hasattr(self, '_force_log_refresh'):
                    self._force_log_refresh.set()

            # If reattached, try multiple methods to send command
            if self._is_reattached:
                logger.debug(f"Attempting to send command to reattached console {self.server_name}")

                # Method 1: Try Windows Console API (AttachConsole) - try first for reattached processes
                if _WIN32_CONSOLE_AVAILABLE:
                    logger.debug(f"Trying Console API for {self.server_name}")
                    if self._send_command_via_console_api(command):
                        on_command_sent()
                        return True

                # Method 2: Try the console's own named pipe (if server was started by Server Manager)
                if _NAMED_PIPES_AVAILABLE:
                    if self._send_command_via_pipe(command):
                        on_command_sent()
                        return True

                # Method 3: Use shared command dispatch from common.py (persistent stdin + queue)
                if send_command_to_server(self.server_name, command):
                    logger.info(f"Command sent via shared dispatcher to {self.server_name}: {command}")
                    on_command_sent()
                    return True

                # All methods failed
                logger.warning(f"Failed to send command to reattached server {self.server_name}")
                self._add_output(f"[WARN] Cannot send commands to this server - console input is only available for servers started in the current session.", "error")
                self._add_output(f"[INFO] To enable console commands, stop and restart the server through the dashboard.", "info")
                return False

            # Normal path: send via command queue (for processes with stdin)
            logger.debug(f"Console is active for {self.server_name}, sending via command queue")
            self.command_queue.put(command)
            return True

        except Exception as e:
            logger.error(f"Error sending command to {self.server_name}: {e}")
            import traceback
            logger.debug(f"send_command error traceback: {traceback.format_exc()}")
            return False

    def show_window(self, parent=None):
        # Show the console window
        try:
            _CRASH_TRACER.record("show_window_enter", self.server_name, has_window=bool(self.window), is_active=self.is_active)

            # Enable GUI updates when showing window
            self.status_updates_active = True

            logger.debug(f"Attempting to show console window for {self.server_name}")
            if self.window and self.window.winfo_exists():
                try:
                    self.window.lift()
                    self.window.focus_set()
                except tk.TclError as e:
                    logger.warning(f"Could not bring window to front for {self.server_name}: {e}")
                    # Try to recreate the window if it's in a bad state
                    self.window = None
                    # Fall through to create new window
                else:
                    _CRASH_TRACER.record("show_window_focus_existing", self.server_name)
                    return True

            # Create window
            if parent:
                self.window = tk.Toplevel(parent)
            else:
                self.window = tk.Tk()
                # Set up Tkinter exception handling only for standalone windows
                server_name = self.server_name
                def console_tkinter_exception_handler(exc_type, exc_value, exc_traceback):
                    try:
                        logger.error(f"Tkinter exception in console window for {server_name}: {exc_type.__name__}: {exc_value}")
                        import traceback
                        logger.debug(f"Console Tkinter traceback: {''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}")
                    except Exception:
                        pass
                # Set the exception handler on the window instance
                self.window.report_callback_exception = console_tkinter_exception_handler

            self.window.title(f"Console - {self.server_name}")
            self.window.geometry("1000x700")

            # Create main frame
            main_frame = ttk.Frame(self.window, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Console output area
            output_frame = ttk.LabelFrame(main_frame, text="Server Output", padding=5)
            output_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

            # Status indicator
            status_frame = ttk.Frame(output_frame)
            status_frame.pack(fill=tk.X, pady=(0, 5))

            self.status_label = ttk.Label(status_frame, text=self._get_status_text(), font=("Segoe UI", 9))
            self.status_label.pack(side=tk.LEFT)

            # Update status periodically
            self._start_status_updates()

            # Text widget with scrollbar - optimised for console performance
            self.text_widget = scrolledtext.ScrolledText(
                output_frame,
                wrap=tk.NONE,
                font=("Consolas", 10),
                bg="black",
                fg="white",
                state=tk.DISABLED,
                height=20,
                undo=False,
                maxundo=0
            )
            self.text_widget.pack(fill=tk.BOTH, expand=True)
            self._bind_scroll_controls()

            # Reset scroll state for reopened consoles.
            self.auto_scroll_enabled = True

            # Configure tags for different message types
            self.text_widget.tag_configure("stdout", foreground="white")
            self.text_widget.tag_configure("stderr", foreground="#FF6B6B")
            self.text_widget.tag_configure("command", foreground="#6BCF7F")
            self.text_widget.tag_configure("system", foreground="#4ECDC4")

            # Command input area
            input_frame = ttk.LabelFrame(main_frame, text="Send Command", padding=5)
            input_frame.pack(fill=tk.X, pady=(0, 10))

            # Command entry and button
            cmd_frame = ttk.Frame(input_frame)
            cmd_frame.pack(fill=tk.X)

            self.command_entry = ttk.Entry(cmd_frame, font=("Consolas", 10))
            self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

            send_btn = ttk.Button(cmd_frame, text="Send", command=self._send_command_gui)
            send_btn.pack(side=tk.RIGHT)

            # Disable command input if no process is running
            if not self.process or not self._is_process_running():
                self.command_entry.config(state=tk.DISABLED)
                send_btn.config(state=tk.DISABLED)

            # Button frame
            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack(fill=tk.X)

            ttk.Button(btn_frame, text="Start Server", command=self._start_server_gui).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Stop Server", command=self._stop_server_gui).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Clear", command=self._clear_output).pack(side=tk.LEFT, padx=(0, 10))
            self.scroll_pause_btn = ttk.Button(btn_frame, text="Pause Scroll", command=self._toggle_scroll_pause)
            self.scroll_pause_btn.pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Kill Process", command=self._kill_process_gui).pack(side=tk.LEFT, padx=(0, 10))

            # Test Commands dropdown
            self._create_test_commands_dropdown(btn_frame)

            ttk.Button(btn_frame, text="Close", command=self.force_close_window).pack(side=tk.RIGHT)

            # Bind events
            self.command_entry.bind("<Return>", lambda e: self._send_command_gui())
            self.command_entry.bind("<Up>", self._prev_command)
            self.command_entry.bind("<Down>", self._next_command)
            self.window.protocol("WM_DELETE_WINDOW", self.force_close_window)

            # Load existing output
            self._populate_existing_output()

            # Focus command entry
            self.command_entry.focus_set()

            logger.debug(f"Console window created successfully for {self.server_name}")
            _CRASH_TRACER.record("show_window_created", self.server_name, has_text_widget=bool(self.text_widget))
            return True

        except Exception as e:
            logger.error(f"Error showing console window for {self.server_name}: {e}")
            import traceback
            logger.debug(f"Console window creation traceback: {traceback.format_exc()}")
            _CRASH_TRACER.record("show_window_error", self.server_name, error=str(e))
            _CRASH_TRACER.dump_recent("show_window_exception", logger)
            return False

    def _populate_existing_output(self):
        # Populate console with existing output buffer and historical log data
        try:
            if not self.text_widget:
                return

            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.delete(1.0, tk.END)

            # Check if buffer already has content
            with self.buffer_lock:
                has_buffer = bool(self.output_buffer)

            if has_buffer:
                # Already have buffer content, show last 500 entries quickly
                with self.buffer_lock:
                    for entry in self.output_buffer[-500:]:
                        self.text_widget.insert(tk.END, entry['text'] + "\n", entry['type'])
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
            elif self._is_reattached:
                # For reattached consoles, skip historical loading for performance
                self.text_widget.insert(tk.END, "[INFO] Top of the console\n", "system")
                self.text_widget.config(state=tk.DISABLED)
                logger.debug(f"Skipped historical loading for reattached console: {self.server_name}")
            else:
                # No buffer yet - show message and load in background
                self.text_widget.insert(tk.END, "Loading console output...\n", "system")
                self.text_widget.config(state=tk.DISABLED)

                # Load historical output in background thread
                def load_history_async():
                    try:
                        self._load_historical_output()
                        # Schedule UI update on main thread after loading
                        if self.window:
                            try:
                                self.window.after(100, self._update_text_from_buffer)
                            except tk.TclError:
                                pass
                    except Exception as e:
                        logger.debug(f"Error loading historical output async: {e}")

                history_thread = threading.Thread(target=load_history_async, daemon=True)
                history_thread.start()

        except Exception as e:
            logger.error(f"Error populating existing output: {e}")

    def _update_text_from_buffer(self):
        # Update text widget from buffer - called after async historical load
        try:
            if not self.text_widget or not self.window:
                return
            try:
                if not self.window.winfo_exists():
                    return
            except tk.TclError:
                return

            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.delete(1.0, tk.END)

            # Only show last 500 entries for performance
            with self.buffer_lock:
                entries_to_show = self.output_buffer[-500:]

            for entry in entries_to_show:
                self.text_widget.insert(tk.END, entry['text'] + "\n", entry['type'])

            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)

        except tk.TclError:
            pass
        except Exception as e:
            logger.debug(f"Error updating text from buffer: {e}")

    def _load_historical_output(self):
        # Load historical output from log files
        try:
            # Load from stdout log file specified in config
            stdout_path = self.server_config.get('LogStdout')
            if stdout_path and os.path.exists(stdout_path):
                self._load_log_file(stdout_path, "stdout")

            # Load from stderr log file specified in config
            stderr_path = self.server_config.get('LogStderr')
            if stderr_path and os.path.exists(stderr_path):
                self._load_log_file(stderr_path, "stderr")

            # Skip loading additional server log files for performance
            logger.debug(f"Loaded historical output from main logs only for {self.server_name}")

        except Exception as e:
            logger.debug(f"Error loading historical output: {e}")

    def _load_log_file(self, log_file_path, msg_type):
        # Load output from a specific log file
        try:
            # Check file size first - skip if too large to prevent memory issues
            file_size = os.path.getsize(log_file_path)
            if file_size > 5 * 1024 * 1024:
                logger.debug(f"Skipping historical load for large log file: {log_file_path} ({file_size} bytes)")
                with self.buffer_lock:
                    self.output_buffer.append({
                        'text': f"[INFO] Log file too large to display ({file_size // 1024 // 1024}MB). See: {log_file_path}",
                        'type': 'system',
                        'timestamp': datetime.datetime.now().isoformat()
                    })
                return

            with open(log_file_path, 'rb') as f:
                # Read lines more efficiently - only load last ~200 lines for quick display
                if file_size > 100 * 1024:
                    # Estimate position for last ~200 lines (assuming average 150 chars per line)
                    estimated_lines_size = 150 * 200
                    if file_size > estimated_lines_size:
                        seek_pos = file_size - estimated_lines_size
                        # Try to seek to a safer position (start of a line)
                        f.seek(seek_pos)
                        # Read a chunk and find the first newline to start from a line boundary
                        chunk = f.read(1024)
                        try:
                            first_newline = chunk.index(b'\n')
                            f.seek(seek_pos + first_newline + 1)
                        except ValueError:
                            # No newline found, just seek back
                            f.seek(seek_pos)

                # Read the remaining content
                content = f.read()

            # Decode with error handling
            try:
                text_content = content.decode('utf-8', errors='replace')
            except UnicodeDecodeError:
                # If UTF-8 fails, try latin-1 which can decode any byte sequence
                text_content = content.decode('latin-1', errors='replace')

            lines = text_content.splitlines()

            # Only load the last 200 lines to avoid overwhelming the console but ensure we get recent output
            if len(lines) > 200:
                lines = lines[-200:]

            for line in lines:
                line = line.strip()
                if line:
                    # Skip repetitive startup messages and old entries
                    if self._is_old_log_entry(line):
                        continue

                    # Format as historical entry
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    formatted_text = f"[{timestamp}] [HISTORY] {line}"

                    # Add to buffer only - GUI update is done separately via _update_text_from_buffer this prevents Tkinter thread safety issues
                    with self.buffer_lock:
                        self.output_buffer.append({
                            'text': formatted_text,
                            'type': msg_type,
                            'timestamp': timestamp
                        })

                        # Maintain buffer size
                        if len(self.output_buffer) > self.max_buffer_size:
                            self.output_buffer.pop(0)

            # Update the log file position to the end of the file for future monitoring this ensures we don't re-read the historical data
            try:
                with open(log_file_path, 'rb') as f:
                    f.seek(0, 2)
                    self.log_file_positions[log_file_path] = f.tell()
            except Exception as e:
                logger.debug(f"Could not update log file position for {log_file_path}: {e}")

        except Exception as e:
            logger.debug(f"Error loading log file {log_file_path}: {e}")

    def _send_command_gui(self):
        # Send command from GUI entry
        try:
            logger.debug(f"Attempting to send command from GUI for {self.server_name}")
            if not self.command_entry:
                logger.debug(f"No command entry widget for {self.server_name}")
                return

            command = self.command_entry.get().strip()
            if command:
                logger.debug(f"Sending command '{command}' to {self.server_name}")
                if self.send_command(command):
                    self.command_entry.delete(0, tk.END)
                    self.history_index = -1
                else:
                    logger.debug(f"Failed to send command to {self.server_name}")
                    # Enhanced error message for stopped servers
                    if not self.process:
                        messagebox.showwarning("Command Error", f"Cannot send commands to '{self.server_name}' - no server process is running.\n\nPlease start the server first.")
                    else:
                        messagebox.showwarning("Command Error", "Failed to send command. Server may not be running.")
        except Exception as e:
            logger.error(f"Error sending command from GUI: {e}")
            import traceback
            logger.debug(f"Command GUI error traceback: {traceback.format_exc()}")

    def _prev_command(self, event):
        # Navigate to previous command in history
        try:
            if self.command_history and self.command_entry:
                if self.history_index == -1:
                    self.history_index = len(self.command_history) - 1
                elif self.history_index > 0:
                    self.history_index -= 1

                self.command_entry.delete(0, tk.END)
                self.command_entry.insert(0, self.command_history[self.history_index])
        except Exception as e:
            logger.debug(f"Error navigating command history: {e}")

    def _next_command(self, event):
        # Navigate to next command in history
        try:
            if self.command_history and self.history_index != -1 and self.command_entry:
                if self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    self.command_entry.delete(0, tk.END)
                    self.command_entry.insert(0, self.command_history[self.history_index])
                else:
                    self.history_index = -1
                    self.command_entry.delete(0, tk.END)
        except Exception as e:
            logger.debug(f"Error navigating command history: {e}")

    def _kill_process_gui(self):
        # Kill process from GUI with confirmation
        try:
            if not self.process:
                messagebox.showwarning("No Process", f"No process is currently attached to {self.server_name}.")
                return

            parent_window = self.window if self.window else None
            if parent_window:
                result = messagebox.askyesno("Kill Process",
                                           f"Are you sure you want to forcefully kill the process for '{self.server_name}'?\n\nThis action cannot be undone and may cause data loss.",
                                           parent=parent_window)
            else:
                result = messagebox.askyesno("Kill Process",
                                           f"Are you sure you want to forcefully kill the process for '{self.server_name}'?\n\nThis action cannot be undone and may cause data loss.")

            if result:
                if self.kill_process():
                    if parent_window:
                        messagebox.showinfo("Success", f"Process for '{self.server_name}' has been killed.", parent=parent_window)
                    else:
                        messagebox.showinfo("Success", f"Process for '{self.server_name}' has been killed.")
                else:
                    if parent_window:
                        messagebox.showerror("Error", f"Failed to kill process for '{self.server_name}'.", parent=parent_window)
                    else:
                        messagebox.showerror("Error", f"Failed to kill process for '{self.server_name}'.")
        except Exception as e:
            logger.error(f"Error in kill process GUI for {self.server_name}: {e}")
            if self.window:
                messagebox.showerror("Error", f"Failed to kill process: {str(e)}", parent=self.window)

    def _start_server_gui(self):
        # Start server from GUI - uses shared server operation for consistency with dashboard
        try:
            parent_window = self.window if self.window else None

            # Check if server is already running
            if self.process and self._is_process_running():
                messagebox.showinfo("Server Running", f"Server '{self.server_name}' is already running.",
                                   parent=parent_window)
                return

            if not self.server_manager:
                messagebox.showerror("Error", "Server manager not available. Please restart the dashboard.",
                                    parent=parent_window)
                return

            # Use shared server operation (runs in background thread, doesn't freeze UI)
            if _DASHBOARD_FUNCTIONS_AVAILABLE:
                def status_callback(message):
                    # Filter out "started successfully" messages - completion_callback provides better one with PID
                    if "started successfully" in message.lower():
                        return
                    # Update status in console (thread-safe via _add_output)
                    self._add_output(f"[INFO] {message}", "system")

                def completion_callback(success, message):
                    # Update UI after operation completes
                    def update_ui():
                        if success:
                            self._add_output(f"[INFO] {message}", "system")
                            # Refresh console state after successful start
                            self._refresh_console_state()
                        else:
                            self._add_output(f"[ERROR] {message}", "error")
                            messagebox.showerror("Error", message, parent=parent_window)

                    # Schedule UI update on main thread if window exists
                    if self.window:
                        self.window.after(0, update_ui)

                # Use stored console_manager reference, or try to get from server_manager
                console_manager = self.console_manager or getattr(self.server_manager, 'console_manager', None)

                if start_server_operation is not None:
                    start_server_operation(
                        server_name=self.server_name,
                        server_manager=self.server_manager,
                        console_manager=console_manager,
                        status_callback=status_callback,
                        completion_callback=completion_callback,
                        parent_window=parent_window
                    )
                else:
                    # Fallback to direct call if dashboard_functions not available
                    def start_callback(message):
                        # Filter out "started successfully" - we'll show a better message with PID after completion
                        if "started successfully" in message.lower():
                            return
                        self._add_output(f"[INFO] {message}", "system")

                    success, message = self.server_manager.start_server_advanced(self.server_name, callback=start_callback)

                    if success:
                        # Show message with PID from the return value
                        self._add_output(f"[INFO] {message}", "system")
                    else:
                        messagebox.showerror("Error", f"Failed to start server '{self.server_name}': {message}",
                                            parent=parent_window)

        except Exception as e:
            logger.error(f"Error in start server GUI for {self.server_name}: {e}")
            if self.window:
                messagebox.showerror("Error", f"Failed to start server: {str(e)}", parent=self.window)

    def _stop_server_gui(self):
        # Stop server from GUI - uses shared server operation for consistency with dashboard
        try:
            parent_window = self.window if self.window else None

            # Check if server is running
            if not self.process or not self._is_process_running():
                messagebox.showinfo("Server Not Running", f"Server '{self.server_name}' is not running.",
                                   parent=parent_window)
                return

            # Confirm stop
            result = messagebox.askyesno("Stop Server",
                                        f"Are you sure you want to stop the server '{self.server_name}'?",
                                        parent=parent_window)

            if not result:
                return

            if not self.server_manager:
                messagebox.showerror("Error", "Server manager not available. Please restart the dashboard.",
                                    parent=parent_window)
                return

            # Use shared server operation (runs in background thread, doesn't freeze UI)
            if _DASHBOARD_FUNCTIONS_AVAILABLE:
                def status_callback(message):
                    # Filter out final "stopped successfully" messages - completion_callback handles that
                    if "stopped successfully" in message.lower():
                        return
                    # Update status in console (thread-safe via _add_output)
                    self._add_output(f"[INFO] {message}", "system")

                def completion_callback(success, message):
                    # Update UI after operation completes
                    def update_ui():
                        if success:
                            self._add_output(f"[INFO] Server stopped successfully", "system")
                            # Refresh console state after successful stop
                            self._refresh_console_state()
                        else:
                            self._add_output(f"[ERROR] {message}", "error")
                            messagebox.showerror("Error", message, parent=parent_window)

                    # Schedule UI update on main thread if window exists
                    if self.window:
                        self.window.after(0, update_ui)

                # Send the stop command directly via the console's own stdin path first.
                # This covers cases where the background stop_server_advanced cannot reach
                # the process (reattached server, no relay running, etc.).
                stop_cmd = (self.server_config or {}).get('StopCommand', '')
                if stop_cmd and self.is_active:
                    self.send_command(stop_cmd)
                    self._add_output(f"[INFO] Sending graceful stop command: {stop_cmd}", "system")

                # Use stored console_manager reference, or try to get from server_manager
                console_manager = self.console_manager or getattr(self.server_manager, 'console_manager', None)

                if stop_server_operation is not None:
                    stop_server_operation(
                        server_name=self.server_name,
                        server_manager=self.server_manager,
                        console_manager=console_manager,
                        status_callback=status_callback,
                        completion_callback=completion_callback,
                        parent_window=parent_window
                    )
                else:
                    # Fallback to direct call if dashboard_functions not available
                    def stop_callback(message):
                        # Filter out "stopped successfully" - we'll show our own message after completion
                        if "stopped successfully" in message.lower():
                            return
                        self._add_output(f"[INFO] {message}", "system")

                    success, message = self.server_manager.stop_server_advanced(self.server_name, callback=stop_callback)

                    if success:
                        self._add_output(f"[INFO] Server stopped successfully", "system")
                    else:
                        messagebox.showerror("Error", f"Failed to stop server '{self.server_name}': {message}",
                                            parent=parent_window)

        except Exception as e:
            logger.error(f"Error in stop server GUI for {self.server_name}: {e}")
            if self.window:
                messagebox.showerror("Error", f"Failed to stop server: {str(e)}", parent=self.window)

    def _create_test_commands_dropdown(self, parent_frame):
        # Create a dropdown menu for test commands
        try:
            palette = get_palette(get_theme_preference("light"))

            # Create menubutton
            test_menu_btn = tk.Menubutton(
                parent_frame,
                text="Test Commands",
                relief=tk.RAISED,
                bg=palette.get("button_bg"),
                fg=palette.get("button_fg"),
                activebackground=palette.get("button_active_bg"),
                activeforeground=palette.get("button_active_fg"),
                highlightbackground=palette.get("border"),
                highlightcolor=palette.get("border"),
            )
            test_menu_btn.pack(side=tk.LEFT, padx=(0, 10))

            # Create menu
            test_menu = tk.Menu(
                test_menu_btn,
                tearoff=0,
                bg=palette.get("menu_bg"),
                fg=palette.get("menu_fg"),
                activebackground=palette.get("menu_active_bg"),
                activeforeground=palette.get("menu_active_fg"),
            )
            test_menu_btn.config(menu=test_menu)

            # Add test command options
            test_menu.add_command(label="Test MOTD", command=self._test_motd_gui)
            test_menu.add_command(label="Test Save Command", command=self._test_save_command_gui)
            test_menu.add_command(label="Test Warning Commands", command=self._test_warning_commands_gui)

        except Exception as e:
            logger.error(f"Error creating test commands dropdown: {e}")

    def _test_motd_gui(self):
        # Test MOTD command from console
        self._run_automation_test("motd")

    def _test_save_command_gui(self):
        # Test save command from console
        self._run_automation_test("save")

    def _test_warning_commands_gui(self):
        # Test warning commands from console
        self._run_automation_test("warning")

    def _run_automation_test(self, test_type):
        # Run automation test - sends commands via the console's own direct stdin path
        try:
            if not self._is_process_running():
                messagebox.showerror("Error", "Server not running", parent=self.window)
                return

            # Get server config for commands
            from Modules.Database.server_configs_database import ServerConfigManager
            db_manager = ServerConfigManager()
            server_config = db_manager.get_server(self.server_name)

            if not server_config:
                messagebox.showerror("Error", "Server configuration not found.", parent=self.window)
                return

            # Load automation settings
            from Modules.core.common import load_automation_settings
            settings = load_automation_settings(server_config)

            # Run the appropriate test
            if test_type == "motd":
                motd_cmd = settings.get('motd_command', '')
                motd_msg = settings.get('motd_message', '')
                if not motd_cmd or not motd_msg:
                    messagebox.showerror("Error", "MOTD command or message not configured.", parent=self.window)
                    return
                command = motd_cmd.replace('{message}', motd_msg)
                success = self.send_command(command)
                if success:
                    self._add_output("[INFO] MOTD command sent successfully", "system")
                else:
                    messagebox.showerror("Error", "Failed to send MOTD command.", parent=self.window)

            elif test_type == "save":
                save_cmd = settings.get('save_command', '')
                if not save_cmd:
                    messagebox.showerror("Error", "Save command not configured.", parent=self.window)
                    return
                success = self.send_command(save_cmd)
                if success:
                    self._add_output(f"[INFO] Save command sent successfully: {save_cmd}", "system")
                else:
                    messagebox.showerror("Error", "Failed to send save command.", parent=self.window)

            elif test_type == "warning":
                warning_cmd = settings.get('warning_command', '')
                msg_template = settings.get('warning_message_template', 'Server restarting in {message}')

                if not warning_cmd:
                    messagebox.showerror("Error", "Warning command not configured.", parent=self.window)
                    return

                # Ask for test time
                import tkinter.simpledialog as simpledialog
                test_minutes = simpledialog.askinteger("Test Warning Time",
                                                     "Enter number of minutes for test warning:",
                                                     initialvalue=5, minvalue=1, parent=self.window)
                if test_minutes is None:
                    return

                if test_minutes == 1:
                    time_msg = "1 minute"
                else:
                    time_msg = f"{test_minutes} minutes"

                # Send a single test warning
                if "{message}" in warning_cmd:
                    command = warning_cmd.replace("{message}", time_msg)
                else:
                    test_message = msg_template.replace("{message}", time_msg)
                    command = warning_cmd.replace("{message}", test_message)

                success = self.send_command(command)
                if success:
                    self._add_output(f"[INFO] Test warning sent successfully: {command}", "system")
                else:
                    messagebox.showerror("Error", "Failed to send test warning.", parent=self.window)

        except Exception as e:
            logger.error(f"Error running automation test {test_type}: {str(e)}")
            if self.window:
                messagebox.showerror("Error", f"Failed to run test: {str(e)}", parent=self.window)

    def _clear_output(self):
        # Clear console output
        try:
            if self.text_widget:
                self.text_widget.config(state=tk.NORMAL)
                self.text_widget.delete(1.0, tk.END)
                self.text_widget.config(state=tk.DISABLED)

            with self.buffer_lock:
                self.output_buffer.clear()

        except Exception as e:
            logger.error(f"Error clearing output: {e}")

    def force_close_window(self):
        # Force close console window (for stuck windows)
        try:
            # Stop status updates
            self.status_updates_active = False

            # Save console state before closing
            self.save_console_state()

            if self.window and self.window.winfo_exists():
                logger.debug(f"Force closing console window for {self.server_name}")
                self.window.destroy()
                self.window = None
                self.text_widget = None
                self.command_entry = None
                return True
            else:
                logger.warning(f"No window to force close for {self.server_name}")
                return False
        except Exception as e:
            logger.error(f"Error force closing console window for {self.server_name}: {e}")
            return False

    def kill_process(self):
        # Forcefully kill the attached process
        try:
            if not self.process:
                logger.warning(f"No process attached to console for {self.server_name}")
                return False

            pid = None
            if hasattr(self.process, 'pid'):
                pid = self.process.pid
            elif isinstance(self.process, int):
                pid = self.process
            else:
                logger.error(f"Cannot determine PID for process attached to {self.server_name}")
                return False

            if not pid:
                logger.error(f"Invalid PID for process attached to {self.server_name}")
                return False

            logger.info(f"Forcefully killing process {pid} for {self.server_name}")

            # Get child processes first before killing parent (using psutil if available)
            children = []
            try:
                import psutil
                if psutil.pid_exists(pid):
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.debug(f"Found {len(children)} child processes for {pid}")
            except Exception as e:
                logger.debug(f"Could not get child processes: {e}")

            # Try graceful termination first
            try:
                # Check if process object has terminate method (subprocess.Popen)
                if hasattr(self.process, 'terminate') and callable(getattr(self.process, 'terminate')) and not isinstance(self.process, int):
                    self.process.terminate()
                    logger.debug(f"Sent terminate signal to process {pid}")
                else:
                    # Fallback to os.kill with SIGTERM
                    os.kill(pid, signal.SIGTERM)
                    logger.debug(f"Sent SIGTERM to process {pid}")

                # Wait a moment for graceful shutdown
                time.sleep(2)

                # Check if process is still running
                if self._is_process_running():
                    logger.warning(f"Process {pid} still running after terminate, forcing kill")

                    # On Windows, use taskkill /F /T which is more reliable for killing process tree
                    if os.name == 'nt':
                        try:
                            subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                        except Exception as e:
                            logger.debug(f"taskkill failed: {e}")
                    else:
                        # Check if process object has kill method
                        if hasattr(self.process, 'kill') and callable(getattr(self.process, 'kill')) and not isinstance(self.process, int):
                            self.process.kill()
                        else:
                            # Force kill with os.kill - use SIGKILL on Unix
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except (OSError, ProcessLookupError):
                                # Process might have already exited
                                pass

                    logger.debug(f"Force killed process {pid}")

            except (OSError, ProcessLookupError) as e:
                logger.warning(f"Process {pid} may have already exited: {e}")

            # Kill any remaining child processes
            for child in children:
                try:
                    if child.is_running():
                        if os.name == 'nt':
                            subprocess.call(['taskkill', '/F', '/PID', str(child.pid)],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                        else:
                            child.kill()
                        logger.debug(f"Killed child process {child.pid}")
                except Exception:
                    pass

            # Verify process is dead
            time.sleep(0.5)
            if self._is_process_running():
                logger.error(f"Process {pid} still running after force kill - attempting final cleanup")
                # Final attempt with taskkill /F /T on Windows
                if os.name == 'nt':
                    try:
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                    except Exception:
                        pass

            # Clean up console state since server was properly killed
            self.cleanup_on_server_stop()

            logger.info(f"Process {self.server_name} (PID: {pid}) was forcefully killed and console cleaned up")

            return True

        except Exception as e:
            logger.error(f"Error killing process for {self.server_name}: {e}")
            return False

# Console manager class
class ConsoleManager:
    # Manages multiple server consoles

    def __init__(self, server_manager=None):
        self.server_manager = server_manager
        self.consoles = {}
        self.lock = threading.RLock()

    def _get_console(self, server_name):
        # Thread-safe lookup helper for a single console object.
        with self.lock:
            return self.consoles.get(server_name)

    def _remove_console_if_same(self, server_name, expected_console):
        # Remove a console only if mapping still points to the expected object.
        with self.lock:
            existing = self.consoles.get(server_name)
            if existing is expected_console:
                self.consoles.pop(server_name, None)
                return True
        return False

    def _recover_manager_lock(self, server_name, reason):
        # Last-resort recovery when manager lock appears wedged.
        try:
            self.lock = threading.RLock()
            logger.warning(f"Recovered console manager lock for {server_name} ({reason})")
            _CRASH_TRACER.record("manager_lock_recovered", server_name, reason=reason)
            return True
        except Exception as e:
            logger.error(f"Failed to recover console manager lock for {server_name}: {e}")
            _CRASH_TRACER.record("manager_lock_recover_error", server_name, error=str(e))
            return False

    def _evict_broken_console(self, server_name, console_obj=None, reason="unknown"):
        # Remove broken console from manager and force-close its UI state.
        removed_console = None
        acquired = False
        try:
            acquired = self.lock.acquire(timeout=1.0)
            if acquired:
                existing = self.consoles.get(server_name)
                if existing and (console_obj is None or existing is console_obj):
                    removed_console = self.consoles.pop(server_name, None)
            else:
                _CRASH_TRACER.record("evict_console_lock_timeout", server_name, reason=reason)

            target_console = removed_console or console_obj
            if target_console:
                try:
                    target_console.status_updates_active = False
                    setattr(target_console, '_status_update_scheduled', False)
                except Exception:
                    pass

                try:
                    target_console.force_close_window()
                except Exception:
                    pass

                try:
                    target_console.window = None
                    target_console.text_widget = None
                    target_console.command_entry = None
                except Exception:
                    pass

            _CRASH_TRACER.record("evict_console_done", server_name, reason=reason, removed=bool(removed_console or console_obj))
            return bool(removed_console or console_obj)
        except Exception as e:
            logger.debug(f"Error evicting broken console for {server_name}: {e}")
            _CRASH_TRACER.record("evict_console_error", server_name, reason=reason, error=str(e))
            return False
        finally:
            if acquired:
                try:
                    self.lock.release()
                except Exception:
                    pass

    # lock_timeout: max seconds to wait for lock (None = blocking, 0 = non-blocking)
    def attach_console_to_process(self, server_name, process, server_config=None, lock_timeout=None):
        # Attach console to a running process
        try:
            acquired = self.lock.acquire(timeout=lock_timeout) if lock_timeout is not None else self.lock.acquire()
            if not acquired:
                logger.debug(f"Could not acquire lock to attach console for {server_name}, skipping")
                return False
            try:
                # Get or create console
                console = self.consoles.get(server_name)
                if not console:
                    if not server_config and self.server_manager:
                        server_config = self.server_manager.get_server_config(server_name)

                    if server_config:
                        console = RealTimeConsole(server_name, server_config, self.server_manager, self)
                        self.consoles[server_name] = console
                    else:
                        logger.error(f"No server config available for {server_name}")
                        return False

                # Attach to process
                return console.attach_to_process(process)
            finally:
                self.lock.release()

        except Exception as e:
            logger.error(f"Error attaching console to process for {server_name}: {e}")
            return False

    def show_console(self, server_name, parent=None, _retry_after_reset=True):
        # Show console window for a server
        try:
            _CRASH_TRACER.record("show_console_enter", server_name)
            logger.debug(f"show_console called for server: {server_name}")
            console = None
            server_config = None
            stale_console_to_cleanup = None

            # Get or create console while holding lock, but don't show window while locked
            _CRASH_TRACER.record("show_console_before_lock", server_name)
            acquired = self.lock.acquire(timeout=2.0)
            if not acquired:
                logger.error(f"Timed out acquiring console manager lock for {server_name}")
                _CRASH_TRACER.record("show_console_lock_timeout", server_name)
                _CRASH_TRACER.dump_recent("show_console_lock_timeout", logger)

                if _retry_after_reset and self._recover_manager_lock(server_name, "show_console_timeout"):
                    _CRASH_TRACER.record("show_console_retry_after_lock_recover", server_name)
                    return self.show_console(server_name, parent=parent, _retry_after_reset=False)
                return False

            _CRASH_TRACER.record("show_console_lock_acquired", server_name)
            try:
                console = self.consoles.get(server_name)
                if console:
                    logger.debug(f"Found existing console for {server_name}")
                    _CRASH_TRACER.record("show_console_existing_console", server_name, is_active=console.is_active)

                    # Never reuse a dead/inactive console object after stop.
                    # Recreating avoids stale widget/thread state causing UI instability.
                    try:
                        has_live_process = bool(console.process and console._is_process_running())
                    except Exception:
                        has_live_process = False

                    if not console.is_active and not has_live_process:
                        stale_console_to_cleanup = console
                        self.consoles.pop(server_name, None)
                        console = None
                        logger.debug(f"Discarded stale console object for {server_name}")
                        _CRASH_TRACER.record("show_console_discard_stale", server_name)

                else:
                    logger.debug(f"No existing console for {server_name}, attempting to create one")
                    # Try to create console if server exists
                    if self.server_manager:
                        try:
                            server_config = self.server_manager.get_server_config(server_name)
                            if server_config:
                                logger.debug(f"Got server config for {server_name}, creating console")
                                console = RealTimeConsole(server_name, server_config, self.server_manager, self)
                                self.consoles[server_name] = console
                                _CRASH_TRACER.record("show_console_created", server_name)
                            else:
                                logger.warning(f"No server config found for {server_name}")
                                _CRASH_TRACER.record("show_console_no_config", server_name)
                        except Exception as e:
                            logger.warning(f"Could not create console for {server_name}: {e}")
                            _CRASH_TRACER.record("show_console_create_error", server_name, error=str(e))

                if not console and self.server_manager:
                    try:
                        server_config = self.server_manager.get_server_config(server_name)
                        if server_config:
                            logger.debug(f"Creating fresh console for {server_name}")
                            console = RealTimeConsole(server_name, server_config, self.server_manager, self)
                            self.consoles[server_name] = console
                            _CRASH_TRACER.record("show_console_created_fresh", server_name)
                    except Exception as e:
                        logger.warning(f"Could not create fresh console for {server_name}: {e}")
                        _CRASH_TRACER.record("show_console_create_fresh_error", server_name, error=str(e))
            finally:
                self.lock.release()
                _CRASH_TRACER.record("show_console_lock_released", server_name)

            if stale_console_to_cleanup:
                try:
                    stale_console_to_cleanup.cleanup_on_server_stop()
                    _CRASH_TRACER.record("show_console_stale_cleanup_done", server_name)
                except Exception as cleanup_error:
                    logger.debug(f"Stale console cleanup failed for {server_name}: {cleanup_error}")
                    _CRASH_TRACER.record("show_console_stale_cleanup_error", server_name, error=str(cleanup_error))

            # If console exists but isn't active, try to attach to running process
            if console and not console.is_active:
                if not server_config and self.server_manager:
                    server_config = self.server_manager.get_server_config(server_name)

                if server_config:
                    pid = server_config.get('ProcessId') or server_config.get('PID')
                    if pid:
                        try:
                            _CRASH_TRACER.record("show_console_try_attach", server_name, pid=pid)
                            # Validate that the PID actually belongs to this server (prevents PID reuse issues)
                            is_valid = False
                            process = None
                            if self.server_manager and hasattr(self.server_manager, 'is_server_process_valid'):
                                is_valid, process = self.server_manager.is_server_process_valid(server_name, pid, server_config)
                            else:
                                # Fallback validation
                                if psutil.pid_exists(pid):
                                    process = psutil.Process(pid)
                                    is_valid = process.is_running()

                            if is_valid and process:
                                logger.debug(f"Attaching console to validated running process for {server_name} (PID: {pid})")
                                _CRASH_TRACER.record("show_console_attach_validated", server_name, pid=pid)
                                # Use quick attach that skips historical output loading
                                if not console._quick_attach_to_process(process):
                                    logger.warning(f"Failed to attach console to process for {server_name} (PID: {pid})")
                                    _CRASH_TRACER.record("show_console_attach_failed", server_name, pid=pid)
                            elif not is_valid:
                                # PID is stale or belongs to a different process. Do not attach to an
                                # unvalidated PID, as that can bind the console to the wrong process.
                                logger.warning(f"PID {pid} for {server_name} failed validation; clearing stale process metadata")
                                console._add_output(
                                    "[WARN] Stored process ID was stale and has been cleared. "
                                    "Start the server again from the dashboard to enable live console attach.",
                                    "warning"
                                )

                                # Clear stale PID metadata
                                server_config.pop('ProcessId', None)
                                server_config.pop('PID', None)
                                server_config.pop('StartTime', None)
                                server_config.pop('ProcessCreateTime', None)
                                if self.server_manager:
                                    self.server_manager.update_server(server_name, server_config)
                                _CRASH_TRACER.record("show_console_cleared_stale_pid", server_name, pid=pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                            logger.debug(f"Could not access process {pid} for {server_name}: {e}")
                            # Clear stale PID
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            if self.server_manager:
                                self.server_manager.update_server(server_name, server_config)
                            _CRASH_TRACER.record("show_console_pid_access_error", server_name, pid=pid, error=str(e))
                        except Exception as e:
                            logger.debug(f"Error checking process for {server_name}: {e}")
                            _CRASH_TRACER.record("show_console_pid_check_error", server_name, pid=pid, error=str(e))

            # Show window OUTSIDE the lock to prevent deadlocks
            if console:
                _CRASH_TRACER.record("show_console_before_show_window", server_name)
                if console.show_window(parent):
                    _CRASH_TRACER.record("show_console_success", server_name)
                    return True

                logger.error(f"Failed to show console window for {server_name}")
                _CRASH_TRACER.record("show_console_show_window_failed", server_name)
                _CRASH_TRACER.dump_recent("show_console_show_window_failed", logger)

                if _retry_after_reset:
                    self._evict_broken_console(server_name, console, reason="show_window_failed")
                    _CRASH_TRACER.record("show_console_retry_after_evict", server_name)
                    return self.show_console(server_name, parent=parent, _retry_after_reset=False)
                return False
            else:
                logger.error(f"Failed to create console for {server_name}")
                _CRASH_TRACER.record("show_console_no_console", server_name)
                messagebox.showerror("Console Error",
                                   f"No console available for server '{server_name}'. "
                                   f"Please start the server first.")
                return False

        except Exception as e:
            logger.error(f"Error showing console for {server_name}: {e}")
            import traceback
            logger.debug(f"show_console error traceback: {traceback.format_exc()}")
            _CRASH_TRACER.record("show_console_exception", server_name, error=str(e))
            _CRASH_TRACER.dump_recent("show_console_exception", logger)
            return False

    def send_command(self, server_name, command):
        # Send command to server console
        try:
            console = self._get_console(server_name)
            if console:
                return console.send_command(command)

            logger.warning(f"No console available for {server_name}")
            return False
        except Exception as e:
            logger.error(f"Error sending command to {server_name}: {e}")
            return False

    def kill_process(self, server_name):
        # Kill the process for a specific server console
        try:
            console = self._get_console(server_name)
            if console:
                return console.kill_process()

            logger.warning(f"No console available for {server_name} to kill process")
            return False
        except Exception as e:
            logger.error(f"Error killing process for {server_name}: {e}")
            return False

    def cleanup_console_on_stop(self, server_name):
        # Clean up a console when a server is properly stopped
        try:
            console = self._get_console(server_name)
            if console:
                console.cleanup_on_server_stop()

                window_open = False
                try:
                    window_open = bool(console.window and console.window.winfo_exists())
                except tk.TclError:
                    window_open = False
                except Exception:
                    window_open = False

                if not console.process and not console.is_active and not window_open:
                    self._remove_console_if_same(server_name, console)

                logger.debug(f"Cleaned up console for {server_name} on server stop")
                return True

            # No console exists, but try to clear any leftover state file
            try:
                temp_console = RealTimeConsole(server_name, {}, None, None)
                temp_console.clear_console_state()
                logger.debug(f"Cleared leftover console state for {server_name}")
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"Error cleaning up console for {server_name}: {e}")
            return False

    def prune_stale_consoles(self):
        # Remove stale/inactive console objects and clean up dead process attachments.
        removed_count = 0
        try:
            with self.lock:
                console_items = list(self.consoles.items())

            for server_name, console in console_items:
                try:
                    process_running = bool(console.process and console._is_process_running())
                except Exception:
                    process_running = False

                if process_running:
                    continue

                try:
                    console.cleanup_on_server_stop()
                except Exception:
                    pass

                window_open = False
                try:
                    window_open = bool(console.window and console.window.winfo_exists())
                except tk.TclError:
                    window_open = False
                except Exception:
                    window_open = False

                if not window_open and self._remove_console_if_same(server_name, console):
                    removed_count += 1

            if removed_count > 0:
                logger.debug(f"Pruned {removed_count} stale console(s)")
        except Exception as e:
            logger.error(f"Error pruning stale consoles: {e}")

        return removed_count

    def force_close_console(self, server_name):
        # Force close console window for a specific server
        try:
            console = self._get_console(server_name)
            if console:
                return console.force_close_window()

            logger.warning(f"No console available for {server_name} to force close")
            return False
        except Exception as e:
            logger.error(f"Error force closing console for {server_name}: {e}")
            return False

    def save_all_console_states(self):
        # Save states for all active consoles (for dashboard close/crash recovery)
        try:
            with self.lock:
                console_items = list(self.consoles.items())

            saved_count = 0
            for server_name, console in console_items:
                try:
                    if console.save_console_state():
                        saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving console state for {server_name}: {e}")

            if saved_count > 0:
                logger.debug(f"Saved {saved_count} console states")
            return saved_count

        except Exception as e:
            logger.error(f"Error saving all console states: {e}")
            return 0

    def cleanup_all_consoles(self):
        # Cleanup all consoles
        try:
            with self.lock:
                console_items = list(self.consoles.items())

            for server_name, console in console_items:
                try:
                    # Save console state before closing (for crash recovery)
                    console.save_console_state()
                    console.force_close_window()
                except Exception as e:
                    logger.error(f"Error closing console window {server_name}: {e}")

            with self.lock:
                self.consoles.clear()
            logger.debug("All consoles cleaned up")

        except Exception as e:
            logger.error(f"Error cleaning up consoles: {e}")

    def show_console_manager_window(self, parent=None):
        # Show console manager window
        try:
            if parent:
                window = tk.Toplevel(parent)
            else:
                window = tk.Tk()

            window.title("Console Manager")
            window.geometry("700x500")

            main_frame = ttk.Frame(window, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Console list
            list_frame = ttk.LabelFrame(main_frame, text="Active Consoles", padding=5)
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

            # Treeview
            columns = ("server", "status", "pid", "window")
            tree = ttk.Treeview(list_frame, columns=columns, show="headings")
            tree.heading("server", text="Server Name")
            tree.heading("status", text="Status")
            tree.heading("pid", text="Process ID")
            tree.heading("window", text="Console Window")

            tree.column("server", width=150, minwidth=100)
            tree.column("status", width=80, minwidth=60)
            tree.column("pid", width=80, minwidth=60)
            tree.column("window", width=120, minwidth=80)

            scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)

            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Buttons
            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack(fill=tk.X)

            def show_selected():
                selection = tree.selection()
                if selection:
                    server_name = tree.item(selection[0])['values'][0]
                    self.show_console(server_name)

            def kill_selected():
                selection = tree.selection()
                if selection:
                    server_name = tree.item(selection[0])['values'][0]
                    if messagebox.askyesno("Kill Process",
                                         f"Are you sure you want to forcefully kill the process for '{server_name}'?\n\nThis action cannot be undone and may cause data loss.",
                                         parent=window):
                        if self.kill_process(server_name):
                            messagebox.showinfo("Success", f"Process for '{server_name}' has been killed.", parent=window)
                            refresh_list()
                        else:
                            messagebox.showerror("Error", f"Failed to kill process for '{server_name}'.", parent=window)
                else:
                    messagebox.showwarning("No Selection", "Please select a console from the list.", parent=window)

            def force_close_selected():
                selection = tree.selection()
                if selection:
                    server_name = tree.item(selection[0])['values'][0]
                    if messagebox.askyesno("Force Close Console",
                                         f"Are you sure you want to forcefully close the console window for '{server_name}'?\n\nThis will close the console window but the server process may still be running.",
                                         parent=window):
                        if self.force_close_console(server_name):
                            messagebox.showinfo("Success", f"Console window for '{server_name}' has been force closed.", parent=window)
                            refresh_list()
                        else:
                            messagebox.showerror("Error", f"Failed to force close console for '{server_name}'.", parent=window)
                else:
                    messagebox.showwarning("No Selection", "Please select a console from the list.", parent=window)

            def refresh_list():
                tree.delete(*tree.get_children())
                with self.lock:
                    for server_name, console in self.consoles.items():
                        status = "Active" if console.is_active else "Inactive"
                        pid = console.process.pid if console.process else "N/A"
                        window_status = "Open" if console.window and console.window.winfo_exists() else "Closed"
                        tree.insert("", "end", values=(server_name, status, pid, window_status))

            ttk.Button(btn_frame, text="Show Console", command=show_selected).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Kill Process", command=kill_selected).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Force Close Console", command=force_close_selected).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Refresh", command=refresh_list).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Close", command=window.destroy).pack(side=tk.RIGHT)

            # Initial refresh
            refresh_list()

            # Auto-refresh every 5 seconds
            def auto_refresh():
                if window.winfo_exists():
                    refresh_list()
                    window.after(5000, auto_refresh)

            window.after(5000, auto_refresh)

        except Exception as e:
            logger.error(f"Error showing console manager window: {e}")

