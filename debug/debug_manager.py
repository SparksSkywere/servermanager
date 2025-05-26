import os
import sys
import json
import subprocess
import logging
import winreg
import time
import platform
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import datetime
import traceback
import ctypes
import psutil

# Add modules directory to path if needed
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
modules_dir = os.path.join(parent_dir, "modules")
if modules_dir not in sys.path:
    sys.path.append(modules_dir)

# Try to import from modules
try:
    from debug import debug_manager, enable_debug, get_system_info, create_diagnostic_report
except ImportError:
    # If import fails, use basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    debug_manager = None

logger = logging.getLogger("DebugManager")

def is_admin():
    """Check if the script is running with administrator privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    """Re-run the script with admin privileges"""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

class DebugManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Server Manager - Debug Center")
        self.root.geometry("600x400")
        self.root.minsize(600, 400)
        
        # Initialize paths
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        
        # Initialize paths and configuration
        self.initialize()
        
        # Set up UI elements
        self.create_ui()
    
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Set up file logging
            log_file = os.path.join(self.paths["logs"], "debug-manager.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            
            # Enable debug mode
            if debug_manager:
                enable_debug()
                
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            messagebox.showerror("Initialization Error", f"Failed to initialize: {str(e)}")
            return False
    
    def create_ui(self):
        """Create the UI elements"""
        # Create group boxes for different debug areas
        self.create_system_group()
        self.create_misc_group()
    
    def create_system_group(self):
        """Create system group box"""
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
        """Create miscellaneous group box"""
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
        """Toggle debug logging mode"""
        if debug_manager:
            if self.debug_var.get():
                enable_debug()
                messagebox.showinfo("Debug Mode", "Debug logging is now enabled.")
            else:
                debug_manager.set_debug_mode(False)
                messagebox.showinfo("Debug Mode", "Debug logging is now disabled.")
    
    def show_system_information(self):
        """Show system information window"""
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
                system_info = get_system_info()
                
                # Format system information
                system_info_text = f"""SYSTEM INFORMATION
-----------------
Computer Name: {platform.node()}
OS: {system_info['system']['system']} {system_info['system']['release']}
Version: {system_info['system']['version']}

HARDWARE
--------
CPU: {system_info['system']['processor']}
Cores: {system_info['cpu']['physical_cores']} physical, {system_info['cpu']['logical_cores']} logical
CPU Usage: {system_info['cpu']['cpu_percent']}%
RAM: {round(system_info['memory']['total'] / (1024**3), 2)} GB ({round(system_info['memory']['available'] / (1024**3), 2)} GB available)

STORAGE
-------
Total: {round(system_info['disk']['total'] / (1024**3), 2)} GB
Free: {round(system_info['disk']['free'] / (1024**3), 2)} GB
Usage: {system_info['disk']['percent']}%

NETWORK
-------
Bytes Sent: {system_info['network']['bytes_sent']}
Bytes Received: {system_info['network']['bytes_recv']}
"""
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
        """Update system information"""
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
        """View system logs"""
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
        """Run full system diagnostics"""
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
                    system_info = get_system_info()
                    results_text.insert(tk.END, f"OS: {system_info['system']['system']} {system_info['system']['release']}\n")
                    results_text.insert(tk.END, f"CPU: {system_info['cpu']['logical_cores']} cores, {system_info['cpu']['cpu_percent']}% used\n")
                    results_text.insert(tk.END, f"Memory: {round(system_info['memory']['used'] / (1024**3), 2)} GB of {round(system_info['memory']['total'] / (1024**3), 2)} GB used ({system_info['memory']['percent']}%)\n")
                    results_text.insert(tk.END, f"Disk: {round(system_info['disk']['used'] / (1024**3), 2)} GB of {round(system_info['disk']['total'] / (1024**3), 2)} GB used ({system_info['disk']['percent']}%)\n\n")
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
                
                if os.path.exists(self.server_manager_dir):
                    results_text.insert(tk.END, f"[OK] Server Manager directory: {self.server_manager_dir}\n", "ok")
                    results_text.tag_config("ok", foreground="green")
                else:
                    results_text.insert(tk.END, f"[ERROR] Server Manager directory not found: {self.server_manager_dir}\n", "error")
                    results_text.tag_config("error", foreground="red")
                
                # Check essential directories
                essential_dirs = ["logs", "config", "servers", "scripts"]
                for dir_name in essential_dirs:
                    dir_path = self.paths.get(dir_name, os.path.join(self.server_manager_dir, dir_name))
                    if os.path.exists(dir_path) and os.path.isdir(dir_path):
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
                
                servers_dir = self.paths.get("servers", os.path.join(self.server_manager_dir, "servers"))
                if os.path.exists(servers_dir):
                    server_files = [f for f in os.listdir(servers_dir) if f.endswith('.json')]
                    if server_files:
                        results_text.insert(tk.END, f"Found {len(server_files)} server configuration(s).\n")
                        
                        # Check a few servers
                        for i, server_file in enumerate(server_files[:3]):  # Check up to 3 servers
                            try:
                                with open(os.path.join(servers_dir, server_file), 'r') as f:
                                    server_config = json.load(f)
                                
                                server_name = server_config.get("Name", server_file.replace(".json", ""))
                                results_text.insert(tk.END, f"  - {server_name}: ")
                                
                                if debug_manager and hasattr(debug_manager, "get_server_status"):
                                    server_status = debug_manager.get_server_status(server_name)
                                    if server_status.get("IsRunning", False):
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
                                        except:
                                            results_text.insert(tk.END, "Unknown\n", "warning")
                                    else:
                                        results_text.insert(tk.END, "Not started\n", "warning")
                            except Exception as e:
                                results_text.insert(tk.END, f"Error reading server config {server_file}: {str(e)}\n", "error")
                    else:
                        results_text.insert(tk.END, "No server configurations found.\n", "warning")
                else:
                    results_text.insert(tk.END, f"Servers directory not found: {servers_dir}\n", "error")
                
                results_text.insert(tk.END, "\n")
                
                # Step 4: Create diagnostic report
                progress_bar["value"] = 80
                progress_label.config(text="Running diagnostics: Creating diagnostic report...")
                diag_window.update()
                time.sleep(0.5)
                
                results_text.insert(tk.END, "--- Diagnostic Report ---\n", "heading")
                
                if debug_manager:
                    try:
                        report_path = create_diagnostic_report()
                        if report_path:
                            results_text.insert(tk.END, f"[OK] Diagnostic report created: {report_path}\n", "ok")
                        else:
                            results_text.insert(tk.END, "[ERROR] Failed to create diagnostic report\n", "error")
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
    app = DebugManager(root)
    root.mainloop()

if __name__ == "__main__":
    main()
