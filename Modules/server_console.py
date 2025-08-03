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
from Modules.logging import get_dashboard_logger

# Get logger
logger = get_dashboard_logger()


class ServerConsole:
    """Manages console interaction for a single server process"""
    
    def __init__(self, server_name, server_config, server_manager=None):
        self.server_name = server_name
        self.server_config = server_config
        self.server_manager = server_manager
        self.process = None
        self.output_queue = queue.Queue()
        self.input_queue = queue.Queue()
        self.output_thread = None
        self.input_thread = None
        self.is_running = False
        self.console_window = None
        self.console_text = None
        self.command_entry = None
        self.command_history = []
        self.history_index = -1
        self.max_output_lines = 1000  # Limit console output to prevent memory issues
        
        # Console output buffer to store recent output
        self.output_buffer = []
        self.max_buffer_lines = 500  # Keep last 500 lines of output
        self.buffer_lock = threading.Lock()
        
        # Real-time output monitoring
        self.monitoring_process = None
        self.log_file_path = None
        self.last_file_position = 0
        
    def _add_to_buffer(self, text, message_type="info"):
        """Add text to the output buffer"""
        try:
            with self.buffer_lock:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.output_buffer.append({
                    'timestamp': timestamp,
                    'text': text.strip(),
                    'type': message_type
                })
                
                # Limit buffer size
                if len(self.output_buffer) > self.max_buffer_lines:
                    self.output_buffer.pop(0)
                    
        except Exception as e:
            logger.error(f"Error adding to output buffer for {self.server_name}: {e}")
    
    def _get_server_log_file(self):
        """Get the log file path for the server"""
        try:
            server_type = self.server_config.get('type', '').lower()
            
            if server_type == 'minecraft':
                # Minecraft servers typically log to logs/latest.log
                install_dir = self.server_config.get('install_dir', '')
                if install_dir and os.path.exists(install_dir):
                    log_file = os.path.join(install_dir, 'logs', 'latest.log')
                    if os.path.exists(log_file):
                        return log_file
                    
                    # Alternative locations
                    alt_log_files = [
                        os.path.join(install_dir, 'server.log'),
                        os.path.join(install_dir, 'logs', 'server.log'),
                        os.path.join(install_dir, 'minecraft_server.log')
                    ]
                    
                    for alt_log in alt_log_files:
                        if os.path.exists(alt_log):
                            return alt_log
            
            elif server_type == 'steam':
                # Steam servers may have different log locations
                install_dir = self.server_config.get('install_dir', '')
                if install_dir and os.path.exists(install_dir):
                    # Common Steam server log patterns
                    possible_logs = [
                        os.path.join(install_dir, 'logs', 'console.log'),
                        os.path.join(install_dir, 'console.log'),
                        os.path.join(install_dir, 'server.log'),
                        os.path.join(install_dir, 'srcds.log'),
                        os.path.join(install_dir, 'logs', 'srcds.log')
                    ]
                    
                    for log_file in possible_logs:
                        if os.path.exists(log_file):
                            return log_file
            
            else:
                # Other server types - check common log locations
                install_dir = self.server_config.get('install_dir', '')
                if install_dir and os.path.exists(install_dir):
                    common_logs = [
                        os.path.join(install_dir, 'server.log'),
                        os.path.join(install_dir, 'console.log'),
                        os.path.join(install_dir, 'logs', 'server.log'),
                        os.path.join(install_dir, 'logs', 'console.log')
                    ]
                    
                    for log_file in common_logs:
                        if os.path.exists(log_file):
                            return log_file
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding log file for {self.server_name}: {e}")
            return None
    
    def _load_recent_output(self):
        """Load recent output from log file or process"""
        try:
            # First, try to get output from log file
            log_file = self._get_server_log_file()
            if log_file and os.path.exists(log_file):
                self._load_from_log_file(log_file)
                return True
            
            # If no log file, try to get output from running process
            if self.process and self.process.is_running():
                self._add_to_buffer(f"Connected to running {self.server_config.get('type', 'Unknown')} server process (PID: {self.process.pid})", "info")
                return True
            
            # No recent output available
            self._add_to_buffer(f"No recent console output available for {self.server_name}", "warning")
            self._add_to_buffer("Console monitoring will start when the server begins outputting new messages.", "info")
            return False
            
        except Exception as e:
            logger.error(f"Error loading recent output for {self.server_name}: {e}")
            self._add_to_buffer(f"Error loading recent output: {str(e)}", "error")
            return False
    
    def _load_from_log_file(self, log_file):
        """Load recent lines from log file"""
        try:
            # Read last N lines from file
            lines_to_read = min(100, self.max_buffer_lines // 2)  # Read last 100 lines or half buffer
            
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Go to end of file
                f.seek(0, 2)
                file_size = f.tell()
                
                # Read chunks from end to find last N lines
                lines = []
                buffer_size = 8192
                pos = file_size
                
                while len(lines) < lines_to_read and pos > 0:
                    # Calculate chunk size
                    chunk_size = min(buffer_size, pos)
                    pos -= chunk_size
                    
                    # Read chunk
                    f.seek(pos)
                    chunk = f.read(chunk_size)
                    
                    # Split into lines and prepend to our list
                    chunk_lines = chunk.split('\n')
                    if pos > 0:
                        # First line might be incomplete, remove it
                        chunk_lines = chunk_lines[1:]
                    
                    lines = chunk_lines + lines
                
                # Keep only the last N lines and remove empty lines
                recent_lines = [line.strip() for line in lines[-lines_to_read:] if line.strip()]
                
                # Add to buffer with appropriate message types
                for line in recent_lines:
                    message_type = self._classify_log_message(line)
                    self._add_to_buffer(line, message_type)
                
                # Store file position for monitoring
                self.last_file_position = file_size
                self.log_file_path = log_file
                
                logger.info(f"Loaded {len(recent_lines)} recent log lines for {self.server_name}")
                
        except Exception as e:
            logger.error(f"Error reading log file {log_file}: {e}")
            self._add_to_buffer(f"Error reading log file: {str(e)}", "error")
    
    def _classify_log_message(self, message):
        """Classify log message type based on content"""
        message_lower = message.lower()
        
        # Error patterns
        if any(pattern in message_lower for pattern in ['error', 'exception', 'failed', 'crash', 'fatal']):
            return "error"
        
        # Warning patterns
        if any(pattern in message_lower for pattern in ['warn', 'warning', 'deprecated', 'outdated']):
            return "warning"
        
        # Command patterns (for Minecraft)
        if any(pattern in message for pattern in ['issued server command:', '] used command:', 'Command used:']):
            return "command"
        
        # Info patterns
        if any(pattern in message_lower for pattern in ['info', 'starting', 'started', 'loaded', 'enabled', 'done']):
            return "info"
        
        return "default"  # Default message type
        
    def start_console(self, process=None):
        """Start console monitoring for a server process"""
        try:
            if process:
                self.process = process
            else:
                # Try to find the process by name/PID
                self.process = self._find_server_process()
            
            # Load recent output before starting monitoring
            self._load_recent_output()
            
            if not self.process:
                logger.warning(f"No process found for server {self.server_name}")
                # Still return True to allow console window to open for log monitoring
                self.is_running = True
                
                # Start log file monitoring if available
                if self.log_file_path:
                    self.output_thread = threading.Thread(
                        target=self._monitor_log_file,
                        daemon=True,
                        name=f"Console-LogMonitor-{self.server_name}"
                    )
                    self.output_thread.start()
                
                return True
            
            self.is_running = True
            
            # Start output monitoring thread
            self.output_thread = threading.Thread(
                target=self._monitor_output_combined,
                daemon=True,
                name=f"Console-Output-{self.server_name}"
            )
            self.output_thread.start()
            
            # Start input handling thread
            self.input_thread = threading.Thread(
                target=self._handle_input,
                daemon=True,
                name=f"Console-Input-{self.server_name}"
            )
            self.input_thread.start()
            
            logger.info(f"Console started for server {self.server_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start console for {self.server_name}: {e}")
            return False
        """Start console monitoring for a server process"""
        try:
            if process:
                self.process = process
            else:
                # Try to find the process by name/PID
                self.process = self._find_server_process()
            
            if not self.process:
                logger.warning(f"No process found for server {self.server_name}")
                return False
            
            self.is_running = True
            
            # Start output monitoring thread
            self.output_thread = threading.Thread(
                target=self._monitor_output,
                daemon=True,
                name=f"Console-Output-{self.server_name}"
            )
            self.output_thread.start()
            
            # Start input handling thread
            self.input_thread = threading.Thread(
                target=self._handle_input,
                daemon=True,
                name=f"Console-Input-{self.server_name}"
            )
            self.input_thread.start()
            
            logger.info(f"Console started for server {self.server_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start console for {self.server_name}: {e}")
            return False
    
    def stop_console(self):
        """Stop console monitoring"""
        try:
            self.is_running = False
            
            # Close console window if open
            if self.console_window:
                self.console_window.destroy()
                self.console_window = None
            
            # Wait for threads to finish
            if self.output_thread and self.output_thread.is_alive():
                self.output_thread.join(timeout=2.0)
            
            if self.input_thread and self.input_thread.is_alive():
                self.input_thread.join(timeout=2.0)
            
            logger.info(f"Console stopped for server {self.server_name}")
            
        except Exception as e:
            logger.error(f"Error stopping console for {self.server_name}: {e}")
    
    def send_command(self, command):
        """Send a command to the server process"""
        try:
            if not self.is_running:
                logger.warning(f"Cannot send command to {self.server_name}: console not running")
                return False
            
            # Add to command history
            if command.strip() and (not self.command_history or self.command_history[-1] != command.strip()):
                self.command_history.append(command.strip())
                # Limit history size
                if len(self.command_history) > 100:
                    self.command_history.pop(0)
            
            # Add command to buffer
            self._add_to_buffer(f"> {command.strip()}", "command")
            
            # Queue the command for input thread
            self.input_queue.put(command + '\n')
            
            # Log the command
            logger.info(f"Command sent to {self.server_name}: {command.strip()}")
            
            # Update console display if window is open
            if self.console_text:
                self._append_to_console(f"> {command.strip()}\n", "command")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send command to {self.server_name}: {e}")
            return False
    
    def show_console_window(self, parent=None):
        """Show the console window for this server"""
        try:
            if self.console_window and self.console_window.winfo_exists():
                # Window already exists, just bring it to front
                self.console_window.lift()
                self.console_window.focus_force()
                return
            
            # Create new console window
            self.console_window = tk.Toplevel(parent)
            self.console_window.title(f"Server Console - {self.server_name}")
            self.console_window.geometry("800x600")
            
            # Create main frame
            main_frame = ttk.Frame(self.console_window, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Server info frame
            info_frame = ttk.LabelFrame(main_frame, text="Server Information", padding=5)
            info_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Server details
            ttk.Label(info_frame, text=f"Name: {self.server_name}", font=("Consolas", 9)).pack(anchor=tk.W)
            server_type = self.server_config.get('type', 'Unknown')
            ttk.Label(info_frame, text=f"Type: {server_type}", font=("Consolas", 9)).pack(anchor=tk.W)
            
            if self.process:
                try:
                    process_info = psutil.Process(self.process.pid)
                    ttk.Label(info_frame, text=f"PID: {self.process.pid}", font=("Consolas", 9)).pack(anchor=tk.W)
                    ttk.Label(info_frame, text=f"Status: {process_info.status()}", font=("Consolas", 9)).pack(anchor=tk.W)
                except:
                    ttk.Label(info_frame, text="Process: Not Available", font=("Consolas", 9)).pack(anchor=tk.W)
            
            # Console output frame
            console_frame = ttk.LabelFrame(main_frame, text="Console Output", padding=5)
            console_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            
            # Create console text widget with scrollbar
            self.console_text = scrolledtext.ScrolledText(
                console_frame,
                font=("Consolas", 9),
                bg="black",
                fg="white",
                insertbackground="white",
                state=tk.DISABLED,
                wrap=tk.WORD
            )
            self.console_text.pack(fill=tk.BOTH, expand=True)
            
            # Configure text tags for different message types
            self.console_text.tag_configure("command", foreground="#90EE90")  # Light green
            self.console_text.tag_configure("error", foreground="#FF6B6B")    # Light red
            self.console_text.tag_configure("warning", foreground="#FFD93D")  # Yellow
            self.console_text.tag_configure("info", foreground="#74C0FC")     # Light blue
            
            # Command input frame
            input_frame = ttk.LabelFrame(main_frame, text="Command Input", padding=5)
            input_frame.pack(fill=tk.X)
            
            # Command entry
            self.command_entry = ttk.Entry(input_frame, font=("Consolas", 9))
            self.command_entry.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 5))
            
            # Send button
            send_button = ttk.Button(input_frame, text="Send", command=self._on_send_command, width=8)
            send_button.pack(side=tk.RIGHT)
            
            # Bind events
            self.command_entry.bind("<Return>", lambda e: self._on_send_command())
            self.command_entry.bind("<Up>", self._on_history_up)
            self.command_entry.bind("<Down>", self._on_history_down)
            self.console_window.protocol("WM_DELETE_WINDOW", self._on_console_close)
            
            # Focus on command entry
            self.command_entry.focus_set()
            
            # Start console monitoring if not already running
            if not self.is_running:
                self.start_console()
            
            # Display recent output from buffer
            self._display_buffered_output()
            
            # Add separator and current session message
            self._append_to_console("=" * 60 + "\n", "info")
            self._append_to_console(f"Console session started for {self.server_name}\n", "info")
            self._append_to_console("Type commands below and press Enter to send them to the server.\n", "info")
            self._append_to_console("Use Up/Down arrow keys to navigate command history.\n", "info")
            
            if self.log_file_path:
                self._append_to_console(f"Monitoring log file: {os.path.basename(self.log_file_path)}\n", "info")
            
            self._append_to_console("=" * 60 + "\n\n", "info")
            
            logger.info(f"Console window opened for {self.server_name}")
            
        except Exception as e:
            logger.error(f"Failed to show console window for {self.server_name}: {e}")
            messagebox.showerror("Console Error", f"Failed to open console window:\n{str(e)}")
    
    def _display_buffered_output(self):
        """Display recent output from the buffer in the console"""
        try:
            if not self.console_text:
                return
            
            with self.buffer_lock:
                if not self.output_buffer:
                    self._append_to_console("No recent console output available.\n", "warning")
                    return
                
                # Add header for recent output
                self._append_to_console("=" * 60 + "\n", "info")
                self._append_to_console("RECENT CONSOLE OUTPUT\n", "info")
                self._append_to_console("=" * 60 + "\n", "info")
                
                # Display buffered output
                for entry in self.output_buffer:
                    formatted_line = f"[{entry['timestamp']}] {entry['text']}\n"
                    self._append_to_console(formatted_line, entry['type'])
            
        except Exception as e:
            logger.error(f"Error displaying buffered output for {self.server_name}: {e}")
    
    def _find_server_process(self):
        """Find the server process by PID or executable name"""
        try:
            # Try to get PID from server manager or config
            pid = None
            if self.server_manager:
                server_status = self.server_manager.get_server_status(self.server_name)
                if server_status and server_status.get('pid'):
                    pid = server_status['pid']
            
            if not pid and 'pid' in self.server_config:
                pid = self.server_config['pid']
            
            if pid:
                try:
                    process = psutil.Process(pid)
                    if process.is_running():
                        return process
                except psutil.NoSuchProcess:
                    pass
            
            # Try to find by executable name
            executable_name = self._get_server_executable_name()
            if executable_name:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.info['name'] and executable_name.lower() in proc.info['name'].lower():
                            return proc
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding process for {self.server_name}: {e}")
            return None
    
    def _monitor_log_file(self):
        """Monitor log file for new output"""
        try:
            if not self.log_file_path or not os.path.exists(self.log_file_path):
                return
            
            while self.is_running:
                try:
                    with open(self.log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        # Seek to last position
                        f.seek(self.last_file_position)
                        
                        # Read new lines
                        new_lines = f.readlines()
                        
                        if new_lines:
                            for line in new_lines:
                                line = line.strip()
                                if line:
                                    message_type = self._classify_log_message(line)
                                    self._add_to_buffer(line, message_type)
                                    
                                    # Update console display if window is open
                                    if self.console_text:
                                        self._append_to_console(line + '\n', message_type)
                            
                            # Update file position
                            self.last_file_position = f.tell()
                    
                    time.sleep(0.5)  # Check every 0.5 seconds
                    
                except FileNotFoundError:
                    # Log file might have been rotated or deleted
                    time.sleep(2)
                    continue
                except Exception as e:
                    logger.error(f"Error monitoring log file for {self.server_name}: {e}")
                    time.sleep(2)
                    
        except Exception as e:
            logger.error(f"Log file monitoring thread error for {self.server_name}: {e}")
    
    def _monitor_output_combined(self):
        """Monitor both process output and log file"""
        try:
            # Start log file monitoring in parallel if available
            log_monitor_thread = None
            if self.log_file_path:
                log_monitor_thread = threading.Thread(
                    target=self._monitor_log_file,
                    daemon=True,
                    name=f"Console-LogFile-{self.server_name}"
                )
                log_monitor_thread.start()
            
            # Monitor process if available
            while self.is_running and self.process:
                try:
                    # Check if process is still alive
                    if not self.process.is_running():
                        self._add_to_buffer("Server process has stopped", "warning")
                        if self.console_text:
                            self._append_to_console("\n[Server process has stopped]\n", "warning")
                        break
                    
                    # For now, we rely primarily on log file monitoring
                    # In future, this could be enhanced to capture stdout/stderr if process was started appropriately
                    time.sleep(2)
                    
                except psutil.NoSuchProcess:
                    self._add_to_buffer("Server process no longer exists", "error")
                    if self.console_text:
                        self._append_to_console("\n[Server process no longer exists]\n", "error")
                    break
                except Exception as e:
                    logger.error(f"Error monitoring process output for {self.server_name}: {e}")
                    time.sleep(2)
            
        except Exception as e:
            logger.error(f"Combined output monitoring thread error for {self.server_name}: {e}")
        finally:
            self.is_running = False
    
    def _get_server_executable_name(self):
        """Get the expected executable name for the server type"""
        server_type = self.server_config.get('type', '').lower()
        
        if server_type == 'minecraft':
            return 'java'  # Minecraft servers run with Java
        elif server_type == 'steam':
            # Get the executable from app ID or server config
            app_id = self.server_config.get('appId')
            if app_id:
                # Common Steam server executables
                steam_executables = {
                    '740': 'srcds',      # Counter-Strike: Global Offensive
                    '232250': 'srcds',   # Team Fortress 2
                    '4020': 'srcds',     # Garry's Mod
                    '90': 'hlds',        # Half-Life 1
                    '440': 'srcds',      # Team Fortress 2
                }
                return steam_executables.get(str(app_id), 'srcds')
            return 'srcds'
        else:
            # For other server types, try to get from config
            executable = self.server_config.get('executable', '')
            if executable:
                return os.path.basename(executable)
        
        return None
    
    def _monitor_output(self):
        """Legacy method - now redirects to combined monitoring"""
        self._monitor_output_combined()
    
    def _handle_input(self):
        """Handle input commands in a separate thread"""
        try:
            while self.is_running:
                try:
                    # Get command from queue (blocking with timeout)
                    command = self.input_queue.get(timeout=1.0)
                    
                    if self.process and self.process.is_running():
                        # For console input, we would need the process to have been
                        # started with stdin=subprocess.PIPE
                        # This implementation assumes we'll extend server startup
                        # to support console input
                        logger.info(f"Would send command to {self.server_name}: {command.strip()}")
                    
                    self.input_queue.task_done()
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error handling input for {self.server_name}: {e}")
            
        except Exception as e:
            logger.error(f"Input handling thread error for {self.server_name}: {e}")
    
    def _append_to_console(self, text, tag=None):
        """Append text to the console display"""
        if not self.console_text:
            return
        
        try:
            # Enable text widget for editing
            self.console_text.config(state=tk.NORMAL)
            
            # Add timestamp
            timestamp = datetime.now().strftime("[%H:%M:%S] ")
            
            # Insert timestamp
            self.console_text.insert(tk.END, timestamp)
            
            # Insert text with tag
            if tag:
                self.console_text.insert(tk.END, text, tag)
            else:
                self.console_text.insert(tk.END, text)
            
            # Limit the number of lines to prevent memory issues
            lines = self.console_text.get("1.0", tk.END).split('\n')
            if len(lines) > self.max_output_lines:
                # Remove oldest lines
                excess_lines = len(lines) - self.max_output_lines
                self.console_text.delete("1.0", f"{excess_lines + 1}.0")
            
            # Disable text widget and scroll to bottom
            self.console_text.config(state=tk.DISABLED)
            self.console_text.see(tk.END)
            
        except Exception as e:
            logger.error(f"Error appending to console for {self.server_name}: {e}")
    
    def _on_send_command(self):
        """Handle send command button/enter key"""
        try:
            if not self.command_entry:
                return
                
            command = self.command_entry.get().strip()
            if command:
                self.send_command(command)
                self.command_entry.delete(0, tk.END)
                self.history_index = -1  # Reset history index
            
        except Exception as e:
            logger.error(f"Error sending command for {self.server_name}: {e}")
    
    def _on_history_up(self, event):
        """Handle up arrow key for command history"""
        try:
            if not self.command_entry or not self.command_history:
                return
                
            if self.history_index == -1:
                self.history_index = len(self.command_history) - 1
            elif self.history_index > 0:
                self.history_index -= 1
            
            if 0 <= self.history_index < len(self.command_history):
                self.command_entry.delete(0, tk.END)
                self.command_entry.insert(0, self.command_history[self.history_index])
            
        except Exception as e:
            logger.error(f"Error handling history up for {self.server_name}: {e}")
    
    def _on_history_down(self, event):
        """Handle down arrow key for command history"""
        try:
            if not self.command_entry or not self.command_history:
                return
                
            if self.history_index < len(self.command_history) - 1:
                self.history_index += 1
                self.command_entry.delete(0, tk.END)
                self.command_entry.insert(0, self.command_history[self.history_index])
            else:
                self.history_index = -1
                self.command_entry.delete(0, tk.END)
            
        except Exception as e:
            logger.error(f"Error handling history down for {self.server_name}: {e}")
    
    def _on_console_close(self):
        """Handle console window close event"""
        try:
            if self.console_window:
                self.console_window.destroy()
            self.console_window = None
            self.console_text = None
            self.command_entry = None
            logger.info(f"Console window closed for {self.server_name}")
            
        except Exception as e:
            logger.error(f"Error closing console window for {self.server_name}: {e}")


class ServerConsoleManager:
    """Manages multiple server consoles"""
    
    def __init__(self, server_manager=None):
        self.server_manager = server_manager
        self.consoles = {}  # server_name -> ServerConsole
        self.active_console_windows = {}  # server_name -> window reference
        self.monitoring_interval = 1.0  # Check for new servers every second
        self.monitoring_thread = None
        self.is_monitoring = False
        
    def start_monitoring(self):
        """Start monitoring for server processes"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitoring_thread = threading.Thread(
                target=self._monitor_servers,
                daemon=True,
                name="ServerConsoleMonitoring"
            )
            self.monitoring_thread.start()
    
    def stop_monitoring(self):
        """Stop monitoring for server processes"""
        self.is_monitoring = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=2.0)
    
    def _monitor_servers(self):
        """Monitor for new server processes and update existing consoles"""
        while self.is_monitoring:
            try:
                if self.server_manager:
                    # Get list of running servers
                    running_servers = self.server_manager.get_running_servers()
                    
                    for server_name in running_servers:
                        if server_name not in self.consoles:
                            # Auto-create console for new running server
                            server_config = self.server_manager.get_server_config(server_name)
                            if server_config:
                                self.get_console(server_name, server_config)
                
                time.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Error in server console monitoring: {e}")
                time.sleep(5)  # Wait longer on error
    
    def get_console(self, server_name, server_config=None):
        """Get or create a console for a server"""
        try:
            if server_name not in self.consoles:
                if not server_config and self.server_manager:
                    server_config = self.server_manager.get_server_config(server_name)
                
                if not server_config:
                    logger.error(f"No server config found for {server_name}")
                    return None
                
                self.consoles[server_name] = ServerConsole(
                    server_name, 
                    server_config, 
                    self.server_manager
                )
            
            return self.consoles[server_name]
            
        except Exception as e:
            logger.error(f"Error getting console for {server_name}: {e}")
            return None
    
    def show_console(self, server_name, server_config=None, parent=None):
        """Show console window for a server"""
        try:
            console = self.get_console(server_name, server_config)
            if console:
                console.show_console_window(parent)
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error showing console for {server_name}: {e}")
            messagebox.showerror("Console Error", f"Failed to show console:\n{str(e)}")
            return False
    
    def send_command_to_server(self, server_name, command):
        """Send a command to a specific server"""
        try:
            if server_name in self.consoles:
                return self.consoles[server_name].send_command(command)
            else:
                logger.warning(f"No console found for server {server_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending command to {server_name}: {e}")
            return False
    
    def close_console(self, server_name):
        """Close console for a specific server"""
        try:
            if server_name in self.consoles:
                self.consoles[server_name].stop_console()
                del self.consoles[server_name]
            
            if server_name in self.active_console_windows:
                del self.active_console_windows[server_name]
            
        except Exception as e:
            logger.error(f"Error closing console for {server_name}: {e}")
    
    def close_all_consoles(self):
        """Close all server consoles"""
        try:
            # Stop monitoring first
            self.stop_monitoring()
            
            for server_name in list(self.consoles.keys()):
                self.close_console(server_name)
            
        except Exception as e:
            logger.error(f"Error closing all consoles: {e}")
    
    def get_active_consoles(self):
        """Get list of servers with active consoles"""
        return list(self.consoles.keys())


def create_console_window(server_name, server_config, server_manager=None, parent=None):
    """Convenience function to create and show a console window"""
    try:
        console = ServerConsole(server_name, server_config, server_manager)
        console.show_console_window(parent)
        return console
        
    except Exception as e:
        logger.error(f"Error creating console window for {server_name}: {e}")
        messagebox.showerror("Console Error", f"Failed to create console window:\n{str(e)}")
        return None


def send_command_to_server_console(server_name, command, console_manager):
    """Convenience function to send a command to a server console"""
    try:
        if console_manager:
            return console_manager.send_command_to_server(server_name, command)
        return False
        
    except Exception as e:
        logger.error(f"Error sending command to {server_name}: {e}")
        return False
