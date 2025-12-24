# Server console interface
# - Real-time output, command input
# - Named pipes, stdin relay, command queue
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
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import psutil

# Windows named pipe support
_NAMED_PIPES_AVAILABLE = False
_WIN32_CONSOLE_AVAILABLE = False
if sys.platform == 'win32':
    try:
        import win32pipe
        import win32file
        import pywintypes
        _NAMED_PIPES_AVAILABLE = True
    except ImportError:
        pass
    
    # Console API for attached process input
    try:
        import ctypes
        from ctypes import wintypes
        
        ATTACH_PARENT_PROCESS = -1
        STD_INPUT_HANDLE = -10
        
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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_logging

# Stdin relay for persistent command input
_STDIN_RELAY_AVAILABLE = False
try:
    from services.stdin_relay import send_command_via_relay
    _STDIN_RELAY_AVAILABLE = True
except ImportError:
    pass

# File-based command queue
_COMMAND_QUEUE_AVAILABLE = False
try:
    from services.command_queue import queue_command, is_relay_active, start_command_relay
    _COMMAND_QUEUE_AVAILABLE = True
except ImportError:
    pass

logger = setup_module_logging("ServerConsole")


class RealTimeConsole:
    # Real-time console for individual server process
    
    def __init__(self, server_name, server_config):
        self.server_name = server_name
        self.server_config = server_config
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
        self.max_buffer_size = 1000
        
        # Log file handles and monitoring
        self.stdout_log = None
        self.stderr_log = None
        self.server_log_paths = []  # Additional server-specific log files to monitor
        self.log_file_positions = {}  # Track positions in log files
        self._force_log_refresh = threading.Event()  # Signal to force immediate log refresh
        
        # State persistence for crash recovery
        self._state_file_path = self._get_state_file_path()
        self._last_state_save_count = 0  # Track buffer size at last save
        self._state_save_interval = 10  # Save state every 10 seconds
        
        # Named pipe for IPC command sending (Windows only)
        self._pipe_name = self._get_pipe_name()
        self._pipe_handle = None
        self._pipe_listener_thread = None
        self._pipe_server_active = False
        self._is_reattached = False  # True if console was reattached to existing process
    
    def _get_pipe_name(self):
        # Get the named pipe name for this server (Windows only)
        try:
            # Sanitize server name for pipe name
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in self.server_name)
            return f"\\\\.\\pipe\\ServerManager_{safe_name}_Console"
        except Exception as e:
            logger.error(f"Error getting pipe name for {self.server_name}: {e}")
            return None
    
    def _get_state_file_path(self):
        # Get the path to the console state file for this server
        try:
            # Use the temp directory in the server manager directory
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            temp_dir = os.path.join(script_dir, "temp", "console_states")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Sanitize server name for filename
            safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in self.server_name)
            safe_name = safe_name.replace(' ', '_')
            
            return os.path.join(temp_dir, f"{safe_name}_console_state.json")
        except Exception as e:
            logger.error(f"Error getting state file path for {self.server_name}: {e}")
            return None
    
    def save_console_state(self):
        # Save current console state to file for crash recovery
        try:
            if not self._state_file_path:
                return False
            
            with self.buffer_lock:
                # Only save if there's new content
                current_count = len(self.output_buffer)
                if current_count == self._last_state_save_count and current_count > 0:
                    return True  # No changes, skip save
                
                state = {
                    'server_name': self.server_name,
                    'timestamp': datetime.now().isoformat(),
                    'process_id': self.process.pid if self.process and hasattr(self.process, 'pid') else None,
                    'is_active': self.is_active,
                    'output_buffer': self.output_buffer[-self.max_buffer_size:],  # Save last max_buffer_size entries
                    'command_history': self.command_history[-100:],  # Save last 100 commands
                }
            
            # Write to temp file first, then rename for atomic write
            temp_file = self._state_file_path + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, default=str)
            
            # Atomic rename
            if os.path.exists(self._state_file_path):
                os.remove(self._state_file_path)
            os.rename(temp_file, self._state_file_path)
            
            self._last_state_save_count = current_count
            logger.debug(f"Saved console state for {self.server_name} ({current_count} entries)")
            return True
            
        except Exception as e:
            logger.error(f"Error saving console state for {self.server_name}: {e}")
            return False
    
    def load_console_state(self):
        # Load console state from file (for crash recovery)
        try:
            if not self._state_file_path or not os.path.exists(self._state_file_path):
                return False
            
            # Check if state file is recent (within last hour)
            file_age = time.time() - os.path.getmtime(self._state_file_path)
            if file_age > 3600:  # 1 hour
                logger.debug(f"Console state file for {self.server_name} is too old ({file_age:.0f}s), skipping")
                return False
            
            with open(self._state_file_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            # Verify this state is for the same server
            if state.get('server_name') != self.server_name:
                logger.warning(f"Console state file mismatch for {self.server_name}")
                return False
            
            # Load command history
            self.command_history = state.get('command_history', [])
            
            # Load output buffer
            saved_buffer = state.get('output_buffer', [])
            if saved_buffer:
                with self.buffer_lock:
                    # Clear existing buffer and load saved state
                    self.output_buffer = saved_buffer
                    self._last_state_save_count = len(self.output_buffer)
                
                logger.debug(f"Loaded console state for {self.server_name} ({len(saved_buffer)} entries)")
                return True
            
            return False
            
        except json.JSONDecodeError as e:
            logger.warning(f"Corrupt console state file for {self.server_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading console state for {self.server_name}: {e}")
            return False
    
    def _start_state_save_thread(self):
        # Start periodic state saving thread
        try:
            if self.state_save_thread and self.state_save_thread.is_alive():
                return  # Already running
            
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
        # Periodically save console state
        try:
            while self.is_active and not self.stop_event.is_set():
                # Wait for the save interval
                if self.stop_event.wait(timeout=self._state_save_interval):
                    break  # Stop event was set
                
                # Save state
                if self.is_active:
                    self.save_console_state()
                    
        except Exception as e:
            logger.error(f"Error in periodic state save for {self.server_name}: {e}")
    
    def clear_console_state(self):
        # Remove the console state file (called when server is properly stopped)
        try:
            if self._state_file_path and os.path.exists(self._state_file_path):
                os.remove(self._state_file_path)
                logger.debug(f"Cleared console state file for {self.server_name}")
        except Exception as e:
            logger.error(f"Error clearing console state file for {self.server_name}: {e}")
    
    def cleanup_on_server_stop(self):
        # Clean up console when server is properly stopped (not crashed)
        # This clears state and buffer so old data doesn't persist
        try:
            self.is_active = False
            pid = self.process.pid if self.process and hasattr(self.process, 'pid') else 'Unknown'
            
            # Clear the console state file - we don't want to restore old state
            self.clear_console_state()
            
            # Clear the output buffer
            with self.buffer_lock:
                self.output_buffer.clear()
            
            # Clear command history
            self.command_history.clear()
            
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
        """Start named pipe server for IPC command input (Windows only)"""
        if not _NAMED_PIPES_AVAILABLE or not self._pipe_name:
            return False
            
        try:
            if self._pipe_server_active:
                return True  # Already running
            
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
        """Stop named pipe server"""
        try:
            self._pipe_server_active = False
            if self._pipe_handle:
                try:
                    win32file.CloseHandle(self._pipe_handle)
                except:
                    pass
                self._pipe_handle = None
            logger.debug(f"Stopped named pipe server for {self.server_name}")
        except Exception as e:
            logger.debug(f"Error stopping pipe server for {self.server_name}: {e}")
    
    def _pipe_server_loop(self):
        """Named pipe server loop - listens for commands and forwards to process stdin"""
        if not _NAMED_PIPES_AVAILABLE:
            return
            
        try:
            while self._pipe_server_active and self.is_active and not self.stop_event.is_set():
                try:
                    # Create named pipe server
                    pipe_name = self._pipe_name if self._pipe_name else f"\\\\.\\pipe\\servermanager_{self.server_name}"
                    self._pipe_handle = win32pipe.CreateNamedPipe(  # type: ignore[arg-type]
                        pipe_name,
                        win32pipe.PIPE_ACCESS_INBOUND,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        1,  # Max instances
                        4096,  # Out buffer size
                        4096,  # In buffer size
                        0,  # Default timeout
                        None  # Security attributes
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
                        if e.winerror == 535:  # ERROR_PIPE_CONNECTED - client already connected
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
                            if e.winerror == 109:  # ERROR_BROKEN_PIPE
                                break  # Client disconnected
                            elif e.winerror == 232:  # ERROR_NO_DATA
                                time.sleep(0.1)
                                continue
                            else:
                                raise
                    
                    # Close this instance of the pipe
                    try:
                        win32pipe.DisconnectNamedPipe(self._pipe_handle)
                        win32file.CloseHandle(self._pipe_handle)
                    except:
                        pass
                    self._pipe_handle = None
                    
                except pywintypes.error as e:
                    if e.winerror == 231:  # ERROR_PIPE_BUSY
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
                except:
                    pass
                self._pipe_handle = None
    
    def _send_command_via_pipe(self, command):
        """Send command to server via named pipe (for reattached consoles)"""
        if not _NAMED_PIPES_AVAILABLE or not self._pipe_name:
            return False
            
        try:
            # Connect to named pipe as client
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_WRITE,
                0,  # No sharing
                None,  # Default security
                win32file.OPEN_EXISTING,
                0,  # Default attributes
                None  # No template file
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
            if e.winerror == 2:  # ERROR_FILE_NOT_FOUND - pipe doesn't exist
                logger.debug(f"Named pipe not available for {self.server_name}, will try alternative method")
            else:
                logger.error(f"Error sending command via pipe to {self.server_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending command via pipe to {self.server_name}: {e}")
            return False
    
    def _send_command_via_console_api(self, command):
        """Send command to reattached process via Windows Console API (AttachConsole)"""
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
                
                # Create INPUT_RECORD structures for each character
                # This simulates keyboard input to the console
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
            except:
                pass
            return False
        
    def attach_to_process(self, process):
        # Attach console to an existing process object (subprocess.Popen or psutil.Process)
        try:
            logger.debug(f"DEBUG: Attempting to attach console to process for {self.server_name}")
            if not process:
                logger.error(f"Cannot attach console to {self.server_name}: No process provided")
                return False
            
            # Detect if this is a reattachment (psutil.Process) vs original start (subprocess.Popen)
            # subprocess.Popen has 'poll' method, psutil.Process has 'is_running' method
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
            # This allows future reattachments to send commands via the pipe
            if not self._is_reattached and _NAMED_PIPES_AVAILABLE:
                self._start_pipe_server()
            elif self._is_reattached:
                # Inform user about command input capabilities for reattached servers
                if _COMMAND_QUEUE_AVAILABLE and is_relay_active(self.server_name):
                    self._add_output(f"=== Console reattached - command input available via command queue ===", "system")
                elif _STDIN_RELAY_AVAILABLE:
                    self._add_output(f"=== Console reattached - attempting to use stdin relay ===", "system")
                else:
                    self._add_output(f"=== Console reattached - command input requires server restart ===", "system")
            
            logger.debug(f"Console attached to {self.server_name} (PID: {pid}, reattached={self._is_reattached})")
            return True
            
        except Exception as e:
            logger.error(f"Error attaching console to {self.server_name}: {e}")
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
                        os.kill(pid, 0)  # Signal 0 just checks if process exists
                        return True
                except (OSError, AttributeError, ProcessLookupError):
                    return False
        except Exception as e:
            logger.debug(f"Error checking if process is running: {e}")
            return False
    
    def _start_monitoring_threads(self):
        # Start all monitoring threads
        try:
            # Start stdout monitoring if process has stdout (subprocess.Popen style)
            if self.process and hasattr(self.process, 'stdout') and self.process.stdout:
                self.output_thread = threading.Thread(
                    target=self._monitor_stdout,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stdout"
                )
                self.output_thread.start()
            
            # Start stderr monitoring (only if not redirected to stdout and has stderr)
            if (self.process and hasattr(self.process, 'stderr') and self.process.stderr and 
                self.process.stderr != self.process.stdout):
                self.error_thread = threading.Thread(
                    target=self._monitor_stderr,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stderr"
                )
                self.error_thread.start()
            
            # Start command input handler (only if process has stdin)
            if self.process and hasattr(self.process, 'stdin') and self.process.stdin:
                self.input_thread = threading.Thread(
                    target=self._handle_commands,
                    daemon=True,
                    name=f"Console-{self.server_name}-Input"
                )
                self.input_thread.start()
            
            # Start log file monitoring for additional output capture
            self._discover_server_logs()
            if self.server_log_paths:
                self.log_monitor_thread = threading.Thread(
                    target=self._monitor_log_files,
                    daemon=True,
                    name=f"Console-{self.server_name}-LogMonitor"
                )
                self.log_monitor_thread.start()
            
        except Exception as e:
            logger.error(f"Error starting monitoring threads for {self.server_name}: {e}")
    
    def _monitor_stdout(self):
        # Monitor stdout from server process
        try:
            logger.debug(f"Started stdout monitoring for {self.server_name}")
            
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
                                            self.stdout_log.write(f"{datetime.now().isoformat()} {line}\n")
                                            self.stdout_log.flush()
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
                        else:
                            # Unix systems - use select for non-blocking reads
                            try:
                                ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                                if ready:
                                    line = self.process.stdout.readline()
                                    if line:
                                        line = line.strip()
                                        if line:
                                            self._add_output(line, "stdout")
                                            if self.stdout_log:
                                                self.stdout_log.write(f"{datetime.now().isoformat()} {line}\n")
                                                self.stdout_log.flush()
                                else:
                                    # Check if process ended
                                    if not self._is_process_running():
                                        self._handle_process_termination()
                                        break
                            except (OSError, ValueError, AttributeError, select.error) as e:
                                # Process stdout became invalid or select failed
                                logger.debug(f"Stdout monitoring failed for {self.server_name}: {e}")
                                self._handle_process_termination()
                                break
                    else:
                        # Check if process ended
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
                                                self.stderr_log.write(f"{datetime.now().isoformat()} {line}\n")
                                                self.stderr_log.flush()
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
                                            self.stderr_log.write(f"{datetime.now().isoformat()} {line}\n")
                                            self.stderr_log.flush()
                                elif not self._is_process_running():
                                    self._handle_process_termination()
                                    break
                                else:
                                    time.sleep(0.05)  # Shorter sleep for more responsive output
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
            logger.debug(f"DEBUG: Starting command handler for {self.server_name}")
            
            while self.is_active and not self.stop_event.is_set():
                try:
                    # Wait for command with timeout
                    command = self.command_queue.get(timeout=1.0)
                    logger.debug(f"DEBUG: Retrieved command from queue for {self.server_name}: '{command}'")
                    
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
            
            # Note: Config log files are handled separately in _load_historical_output
            # We don't add them to server_log_paths to avoid duplication
            
            # Then discover additional log files in the install directory
            install_dir = self.server_config.get('InstallDir', '')
            if not install_dir or not os.path.exists(install_dir):
                return
            
            # Common server log file patterns
            log_patterns = [
                'logs/*.log',
                'logs/*.txt', 
                '*.log',
                'console.log',
                'server.log',
                'srcds.log',
                'debug.log',
                'l4d2/logs/*.log',  # L4D2 specific
                'left4dead2/logs/*.log',  # L4D2 specific
                'addons/sourcemod/logs/*.log'  # SourceMod logs
            ]
            
            for pattern in log_patterns:
                full_pattern = os.path.join(install_dir, pattern)
                for log_file in glob.glob(full_pattern):
                    if os.path.isfile(log_file) and log_file not in self.server_log_paths:
                        # Skip config log files to avoid duplication
                        if log_file == stdout_path or log_file == stderr_path:
                            continue
                        self.server_log_paths.append(log_file)
                        logger.debug(f"Found server log file: {log_file}")
            
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
                    
                    for log_file in self.server_log_paths:
                        try:
                            if os.path.exists(log_file):
                                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                                    # Seek to last known position
                                    f.seek(self.log_file_positions.get(log_file, 0))
                                    
                                    # Read new lines
                                    new_lines = []
                                    for line in f:
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
                                    
                                    # Update position
                                    self.log_file_positions[log_file] = f.tell()
                        except Exception as e:
                            logger.debug(f"Error reading log file {log_file}: {e}")
                    
                    # Wait for next cycle, but respond to force refresh quickly
                    # Use shorter wait intervals and check for force refresh signal
                    if self._force_log_refresh.wait(timeout=0.1):
                        # Force refresh was signaled - clear it and continue immediately
                        self._force_log_refresh.clear()
                        continue
                    # Otherwise wait a bit more (total ~500ms between checks normally)
                    for _ in range(4):
                        if self._force_log_refresh.wait(timeout=0.1):
                            self._force_log_refresh.clear()
                            break
                    
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
            if 'Command:' in line and 'srcds.exe' in line:
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
        except:
            return False
    
    def _add_output(self, text, msg_type="info"):
        # Add output to buffer and update GUI
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_text = f"[{timestamp}] {text}"
            
            with self.buffer_lock:
                self.output_buffer.append({
                    'text': formatted_text,
                    'type': msg_type,
                    'timestamp': timestamp
                })
                
                # Maintain buffer size
                if len(self.output_buffer) > self.max_buffer_size:
                    self.output_buffer.pop(0)
            
            # Update GUI if window is open
            if self.window and self.text_widget:
                self._update_gui_output(formatted_text, msg_type)
                
        except Exception as e:
            logger.debug(f"Error adding output for {self.server_name}: {e}")
    
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
        # Start periodic status updates
        try:
            def update_status():
                try:
                    if self.window and self.window.winfo_exists() and hasattr(self, 'status_label'):
                        self.status_label.config(text=self._get_status_text())
                        
                        # Enable/disable command input based on process status
                        is_running = self.process and self._is_process_running()
                        if hasattr(self, 'command_entry') and self.command_entry:
                            self.command_entry.config(state=tk.NORMAL if is_running else tk.DISABLED)
                        
                        # Schedule next update
                        self.window.after(2000, update_status)  # Update every 2 seconds
                except tk.TclError:
                    # Window was destroyed
                    pass
                except Exception as e:
                    logger.debug(f"Error updating status: {e}")
            
            # Start the update cycle
            if self.window and self.window.winfo_exists():
                self.window.after(1000, update_status)  # First update after 1 second
                
        except Exception as e:
            logger.debug(f"Error starting status updates: {e}")
    
    def _update_gui_output(self, text, msg_type):
        # Update GUI with new output in thread-safe manner
        try:
            def update():
                try:
                    # Double-check window exists before updating
                    if (self.window and self.window.winfo_exists() and 
                        self.text_widget and hasattr(self.text_widget, 'config')):
                        self.text_widget.config(state=tk.NORMAL)
                        self.text_widget.insert(tk.END, text + "\n", msg_type)
                        self.text_widget.see(tk.END)
                        
                        # Limit lines in widget
                        lines = int(self.text_widget.index('end-1c').split('.')[0])
                        if lines > 1000:
                            self.text_widget.delete(1.0, f"{lines-1000}.0")
                        
                        self.text_widget.config(state=tk.DISABLED)
                    # If window doesn't exist, silently ignore
                except tk.TclError:
                    # Window was destroyed, ignore
                    pass
                except Exception as e:
                    logger.debug(f"GUI update error: {e}")
            
            # Check window exists before scheduling update
            if self.window and self.window.winfo_exists():
                try:
                    self.window.after(0, update)
                except tk.TclError:
                    # Window was destroyed between check and after() call
                    pass
            # If no window, silently ignore
                
        except Exception as e:
            logger.debug(f"Error scheduling GUI update: {e}")
    
    def send_command(self, command):
        # Send command to server process
        try:
            logger.debug(f"DEBUG: send_command called for {self.server_name} with command: '{command}'")
            if not self.is_active:
                logger.warning(f"DEBUG: Console not active for {self.server_name}")
                return False
            if not command.strip():
                logger.warning(f"DEBUG: Empty command for {self.server_name}")
                return False
            
            command = command.strip()
            
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
                logger.debug(f"DEBUG: Attempting to send command to reattached console {self.server_name}")
                
                # Method 1: Try command queue first (file-based, works if relay is running)
                if _COMMAND_QUEUE_AVAILABLE:
                    logger.debug(f"DEBUG: Trying command queue for {self.server_name}")
                    if is_relay_active(self.server_name):
                        success, message = queue_command(self.server_name, command)
                        if success:
                            logger.info(f"Command queued for {self.server_name}: {command}")
                            on_command_sent()
                            return True
                        else:
                            logger.debug(f"Command queue failed for {self.server_name}: {message}")
                    else:
                        logger.debug(f"No command queue relay active for {self.server_name}")
                
                # Method 2: Try stdin relay (named pipe maintained since server start)
                if _STDIN_RELAY_AVAILABLE:
                    logger.debug(f"DEBUG: Trying stdin relay for {self.server_name}")
                    try:
                        success, message = send_command_via_relay(self.server_name, command)
                        if success:
                            logger.info(f"Command sent via stdin relay to {self.server_name}: {command}")
                            on_command_sent()
                            return True
                        else:
                            logger.debug(f"Stdin relay failed for {self.server_name}: {message}")
                    except Exception as e:
                        logger.debug(f"Stdin relay error for {self.server_name}: {e}")
                
                # Method 3: Try the console's own named pipe (if server was started by Server Manager)
                if _NAMED_PIPES_AVAILABLE:
                    if self._send_command_via_pipe(command):
                        on_command_sent()
                        return True
                
                # Method 4: Try Windows Console API (AttachConsole) - rarely works for hidden console apps
                if _WIN32_CONSOLE_AVAILABLE:
                    logger.debug(f"DEBUG: Trying Console API for {self.server_name}")
                    if self._send_command_via_console_api(command):
                        on_command_sent()
                        return True
                
                # All methods failed
                logger.warning(f"Failed to send command to reattached server {self.server_name}")
                self._add_output(f"[WARN] Cannot send commands to this server - console input is only available for servers started in the current session.", "error")
                self._add_output(f"[INFO] To enable console commands, stop and restart the server through the dashboard.", "info")
                return False
            
            # Normal path: send via command queue (for processes with stdin)
            logger.debug(f"DEBUG: Console is active for {self.server_name}, sending via command queue")
            self.command_queue.put(command)
            return True
            
        except Exception as e:
            logger.error(f"Error sending command to {self.server_name}: {e}")
            import traceback
            logger.error(f"DEBUG: send_command error traceback: {traceback.format_exc()}")
            return False
    
    def show_window(self, parent=None):
        # Show the console window
        try:
            logger.debug(f"DEBUG: Attempting to show console window for {self.server_name}")
            if self.window and self.window.winfo_exists():
                self.window.lift()
                self.window.focus_set()
                return
            
            # Create window
            if parent:
                self.window = tk.Toplevel(parent)
            else:
                self.window = tk.Tk()
            
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
            
            # Text widget with scrollbar
            self.text_widget = scrolledtext.ScrolledText(
                output_frame,
                wrap=tk.WORD,
                font=("Consolas", 10),
                bg="black",
                fg="white",
                state=tk.DISABLED
            )
            self.text_widget.pack(fill=tk.BOTH, expand=True)
            
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
            
            ttk.Button(btn_frame, text="Clear", command=self._clear_output).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Kill Process", command=self._kill_process_gui).pack(side=tk.LEFT, padx=(0, 10))
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
            
            logger.debug(f"DEBUG: Console window created successfully for {self.server_name}")
            
        except Exception as e:
            logger.error(f"Error showing console window for {self.server_name}: {e}")
            import traceback
            logger.error(f"DEBUG: Console window creation traceback: {traceback.format_exc()}")
    
    def _populate_existing_output(self):
        # Populate console with existing output buffer and historical log data
        try:
            if not self.text_widget:
                return
                
            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.delete(1.0, tk.END)
            
            # Only load historical output if buffer is empty (first time)
            with self.buffer_lock:
                if not self.output_buffer:
                    self._load_historical_output()
            
            # Add current buffer output
            with self.buffer_lock:
                for entry in self.output_buffer:
                    self.text_widget.insert(tk.END, entry['text'] + "\n", entry['type'])
            
            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)
            
        except Exception as e:
            logger.error(f"Error populating existing output: {e}")
    
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
            
            # Load from additional server log files (discovered in install directory)
            for log_file in self.server_log_paths:
                if os.path.exists(log_file):
                    self._load_log_file(log_file, "stdout")
                    
        except Exception as e:
            logger.debug(f"Error loading historical output: {e}")
    
    def _load_log_file(self, log_file_path, msg_type):
        # Load output from a specific log file
        try:
            # Check file size first - skip if too large to prevent memory issues
            file_size = os.path.getsize(log_file_path)
            if file_size > 10 * 1024 * 1024:  # 10MB limit
                logger.debug(f"Skipping historical load for large log file: {log_file_path} ({file_size} bytes)")
                return
                
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read lines more efficiently - don't load entire file for large files
                if file_size > 1024 * 1024:  # For files > 1MB, seek to approximate end
                    # Estimate position for last ~1000 lines (assuming average 100 chars per line)
                    estimated_lines_size = 100 * 1000
                    if file_size > estimated_lines_size:
                        f.seek(file_size - estimated_lines_size)
                        # Skip first line as it might be partial
                        f.readline()
                
                lines = f.readlines()
                
                # Only load the last 500 lines to avoid overwhelming the console
                # but ensure we get recent output
                if len(lines) > 500:
                    lines = lines[-500:]
                
                for line in lines:
                    line = line.strip()
                    if line:
                        # Skip repetitive startup messages and old entries
                        if self._is_old_log_entry(line):
                            continue
                            
                        # Format as historical entry
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        formatted_text = f"[{timestamp}] [HISTORY] {line}"
                        
                        # Add to buffer
                        with self.buffer_lock:
                            self.output_buffer.append({
                                'text': formatted_text,
                                'type': msg_type,
                                'timestamp': timestamp
                            })
                            
                            # Maintain buffer size
                            if len(self.output_buffer) > self.max_buffer_size:
                                self.output_buffer.pop(0)
                        
                        # Update GUI if available
                        if self.text_widget and self.window and self.window.winfo_exists():
                            self.text_widget.insert(tk.END, formatted_text + "\n", msg_type)
                            
                # Update the log file position to the end of the file for future monitoring
                # This ensures we don't re-read the historical data
                f.seek(0, 2)  # Seek to end
                self.log_file_positions[log_file_path] = f.tell()
                            
        except Exception as e:
            logger.debug(f"Error loading log file {log_file_path}: {e}")
    
    def _send_command_gui(self):
        # Send command from GUI entry
        try:
            logger.debug(f"DEBUG: Attempting to send command from GUI for {self.server_name}")
            if not self.command_entry:
                logger.warning(f"DEBUG: No command entry widget for {self.server_name}")
                return
                
            command = self.command_entry.get().strip()
            if command:
                logger.debug(f"DEBUG: Sending command '{command}' to {self.server_name}")
                if self.send_command(command):
                    self.command_entry.delete(0, tk.END)
                    self.history_index = -1
                else:
                    logger.warning(f"DEBUG: Failed to send command to {self.server_name}")
                    # Enhanced error message for stopped servers
                    if not self.process:
                        messagebox.showwarning("Command Error", f"Cannot send commands to '{self.server_name}' - no server process is running.\n\nPlease start the server first.")
                    else:
                        messagebox.showwarning("Command Error", "Failed to send command. Server may not be running.")
        except Exception as e:
            logger.error(f"Error sending command from GUI: {e}")
            import traceback
            logger.error(f"DEBUG: Command GUI error traceback: {traceback.format_exc()}")
    
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
            # This clears state file and buffer so old data doesn't persist
            self.cleanup_on_server_stop()
            
            logger.info(f"Process {self.server_name} (PID: {pid}) was forcefully killed and console cleaned up")
            
            return True
            
        except Exception as e:
            logger.error(f"Error killing process for {self.server_name}: {e}")
            return False


class ConsoleManager:
    # Manages multiple server consoles
    
    def __init__(self, server_manager=None):
        self.server_manager = server_manager
        self.consoles = {}  # server_name -> RealTimeConsole
        self.lock = threading.Lock()
        
    def create_console(self, server_name, server_config):
        # Create a new console for a server
        try:
            with self.lock:
                if server_name not in self.consoles:
                    console = RealTimeConsole(server_name, server_config) 
                    self.consoles[server_name] = console
                    logger.debug(f"Created console for {server_name}")
                    return console
                else:
                    return self.consoles[server_name]
        except Exception as e:
            logger.error(f"Error creating console for {server_name}: {e}")
            return None
    
    def attach_console_to_process(self, server_name, process, server_config=None):
        # Attach console to a running process
        try:
            with self.lock:
                # Get or create console
                console = self.consoles.get(server_name)
                if not console:
                    if not server_config and self.server_manager:
                        server_config = self.server_manager.get_server_config(server_name)
                    
                    if server_config:
                        console = RealTimeConsole(server_name, server_config)
                        self.consoles[server_name] = console
                    else:
                        logger.error(f"No server config available for {server_name}")
                        return False
                
                # Attach to process
                return console.attach_to_process(process)
                
        except Exception as e:
            logger.error(f"Error attaching console to process for {server_name}: {e}")
            return False
    
    def show_console(self, server_name, parent=None):
        # Show console window for a server
        try:
            logger.debug(f"DEBUG: show_console called for server: {server_name}")
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    logger.debug(f"DEBUG: Found existing console for {server_name}")
                    console.show_window(parent)
                    return True
                else:
                    logger.debug(f"DEBUG: No existing console for {server_name}, attempting to create one")
                    # Try to create console if server exists
                    if self.server_manager:
                        try:
                            server_config = self.server_manager.get_server_config(server_name)
                            if server_config:
                                logger.debug(f"DEBUG: Got server config for {server_name}, creating console")
                                console = RealTimeConsole(server_name, server_config)
                                self.consoles[server_name] = console
                                console.show_window(parent)
                                return True
                            else:
                                logger.warning(f"DEBUG: No server config found for {server_name}")
                        except Exception as e:
                            logger.warning(f"Could not create console for {server_name}: {e}")
                    
                    logger.error(f"DEBUG: Failed to create console for {server_name}")
                    messagebox.showerror("Console Error", 
                                       f"No console available for server '{server_name}'. "
                                       f"Please start the server first.")
                    return False
                    
        except Exception as e:
            logger.error(f"Error showing console for {server_name}: {e}")
            import traceback
            logger.error(f"DEBUG: show_console error traceback: {traceback.format_exc()}")
            return False
    
    def send_command(self, server_name, command):
        # Send command to server console
        try:
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    return console.send_command(command)
                else:
                    logger.warning(f"No console available for {server_name}")
                    return False
        except Exception as e:
            logger.error(f"Error sending command to {server_name}: {e}")
            return False
    
    def kill_process(self, server_name):
        # Kill the process for a specific server console
        try:
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    return console.kill_process()
                else:
                    logger.warning(f"No console available for {server_name} to kill process")
                    return False
        except Exception as e:
            logger.error(f"Error killing process for {server_name}: {e}")
            return False
    
    def cleanup_console_on_stop(self, server_name):
        # Clean up a console when a server is properly stopped
        # This clears state file and buffer so old PIDs don't cause issues
        try:
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    console.cleanup_on_server_stop()
                    logger.debug(f"Cleaned up console for {server_name} on server stop")
                    return True
                else:
                    # No console exists, but try to clear any leftover state file
                    # by creating a temporary console just to clear state
                    try:
                        temp_console = RealTimeConsole(server_name, {})
                        temp_console.clear_console_state()
                        logger.debug(f"Cleared leftover console state for {server_name}")
                    except Exception:
                        pass
                    return False
        except Exception as e:
            logger.error(f"Error cleaning up console for {server_name}: {e}")
            return False
    
    def force_close_console(self, server_name):
        # Force close console window for a specific server
        try:
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    return console.force_close_window()
                else:
                    logger.warning(f"No console available for {server_name} to force close")
                    return False
        except Exception as e:
            logger.error(f"Error force closing console for {server_name}: {e}")
            return False
    
    def save_all_console_states(self):
        # Save states for all active consoles (for dashboard close/crash recovery)
        try:
            with self.lock:
                saved_count = 0
                for server_name, console in list(self.consoles.items()):
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
                for server_name, console in list(self.consoles.items()):
                    try:
                        # Save console state before closing (for crash recovery)
                        console.save_console_state()
                        console.force_close_window()
                    except Exception as e:
                        logger.error(f"Error closing console window {server_name}: {e}")
                
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
                    self.show_console(server_name, window)
            
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


# For backward compatibility - alias the new classes to the old names
ServerConsole = RealTimeConsole
ServerConsoleManager = ConsoleManager