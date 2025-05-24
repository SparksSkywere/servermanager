import os
import sys
import subprocess
import zipfile
import json
import winreg
import urllib.request
import shutil
import argparse
import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
import ctypes
from pathlib import Path

# Define global variables
log_memory = []
log_file_path = None
current_version = "0.2"
steamcmd_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
registry_path = r"Software\SkywereIndustries\Servermanager"

# Function to check if the current user is an administrator
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

# Function to run as administrator
def run_as_admin():
    if not is_admin():
        # Re-run the script with admin rights
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit(0)

# Function to write messages to log (stored in memory first)
def write_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{timestamp} - {message}"
    
    # Print to console
    print(log_message)
    
    # Store the log message in memory
    log_memory.append(log_message)

# Function to write the log from memory to file
def write_log_to_file(log_file_path):
    if not log_file_path:
        print("Log file path is not set. Cannot write log.")
        return
    
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        
        # Write each log entry stored in memory to the log file
        with open(log_file_path, 'w') as f:
            for log_message in log_memory:
                f.write(log_message + "\n")
        print(f"Log successfully written to file: {log_file_path}")
    except Exception as e:
        print(f"Failed to write to log file: {str(e)}")

# Function to select installation directory using GUI
def select_folder_dialog():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    # Show an info message
    messagebox.showinfo("Server Manager Installer", "Please select the directory where you want to install Server Manager")
    
    # Show the folder selection dialog
    folder_path = filedialog.askdirectory(title="Select Installation Directory")
    
    if not folder_path:
        print("No directory selected, exiting...")
        sys.exit(0)
        
    return folder_path

# Function to download and extract SteamCMD
def download_steamcmd(steamcmd_path):
    write_log(f"Downloading SteamCMD to {steamcmd_path}")
    
    steamcmd_zip = os.path.join(steamcmd_path, "steamcmd.zip")
    steamcmd_exe = os.path.join(steamcmd_path, "steamcmd.exe")
    
    # Only download if it doesn't already exist
    if not os.path.exists(steamcmd_exe):
        try:
            # Download SteamCMD zip file
            urllib.request.urlretrieve(steamcmd_url, steamcmd_zip)
            write_log("SteamCMD download completed")
            
            # Extract the zip file
            with zipfile.ZipFile(steamcmd_zip, 'r') as zip_ref:
                zip_ref.extractall(steamcmd_path)
            write_log("SteamCMD extraction completed")
            
            # Clean up zip file
            os.remove(steamcmd_zip)
            
            return True
        except Exception as e:
            write_log(f"Error downloading/extracting SteamCMD: {str(e)}")
            return False
    else:
        write_log("SteamCMD already exists, skipping download")
        return True

# Function to run SteamCMD to update/validate itself
def update_steamcmd(steamcmd_path):
    steamcmd_exe = os.path.join(steamcmd_path, "steamcmd.exe")
    
    if not os.path.exists(steamcmd_exe):
        write_log("SteamCMD executable not found")
        return False
    
    try:
        write_log("Running SteamCMD to update itself")
        subprocess.run([steamcmd_exe, "+login", "anonymous", "+quit"], 
                      check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        write_log("SteamCMD update completed")
        return True
    except subprocess.CalledProcessError as e:
        write_log(f"Error updating SteamCMD: {str(e)}")
        return False

# Function to create directory structure
def create_directory_structure(server_manager_dir):
    write_log(f"Creating directory structure in {server_manager_dir}")
    
    # Define directories to create
    directories = [
        "",  # Root directory
        "logs",
        "config",
        "scripts",
        "modules",
        "static",
        "templates",
        "servers",
        "temp",
        "icons"
    ]
    
    try:
        # Create each directory
        for directory in directories:
            dir_path = os.path.join(server_manager_dir, directory)
            os.makedirs(dir_path, exist_ok=True)
        
        write_log("Directory structure created successfully")
        return True
    except Exception as e:
        write_log(f"Error creating directory structure: {str(e)}")
        return False

# Function to create registry entries
def create_registry_entries(steamcmd_path, server_manager_dir, web_port=8080):
    write_log("Creating registry entries")
    
    try:
        # Create the registry key
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        
        # Set values
        winreg.SetValueEx(key, "CurrentVersion", 0, winreg.REG_SZ, current_version)
        winreg.SetValueEx(key, "SteamCMDPath", 0, winreg.REG_SZ, steamcmd_path)
        winreg.SetValueEx(key, "Servermanagerdir", 0, winreg.REG_SZ, server_manager_dir)
        winreg.SetValueEx(key, "InstallDate", 0, winreg.REG_SZ, datetime.now().isoformat())
        winreg.SetValueEx(key, "LastUpdate", 0, winreg.REG_SZ, datetime.now().isoformat())
        winreg.SetValueEx(key, "WebPort", 0, winreg.REG_SZ, str(web_port))
        
        # Close the key
        winreg.CloseKey(key)
        
        write_log("Registry entries created successfully")
        return True
    except Exception as e:
        write_log(f"Error creating registry entries: {str(e)}")
        return False

# Function to install required Python packages
def install_required_packages():
    write_log("Installing required Python packages")
    
    # List of required packages
    required_packages = [
        "flask",
        "pystray",
        "pillow",
        "psutil",
        "requests",
        "pycrypto",
        "matplotlib"
    ]
    
    try:
        for package in required_packages:
            write_log(f"Installing {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        
        write_log("All required packages installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        write_log(f"Error installing packages: {str(e)}")
        return False

# Function to copy script files from source to destination
def copy_script_files(server_manager_dir):
    write_log("Copying script files to server manager directory")
    
    try:
        # Get the directory of the current script
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Directories to copy
        directories = ["scripts", "modules", "static", "templates", "icons"]
        
        for directory in directories:
            src_dir = os.path.join(current_dir, directory)
            dst_dir = os.path.join(server_manager_dir, directory)
            
            # Skip if source directory doesn't exist
            if not os.path.exists(src_dir):
                write_log(f"Source directory {src_dir} not found, skipping")
                continue
            
            # Copy all files from source to destination
            for item in os.listdir(src_dir):
                src_item = os.path.join(src_dir, item)
                dst_item = os.path.join(dst_dir, item)
                
                if os.path.isfile(src_item):
                    shutil.copy2(src_item, dst_item)
                    write_log(f"Copied {item} to {dst_dir}")
        
        write_log("Script files copied successfully")
        return True
    except Exception as e:
        write_log(f"Error copying script files: {str(e)}")
        return False

# Function to create startup shortcuts
def create_shortcuts(server_manager_dir):
    write_log("Creating shortcuts")
    
    try:
        # Create batch files for easy starting/stopping
        start_batch = os.path.join(server_manager_dir, "start_server_manager.bat")
        stop_batch = os.path.join(server_manager_dir, "stop_server_manager.bat")
        
        # Create start batch file
        with open(start_batch, 'w') as f:
            f.write('@echo off\n')
            f.write('echo Starting Server Manager...\n')
            f.write(f'python "{os.path.join(server_manager_dir, "scripts", "launcher.py")}"\n')
            f.write('echo Server Manager started.\n')
            f.write('pause\n')
        
        # Create stop batch file
        with open(stop_batch, 'w') as f:
            f.write('@echo off\n')
            f.write('echo Stopping Server Manager...\n')
            f.write(f'python "{os.path.join(server_manager_dir, "scripts", "stop_servermanager.py")}"\n')
            f.write('echo Server Manager stopped.\n')
            f.write('pause\n')
        
        write_log("Shortcuts created successfully")
        return True
    except Exception as e:
        write_log(f"Error creating shortcuts: {str(e)}")
        return False

# Function to create initial configuration
def create_initial_config(server_manager_dir):
    write_log("Creating initial configuration")
    
    try:
        config_dir = os.path.join(server_manager_dir, "config")
        
        # Create a basic configuration file
        config = {
            "version": current_version,
            "install_date": datetime.now().isoformat(),
            "web_port": 8080,
            "enable_auto_updates": True,
            "enable_tray_icon": True,
            "check_updates_interval": 3600,  # seconds
            "servers_directory": os.path.join(server_manager_dir, "servers")
        }
        
        # Write to config file
        config_file = os.path.join(config_dir, "config.json")
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
        
        write_log("Initial configuration created successfully")
        return True
    except Exception as e:
        write_log(f"Error creating initial configuration: {str(e)}")
        return False

# Function to run installation process with GUI progress bar
def run_installation():
    # Initialize Tkinter
    root = tk.Tk()
    root.title("Server Manager Installation")
    root.geometry("500x300")
    root.resizable(False, False)
    
    # Add a header
    header_label = tk.Label(root, text="Server Manager Installation", font=("Arial", 16, "bold"))
    header_label.pack(pady=10)
    
    # Add an info label
    info_label = tk.Label(root, text="This wizard will guide you through the installation process.")
    info_label.pack(pady=10)
    
    # Select installation directory
    dir_frame = tk.Frame(root)
    dir_frame.pack(pady=10, fill=tk.X, padx=20)
    
    dir_label = tk.Label(dir_frame, text="Installation Directory:")
    dir_label.grid(row=0, column=0, sticky=tk.W)
    
    dir_var = tk.StringVar()
    dir_entry = tk.Entry(dir_frame, textvariable=dir_var, width=30)
    dir_entry.grid(row=0, column=1, padx=5)
    
    def browse_directory():
        folder_path = filedialog.askdirectory(title="Select Installation Directory")
        if folder_path:
            dir_var.set(folder_path)
    
    browse_button = tk.Button(dir_frame, text="Browse", command=browse_directory)
    browse_button.grid(row=0, column=2, padx=5)
    
    # Web port option
    port_frame = tk.Frame(root)
    port_frame.pack(pady=10, fill=tk.X, padx=20)
    
    port_label = tk.Label(port_frame, text="Web Server Port:")
    port_label.grid(row=0, column=0, sticky=tk.W)
    
    port_var = tk.IntVar(value=8080)
    port_entry = tk.Entry(port_frame, textvariable=port_var, width=10)
    port_entry.grid(row=0, column=1, padx=5, sticky=tk.W)
    
    # Progress bar and status
    progress_frame = tk.Frame(root)
    progress_frame.pack(pady=20, fill=tk.X, padx=20)
    
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100)
    progress_bar.pack(fill=tk.X)
    
    status_var = tk.StringVar(value="Ready to install")
    status_label = tk.Label(progress_frame, textvariable=status_var)
    status_label.pack(pady=5)
    
    # Control buttons
    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)
    
    def start_installation():
        # Validate inputs
        install_dir = dir_var.get()
        web_port = port_var.get()
        
        if not install_dir:
            messagebox.showerror("Error", "Please select an installation directory")
            return
        
        if not (1024 <= web_port <= 65535):
            messagebox.showerror("Error", "Port must be between 1024 and 65535")
            return
        
        # Disable inputs during installation
        dir_entry.config(state=tk.DISABLED)
        port_entry.config(state=tk.DISABLED)
        browse_button.config(state=tk.DISABLED)
        install_button.config(state=tk.DISABLED)
        cancel_button.config(state=tk.DISABLED)
        
        # Run installation in a separate thread
        def installation_thread():
            global log_file_path
            
            try:
                # Create server manager directory
                server_manager_dir = os.path.join(install_dir, "servermanager")
                os.makedirs(server_manager_dir, exist_ok=True)
                
                # Set log file path
                log_file_path = os.path.join(server_manager_dir, "install_log.txt")
                
                # Installation steps
                steps = [
                    ("Downloading SteamCMD", lambda: download_steamcmd(install_dir)),
                    ("Updating SteamCMD", lambda: update_steamcmd(install_dir)),
                    ("Creating directory structure", lambda: create_directory_structure(server_manager_dir)),
                    ("Installing required packages", lambda: install_required_packages()),
                    ("Copying script files", lambda: copy_script_files(server_manager_dir)),
                    ("Creating registry entries", lambda: create_registry_entries(install_dir, server_manager_dir, web_port)),
                    ("Creating shortcuts", lambda: create_shortcuts(server_manager_dir)),
                    ("Creating initial configuration", lambda: create_initial_config(server_manager_dir))
                ]
                
                # Run each step
                for i, (step_name, step_func) in enumerate(steps):
                    # Update status
                    status_var.set(step_name)
                    progress_var.set((i / len(steps)) * 100)
                    root.update_idletasks()
                    
                    # Run the step
                    success = step_func()
                    
                    if not success:
                        raise Exception(f"Failed to {step_name.lower()}")
                
                # Update progress to 100%
                progress_var.set(100)
                status_var.set("Installation completed successfully")
                
                # Write log to file
                write_log_to_file(log_file_path)
                
                # Show success message
                messagebox.showinfo("Installation Complete", 
                                   f"Server Manager has been successfully installed to {server_manager_dir}.\n\n"
                                   f"You can start it using the shortcuts created in the installation directory.")
                
                # Close the window
                root.quit()
                
            except Exception as e:
                # Show error message
                error_msg = f"Installation failed: {str(e)}"
                write_log(error_msg)
                
                # Write log to file
                if log_file_path:
                    write_log_to_file(log_file_path)
                
                messagebox.showerror("Installation Failed", error_msg)
                
                # Re-enable inputs
                dir_entry.config(state=tk.NORMAL)
                port_entry.config(state=tk.NORMAL)
                browse_button.config(state=tk.NORMAL)
                install_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.NORMAL)
        
        # Start installation thread
        threading.Thread(target=installation_thread, daemon=True).start()
    
    install_button = tk.Button(button_frame, text="Install", command=start_installation, width=10)
    install_button.pack(side=tk.LEFT, padx=10)
    
    cancel_button = tk.Button(button_frame, text="Cancel", command=root.quit, width=10)
    cancel_button.pack(side=tk.LEFT, padx=10)
    
    # Run the GUI
    root.mainloop()

def main():
    try:
        # Ensure running as administrator
        run_as_admin()
        
        # Run the installation process
        run_installation()
        
        return 0
    except Exception as e:
        print(f"Installation failed: {str(e)}")
        write_log(f"Installation failed: {str(e)}")
        if os.path.exists(os.path.dirname(log_file_path or "")):
            write_log_to_file(log_file_path)
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
