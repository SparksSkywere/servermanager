# Automation Settings Window
# -*- coding: utf-8 -*-
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging, load_automation_settings, save_automation_settings
setup_module_path()
from Modules.Database.server_configs_database import ServerConfigManager
from Modules.server_automation import ServerAutomationManager
from Modules.server_manager import ServerManager

logger: logging.Logger = setup_module_logging("AutomationUI")

class AutomationSettingsWindow:
    # Window for configuring server automation settings (MOTD, restart warnings, start commands)
    def __init__(self, parent=None, server_manager=None):
        self.parent = parent
        self.window = None
        self.server_manager = server_manager or ServerConfigManager()
        self.db_manager = ServerConfigManager()
        self.servers = []
        self.current_server = None
        self.variables = {}

        # Create the window
        self.create_window()

    def create_window(self):
        # Create the main automation settings window
        self.window = tk.Toplevel(self.parent) if self.parent else tk.Tk()
        self.window.title("Server Automation Settings")
        self.window.geometry("800x700")
        self.window.resizable(True, True)

        # Create main frame
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create scrollable frame for settings
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Add mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        def _bind_to_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_from_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind('<Enter>', _bind_to_mousewheel)
        canvas.bind('<Leave>', _unbind_from_mousewheel)

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Title
        title_label = ttk.Label(scrollable_frame, text="Server Automation Settings",
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 10))

        # Server selection
        server_frame = ttk.LabelFrame(scrollable_frame, text="Select Server", padding="5")
        server_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(server_frame, text="Server:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.server_var = tk.StringVar()
        self.server_combo = ttk.Combobox(server_frame, textvariable=self.server_var,
                                        state="readonly", width=40)
        self.server_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.server_combo.bind("<<ComboboxSelected>>", self.on_server_selected)

        refresh_btn = ttk.Button(server_frame, text="Refresh", command=self.load_servers)
        refresh_btn.grid(row=0, column=2, padx=5, pady=5)

        # Settings frame
        settings_frame = ttk.LabelFrame(scrollable_frame, text="Automation Settings", padding="10")
        settings_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # MOTD Settings
        motd_frame = ttk.LabelFrame(settings_frame, text="MOTD (Message of the Day)", padding="5")
        motd_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(motd_frame, text="MOTD Command:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_cmd_var = tk.StringVar()
        motd_cmd_entry = ttk.Entry(motd_frame, textvariable=self.motd_cmd_var, width=50)
        motd_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(motd_frame, text="MOTD Message:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_msg_var = tk.StringVar()
        motd_msg_entry = ttk.Entry(motd_frame, textvariable=self.motd_msg_var, width=50)
        motd_msg_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(motd_frame, text="Broadcast Interval (minutes):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_interval_var = tk.StringVar(value="0")
        motd_interval_entry = ttk.Entry(motd_frame, textvariable=self.motd_interval_var, width=10)
        motd_interval_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(motd_frame, text="0 = disabled", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)

        # Start Command
        start_frame = ttk.LabelFrame(settings_frame, text="Start Command", padding="5")
        start_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(start_frame, text="Command to run after server starts:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.start_cmd_var = tk.StringVar()
        start_cmd_entry = ttk.Entry(start_frame, textvariable=self.start_cmd_var, width=50)
        start_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        # Scheduled Restart
        restart_frame = ttk.LabelFrame(settings_frame, text="Scheduled Restart", padding="5")
        restart_frame.pack(fill=tk.X, pady=(0, 10))

        self.scheduled_restart_var = tk.BooleanVar()
        scheduled_restart_check = ttk.Checkbutton(restart_frame,
                                                 text="Enable scheduled restart with warnings",
                                                 variable=self.scheduled_restart_var)
        scheduled_restart_check.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W, columnspan=3)

        ttk.Label(restart_frame, text="Warning Command:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_cmd_var = tk.StringVar()
        warning_cmd_entry = ttk.Entry(restart_frame, textvariable=self.warning_cmd_var, width=50)
        warning_cmd_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(restart_frame, text="Warning Intervals (minutes):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_intervals_var = tk.StringVar(value="30,15,10,5,1")
        warning_intervals_entry = ttk.Entry(restart_frame, textvariable=self.warning_intervals_var, width=20)
        warning_intervals_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(restart_frame, text="e.g., 30,15,10,5,1", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)

        ttk.Label(restart_frame, text="Warning Restart Message:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_msg_template_var = tk.StringVar(value="Server restarting in {message}")
        warning_msg_entry = ttk.Entry(restart_frame, textvariable=self.warning_msg_template_var, width=50)
        warning_msg_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(restart_frame, text="Use {message} for time", font=("Segoe UI", 8)).grid(row=3, column=2, padx=5, pady=5, sticky=tk.W)

        # Stop Command
        stop_frame = ttk.LabelFrame(settings_frame, text="Stop Command", padding="5")
        stop_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(stop_frame, text="Command to gracefully stop the server:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.stop_cmd_var = tk.StringVar()
        stop_cmd_entry = ttk.Entry(stop_frame, textvariable=self.stop_cmd_var, width=50)
        stop_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        # Save Command
        save_frame = ttk.LabelFrame(settings_frame, text="Save Command", padding="5")
        save_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(save_frame, text="Command to save world/data before shutdown:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.save_cmd_var = tk.StringVar()
        save_cmd_entry = ttk.Entry(save_frame, textvariable=self.save_cmd_var, width=50)
        save_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        # Test buttons frame
        test_frame = ttk.LabelFrame(settings_frame, text="Test Commands", padding="5")
        test_frame.pack(fill=tk.X, pady=(0, 10))

        test_motd_btn = ttk.Button(test_frame, text="Test MOTD", command=self.test_motd_command)
        test_motd_btn.grid(row=0, column=0, padx=5, pady=5)

        test_save_btn = ttk.Button(test_frame, text="Test Save Command", command=self.test_save_command)
        test_save_btn.grid(row=1, column=0, padx=5, pady=5)

        # Warning test with time entry
        warning_test_frame = ttk.Frame(test_frame)
        warning_test_frame.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        test_warning_btn = ttk.Button(warning_test_frame, text="Test Warning", command=self.test_warning_command)
        test_warning_btn.pack(side=tk.LEFT)

        ttk.Label(warning_test_frame, text="Time (minutes):").pack(side=tk.LEFT, padx=(10, 2))
        self.warning_test_time_var = tk.StringVar(value="5")
        warning_time_entry = ttk.Entry(warning_test_frame, textvariable=self.warning_test_time_var, width=8)
        warning_time_entry.pack(side=tk.LEFT)

        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        save_btn = ttk.Button(button_frame, text="Save Settings", command=self.save_settings)
        save_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.window.destroy)
        cancel_btn.pack(side=tk.RIGHT)

        # Load initial data
        self.load_servers()

        # Centre the window
        self.window.update_idletasks()
        window_width = self.window.winfo_width()
        window_height = self.window.winfo_height()

        if self.parent:
            # Centre on parent window
            parent_x = self.parent.winfo_x()
            parent_y = self.parent.winfo_y()
            parent_width = self.parent.winfo_width()
            parent_height = self.parent.winfo_height()

            # Calculate center position relative to parent
            x = parent_x + (parent_width // 2) - (window_width // 2)
            y = parent_y + (parent_height // 2) - (window_height // 2)

            # Get screen dimensions for the screen containing the parent window
            screen_width = self.parent.winfo_screenwidth()
            screen_height = self.parent.winfo_screenheight()

            # Ensure window stays within screen bounds
            x = max(0, min(x, screen_width - window_width))
            y = max(0, min(y, screen_height - window_height))

            self.window.geometry(f"+{x}+{y}")
        else:
            # Centre on primary screen if no parent
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()
            x = (screen_width // 2) - (window_width // 2)
            y = (screen_height // 2) - (window_height // 2)

            # Ensure window stays within screen bounds
            x = max(0, min(x, screen_width - window_width))
            y = max(0, min(y, screen_height - window_height))

            self.window.geometry(f"+{x}+{y}")

    def load_servers(self):
        # Load available servers into the combobox
        try:
            servers = self.server_manager.get_all_servers()
            if isinstance(servers, dict):
                # ServerManager returns dict keyed by name
                self.servers = list(servers.values())
            elif isinstance(servers, list):
                # ServerConfigManager returns list
                self.servers = servers
            else:
                self.servers = []

            # Extract server names, handling both 'Name' and 'name' keys
            server_names = []
            for server in self.servers:
                if isinstance(server, dict):
                    name = server.get('Name') or server.get('name', '')
                    if name:
                        server_names.append(name)
                elif isinstance(server, str):
                    # Fallback for string server names
                    server_names.append(server)

            self.server_combo['values'] = server_names

            if server_names and not self.server_var.get():
                self.server_var.set(server_names[0])
                self.on_server_selected()

        except Exception as e:
            logger.error(f"Error loading servers: {str(e)}")
            messagebox.showerror("Error", f"Failed to load servers: {str(e)}")

    def on_server_selected(self, event=None):
        # Load settings for the selected server
        server_name = self.server_var.get()
        if not server_name:
            return

        try:
            server_config = self.db_manager.get_server(server_name)
            if server_config:
                # Load automation settings using common function
                settings = load_automation_settings(server_config)

                # Update UI variables
                self.motd_cmd_var.set(settings.get('motd_command', ''))
                self.motd_msg_var.set(settings.get('motd_message', ''))
                self.motd_interval_var.set(str(settings.get('motd_interval', 0)))
                self.start_cmd_var.set(settings.get('start_command', ''))
                self.stop_cmd_var.set(settings.get('stop_command', ''))
                self.save_cmd_var.set(settings.get('save_command', ''))
                self.scheduled_restart_var.set(settings.get('scheduled_restart_enabled', False))
                self.warning_cmd_var.set(settings.get('warning_command', ''))
                self.warning_intervals_var.set(settings.get('warning_intervals', '30,15,10,5,1'))
                self.warning_msg_template_var.set(settings.get('warning_message_template', 'Server restarting in {message}'))

        except Exception as e:
            logger.error(f"Error loading server settings: {str(e)}")
            messagebox.showerror("Error", f"Failed to load server settings: {str(e)}")

    def test_motd_command(self):
        # Test the MOTD command by sending it to the live server
        server_name = self.server_var.get()
        if not server_name:
            messagebox.showwarning("Warning", "Please select a server first.")
            return

        motd_cmd = self.motd_cmd_var.get().strip()
        motd_msg = self.motd_msg_var.get().strip()

        if not motd_cmd:
            messagebox.showwarning("Warning", "No MOTD command configured.")
            return

        if not motd_msg:
            messagebox.showwarning("Warning", "No MOTD message configured.")
            return

        if not isinstance(self.server_manager, (ServerManager, ServerConfigManager)):
            messagebox.showerror("Error", "Cannot test commands without server manager access.")
            return

        # Check if server is running
        automation = ServerAutomationManager(self.server_manager)
        if not automation._is_server_running(server_name):
            messagebox.showerror("Error", "Server not running")
            return

        # Send the command
        try:
            success = automation.send_motd(server_name, motd_msg)
            if success:
                logger.info("MOTD command sent successfully!")
            else:
                messagebox.showerror("Error", "Failed to send MOTD command.")
        except Exception as e:
            logger.error(f"Error testing MOTD: {str(e)}")
            messagebox.showerror("Error", f"Failed to test MOTD: {str(e)}")

    def test_warning_command(self):
        # Test the warning command by sending a sample warning to the live server
        server_name = self.server_var.get()
        if not server_name:
            messagebox.showwarning("Warning", "Please select a server first.")
            return

        warning_cmd = self.warning_cmd_var.get().strip()
        msg_template = self.warning_msg_template_var.get().strip()

        if not warning_cmd:
            messagebox.showwarning("Warning", "No warning command configured.")
            return

        if not msg_template:
            msg_template = "Server restarting in {message}"

        if not isinstance(self.server_manager, (ServerManager, ServerConfigManager)):
            messagebox.showerror("Error", "Cannot test commands without server manager access.")
            return

        # Check if server is running
        automation = ServerAutomationManager(self.server_manager)
        if not automation._is_server_running(server_name):
            messagebox.showerror("Error", "Server not running")
            return

        # Get test time from entry field
        try:
            test_minutes = int(self.warning_test_time_var.get().strip())
            if test_minutes <= 0:
                raise ValueError("Must be positive")
            if test_minutes == 1:
                time_msg = "1 minute"
            else:
                time_msg = f"{test_minutes} minutes"
        except ValueError:
            messagebox.showwarning("Warning", "Please enter a valid positive number for minutes.")
            return

        # Send a single test warning
        if "{message}" in warning_cmd:
            # Use {message} directly in the warning command
            command = warning_cmd.replace("{message}", time_msg)
        else:
            # Use the message template approach
            test_message = msg_template.replace("{message}", time_msg)
            command = warning_cmd.replace("{message}", test_message)

        try:
            success = automation._send_command_to_server(server_name, command)
            if success:
                logger.info(f"Test warning sent successfully: {command}")
            else:
                messagebox.showerror("Error", "Failed to send test warning.")
        except Exception as e:
            logger.error(f"Error testing warning: {str(e)}")
            messagebox.showerror("Error", f"Failed to test warning: {str(e)}")

    def test_save_command(self):
        # Test the save command by sending it to the live server
        server_name = self.server_var.get()
        if not server_name:
            messagebox.showwarning("Warning", "Please select a server first.")
            return

        save_cmd = self.save_cmd_var.get().strip()

        if not save_cmd:
            messagebox.showwarning("Warning", "No save command configured.")
            return

        if not isinstance(self.server_manager, (ServerManager, ServerConfigManager)):
            messagebox.showerror("Error", "Cannot test commands without server manager access.")
            return

        # Check if server is running
        automation = ServerAutomationManager(self.server_manager)
        if not automation._is_server_running(server_name):
            messagebox.showerror("Error", "Server not running")
            return

        # Send the command
        try:
            success = automation._send_command_to_server(server_name, save_cmd)
            if success:
                logger.info(f"Save command sent successfully: {save_cmd}")
            else:
                messagebox.showerror("Error", "Failed to send save command.")
        except Exception as e:
            logger.error(f"Error testing save command: {str(e)}")
            messagebox.showerror("Error", f"Failed to test save command: {str(e)}")

    def save_settings(self):
        # Save the automation settings for the current server
        server_name = self.server_var.get()
        if not server_name:
            messagebox.showwarning("Warning", "Please select a server first.")
            return

        try:
            # Prepare automation data
            automation_data = {
                'motd_command': self.motd_cmd_var.get(),
                'motd_message': self.motd_msg_var.get(),
                'motd_interval': self.motd_interval_var.get(),
                'start_command': self.start_cmd_var.get(),
                'stop_command': self.stop_cmd_var.get(),
                'save_command': self.save_cmd_var.get(),
                'scheduled_restart_enabled': self.scheduled_restart_var.get(),
                'warning_command': self.warning_cmd_var.get(),
                'warning_intervals': self.warning_intervals_var.get(),
                'warning_message_template': self.warning_msg_template_var.get()
            }

            # Save using common function
            update_data = save_automation_settings({}, automation_data)

            # Update the server configuration
            success = self.db_manager.update_server(server_name, update_data)

            if success:
                messagebox.showinfo("Success", f"Automation settings saved for {server_name}")
                logger.info(f"Automation settings saved for {server_name}")
                # If we have a live server manager, reload the server config
                if isinstance(self.server_manager, ServerManager):
                    self.server_manager.reload_server(server_name)
            else:
                messagebox.showerror("Error", f"Failed to save settings for {server_name}")

        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")
            messagebox.showerror("Error", f"Failed to save settings: {str(e)}")

    def show(self):
        # Show the window and wait for it to close
        if self.window is not None:
            self.window.mainloop()

def open_automation_settings(parent=None, server_manager=None):
    # Function to open the automation settings window
    try:
        window = AutomationSettingsWindow(parent, server_manager)
        if parent:
            # Modal mode - wait for window to close
            parent.wait_window(window.window)
        else:
            # Standalone mode
            window.show()
    except Exception as e:
        logger.error(f"Error opening automation settings: {str(e)}")
        messagebox.showerror("Error", f"Failed to open automation settings: {str(e)}")

if __name__ == "__main__":
    # Test the window
    open_automation_settings()