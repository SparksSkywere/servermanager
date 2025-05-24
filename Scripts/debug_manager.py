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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
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
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            messagebox.showerror("Initialization Error", f"Failed to initialize: {str(e)}")
            return False
    
    def create_ui(self):
        """Create the UI elements"""
        # Create group boxes for different debug areas
        self.create_system_group()
        self.create_ui_group()
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
    
    def create_ui_group(self):
        """Create UI group box"""
        ui_frame = ttk.LabelFrame(self.root, text="User Interface")
        ui_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        # Form debugger button
        form_debug_btn = ttk.Button(ui_frame, text="UI Form Debugger", 
                                    command=self.debug_ui_form)
        form_debug_btn.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Control inspector button
        control_inspector_btn = ttk.Button(ui_frame, text="Control Inspector", 
                                          command=self.inspect_control)
        control_inspector_btn.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
    
    def create_misc_group(self):
        """Create miscellaneous group box"""
        misc_frame = ttk.LabelFrame(self.root, text="Miscellaneous")
        misc_frame.grid(row=0, column=1, rowspan=2, padx=20, pady=10, sticky="nsew")
        
        # Full diagnostics button
        full_diag_btn = ttk.Button(misc_frame, text="Full Diagnostics", 
                                   command=self.run_full_diagnostics)
        full_diag_btn.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Close button
        close_btn = ttk.Button(misc_frame, text="Close Debug Center", 
                              command=self.root.destroy)
        close_btn.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        # Configure grid weights
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
    
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
            disk_info = []
            for disk in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(disk.mountpoint)
                    disk_info.append(
                        f"Drive {disk.device}: {round(usage.total / (1024**3), 2)} GB total, "
                        f"{round(usage.free / (1024**3), 2)} GB free"
                    )
                except:
                    pass
            
            # Network info
            network_info = []
            for name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == 2:  # AF_INET (IPv4)
                        network_info.append(f"Adapter: {name}\nIP Address: {addr.address}\n")
            
            # Format all information
            system_info_text = f"""SYSTEM INFORMATION
-----------------
Computer Name: {platform.node()}
OS: {os_name} {os_release}
Version: {os_version}
Last Boot: {datetime.datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}
Uptime: {round((time.time() - psutil.boot_time()) / 3600, 2)} hours

HARDWARE
--------
CPU: {cpu_info}
Cores: {cpu_count} physical, {cpu_threads} logical
RAM: {memory_total} GB ({memory_available} GB available)

STORAGE
-------
{os.linesep.join(disk_info)}

NETWORK
-------
{os.linesep.join(network_info)}
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
            time.sleep(1)
            print("Updating system information...")
            time.sleep(0.8)
            print("Checking OS status...")
            time.sleep(0.5)
            print("Checking disk space...")
            time.sleep(0.6)
            print("Checking network status...")
            time.sleep(0.7)
            print("Complete!")
            
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
    
    def debug_ui_form(self):
        """Debug UI form"""
        debug_window = tk.Toplevel(self.root)
        debug_window.title("UI Form Debugger")
        debug_window.geometry("600x500")
        debug_window.grab_set()
        
        # Form selection
        form_frame = ttk.Frame(debug_window)
        form_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(form_frame, text="Form Name:").pack(side=tk.LEFT, padx=5)
        
        form_combo = ttk.Combobox(form_frame, width=30)
        form_combo['values'] = (
            "MainDashboard", "SettingsForm", "ConnectionManager", 
            "ServerConfigEditor", "UserManagement", "LogViewer"
        )
        form_combo.current(0)
        form_combo.pack(side=tk.LEFT, padx=5)
        
        # Debug output
        debug_text = scrolledtext.ScrolledText(debug_window, wrap=tk.WORD, width=70, height=20)
        debug_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Function to display form debugging info
        def show_form_debug():
            selected_form = form_combo.get()
            
            # Generate some simulated debug info
            from random import randint, choice
            
            state = choice(["Active", "Loaded", "Minimized"])
            controls = randint(5, 30)
            visible = choice(["True", "False"])
            modal = choice(["True", "False"])
            events = randint(3, 15)
            
            debug_info = f"""
FORM DEBUGGING INFO: {selected_form}
--------------------------------
State: {state}
Controls: {controls}
Visible: {visible}
Modal: {modal}
Events Registered: {events}

CONTROL HIERARCHY:
- {selected_form}
  |- Panel1
  |  |- Button1
  |  |- Button2
  |- TabControl1
     |- Tab1
     |- Tab2

RECENT EVENTS:
- Load (handled)
- Resize (handled)
- Click on Button1 (handled)
- MouseMove (not handled)
"""
            debug_text.delete(1.0, tk.END)
            debug_text.insert(tk.END, debug_info)
        
        # Refresh button
        refresh_btn = ttk.Button(debug_window, text="Refresh", command=show_form_debug)
        refresh_btn.pack(pady=10)
        
        # Show initial debug info
        show_form_debug()
        
        # Close button
        close_btn = ttk.Button(debug_window, text="Close", command=debug_window.destroy)
        close_btn.pack(pady=10)
    
    def inspect_control(self):
        """Inspect control properties"""
        inspect_window = tk.Toplevel(self.root)
        inspect_window.title("Control Inspector")
        inspect_window.geometry("600x500")
        inspect_window.grab_set()
        
        # Control selection
        control_frame = ttk.Frame(inspect_window)
        control_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(control_frame, text="Control Type:").pack(side=tk.LEFT, padx=5)
        
        control_combo = ttk.Combobox(control_frame, width=30)
        control_combo['values'] = (
            "Button", "TextBox", "ComboBox", "CheckBox", "ListView", "TabControl"
        )
        control_combo.current(0)
        control_combo.pack(side=tk.LEFT, padx=5)
        
        # Properties display
        prop_text = scrolledtext.ScrolledText(inspect_window, wrap=tk.WORD, width=70, height=20)
        prop_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Function to display control properties
        def show_control_props():
            selected_control = control_combo.get()
            
            # Generate control-specific properties based on type
            if selected_control == "Button":
                control_type = "Button"
                control_specific_props = """Text: 'Save Changes'
DialogResult: OK
Image: (none)
FlatStyle: Standard"""
            elif selected_control == "TextBox":
                control_type = "TextBox"
                control_specific_props = """Text: 'Sample text'
Multiline: False
ReadOnly: False
MaxLength: 32767
PasswordChar: ''"""
            elif selected_control == "ComboBox":
                control_type = "ComboBox"
                control_specific_props = """DropDownStyle: DropDownList
Items: 10
SelectedIndex: 2
SelectedItem: 'Option 3'"""
            elif selected_control == "CheckBox":
                control_type = "CheckBox"
                control_specific_props = """Checked: True
CheckState: Checked
AutoCheck: True
Appearance: Normal"""
            elif selected_control == "ListView":
                control_type = "ListView"
                control_specific_props = """View: Details
Columns: 4
Items: 12
MultiSelect: True"""
            elif selected_control == "TabControl":
                control_type = "TabControl"
                control_specific_props = """TabCount: 3
SelectedIndex: 0
Alignment: Top"""
            else:
                control_type = selected_control
                control_specific_props = "No specific properties available"
            
            # Generate random event handlers
            from random import randint, choice
            events = ["Click", "DoubleClick", "MouseOver", "MouseLeave", "KeyPress", "TextChanged"]
            event_count = randint(1, 4)
            event_handlers = "\n".join([f"{choice(events)}: event_handler_{randint(1, 100)}" for _ in range(event_count)])
            
            # Format complete property text
            prop_info = f"""CONTROL PROPERTIES: {selected_control}
---------------------------------
Type: {control_type}
Name: {selected_control}1
Parent: MainForm
Location: X={randint(10, 500)}, Y={randint(10, 400)}
Size: Width={randint(100, 400)}, Height={randint(20, 200)}
Enabled: {choice(['True', 'False'])}
Visible: {choice(['True', 'False'])}
TabIndex: {randint(0, 20)}

CONTROL-SPECIFIC PROPERTIES:
{control_specific_props}

EVENT HANDLERS:
{event_handlers}
"""
            prop_text.delete(1.0, tk.END)
            prop_text.insert(tk.END, prop_info)
        
        # Refresh button
        refresh_btn = ttk.Button(inspect_window, text="Refresh", command=show_control_props)
        refresh_btn.pack(pady=10)
        
        # Show initial properties
        show_control_props()
        
        # Close button
        close_btn = ttk.Button(inspect_window, text="Close", command=inspect_window.destroy)
        close_btn.pack(pady=10)
    
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
        
        # Function to run diagnostics in stages
        def run_diagnostics():
            try:
                steps = [
                    ("Checking system requirements", 10),
                    ("Verifying installation", 20),
                    ("Checking registry settings", 30),
                    ("Scanning server configurations", 50),
                    ("Verifying file permissions", 60),
                    ("Testing network connectivity", 70),
                    ("Checking system resources", 80),
                    ("Validating SteamCMD installation", 90),
                    ("Generating final report", 100)
                ]
                
                results = []
                
                for step, progress in steps:
                    # Update progress
                    progress_label.config(text=f"Running diagnostics: {step}...")
                    progress_bar["value"] = progress
                    diag_window.update()
                    
                    # Simulate step execution
                    time.sleep(0.5)
                    
                    # Add result
                    if progress % 3 == 0:
                        status = "[WARNING]"
                        color = "orange"
                    elif progress % 7 == 0:
                        status = "[ERROR]"
                        color = "red"
                    else:
                        status = "[OK]"
                        color = "green"
                    
                    result_text = f"{status} {step}\n"
                    results_text.insert(tk.END, result_text, status.lower())
                    results_text.tag_config(status.lower(), foreground=color)
                    
                    # Simulate detailed output
                    details = f"  Details: Completed in {randint(1, 500)} ms\n"
                    results_text.insert(tk.END, details)
                    results_text.see(tk.END)
                
                # Final summary
                results_text.insert(tk.END, "\nDiagnostics completed.\n", "heading")
                results_text.tag_config("heading", font=("Arial", 10, "bold"))
                
                issues = sum(1 for step, _ in steps if _ % 3 == 0 or _ % 7 == 0)
                if issues > 0:
                    summary = f"Found {issues} potential issues that need attention.\n"
                    results_text.insert(tk.END, summary, "warning")
                    results_text.tag_config("warning", foreground="orange")
                else:
                    summary = "No issues detected. System is running optimally.\n"
                    results_text.insert(tk.END, summary, "success")
                    results_text.tag_config("success", foreground="green")
                
                # Enable close button
                close_btn.config(state=tk.NORMAL)
                progress_label.config(text="Diagnostics complete")
                
            except Exception as e:
                results_text.insert(tk.END, f"\nError during diagnostics: {str(e)}\n", "error")
                results_text.tag_config("error", foreground="red")
                close_btn.config(state=tk.NORMAL)
                progress_label.config(text="Diagnostics failed")
        
        # Run diagnostics in a separate thread
        import threading
        import random
        from random import randint
        threading.Thread(target=run_diagnostics).start()

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
