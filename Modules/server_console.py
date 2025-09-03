# Real-time server console interface with interactive command support

# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import time
import queue
import logging
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import psutil

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import logging functions
from Modules.server_logging import get_dashboard_logger

# Get logger
logger = get_dashboard_logger()


class RealTimeConsole:
    # Real-time console for individual server process with interactive command support
    
    def __init__(self, server_name, server_config):
        self.server_name = server_name
        self.server_config = server_config
        self.process = None
        self.is_active = False
        
        # GUI components
        self.window = None
        self.text_widget = None
        self.command_entry = None
        
        # Threading components
        self.output_thread = None
        self.error_thread = None
        self.input_thread = None
        self.log_monitor_thread = None  # Additional thread for log file monitoring
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
        
    def attach_to_process(self, process):
        # Attach console to an existing process object
        try:
            if not process:
                logger.error(f"Cannot attach console to {self.server_name}: No process provided")
                return False
                
            self.process = process
            self.is_active = True
            self.stop_event.clear()
            
            # Open log files if specified
            self._open_log_files()
            
            # Add session start message
            self._add_output(f"=== Console attached to {self.server_name} (PID: {process.pid}) ===", "system")
            
            # Start monitoring threads
            self._start_monitoring_threads()
            
            logger.info(f"Console attached to {self.server_name} (PID: {process.pid})")
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
    
    def _start_monitoring_threads(self):
        # Start all monitoring threads
        try:
            # Start stdout monitoring
            if self.process and hasattr(self.process, 'stdout') and self.process.stdout:
                self.output_thread = threading.Thread(
                    target=self._monitor_stdout,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stdout"
                )
                self.output_thread.start()
            
            # Start stderr monitoring (only if not redirected to stdout)
            if self.process and hasattr(self.process, 'stderr') and self.process.stderr and self.process.stderr != self.process.stdout:
                self.error_thread = threading.Thread(
                    target=self._monitor_stderr,
                    daemon=True,
                    name=f"Console-{self.server_name}-Stderr"
                )
                self.error_thread.start()
            
            # Start command input handler
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
                    if self.process and hasattr(self.process, 'stdout') and self.process.stdout:
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
                                elif self.process.poll() is not None:
                                    # Process has ended
                                    break
                                else:
                                    # Small sleep to prevent excessive CPU usage
                                    time.sleep(0.01)
                            except Exception as e:
                                logger.debug(f"Windows stdout read error: {e}")
                                time.sleep(0.1)
                        else:
                            # Unix systems - use select for non-blocking reads
                            try:
                                import select
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
                                    if self.process.poll() is not None:
                                        break
                            except ImportError:
                                # Fallback without select
                                line = self.process.stdout.readline()
                                if line:
                                    line = line.strip()
                                    if line:
                                        self._add_output(line, "stdout")
                                        if self.stdout_log:
                                            self.stdout_log.write(f"{datetime.now().isoformat()} {line}\n")
                                            self.stdout_log.flush()
                                elif self.process.poll() is not None:
                                    break
                                else:
                                    time.sleep(0.05)
                    else:
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
                    if self.process and hasattr(self.process, 'stderr') and self.process.stderr:
                        # Use select/poll for non-blocking reads if available
                        try:
                            import select
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
                                    if self.process.poll() is not None:
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
                                elif self.process.poll() is not None:
                                    break
                                else:
                                    time.sleep(0.05)  # Shorter sleep for more responsive output
                        except ImportError:
                            # Fallback for systems without select
                            line = self.process.stderr.readline()
                            if line:
                                line = line.strip()
                                if line:
                                    self._add_output(line, "stderr")
                                    if self.stderr_log:
                                        self.stderr_log.write(f"{datetime.now().isoformat()} {line}\n")
                                        self.stderr_log.flush()
                            elif self.process.poll() is not None:
                                break
                            else:
                                time.sleep(0.05)
                    else:
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
            logger.debug(f"Started command handler for {self.server_name}")
            
            while self.is_active and not self.stop_event.is_set():
                try:
                    # Wait for command with timeout
                    command = self.command_queue.get(timeout=1.0)
                    
                    if command and self.process and hasattr(self.process, 'stdin') and self.process.stdin:
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
                        except Exception as e:
                            logger.error(f"Error sending command '{command}' to {self.server_name}: {e}")
                    else:
                        logger.warning(f"Cannot send command to {self.server_name}: process or stdin not available")
                    
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
            
            import glob
            for pattern in log_patterns:
                full_pattern = os.path.join(install_dir, pattern)
                for log_file in glob.glob(full_pattern):
                    if os.path.isfile(log_file) and log_file not in self.server_log_paths:
                        self.server_log_paths.append(log_file)
                        # Start from END of file to only show new content from current session
                        try:
                            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                                f.seek(0, 2)  # Seek to end of file
                                self.log_file_positions[log_file] = f.tell()
                        except:
                            self.log_file_positions[log_file] = 0
                        logger.debug(f"Found server log file: {log_file} (starting from end)")
            
        except Exception as e:
            logger.debug(f"Error discovering server logs: {e}")
    
    def _monitor_log_files(self):
        # Monitor additional server log files for output
        try:
            logger.debug(f"Started log file monitoring for {self.server_name}")
            
            while self.is_active and not self.stop_event.is_set():
                try:
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
                    
                    time.sleep(0.5)  # Check log files every 500ms (less frequent than before)
                    
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
    
    def _update_gui_output(self, text, msg_type):
        # Update GUI with new output in thread-safe manner
        try:
            def update():
                if self.text_widget and self.window and self.window.winfo_exists():
                    try:
                        self.text_widget.config(state=tk.NORMAL)
                        self.text_widget.insert(tk.END, text + "\n", msg_type)
                        self.text_widget.see(tk.END)
                        
                        # Limit lines in widget
                        lines = int(self.text_widget.index('end-1c').split('.')[0])
                        if lines > 1000:
                            self.text_widget.delete(1.0, f"{lines-1000}.0")
                        
                        self.text_widget.config(state=tk.DISABLED)
                    except Exception as e:
                        logger.debug(f"GUI update error: {e}")
            
            if self.window:
                self.window.after(0, update)
                
        except Exception as e:
            logger.debug(f"Error scheduling GUI update: {e}")
    
    def send_command(self, command):
        # Send command to server process
        try:
            if self.is_active and command.strip():
                self.command_queue.put(command.strip())
                return True
            return False
        except Exception as e:
            logger.error(f"Error sending command to {self.server_name}: {e}")
            return False
    
    def show_window(self, parent=None):
        # Show the console window
        try:
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
            
            # Button frame
            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack(fill=tk.X)
            
            ttk.Button(btn_frame, text="Clear", command=self._clear_output).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Close", command=self._close_window).pack(side=tk.RIGHT)
            
            # Bind events
            self.command_entry.bind("<Return>", lambda e: self._send_command_gui())
            self.command_entry.bind("<Up>", self._prev_command)
            self.command_entry.bind("<Down>", self._next_command)
            self.window.protocol("WM_DELETE_WINDOW", self._close_window)
            
            # Load existing output
            self._populate_existing_output()
            
            # Focus command entry
            self.command_entry.focus_set()
            
        except Exception as e:
            logger.error(f"Error showing console window for {self.server_name}: {e}")
    
    def _populate_existing_output(self):
        # Populate console with existing output buffer
        try:
            if not self.text_widget:
                return
                
            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.delete(1.0, tk.END)
            
            with self.buffer_lock:
                for entry in self.output_buffer:
                    self.text_widget.insert(tk.END, entry['text'] + "\n", entry['type'])
            
            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)
            
        except Exception as e:
            logger.error(f"Error populating existing output: {e}")
    
    def _send_command_gui(self):
        # Send command from GUI entry
        try:
            if not self.command_entry:
                return
                
            command = self.command_entry.get().strip()
            if command:
                if self.send_command(command):
                    self.command_entry.delete(0, tk.END)
                    self.history_index = -1
                else:
                    messagebox.showwarning("Command Error", "Failed to send command. Server may not be running.")
        except Exception as e:
            logger.error(f"Error sending command from GUI: {e}")
    
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
    
    def _close_window(self):
        # Close console window
        try:
            if self.window:
                self.window.destroy()
                self.window = None
                self.text_widget = None
                self.command_entry = None
        except Exception as e:
            logger.error(f"Error closing console window: {e}")
    
    def detach(self):
        # Detach from process and cleanup
        try:
            logger.info(f"Detaching console from {self.server_name}")
            
            self.is_active = False
            self.stop_event.set()
            
            # Add session end message
            self._add_output(f"=== Console detached from {self.server_name} ===", "system")
            
            # Close log files
            self._close_log_files()
            
            # Wait for threads to finish
            threads = [self.output_thread, self.error_thread, self.input_thread, self.log_monitor_thread]
            for thread in threads:
                if thread and thread.is_alive():
                    thread.join(timeout=2.0)
            
            # Clear process reference
            self.process = None
            
        except Exception as e:
            logger.error(f"Error detaching console from {self.server_name}: {e}")


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
                    logger.info(f"Created console for {server_name}")
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
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    console.show_window(parent)
                    return True
                else:
                    # Try to create console if server exists
                    if self.server_manager:
                        try:
                            server_config = self.server_manager.get_server_config(server_name)
                            if server_config:
                                console = RealTimeConsole(server_name, server_config)
                                self.consoles[server_name] = console
                                console.show_window(parent)
                                return True
                        except Exception as e:
                            logger.warning(f"Could not create console for {server_name}: {e}")
                    
                    messagebox.showerror("Console Error", 
                                       f"No console available for server '{server_name}'. "
                                       f"Please start the server first.")
                    return False
                    
        except Exception as e:
            logger.error(f"Error showing console for {server_name}: {e}")
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
    
    def detach_console(self, server_name):
        # Detach console from server process
        try:
            with self.lock:
                console = self.consoles.get(server_name)
                if console:
                    console.detach()
                    del self.consoles[server_name]
                    logger.info(f"Detached console from {server_name}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error detaching console from {server_name}: {e}")
            return False
    
    def cleanup_all_consoles(self):
        # Cleanup all consoles
        try:
            with self.lock:
                for server_name, console in list(self.consoles.items()):
                    try:
                        console.detach()
                    except Exception as e:
                        logger.error(f"Error detaching console {server_name}: {e}")
                
                self.consoles.clear()
                logger.info("All consoles cleaned up")
                
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
            columns = ("server", "status", "pid")
            tree = ttk.Treeview(list_frame, columns=columns, show="headings")
            tree.heading("server", text="Server Name")
            tree.heading("status", text="Status")  
            tree.heading("pid", text="Process ID")
            
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
            
            def refresh_list():
                tree.delete(*tree.get_children())
                with self.lock:
                    for server_name, console in self.consoles.items():
                        status = "Active" if console.is_active else "Inactive"
                        pid = console.process.pid if console.process else "N/A"
                        tree.insert("", "end", values=(server_name, status, pid))
            
            ttk.Button(btn_frame, text="Show Console", command=show_selected).pack(side=tk.LEFT, padx=(0, 10))
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
