# Debug manager - diagnostics GUI
import os
import sys
import subprocess
import time
import platform
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import traceback
import ctypes
import psutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path, setup_module_logging, is_admin
setup_module_path()

try:
    from debug.debug import DebugManager as CoreDebugManager
    from Modules.server_logging import get_debug_logger
    debug_manager = CoreDebugManager()
    logger = get_debug_logger("debug-manager")
except Exception:
    logger = setup_module_logging("DebugManager")
    debug_manager = None


def run_as_admin():
    # Elevate to admin
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

class DebugManagerGUI:
    # - Debug centre UI
    # - Log viewer, diagnostics
    def __init__(self, root):
        self.root = root
        self.root.title("Server Manager - Debug Centre")
        self.root.geometry("600x400")
        self.root.minsize(600, 400)
        
        from Modules.common import REGISTRY_PATH
        self.registry_path = REGISTRY_PATH
        self.server_manager_dir = None
        self.paths = {}
        
        self.initialise()
        
        # Set up UI
        self.create_ui()
    
    def initialise(self):
        # Init paths/config from registry
        try:
            from Modules.common import get_server_manager_dir
            self.server_manager_dir = get_server_manager_dir()
            
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "Modules"),
                "debug": os.path.join(self.server_manager_dir, "logs", "debug")
            }
            
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            logger.info(f"Init complete. SM dir: {self.server_manager_dir}")
            
            if debug_manager:
                debug_manager.set_debug_mode(True)
                
            return True
            
        except Exception as e:
            logger.error(f"Init failed: {str(e)}")
            messagebox.showerror("Init Error", f"Failed to initialise: {str(e)}")
            return False
    
    def create_ui(self):
        # Create the UI elements
        self.create_system_group()
        self.create_misc_group()
    
    def create_system_group(self):
        # Create system group box
        system_frame = ttk.LabelFrame(self.root, text="System")
        system_frame.grid(row=0, column=0, padx=20, pady=10, sticky="nsew")
        
        # System info button
        system_info_btn = ttk.Button(system_frame, text="System Information", 
                                      command=self.show_system_information)
        system_info_btn.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # System refresh button
        system_refresh_btn = ttk.Button(system_frame, text="Update System Info", 
                                        command=self.update_system_information)
        system_refresh_btn.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        # System logs button
        system_logs_btn = ttk.Button(system_frame, text="View System Logs", 
                                     command=self.view_system_logs)
        system_logs_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
    
    def create_misc_group(self):
        # Create miscellaneous group box
        misc_frame = ttk.LabelFrame(self.root, text="Miscellaneous")
        misc_frame.grid(row=0, column=1, rowspan=2, padx=20, pady=10, sticky="nsew")
        
        # Full diagnostics button
        full_diag_btn = ttk.Button(misc_frame, text="Full Diagnostics", 
                                   command=self.run_full_diagnostics)
        full_diag_btn.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Debug log toggle
        self.debug_var = tk.BooleanVar(value=debug_manager.is_debug_enabled() if debug_manager else False)
        debug_check = ttk.Checkbutton(misc_frame, text="Enable Debug Logging", 
                                     variable=self.debug_var, command=self.toggle_debug)
        debug_check.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        # Close button
        close_btn = ttk.Button(misc_frame, text="Close Debug Center", 
                              command=self.root.destroy)
        close_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        
        # Configure grid weights
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
    
    def toggle_debug(self):
        # Toggle debug logging mode
        if debug_manager:
            if self.debug_var.get():
                debug_manager.set_debug_mode(True)
                messagebox.showinfo("Debug Mode", "Debug logging is now enabled.")
            else:
                debug_manager.set_debug_mode(False)
                messagebox.showinfo("Debug Mode", "Debug logging is now disabled.")
    
    def show_system_information(self):
        # Show system information window
        info_window = tk.Toplevel(self.root)
        info_window.title("System Information")
        info_window.geometry("600x500")
        info_window.grab_set()
        
        # Create text box for info display
        info_text = scrolledtext.ScrolledText(info_window, wrap=tk.WORD, font=("Consolas", 10))
        info_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Get system info
        try:
            if debug_manager:
                # Use the debug module to get system info
                system_info = debug_manager.get_system_info()
                
                # Format system information with proper error handling
                if isinstance(system_info, dict):
                    system_data = system_info.get('system', {})
                    cpu_data = system_info.get('cpu', {})
                    memory_data = system_info.get('memory', {})
                    disk_data = system_info.get('disk', {})
                    network_data = system_info.get('network', {})
                    
                    # Ensure all data are dictionaries
                    if not isinstance(system_data, dict):
                        system_data = {}
                    if not isinstance(cpu_data, dict):
                        cpu_data = {}
                    if not isinstance(memory_data, dict):
                        memory_data = {}
                    if not isinstance(disk_data, dict):
                        disk_data = {}
                    if not isinstance(network_data, dict):
                        network_data = {}
                    
                    system_info_text = f"""SYSTEM INFORMATION
-----------------
Computer Name: {platform.node()}
OS: {system_data.get('system', 'Unknown')} {system_data.get('release', 'Unknown')}
Version: {system_data.get('version', 'Unknown')}

HARDWARE
--------
CPU: {system_data.get('processor', 'Unknown')}
Cores: {cpu_data.get('physical_cores', 'Unknown')} physical, {cpu_data.get('logical_cores', 'Unknown')} logical
CPU Usage: {cpu_data.get('cpu_percent', 'Unknown')}%
RAM: {round(float(memory_data.get('total', 0)) / (1024**3), 2)} GB ({round(float(memory_data.get('available', 0)) / (1024**3), 2)} GB available)

STORAGE
-------
Total: {round(float(disk_data.get('total', 0)) / (1024**3), 2)} GB
Free: {round(float(disk_data.get('free', 0)) / (1024**3), 2)} GB
Usage: {disk_data.get('percent', 'Unknown')}%

NETWORK
-------
Bytes Sent: {network_data.get('bytes_sent', 'Unknown')}
Bytes Received: {network_data.get('bytes_recv', 'Unknown')}
"""
                else:
                    system_info_text = "Error: Unable to retrieve system information from debug module\n"
            else:
                # Fallback to direct psutil calls
                # OS info
                os_name = platform.system()
                os_version = platform.version()
                os_release = platform.release()
                
                # CPU info
                cpu_info = platform.processor()
                cpu_count = psutil.cpu_count(logical=False)
                cpu_threads = psutil.cpu_count(logical=True)
                
                # Memory info
                memory = psutil.virtual_memory()
                memory_total = round(memory.total / (1024**3), 2)
                memory_available = round(memory.available / (1024**3), 2)
                
                # Disk info
                disk_usage = psutil.disk_usage('/')
                
                system_info_text = f"""SYSTEM INFORMATION
-----------------
Computer Name: {platform.node()}
OS: {os_name} {os_release}
Version: {os_version}

HARDWARE
--------
CPU: {cpu_info}
Cores: {cpu_count} physical, {cpu_threads} logical
RAM: {memory_total} GB ({memory_available} GB available)

STORAGE
-------
Total: {round(disk_usage.total / (1024**3), 2)} GB
Free: {round(disk_usage.free / (1024**3), 2)} GB
Usage: {disk_usage.percent}%
"""

            # Insert text
            info_text.insert(tk.END, system_info_text)
            
        except Exception as e:
            error_text = f"Error gathering system information: {str(e)}\n\n{traceback.format_exc()}"
            info_text.insert(tk.END, error_text)
        
        # Close button
        close_btn = ttk.Button(info_window, text="Close", command=info_window.destroy)
        close_btn.pack(pady=10)
    
    def update_system_information(self):
        # Update system information
        # Create progress window
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Updating System Information")
        progress_window.geometry("400x150")
        progress_window.grab_set()
        
        # Progress message
        message_label = ttk.Label(progress_window, 
                                text="Refreshing system information and diagnostics. This may take a moment...")
        message_label.pack(pady=20)
        
        # Progress bar
        progress_bar = ttk.Progressbar(progress_window, mode="indeterminate")
        progress_bar.pack(fill=tk.X, padx=20, pady=10)
        progress_bar.start()
        
        # Simulate updating system info
        def do_update():
            time.sleep(2)  # Give time for any system data to refresh
            
            # Close progress window and show updated info
            progress_window.destroy()
            self.show_system_information()
        
        # Run update in separate thread
        self.root.after(100, do_update)
    
    def view_system_logs(self):
        # View system logs
        # Try to get log directory from registry
        log_path = self.paths["logs"]
        
        if not os.path.exists(log_path):
            messagebox.showerror("Error", "Log directory not found")
            return
        
        # Open log directory with system file explorer
        if platform.system() == "Windows":
            os.startfile(log_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", log_path])
        else:  # Linux and other Unix-like systems
            subprocess.Popen(["xdg-open", log_path])
    
    def run_full_diagnostics(self):
        # Run full system diagnostics
        # Create progress window
        diag_window = tk.Toplevel(self.root)
        diag_window.title("Running Full Diagnostics")
        diag_window.geometry("500x400")
        diag_window.grab_set()
        
        # Progress label
        progress_label = ttk.Label(diag_window, text="Running diagnostics, please wait...")
        progress_label.pack(pady=10)
        
        # Progress bar
        progress_bar = ttk.Progressbar(diag_window, length=400, mode="determinate")
        progress_bar.pack(pady=10, padx=20)
        
        # Results text
        results_text = scrolledtext.ScrolledText(diag_window, wrap=tk.WORD, width=60, height=15)
        results_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Close button (initially disabled)
        close_btn = ttk.Button(diag_window, text="Close", command=diag_window.destroy, state=tk.DISABLED)
        close_btn.pack(pady=10)
        
        # Function to run diagnostics
        def run_diagnostics():
            try:
                # Update progress
                progress_bar["value"] = 10
                progress_label.config(text="Running diagnostics: Checking system requirements...")
                diag_window.update()
                
                results_text.insert(tk.END, "Starting diagnostics...\n\n")
                
                # Step 1: System information
                progress_bar["value"] = 20
                progress_label.config(text="Running diagnostics: Gathering system information...")
                diag_window.update()
                time.sleep(0.5)
                
                results_text.insert(tk.END, "--- System Information ---\n", "heading")
                results_text.tag_config("heading", font=("Arial", 10, "bold"))
                
                if debug_manager:
                    try:
                        system_info = debug_manager.get_system_info()
                        if isinstance(system_info, dict):
                            # Get system info safely
                            system_data = system_info.get('system', {})
                            cpu_data = system_info.get('cpu', {})
                            
                            if isinstance(system_data, dict):
                                os_name = system_data.get('system', 'Unknown')
                                os_release = system_data.get('release', 'Unknown')
                                results_text.insert(tk.END, f"OS: {os_name} {os_release}\n")
                            
                            if isinstance(cpu_data, dict):
                                cpu_cores = cpu_data.get('logical_cores', 'Unknown')
                                cpu_percent = cpu_data.get('cpu_percent', 'Unknown')
                                results_text.insert(tk.END, f"CPU: {cpu_cores} cores, {cpu_percent}% used\n")
                            
                            memory_info = system_info.get('memory', {})
                            if isinstance(memory_info, dict):
                                mem_used = memory_info.get('used', 0)
                                mem_total = memory_info.get('total', 0)
                                mem_percent = memory_info.get('percent', 0)
                                if isinstance(mem_used, (int, float)) and isinstance(mem_total, (int, float)):
                                    results_text.insert(tk.END, f"Memory: {round(mem_used / (1024**3), 2)} GB of {round(mem_total / (1024**3), 2)} GB used ({mem_percent}%)\n")
                                else:
                                    results_text.insert(tk.END, "Memory: Information unavailable\n")
                            
                            disk_info = system_info.get('disk', {})
                            if isinstance(disk_info, dict):
                                disk_used = disk_info.get('used', 0)
                                disk_total = disk_info.get('total', 0)
                                disk_percent = disk_info.get('percent', 0)
                                if isinstance(disk_used, (int, float)) and isinstance(disk_total, (int, float)):
                                    results_text.insert(tk.END, f"Disk: {round(disk_used / (1024**3), 2)} GB of {round(disk_total / (1024**3), 2)} GB used ({disk_percent}%)\n\n")
                                else:
                                    results_text.insert(tk.END, "Disk: Information unavailable\n\n")
                        else:
                            results_text.insert(tk.END, "System information unavailable from debug module\n\n")
                    except Exception as e:
                        results_text.insert(tk.END, f"Error getting system info: {str(e)}\n\n")
                else:
                    # Fallback to direct calls
                    mem = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')
                    results_text.insert(tk.END, f"OS: {platform.system()} {platform.release()}\n")
                    results_text.insert(tk.END, f"CPU: {psutil.cpu_count()} cores, {psutil.cpu_percent()}% used\n")
                    results_text.insert(tk.END, f"Memory: {round(mem.used / (1024**3), 2)} GB of {round(mem.total / (1024**3), 2)} GB used ({mem.percent}%)\n")
                    results_text.insert(tk.END, f"Disk: {round(disk.used / (1024**3), 2)} GB of {round(disk.total / (1024**3), 2)} GB used ({disk.percent}%)\n\n")
                
                # Step 2: Installation verification
                progress_bar["value"] = 40
                progress_label.config(text="Running diagnostics: Verifying installation...")
                diag_window.update()
                time.sleep(0.5)
                
                results_text.insert(tk.END, "--- Installation Verification ---\n", "heading")
                
                if self.server_manager_dir and os.path.exists(self.server_manager_dir):
                    results_text.insert(tk.END, f"[OK] Server Manager directory: {self.server_manager_dir}\n", "ok")
                    results_text.tag_config("ok", foreground="green")
                else:
                    results_text.insert(tk.END, f"[ERROR] Server Manager directory not found: {self.server_manager_dir}\n", "error")
                    results_text.tag_config("error", foreground="red")
                
                # Check essential directories
                essential_dirs = ["logs", "config", "servers", "scripts"]
                for dir_name in essential_dirs:
                    if self.server_manager_dir:
                        dir_path = self.paths.get(dir_name, os.path.join(self.server_manager_dir, dir_name))
                    else:
                        dir_path = self.paths.get(dir_name, "")
                    
                    if dir_path and os.path.exists(dir_path) and os.path.isdir(dir_path):
                        results_text.insert(tk.END, f"[OK] {dir_name.capitalize()} directory: {dir_path}\n", "ok")
                    else:
                        results_text.insert(tk.END, f"[ERROR] {dir_name.capitalize()} directory not found: {dir_path}\n", "error")
                
                results_text.insert(tk.END, "\n")
                
                # Step 3: Server check
                progress_bar["value"] = 60
                progress_label.config(text="Running diagnostics: Checking servers...")
                diag_window.update()
                time.sleep(0.5)
                
                results_text.insert(tk.END, "--- Server Status ---\n", "heading")
                
                # Get servers from database
                try:
                    from Modules.Database.server_configs_database import ServerConfigManager
                    manager = ServerConfigManager()
                    all_servers = manager.get_all_servers()
                    
                    if all_servers:
                        results_text.insert(tk.END, f"Found {len(all_servers)} server configuration(s) in database.\n")
                        
                        # Check a few servers
                        for i, server_config in enumerate(all_servers[:3]):  # Check up to 3 servers
                            try:
                                # Ensure server_config is a dictionary
                                if not isinstance(server_config, dict):
                                    results_text.insert(tk.END, f"  - Server {i+1}: Invalid config format\n", "error")
                                    continue
                                    
                                server_name = server_config.get("Name", "Unknown")
                                results_text.insert(tk.END, f"  - {server_name}: ")
                                
                                if debug_manager and hasattr(debug_manager, "get_server_status"):
                                    server_status = debug_manager.get_server_status(server_name)
                                    if isinstance(server_status, dict) and server_status.get("IsRunning", False):
                                        results_text.insert(tk.END, "Running\n", "ok")
                                    else:
                                        results_text.insert(tk.END, "Stopped\n", "warning")
                                        results_text.tag_config("warning", foreground="orange")
                                else:
                                    if "PID" in server_config and server_config["PID"]:
                                        try:
                                            pid = int(server_config["PID"])
                                            if psutil.pid_exists(pid):
                                                results_text.insert(tk.END, "Running\n", "ok")
                                            else:
                                                results_text.insert(tk.END, "Stopped\n", "warning")
                                        except (ValueError, psutil.Error, OSError):
                                            results_text.insert(tk.END, "Unknown\n", "warning")
                                    else:
                                        results_text.insert(tk.END, "Not started\n", "warning")
                            except Exception as e:
                                results_text.insert(tk.END, f"Error reading server config: {str(e)}\n", "error")
                    else:
                        results_text.insert(tk.END, "No server configurations found in database.\n", "warning")
                except Exception as e:
                    results_text.insert(tk.END, f"Error accessing database: {str(e)}\n", "error")
                
                results_text.insert(tk.END, "\n")
                
                # Step 4: Create diagnostic report
                progress_bar["value"] = 80
                progress_label.config(text="Running diagnostics: Creating diagnostic report...")
                diag_window.update()
                time.sleep(0.5)
                
                results_text.insert(tk.END, "--- Diagnostic Report ---\n", "heading")
                
                if debug_manager:
                    try:
                        # Use debug_manager if it provides a create_diagnostic_report method; otherwise skip
                        report_path = None
                        if hasattr(debug_manager, 'create_diagnostic_report'):
                            report_path = debug_manager.create_diagnostic_report()
                        if report_path:
                            results_text.insert(tk.END, f"[OK] Diagnostic report created: {report_path}\n", "ok")
                        else:
                            results_text.insert(tk.END, "[INFO] Diagnostic report feature not available or not created.\n", "warning")
                    except Exception as e:
                        results_text.insert(tk.END, f"[ERROR] Error creating diagnostic report: {str(e)}\n", "error")
                else:
                    results_text.insert(tk.END, "[WARNING] Debug module not available, skipping diagnostic report\n", "warning")
                
                # Final summary
                progress_bar["value"] = 100
                progress_label.config(text="Diagnostics complete")
                diag_window.update()
                
                results_text.insert(tk.END, "\nDiagnostics completed.\n", "heading")
                
                # Enable close button
                close_btn.config(state=tk.NORMAL)
                
            except Exception as e:
                results_text.insert(tk.END, f"\nError during diagnostics: {str(e)}\n", "error")
                traceback_text = traceback.format_exc()
                results_text.insert(tk.END, f"\n{traceback_text}\n", "error")
                close_btn.config(state=tk.NORMAL)
                progress_label.config(text="Diagnostics failed")
        
        # Run diagnostics in a separate thread
        self.root.after(100, run_diagnostics)

def main():
    # Check for admin privileges
    if not is_admin():
        run_as_admin()
    
    # Create the main window
    root = tk.Tk()
    app = DebugManagerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
