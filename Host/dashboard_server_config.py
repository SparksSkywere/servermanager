# -*- coding: utf-8 -*-
# Dashboard server configuration dialogs - Configure, Java, Minecraft, Steam, Other server types

import os
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import TYPE_CHECKING, Any, Dict, Optional

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_dashboard_logger
from Host.dashboard_functions import (
    centre_window, load_appid_scanner_list,
    rename_server_configuration
)

if TYPE_CHECKING:
    from Modules.server_manager import ServerManager

logger = get_dashboard_logger()

class ServerConfigMixin:
    # Type stubs for attributes provided by ServerManagerDashboard at runtime
    if TYPE_CHECKING:
        root: tk.Tk
        server_manager: Optional[ServerManager]
        variables: Dict[str, Any]
        current_user: Any

        @property
        def paths(self) -> Dict[str, Any]: ...
        @property
        def server_manager_dir(self) -> str: ...
        @property
        def config(self) -> Dict[str, Any]: ...

        def get_current_server_list(self) -> Optional[ttk.Treeview]: ...
        def get_current_subhost(self) -> Optional[str]: ...
        def update_server_list(self, force_refresh: bool = False) -> None: ...

    def _create_scrollable_dialog(self, parent, title, width_ratio=0.9, height_ratio=0.8):
        # Create a scrollable dialog with standard setup
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog_width = min(900, int(parent.winfo_screenwidth() * width_ratio))
        dialog_height = min(850, int(parent.winfo_screenheight() * height_ratio))
        dialog.geometry(f"{dialog_width}x{dialog_height}")

        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def update_canvas_width(event=None):
            try:
                if canvas.winfo_width() > 1:
                    canvas.itemconfig(1, width=canvas.winfo_width())
            except tk.TclError:
                pass

        canvas.bind("<Configure>", update_canvas_width)

        scrollable_frame.columnconfigure(0, weight=1, minsize=200)
        scrollable_frame.columnconfigure(1, weight=1, minsize=200)
        scrollable_frame.columnconfigure(2, weight=1, minsize=200)
        scrollable_frame.columnconfigure(3, weight=1, minsize=200)

        return dialog, scrollable_frame

    def _create_labeled_entry(self, parent, label_text, variable, row, column=0, width=30):
        # Create a labeled entry field
        ttk.Label(parent, text=f"{label_text}:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=column, padx=10, pady=5, sticky=tk.W)
        entry = ttk.Entry(parent, textvariable=variable, width=width, font=("Segoe UI", 10))
        entry.grid(row=row, column=column+1, padx=10, pady=5, sticky=tk.EW)
        return entry

    def _create_labeled_combo(self, parent, label_text, variable, values, row, column=0, width=27):
        # Create a labeled combobox
        ttk.Label(parent, text=f"{label_text}:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=column, padx=10, pady=5, sticky=tk.W)
        combo = ttk.Combobox(parent, textvariable=variable, values=values,
                           state="readonly", width=width, font=("Segoe UI", 10))
        combo.grid(row=row, column=column+1, padx=10, pady=5, sticky=tk.W)
        return combo

    def _browse_appid(self, appid_var, parent_dialog):
        # Browse and select Steam dedicated server AppID
        appid_dialog = tk.Toplevel(parent_dialog)
        appid_dialog.title("Select Dedicated Server")
        appid_dialog.transient(parent_dialog)
        appid_dialog.grab_set()
        appid_dialog.geometry("600x500")

        search_frame = ttk.Frame(appid_dialog, padding=10)
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(5, 10))

        try:
            dedicated_servers_data, metadata = load_appid_scanner_list(self.server_manager_dir)

            if not dedicated_servers_data:
                error_msg = "Scanner AppID list not available - database must be populated first"
                logger.error(error_msg)
                messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
                return

            dedicated_servers = [
                {
                    "name": server.get("name", "Unknown Server"),
                    "appid": str(server.get("appid", "0")),
                    "developer": server.get("developer", ""),
                    "publisher": server.get("publisher", ""),
                    "description": server.get("description", ""),
                    "type": server.get("type", "Dedicated Server")
                }
                for server in dedicated_servers_data
            ]

            logger.info(f"Loaded {len(dedicated_servers)} dedicated servers from scanner (last updated: {metadata.get('last_updated', 'Unknown')})")

            if metadata.get('last_updated'):
                last_updated = metadata['last_updated']
                if 'T' in last_updated:
                    try:
                        dt = datetime.datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                        ttk.Label(search_frame, text=f"Data last updated: {formatted_date}",
                                foreground="gray", font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
                    except (ValueError, TypeError):
                        pass

        except Exception as e:
            error_msg = f"Failed to load AppID scanner data from database: {e}"
            logger.error(error_msg)
            messagebox.showerror("Database Error", f"{error_msg}\n\nThe database must be available and populated with AppID scanner data.")
            return

        list_frame = ttk.Frame(appid_dialog, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "appid", "developer", "type")
        server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        server_tree.heading("name", text="Server Name")
        server_tree.heading("appid", text="App ID")
        server_tree.heading("developer", text="Developer")
        server_tree.heading("type", text="Type")
        server_tree.column("name", width=300)
        server_tree.column("appid", width=80)
        server_tree.column("developer", width=150)
        server_tree.column("type", width=120)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
        server_tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def populate_servers(filter_text: str = ""):
            server_tree.delete(*server_tree.get_children())
            for server in dedicated_servers:
                server_name = server["name"]
                if not filter_text or filter_text.lower() in server_name.lower():
                    server_tree.insert("", tk.END, values=(
                        server_name,
                        server["appid"],
                        server.get("developer", "Unknown")[:25] + ("..." if len(server.get("developer", "")) > 25 else ""),
                        server.get("type", "Dedicated Server")
                    ))

        populate_servers()

        def on_search(*args):
            populate_servers(search_var.get())

        search_var.trace('w', on_search)

        def show_server_info(event):
            item = server_tree.selection()
            if item:
                selected_server = None
                item_values = server_tree.item(item[0])['values']
                for server in dedicated_servers:
                    if server["appid"] == str(item_values[1]):
                        selected_server = server
                        break

                if selected_server and selected_server.get("description"):
                    tooltip = tk.Toplevel(appid_dialog)
                    tooltip.wm_overrideredirect(True)
                    tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")

                    desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")

                    label = tk.Label(tooltip, text=f"{selected_server['name']}\n\n{desc}",
                                   background="lightyellow", relief="solid", borderwidth=1,
                                   wraplength=300, justify=tk.LEFT, font=("Segoe UI", 9))
                    label.pack()

                    tooltip.after(3000, tooltip.destroy)

        server_tree.bind('<Double-1>', show_server_info)

        button_frame = ttk.Frame(appid_dialog, padding=10)
        button_frame.pack(fill=tk.X)

        def select_server():
            selected = server_tree.selection()
            if selected:
                item = server_tree.item(selected[0])
                appid = item['values'][1]
                appid_var.set(appid)
                appid_dialog.destroy()
            else:
                messagebox.showinfo("No Selection", "Please select a server from the list.")

        def cancel_selection():
            appid_dialog.destroy()

        ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)

        centre_window(appid_dialog, 600, 500, parent_dialog)

    def _create_startup_configuration_section(self, parent, server_config, install_dir):
        # Create the startup configuration section and return all variables
        startup_frame = ttk.LabelFrame(parent, text="Startup Configuration", padding=10)
        startup_frame.pack(fill=tk.X, pady=(0, 15))

        exe_var = tk.StringVar(value=server_config.get('ExecutablePath', ''))
        exe_entry = self._create_labeled_entry(startup_frame, "Executable", exe_var, 0)

        def browse_exe():
            fp = filedialog.askopenfilename(initialdir=install_dir,
                filetypes=[("Executables", "*.exe;*.bat;*.cmd;*.ps1;*.sh"), ("All Files", "*.*")])
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp, install_dir]) == install_dir else fp
                exe_var.set(rel)
        ttk.Button(startup_frame, text="Browse", command=browse_exe).grid(row=0, column=2, padx=10, pady=5)

        stop_var = tk.StringVar(value=server_config.get('StopCommand', ''))
        self._create_labeled_entry(startup_frame, "Stop Command", stop_var, 1)

        args_frame = ttk.LabelFrame(startup_frame, text="Startup Arguments", padding=5)
        args_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky="ew")

        startup_mode_var = tk.StringVar(value="manual" if not server_config.get('UseConfigFile', False) else "config")

        manual_radio = ttk.Radiobutton(args_frame, text="Manual Arguments", variable=startup_mode_var, value="manual")
        manual_radio.grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)

        config_radio = ttk.Radiobutton(args_frame, text="Use Configuration File", variable=startup_mode_var, value="config")
        config_radio.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)

        manual_frame = ttk.Frame(args_frame)
        manual_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        ttk.Label(manual_frame, text="Startup Args:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        args_var = tk.StringVar(value=server_config.get('StartupArgs', ''))
        args_entry = ttk.Entry(manual_frame, textvariable=args_var, width=35)
        args_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)

        config_frame = ttk.Frame(args_frame)
        config_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        ttk.Label(config_frame, text="Config File:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        config_file_var = tk.StringVar(value=server_config.get('ConfigFilePath', ''))
        config_file_entry = ttk.Entry(config_frame, textvariable=config_file_var, width=25)
        config_file_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)

        def browse_config():
            fp = filedialog.askopenfilename(
                initialdir=install_dir,
                title="Select Configuration File",
                filetypes=[
                    ("Config Files", "*.cfg;*.conf;*.ini;*.json;*.xml;*.yaml;*.yml;*.properties;*.txt"),
                    ("All Files", "*.*")
                ]
            )
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp, install_dir]) == install_dir else fp
                config_file_var.set(rel)
        ttk.Button(config_frame, text="Browse", command=browse_config, width=10).grid(row=0, column=2, padx=5, pady=2)

        ttk.Label(config_frame, text="Config Argument:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        config_arg_var = tk.StringVar(value=server_config.get('ConfigArgument', '--config'))
        config_arg_entry = ttk.Entry(config_frame, textvariable=config_arg_var, width=15)
        config_arg_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(e.g., --config, -c, +exec)", foreground="gray").grid(row=1, column=2, padx=5, pady=2, sticky=tk.W)

        ttk.Label(config_frame, text="Additional Args:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        additional_args_var = tk.StringVar(value=server_config.get('AdditionalArgs', ''))
        additional_args_entry = ttk.Entry(config_frame, textvariable=additional_args_var, width=25)
        additional_args_entry.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(optional)", foreground="gray").grid(row=2, column=2, padx=5, pady=2, sticky=tk.W)

        startup_frame.grid_columnconfigure(0, weight=0, minsize=120)
        startup_frame.grid_columnconfigure(1, weight=1, minsize=200)
        startup_frame.grid_columnconfigure(2, weight=0, minsize=80)
        args_frame.grid_columnconfigure(0, weight=1)
        args_frame.grid_columnconfigure(1, weight=1)
        args_frame.grid_columnconfigure(2, weight=0)
        manual_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(2, weight=0)

        def toggle_startup_mode():
            mode = startup_mode_var.get()
            if mode == "manual":
                args_entry.config(state=tk.NORMAL)
                config_file_entry.config(state=tk.DISABLED)
                config_arg_entry.config(state=tk.DISABLED)
                additional_args_entry.config(state=tk.DISABLED)
            else:
                args_entry.config(state=tk.DISABLED)
                config_file_entry.config(state=tk.NORMAL)
                config_arg_entry.config(state=tk.NORMAL)
                additional_args_entry.config(state=tk.NORMAL)

        startup_mode_var.trace('w', lambda *args: toggle_startup_mode())
        toggle_startup_mode()

        return exe_var, stop_var, startup_mode_var, args_var, config_file_var, config_arg_var, additional_args_var

    def _create_command_preview_section(self, parent, exe_var, startup_mode_var, args_var,
                                      config_file_var, config_arg_var, additional_args_var,
                                      install_dir):
        # Create the command preview section
        preview_frame = ttk.LabelFrame(parent, text="Command Preview", padding=10)
        preview_frame.pack(fill=tk.X, pady=(0, 15))

        preview_text = tk.Text(preview_frame, height=3, wrap=tk.WORD, background="lightgray", font=("Consolas", 9))
        preview_text.pack(fill=tk.X, padx=5, pady=5)

        def update_preview():
            try:
                exe = exe_var.get().strip()
                mode = startup_mode_var.get()

                cmd_parts = []
                if exe:
                    exe_abs = exe if os.path.isabs(exe) else os.path.join(install_dir, exe)
                    cmd_parts.append(f'"{exe_abs}"')

                if mode == "manual":
                    args = args_var.get().strip()
                    if args:
                        cmd_parts.append(args)
                else:
                    config_file_path = config_file_var.get().strip()
                    config_arg = config_arg_var.get().strip()
                    additional_args = additional_args_var.get().strip()

                    if additional_args:
                        cmd_parts.append(additional_args)

                    if config_file_path and config_arg:
                        config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                        cmd_parts.append(f'{config_arg} "{config_abs}"')

                cmd_preview = ' '.join(cmd_parts) if cmd_parts else "No executable specified"

                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, cmd_preview)
            except Exception as e:
                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, f"Error generating preview: {str(e)}")

        def on_change(*args):
            update_preview()

        exe_var.trace('w', on_change)
        args_var.trace('w', on_change)
        startup_mode_var.trace('w', on_change)
        config_file_var.trace('w', on_change)
        config_arg_var.trace('w', on_change)
        additional_args_var.trace('w', on_change)

        update_preview()

        return update_preview

    def _create_scheduled_commands_section(self, parent, server_config):
        # Create the scheduled commands section and return all variables
        commands_frame = ttk.LabelFrame(parent, text="\u23f0 Scheduled Commands", padding=10)
        commands_frame.pack(fill=tk.X, pady=(0, 15))

        save_cmd_var = tk.StringVar(value=server_config.get('SaveCommand', ''))
        self._create_labeled_entry(commands_frame, "Save Command", save_cmd_var, 0, width=30)
        ttk.Label(commands_frame, text="Command to save world/data before shutdown (e.g., 'save-all', '/save')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)

        start_cmd_var = tk.StringVar(value=server_config.get('StartCommand', ''))
        self._create_labeled_entry(commands_frame, "Start Command", start_cmd_var, 1, width=30)
        ttk.Label(commands_frame, text="Command to run after server starts (e.g., 'say Server is ready!')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)

        warning_cmd_var = tk.StringVar(value=server_config.get('WarningCommand', ''))
        self._create_labeled_entry(commands_frame, "Warning Command", warning_cmd_var, 2, width=30)
        ttk.Label(commands_frame, text="Shutdown/restart warning (use {message} placeholder, e.g., 'broadcast {message}')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)

        warning_intervals_var = tk.StringVar(value=server_config.get('WarningIntervals', '15,10,5,1'))
        self._create_labeled_entry(commands_frame, "Warning Intervals", warning_intervals_var, 3, width=30)
        ttk.Label(commands_frame, text="Minutes before shutdown to warn (comma-separated, e.g., '15,10,5,1')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=3, column=2, padx=5, pady=5, sticky=tk.W)

        motd_cmd_var = tk.StringVar(value=server_config.get('MotdCommand', ''))
        self._create_labeled_entry(commands_frame, "MOTD Command", motd_cmd_var, 4, width=30)
        ttk.Label(commands_frame, text="Command to broadcast messages (e.g., 'say {message}', 'broadcast {message}')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=4, column=2, padx=5, pady=5, sticky=tk.W)

        motd_msg_var = tk.StringVar(value=server_config.get('MotdMessage', ''))
        self._create_labeled_entry(commands_frame, "MOTD Message", motd_msg_var, 5, width=30)
        ttk.Label(commands_frame, text="Default message for MOTD broadcasts",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=5, column=2, padx=5, pady=5, sticky=tk.W)

        motd_interval_var = tk.StringVar(value=str(server_config.get('MotdInterval', 0)))
        self._create_labeled_entry(commands_frame, "MOTD Interval", motd_interval_var, 6, width=30)
        ttk.Label(commands_frame, text="How often to broadcast MOTD (minutes, 0 = disabled)",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=6, column=2, padx=5, pady=5, sticky=tk.W)

        commands_frame.grid_columnconfigure(0, weight=0, minsize=140)
        commands_frame.grid_columnconfigure(1, weight=1, minsize=200)
        commands_frame.grid_columnconfigure(2, weight=0, minsize=300)

        return save_cmd_var, start_cmd_var, warning_cmd_var, warning_intervals_var, motd_cmd_var, motd_msg_var, motd_interval_var

    def configure_server(self):
        # Configure server settings including name, type, AppID, and startup configuration
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected[0])['values'][0]
        current_subhost = self.get_current_subhost()

        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return

        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return

        install_dir = server_config.get('InstallDir', '')

        dialog, scrollable_frame = self._create_scrollable_dialog(
            self.root, f"Configure Server: {server_name}")

        # Server Identity Section
        identity_frame = ttk.LabelFrame(scrollable_frame, text="Server Identity", padding=10)
        identity_frame.pack(fill=tk.X, pady=(0, 15))

        name_var = tk.StringVar(value=server_name)
        name_entry = self._create_labeled_entry(identity_frame, "Server Name", name_var, 0)

        current_server_type = server_config.get('Type', 'Other')
        type_var = tk.StringVar(value=current_server_type)
        type_combo = self._create_labeled_combo(identity_frame, "Server Type", type_var,
                                              ["Steam", "Minecraft", "Other"], 1)

        appid_var = tk.StringVar(value=str(server_config.get('appid', server_config.get('AppID', ''))))
        appid_entry = self._create_labeled_entry(identity_frame, "AppID", appid_var, 2, width=15)

        def browse_appid():
            self._browse_appid(appid_var, dialog)

        appid_browse_btn = ttk.Button(identity_frame, text="Browse", command=browse_appid, width=10)
        appid_browse_btn.grid(row=2, column=2, padx=5, pady=5)

        appid_help = ttk.Label(identity_frame, text="(Steam servers only)", foreground="gray", font=("Segoe UI", 8))
        appid_help.grid(row=2, column=3, padx=5, pady=5, sticky=tk.W)

        # Install directory (editable)
        ttk.Label(identity_frame, text="Install Directory:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        install_dir_var = tk.StringVar(value=install_dir)
        install_dir_entry = ttk.Entry(identity_frame, textvariable=install_dir_var, width=25, font=("Segoe UI", 9))
        install_dir_entry.grid(row=3, column=1, padx=10, pady=5, sticky=tk.EW)

        def browse_install_dir():
            current_dir = install_dir_var.get()
            if not os.path.exists(current_dir):
                current_dir = os.path.dirname(current_dir) if current_dir else ""

            selected_dir = filedialog.askdirectory(initialdir=current_dir, title="Select Server Installation Directory")
            if selected_dir:
                old_dir = install_dir_var.get()
                if old_dir != selected_dir:
                    install_dir_var.set(selected_dir)
                    update_paths_for_new_install_dir(old_dir, selected_dir)

        ttk.Button(identity_frame, text="Browse", command=browse_install_dir, width=8).grid(row=3, column=2, padx=5, pady=5)

        def test_install_dir_path():
            dir_path = install_dir_var.get().strip()
            if not dir_path:
                messagebox.showinfo("Test", "No install directory specified.")
                return
            if os.path.exists(dir_path) and os.path.isdir(dir_path):
                messagebox.showinfo("Test OK", f"Directory exists: {dir_path}")
            else:
                messagebox.showwarning("Test Failed", f"Directory not found: {dir_path}")

        ttk.Button(identity_frame, text="Test Path", command=test_install_dir_path, width=10).grid(row=3, column=3, padx=5, pady=5)

        def update_paths_for_new_install_dir(old_dir, new_dir):
            try:
                if not old_dir or not new_dir or old_dir == new_dir:
                    return

                exe_path = exe_var.get().strip()
                if exe_path and not os.path.isabs(exe_path):
                    old_full_path = os.path.join(old_dir, exe_path)
                    if not os.path.exists(old_full_path):
                        new_full_path = os.path.join(new_dir, os.path.basename(exe_path))
                        if os.path.exists(new_full_path):
                            exe_var.set(os.path.basename(exe_path))

                config_path = config_file_var.get().strip()
                if config_path and not os.path.isabs(config_path):
                    old_config_full = os.path.join(old_dir, config_path)
                    if not os.path.exists(old_config_full):
                        for ext in ['.cfg', '.conf', '.ini', '.json', '.yaml', '.yml', '.properties', '.txt']:
                            potential_config = os.path.join(new_dir, f"server{ext}")
                            if os.path.exists(potential_config):
                                config_file_var.set(f"server{ext}")
                                break

                update_preview()

            except Exception as e:
                logger.warning(f"Error updating paths for new install directory: {str(e)}")

        def on_install_dir_change(*args):
            update_preview()

        install_dir_var.trace('w', on_install_dir_change)

        identity_frame.grid_columnconfigure(1, weight=1)
        identity_frame.grid_columnconfigure(2, weight=0)
        identity_frame.grid_columnconfigure(3, weight=0)

        def toggle_appid_field():
            if type_var.get() == "Steam":
                appid_entry.config(state=tk.NORMAL)
                appid_browse_btn.config(state=tk.NORMAL)
                appid_help.config(text="(Required for Steam servers)")
            else:
                appid_entry.config(state=tk.DISABLED)
                appid_browse_btn.config(state=tk.DISABLED)
                appid_help.config(text="(Steam servers only)")

        type_var.trace('w', lambda *args: toggle_appid_field())
        toggle_appid_field()

        # Startup Configuration Section
        startup_vars = self._create_startup_configuration_section(scrollable_frame, server_config, install_dir)
        exe_var, stop_var, startup_mode_var, args_var, config_file_var, config_arg_var, additional_args_var = startup_vars

        # Preview command line
        update_preview = self._create_command_preview_section(scrollable_frame, exe_var, startup_mode_var, args_var,
                                                            config_file_var, config_arg_var, additional_args_var,
                                                            install_dir)

        # Scheduled Commands Section
        scheduled_vars = self._create_scheduled_commands_section(scrollable_frame, server_config)
        save_cmd_var, start_cmd_var, warning_cmd_var, warning_intervals_var, motd_cmd_var, motd_msg_var, motd_interval_var = scheduled_vars

        # Server Type-Specific Configuration Sections
        server_type = server_config.get('Type', 'Other')

        java_path_var = ram_var = jvm_args_var = mc_version_var = None
        auto_update_var = validate_files_var = None
        notes_var = None

        if server_type == "Minecraft":
            minecraft_section = ttk.LabelFrame(scrollable_frame, text="\U0001f3ae Minecraft Settings", padding=10)
            minecraft_section.pack(fill=tk.X, pady=(15, 0))

            java_info_frame = ttk.LabelFrame(minecraft_section, text="Java Configuration", padding=10)
            java_info_frame.pack(fill=tk.X, pady=(0, 10))

            ttk.Label(java_info_frame, text="Java Path:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            java_path_var = tk.StringVar(value=server_config.get("JavaPath", "java"))
            java_entry = ttk.Entry(java_info_frame, textvariable=java_path_var, width=30, font=("Segoe UI", 10))
            java_entry.grid(row=0, column=1, sticky=tk.EW, padx=10, pady=5)

            def browse_java():
                file_types = [("Java Executable", "java.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
                java_path = filedialog.askopenfilename(title="Select Java Executable", filetypes=file_types)
                if java_path:
                    java_path_var.set(java_path)

            ttk.Button(java_info_frame, text="Browse", command=browse_java).grid(row=0, column=2, padx=5, pady=5)

            def auto_detect_java():
                try:
                    from Modules.minecraft import get_recommended_java_for_minecraft
                    version = server_config.get("Version", "")
                    if version:
                        recommended = get_recommended_java_for_minecraft(version)
                        if recommended:
                            java_path_var.set(recommended["path"])
                            messagebox.showinfo("Auto-Detect", f"Found: {recommended['display_name']}")
                        else:
                            messagebox.showwarning("No Java Found", "No compatible Java installation found.")
                    else:
                        messagebox.showwarning("No Version", "Minecraft version not specified in server config.")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to detect Java: {str(e)}")

            ttk.Button(java_info_frame, text="Auto-Detect", command=auto_detect_java).grid(row=0, column=3, padx=5, pady=5)

            ttk.Label(java_info_frame, text="RAM (MB):", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            ram_var = tk.StringVar(value=str(server_config.get("RAM", 1024)))
            ttk.Entry(java_info_frame, textvariable=ram_var, width=15, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)

            ttk.Label(java_info_frame, text="JVM Args:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky=tk.W, pady=5, padx=10)
            jvm_args_var = tk.StringVar(value=server_config.get("JVMArgs", ""))
            ttk.Entry(java_info_frame, textvariable=jvm_args_var, width=30, font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=10, pady=5)

            ttk.Label(java_info_frame, text="MC Version:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky=tk.W, pady=5, padx=10)
            mc_version_var = tk.StringVar(value=server_config.get("Version", ""))
            ttk.Entry(java_info_frame, textvariable=mc_version_var, width=25, font=("Segoe UI", 10)).grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)

            java_info_frame.grid_columnconfigure(0, weight=0, minsize=100)
            java_info_frame.grid_columnconfigure(1, weight=1, minsize=150)
            java_info_frame.grid_columnconfigure(2, weight=0, minsize=80)
            java_info_frame.grid_columnconfigure(3, weight=0, minsize=100)

        elif server_type == "Steam":
            steam_section = ttk.LabelFrame(scrollable_frame, text="\U0001f682 Steam Settings", padding=10)
            steam_section.pack(fill=tk.X, pady=(15, 0))

            steam_info_frame = ttk.LabelFrame(steam_section, text="Steam Configuration", padding=10)
            steam_info_frame.pack(fill=tk.X, pady=(0, 10))

            auto_update_var = tk.BooleanVar(value=server_config.get("AutoUpdate", False))
            ttk.Checkbutton(steam_info_frame, text="Enable automatic updates", variable=auto_update_var).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)

            validate_files_var = tk.BooleanVar(value=server_config.get("ValidateFiles", False))
            ttk.Checkbutton(steam_info_frame, text="Validate files on update", variable=validate_files_var).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)

            steam_info_frame.grid_columnconfigure(0, weight=1)
            steam_info_frame.grid_columnconfigure(1, weight=0)

        elif server_type == "Other":
            other_section = ttk.LabelFrame(scrollable_frame, text="\U0001f527 Custom Server Settings", padding=10)
            other_section.pack(fill=tk.X, pady=(15, 0))

            custom_frame = ttk.LabelFrame(other_section, text="Custom Configuration", padding=10)
            custom_frame.pack(fill=tk.X, pady=(0, 10))

            ttk.Label(custom_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            ttk.Label(custom_frame, text="Other/Custom", font=("Segoe UI", 10)).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)

            ttk.Label(custom_frame, text="Configuration Notes:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            notes_var = tk.StringVar(value=server_config.get("Notes", ""))
            ttk.Entry(custom_frame, textvariable=notes_var, width=35, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)

            custom_frame.grid_columnconfigure(0, weight=0, minsize=140)
            custom_frame.grid_columnconfigure(1, weight=1, minsize=200)

        if name_var.get() != server_name or type_var.get() != current_server_type:
            warning_frame = ttk.Frame(scrollable_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))

            warning_label = ttk.Label(warning_frame,
                                    text="\u26a0 Warning: Changing server name or type will update configuration files. Ensure server is stopped.",
                                    foreground="orange", font=("Segoe UI", 9, "bold"), wraplength=650)
            warning_label.pack()

        # Button frame at bottom
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=10)

        def validate_inputs():
            errors = []
            new_name = name_var.get().strip()
            new_type = type_var.get()
            new_appid = appid_var.get().strip()

            if not new_name:
                errors.append("Server name cannot be empty")
            elif new_name != server_name and self.server_manager:
                try:
                    existing_config = self.server_manager.get_server_config(new_name)
                    if existing_config:
                        errors.append(f"Server name '{new_name}' already exists")
                except Exception:
                    pass

            if new_type == 'Steam':
                if not new_appid:
                    errors.append("AppID is required for Steam servers")
                elif not new_appid.isdigit():
                    errors.append("AppID must contain only numbers")

            return errors

        def save_configuration():
            errors = validate_inputs()
            if errors:
                messagebox.showerror("Validation Error", "\n".join(errors))
                return

            new_name = name_var.get().strip()
            new_type = type_var.get()
            new_appid = appid_var.get().strip()
            exe_path = exe_var.get().strip()
            stop_cmd = stop_var.get().strip()
            mode = startup_mode_var.get()

            try:
                exe_abs = exe_path if os.path.isabs(exe_path) else os.path.join(install_dir_var.get(), exe_path)
                if not os.path.exists(exe_abs):
                    if not messagebox.askyesno("Warning", f"Executable not found: {exe_abs}\nSave anyway?"):
                        return

                if mode == "manual":
                    startup_args = args_var.get().strip()
                    use_config = False
                    config_file_path = ""
                    config_arg = ""
                    additional_args = ""
                else:
                    startup_args = ""
                    use_config = True
                    config_file_path = config_file_var.get().strip()
                    config_arg = config_arg_var.get().strip()
                    additional_args = additional_args_var.get().strip()

                    if config_file_path:
                        config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir_var.get(), config_file_path)
                        if not os.path.exists(config_abs):
                            if not messagebox.askyesno("Warning", f"Config file not found: {config_abs}\nSave anyway?"):
                                return
                        if not config_arg:
                            messagebox.showerror("Validation Error", "Config argument is required when using config file.")
                            return
                    else:
                        messagebox.showerror("Validation Error", "Config file path is required when using config file mode.")
                        return

                name_changed = new_name != server_name
                type_changed = new_type != current_server_type
                current_appid_str = str(server_config.get('appid', server_config.get('AppID', ''))) if server_config else ''
                appid_changed = new_type == 'Steam' and new_appid != current_appid_str

                if name_changed or type_changed or appid_changed:
                    if server_config:
                        updated_config = server_config.copy()
                        updated_config['type'] = new_type
                        if new_type == 'Steam' and new_appid:
                            updated_config['appid'] = int(new_appid)
                            updated_config['AppID'] = int(new_appid)

                    if name_changed:
                        success, message = rename_server_configuration(server_name, new_name,
                                                                      self.server_manager)
                        if not success:
                            messagebox.showerror("Error", f"Failed to rename server: {message}")
                            return
                        current_server_name = new_name
                    else:
                        try:
                            if not self.server_manager:
                                messagebox.showerror("Error", "Server manager not available")
                                return

                            current_config = self.server_manager.get_server_config(server_name)
                            if not current_config:
                                messagebox.showerror("Error", "Could not load server configuration")
                                return

                            current_config['type'] = new_type
                            if new_type == 'Steam' and new_appid:
                                current_config['appid'] = int(new_appid)
                                current_config['AppID'] = int(new_appid)

                            self.server_manager.update_server(server_name, current_config)
                            logger.info(f"Updated server type/AppID for '{server_name}'")
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to update server configuration: {str(e)}")
                            return
                        current_server_name = server_name
                else:
                    current_server_name = server_name

                if self.server_manager:
                    success, message = self.server_manager.update_server_config(
                        current_server_name, exe_path, startup_args, stop_cmd, use_config_file=use_config,
                        config_file_path=config_file_path, config_argument=config_arg, additional_args=additional_args
                    )
                else:
                    success = False
                    message = "Server manager not available"

                if success and install_dir_var.get() != server_config.get('InstallDir'):
                    try:
                        if self.server_manager:
                            current_config = self.server_manager.get_server_config(current_server_name)
                            if current_config:
                                current_config['InstallDir'] = install_dir_var.get()
                                self.server_manager.update_server(current_server_name, current_config)
                                logger.info(f"Updated InstallDir for server '{current_server_name}' to: {install_dir_var.get()}")
                    except Exception as e:
                        logger.warning(f"Failed to update InstallDir: {str(e)}")

                if success:
                    try:
                        if self.server_manager:
                            updated_config = self.server_manager.get_server_config(current_server_name)
                            if updated_config:
                                updated_config['SaveCommand'] = save_cmd_var.get().strip()
                                updated_config['StartCommand'] = start_cmd_var.get().strip()
                                updated_config['WarningCommand'] = warning_cmd_var.get().strip()
                                updated_config['WarningIntervals'] = warning_intervals_var.get().strip()
                                updated_config['MotdCommand'] = motd_cmd_var.get().strip()
                                updated_config['MotdMessage'] = motd_msg_var.get().strip()
                                try:
                                    updated_config['MotdInterval'] = int(motd_interval_var.get().strip()) if motd_interval_var.get().strip() else 0
                                except (ValueError, TypeError):
                                    updated_config['MotdInterval'] = 0
                                self.server_manager.update_server(current_server_name, updated_config)
                                logger.info(f"Updated scheduled command configuration for server '{current_server_name}'")
                    except Exception as e:
                        logger.warning(f"Failed to update scheduled command settings: {str(e)}")

                if success and new_type:
                    try:
                        if self.server_manager:
                            updated_config = self.server_manager.get_server_config(current_server_name)
                            if updated_config:
                                if new_type == "Minecraft":
                                    if java_path_var is not None:
                                        updated_config['JavaPath'] = java_path_var.get()
                                    if ram_var is not None:
                                        try:
                                            updated_config['RAM'] = int(ram_var.get())
                                        except ValueError:
                                            pass
                                    if jvm_args_var is not None:
                                        updated_config['JVMArgs'] = jvm_args_var.get()
                                    if mc_version_var is not None:
                                        updated_config['Version'] = mc_version_var.get()
                                elif new_type == "Steam":
                                    if auto_update_var is not None:
                                        updated_config['AutoUpdate'] = auto_update_var.get()
                                    if validate_files_var is not None:
                                        updated_config['ValidateFiles'] = validate_files_var.get()
                                elif new_type == "Other":
                                    if notes_var is not None:
                                        updated_config['Notes'] = notes_var.get()

                                self.server_manager.update_server(current_server_name, updated_config)
                                logger.info(f"Updated {new_type}-specific configuration for server '{current_server_name}'")
                    except Exception as e:
                        logger.warning(f"Failed to update {new_type}-specific settings: {str(e)}")

                    actions = []
                    if name_changed:
                        actions.append(f"renamed to '{new_name}'")
                    if type_changed:
                        actions.append(f"changed type to '{new_type}'")
                    if appid_changed:
                        actions.append(f"updated AppID to {new_appid}")

                    if actions:
                        username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                        logger.info(f"USER_ACTION: {username} - Server '{server_name}' {', '.join(actions)}")

                    username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                    logger.info(f"USER_ACTION: {username} updated startup configuration for server '{current_server_name}'")

                    messagebox.showinfo("Success", "Server configuration saved successfully.")
                    dialog.destroy()

                    self.update_server_list(force_refresh=True)
                else:
                    messagebox.showerror("Error", f"Failed to save startup configuration: {message}")

            except Exception as e:
                logger.error(f"Error saving server configuration: {str(e)}")
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")

        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save Configuration", command=save_configuration).pack(side=tk.RIGHT)

        centre_window(dialog, None, None, self.root)