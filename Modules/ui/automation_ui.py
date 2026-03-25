# Automation Settings Window
# -*- coding: utf-8 -*-
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path, setup_module_logging, load_automation_settings, save_automation_settings
from Modules.core.theme import get_theme_preference, apply_theme
setup_module_path()
from Modules.Database.server_configs_database import ServerConfigManager
from Modules.server.server_manager import ServerManager

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
        self.status_var = tk.StringVar(value="")

        # Create the window
        self.create_window()

    def create_window(self):
        # Create the main automation settings window
        self.window = tk.Toplevel(self.parent) if self.parent else tk.Tk()
        self.window.title("Server Automation Settings")
        self.window.geometry("900x730")
        self.window.minsize(860, 700)
        self.window.resizable(True, True)

        try:
            apply_theme(self.window, get_theme_preference("light"))
        except Exception as e:
            logger.debug(f"Could not apply saved theme to automation window: {e}")

        # Create main frame
        main_frame = ttk.Frame(self.window, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)

        # Create scrollable frame for settings
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Keep the scrollable content width in sync with canvas width to avoid dead space.
        def _on_canvas_configure(event):
            canvas.itemconfigure(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        scrollable_frame.columnconfigure(0, weight=1)

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
        title_label.pack(fill=tk.X, pady=(0, 12))

        # Server selection
        server_frame = ttk.LabelFrame(scrollable_frame, text="Select Server", padding="10")
        server_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(server_frame, text="Server:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.server_var = tk.StringVar()
        self.server_combo = ttk.Combobox(server_frame, textvariable=self.server_var,
                                        state="readonly")
        self.server_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.server_combo.bind("<<ComboboxSelected>>", self.on_server_selected)

        refresh_btn = ttk.Button(server_frame, text="Refresh", command=self.load_servers)
        refresh_btn.grid(row=0, column=2, padx=5, pady=5)
        server_frame.columnconfigure(1, weight=1)

        # Settings frame
        settings_frame = ttk.LabelFrame(scrollable_frame, text="Automation Settings", padding="10")
        settings_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        settings_frame.columnconfigure(0, weight=1)

        # MOTD Settings
        motd_frame = ttk.LabelFrame(settings_frame, text="MOTD (Message of the Day)", padding="8")
        motd_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(motd_frame, text="MOTD Command:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_cmd_var = tk.StringVar()
        motd_cmd_entry = ttk.Entry(motd_frame, textvariable=self.motd_cmd_var)
        motd_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(motd_frame, text="MOTD Message:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_msg_var = tk.StringVar()
        motd_msg_entry = ttk.Entry(motd_frame, textvariable=self.motd_msg_var)
        motd_msg_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(motd_frame, text="Broadcast Interval (minutes):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.motd_interval_var = tk.StringVar(value="0")
        motd_interval_entry = ttk.Entry(motd_frame, textvariable=self.motd_interval_var, width=10)
        motd_interval_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(motd_frame, text="0 = disabled", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)
        motd_frame.columnconfigure(1, weight=1)

        # Start Command
        start_frame = ttk.LabelFrame(settings_frame, text="Start Command", padding="8")
        start_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(start_frame, text="Command to run after server starts:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.start_cmd_var = tk.StringVar()
        start_cmd_entry = ttk.Entry(start_frame, textvariable=self.start_cmd_var)
        start_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        start_frame.columnconfigure(1, weight=1)

        # Scheduled Restart
        restart_frame = ttk.LabelFrame(settings_frame, text="Scheduled Restart", padding="8")
        restart_frame.pack(fill=tk.X, pady=(0, 10))

        self.scheduled_restart_var = tk.BooleanVar()
        scheduled_restart_check = ttk.Checkbutton(restart_frame,
                                                 text="Enable scheduled restart with warnings",
                                                 variable=self.scheduled_restart_var)
        scheduled_restart_check.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W, columnspan=3)

        ttk.Label(restart_frame, text="Warning Command:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_cmd_var = tk.StringVar()
        warning_cmd_entry = ttk.Entry(restart_frame, textvariable=self.warning_cmd_var)
        warning_cmd_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(restart_frame, text="Warning Intervals (minutes):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_intervals_var = tk.StringVar(value="30,15,10,5,1")
        warning_intervals_entry = ttk.Entry(restart_frame, textvariable=self.warning_intervals_var, width=20)
        warning_intervals_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(restart_frame, text="e.g., 30,15,10,5,1", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)

        ttk.Label(restart_frame, text="Warning Restart Message:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        self.warning_msg_template_var = tk.StringVar(value="Server restarting in {message}")
        warning_msg_entry = ttk.Entry(restart_frame, textvariable=self.warning_msg_template_var)
        warning_msg_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(restart_frame, text="Use {message} for time", font=("Segoe UI", 8)).grid(row=3, column=2, padx=5, pady=5, sticky=tk.W)
        restart_frame.columnconfigure(1, weight=1)

        # Stop Command
        stop_frame = ttk.LabelFrame(settings_frame, text="Stop Command", padding="8")
        stop_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(stop_frame, text="Command to gracefully stop the server:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.stop_cmd_var = tk.StringVar()
        stop_cmd_entry = ttk.Entry(stop_frame, textvariable=self.stop_cmd_var)
        stop_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        stop_frame.columnconfigure(1, weight=1)

        # Save Command
        save_frame = ttk.LabelFrame(settings_frame, text="Save Command", padding="8")
        save_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(save_frame, text="Command to save world/data before shutdown:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.save_cmd_var = tk.StringVar()
        save_cmd_entry = ttk.Entry(save_frame, textvariable=self.save_cmd_var)
        save_cmd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        save_frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        save_btn = ttk.Button(button_frame, text="Save Settings", command=self.save_settings)
        save_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.window.destroy)
        cancel_btn.pack(side=tk.RIGHT)

        # Inline status feedback (reduces modal popups for routine actions)
        status_label = ttk.Label(scrollable_frame, textvariable=self.status_var, foreground="gray")
        status_label.pack(fill=tk.X, pady=(8, 0))

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
            self._set_status(f"Failed to load servers: {str(e)}", is_error=True)

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
            self._set_status(f"Failed to load server settings: {str(e)}", is_error=True)

    def save_settings(self):
        # Save the automation settings for the current server
        server_name = self.server_var.get()
        if not server_name:
            self._set_status("Please select a server first.", is_error=True)
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
                self._set_status(f"Automation settings saved for {server_name}")
                logger.info(f"Automation settings saved for {server_name}")
                # If we have a live server manager, reload the server config
                if isinstance(self.server_manager, ServerManager):
                    self.server_manager.reload_server(server_name)
            else:
                self._set_status(f"Failed to save settings for {server_name}", is_error=True)

        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")
            self._set_status(f"Failed to save settings: {str(e)}", is_error=True)

    def _set_status(self, text, is_error=False):
        # Update inline status text to reduce modal UX interruptions.
        if self.status_var is not None:
            prefix = "Error: " if is_error else ""
            self.status_var.set(prefix + text)

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