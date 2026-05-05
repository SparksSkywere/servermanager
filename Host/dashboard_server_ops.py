# -*- coding: utf-8 -*-
# Dashboard server operations - Start, stop, restart, kill, update, import, export

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Any, Dict, Optional

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path
setup_module_path()

from Modules.core.server_logging import get_dashboard_logger
from Host.dashboard_functions import (
    centre_window, update_server_status_in_treeview, open_directory_in_explorer,
    import_server_from_directory_dialog, import_server_from_export_dialog,
    export_server_dialog, create_progress_dialog_with_console,
    start_server_operation, stop_server_operation, restart_server_operation,
    cleanup_orphaned_process_entries, cleanup_orphaned_relay_files # type: ignore
)
from debug.debug import get_server_process_details, log_exception, monitor_process_resources

if TYPE_CHECKING:
    from Modules.server.server_manager import ServerManager
    from Modules.server.server_console import ConsoleManager
    from Modules.updates.server_updates import ServerUpdateManager

logger = get_dashboard_logger()

class ServerOpsMixin:
    # Type stubs for attributes provided by ServerManagerDashboard at runtime
    if TYPE_CHECKING:
        root: tk.Tk
        server_manager: Optional[ServerManager]
        console_manager: Optional[ConsoleManager]
        update_manager: Optional[ServerUpdateManager]
        variables: Dict[str, Any]
        current_user: Any

        @property
        def paths(self) -> Dict[str, Any]: ...
        @property
        def server_manager_dir(self) -> str: ...
        @property
        def config(self) -> Dict[str, Any]: ...

        def get_current_server_list(self) -> Optional[ttk.Treeview]: ...
        def update_server_list(self, force_refresh: bool = False) -> None: ...
        def update_system_info(self) -> None: ...
        def update_webserver_status(self) -> None: ...

    def _make_server_op_callback(self, error_as_info=False):
        # Create a standard server operation completion callback.
        # error_as_info=True routes failure messages to info dialogs for non-critical operations.
        def on_completion(success, message):
            def update_ui():
                if not success:
                    if error_as_info:
                        messagebox.showinfo("Info", message)
                    else:
                        messagebox.showerror("Error", message)
                self.update_server_list(force_refresh=True)
            self.root.after(0, update_ui)
        return on_completion

    @staticmethod
    def _make_progress_callback(progress_dialog, scheduled=False):
        # Create a progress callback for update/restart operations.
        # scheduled=True enables logger output and supports a missing progress dialog.
        def progress_callback(message):
            try:
                if progress_dialog and hasattr(progress_dialog, 'update_console'):
                    progress_dialog.update_console(message)
                elif not scheduled:
                    print(message)
                if scheduled:
                    logger.info(message)
            except Exception as e:
                if not scheduled:
                    print(f"Console callback error: {e}, message: {message}")
                logger.error(f"Console callback error: {e}, message: {message}")
        return progress_callback

    def start_server(self):
        # Start the selected game server (Steam/Minecraft/Other)
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return

        self.update_server_status(server_name, "Starting...")

        start_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=self._make_server_op_callback()
        )

    def stop_server(self):
        # Stop the selected game server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return

        confirm = messagebox.askyesno("Confirm Stop",
                                    f"Are you sure you want to stop the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        if not confirm:
            return

        self.update_server_status(server_name, "Stopping...")

        stop_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=self._make_server_op_callback(error_as_info=True)
        )

    def restart_server(self):
        # Restart the selected game server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return

        confirm = messagebox.askyesno("Confirm Restart",
                                    f"Are you sure you want to restart the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        if not confirm:
            return

        self.update_server_status(server_name, "Restarting...")

        restart_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=self._make_server_op_callback()
        )

    def view_process_details(self):
        # View detailed process information for a server using debug module
        from tkinter import scrolledtext

        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        try:
            process_details = get_server_process_details(server_name)

            if "error" in process_details:
                messagebox.showerror("Error", process_details["error"])
                return

            # Determine memory display based on server/process type
            memory_info = process_details['memory_info']
            is_java_process = False
            try:
                cmdline = process_details.get('cmdline', [])
                is_java_process = any('java' in arg.lower() or 'javaw' in arg.lower() for arg in cmdline)
            except Exception:
                pass
            if not is_java_process:
                # Fall back to server type from config
                srv_cfg = process_details.get('server_config', {})
                if srv_cfg.get('Type', '').lower() == 'minecraft':
                    is_java_process = True

            if is_java_process:
                memory_display = f"{memory_info['vms'] / (1024 * 1024):.1f} MB (JVM)"
            else:
                memory_display = f"{memory_info['rss'] / (1024 * 1024):.1f} MB"

            dialog = tk.Toplevel(self.root)
            dialog.title(f"Process Details: {server_name} (PID: {process_details['pid']})")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.minsize(760, 620)

            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)

            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

            # Basic Info Tab
            basic_frame = ttk.Frame(notebook)
            notebook.add(basic_frame, text="Basic Info")

            info_grid = ttk.Frame(basic_frame)
            info_grid.pack(fill=tk.X, padx=10, pady=10)
            info_grid.columnconfigure(1, weight=1)
            info_grid.columnconfigure(3, weight=1)

            info_items = [
                ("PID:", str(process_details["pid"])),
                ("Status:", process_details["status"]),
                ("Name:", process_details["name"]),
                ("Server Uptime:", process_details.get("server_uptime", "Unknown")),
                ("CPU Usage:", f"{process_details['cpu_percent']:.1f}%"),
                ("Memory Usage:", memory_display),
                ("Memory %:", f"{process_details['memory_percent']:.1f}%"),
                ("Threads:", str(process_details["num_threads"]))
            ]

            for i, (label, value) in enumerate(info_items):
                row = i // 2
                col = (i % 2) * 2
                ttk.Label(info_grid, text=label, width=15).grid(row=row, column=col, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=value).grid(row=row, column=col+1, sticky=tk.W, padx=5, pady=2)

            if "exe" in process_details and process_details["exe"] != "Access Denied":
                ttk.Label(info_grid, text="Executable:").grid(row=len(info_items)//2 + 1, column=0, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=process_details["exe"]).grid(row=len(info_items)//2 + 1, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)

            # Resources Tab
            resources_frame = ttk.Frame(notebook)
            notebook.add(resources_frame, text="Resources")

            resource_text = scrolledtext.ScrolledText(resources_frame, width=80, height=20)
            resource_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            jvm_section = ""
            if is_java_process:
                jvm_section = f"JVM Heap (VMS): {memory_info['vms'] / (1024 * 1024):.2f} MB\n"

            resource_info = f"""Memory Information:
RSS (Resident Set Size): {memory_info['rss'] / (1024 * 1024):.2f} MB
VMS (Virtual Memory Size): {memory_info['vms'] / (1024 * 1024):.2f} MB
{jvm_section}Memory Percentage: {process_details['memory_percent']:.2f}%
Process Type: {'Java/JVM' if is_java_process else 'Native'}

Open Files: {process_details.get('open_files_count', 'N/A')}
Network Connections: {process_details.get('connections_count', 'N/A')}

Command Line: {' '.join(process_details.get('cmdline', ['N/A']))}

Working Directory: {process_details.get('cwd', 'N/A')}
"""
            resource_text.insert(tk.END, resource_info)
            resource_text.config(state=tk.DISABLED)

            # Children Tab
            if process_details.get("children"):
                children_frame = ttk.Frame(notebook)
                notebook.add(children_frame, text="Child Processes")

                child_list = ttk.Treeview(children_frame, columns=("pid", "name", "status", "cpu", "memory"), show="headings")
                child_list.heading("pid", text="PID")
                child_list.heading("name", text="Name")
                child_list.heading("status", text="Status")
                child_list.heading("cpu", text="CPU %")
                child_list.heading("memory", text="Memory MB")

                child_list.column("pid", width=60)
                child_list.column("name", width=200)
                child_list.column("status", width=80)
                child_list.column("cpu", width=80)
                child_list.column("memory", width=100)

                child_scroll = ttk.Scrollbar(children_frame, orient=tk.VERTICAL, command=child_list.yview)
                child_list.configure(yscrollcommand=child_scroll.set)

                child_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                child_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

                for child in process_details["children"]:
                    child_list.insert("", tk.END, values=(
                        child["pid"], child["name"], child["status"],
                        f"{child['cpu_percent']:.1f}", f"{child['memory_mb']:.1f}"
                    ))

            # Network Tab
            if process_details.get("connections"):
                network_frame = ttk.Frame(notebook)
                notebook.add(network_frame, text="Network")

                conn_list = ttk.Treeview(network_frame, columns=("family", "type", "local", "remote", "status"), show="headings")
                conn_list.heading("family", text="Family")
                conn_list.heading("type", text="Type")
                conn_list.heading("local", text="Local Address")
                conn_list.heading("remote", text="Remote Address")
                conn_list.heading("status", text="Status")

                conn_scroll = ttk.Scrollbar(network_frame, orient=tk.VERTICAL, command=conn_list.yview)
                conn_list.configure(yscrollcommand=conn_scroll.set)

                conn_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                conn_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

                for conn in process_details["connections"]:
                    conn_list.insert("", tk.END, values=(
                        conn["family"], conn["type"], conn["local_address"],
                        conn["remote_address"], conn["status"]
                    ))

            # Log Files Tab
            server_config = process_details.get("server_config", {})
            if server_config.get("LogStdout") or server_config.get("LogStderr"):
                logs_frame = ttk.Frame(notebook)
                notebook.add(logs_frame, text="Log Files")

                log_grid = ttk.Frame(logs_frame)
                log_grid.pack(fill=tk.X, padx=10, pady=10)
                log_grid.columnconfigure(1, weight=1)

                row = 0
                if server_config.get("LogStdout"):
                    ttk.Label(log_grid, text="Stdout Log:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
                    ttk.Label(log_grid, text=server_config["LogStdout"]).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)

                    def open_stdout_log():
                        try:
                            if os.path.exists(server_config["LogStdout"]):
                                os.startfile(server_config["LogStdout"])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")

                    ttk.Button(log_grid, text="Open", command=open_stdout_log, width=10).grid(row=row, column=2, padx=5, pady=2)
                    row += 1

                if server_config.get("LogStderr"):
                    ttk.Label(log_grid, text="Stderr Log:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=2)
                    ttk.Label(log_grid, text=server_config["LogStderr"]).grid(row=row, column=1, sticky=tk.W, padx=5, pady=2)

                    def open_stderr_log():
                        try:
                            if os.path.exists(server_config["LogStderr"]):
                                os.startfile(server_config["LogStderr"])
                            else:
                                messagebox.showinfo("Not Found", "Log file not found.")
                        except Exception as e:
                            messagebox.showerror("Error", f"Could not open log file: {str(e)}")

                    ttk.Button(log_grid, text="Open", command=open_stderr_log, width=10).grid(row=row, column=2, padx=5, pady=2)

            # Action buttons
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=10)

            def refresh_process_info():
                dialog.destroy()
                self.view_process_details()

            ttk.Button(button_frame, text="Refresh", command=refresh_process_info, width=15).pack(side=tk.LEFT, padx=(0, 10))

            def monitor_process():
                try:
                    monitor_data = monitor_process_resources(process_details["pid"], 10)
                    if "error" not in monitor_data:
                        messagebox.showinfo("Monitoring Complete",
                                          f"Monitored process for {monitor_data['duration']} seconds.\n"
                                          f"Collected {monitor_data['sample_count']} samples.")
                    else:
                        messagebox.showerror("Error", monitor_data["error"])
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to monitor process: {str(e)}")

            ttk.Button(button_frame, text="Monitor (10s)", command=monitor_process, width=15).pack(side=tk.LEFT, padx=(0, 10))

            def stop_from_details():
                dialog.destroy()
                self.stop_server()

            ttk.Button(button_frame, text="Stop Process", command=stop_from_details, width=15).pack(side=tk.RIGHT, padx=(0, 10))
            ttk.Button(button_frame, text="Close", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=(0, 10))

            centre_window(dialog, 700, 600, self.root)

        except Exception as e:
            log_exception(e, f"Error viewing process details for {server_name}")
            messagebox.showerror("Error", f"Failed to get process details: {str(e)}")

    def show_server_console(self):
        # Show console window for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        try:
            if not self.console_manager:
                messagebox.showerror("Console Error", "Console manager not available.")
                return

            server_config = None
            if self.server_manager:
                try:
                    server_config = self.server_manager.get_server_config(server_name)
                except Exception as e:
                    logger.warning(f"Could not get server config for {server_name}: {e}")

            if not server_config:
                server_values = current_list.item(selected_items[0])['values']
                server_config = {
                    'name': server_name,
                    'type': 'Unknown',
                    'pid': server_values[2] if len(server_values) > 2 else None
                }

            success = self.console_manager.show_console(server_name, parent=self.root)

            if success:
                username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                logger.info(f"USER_ACTION: {username} opened console for server: {server_name}")
            else:
                messagebox.showerror("Console Error", f"Failed to open console for {server_name}")

        except Exception as e:
            log_exception(e, f"Error showing console for {server_name}")
            messagebox.showerror("Console Error", f"Failed to open console:\n{str(e)}")

    def update_server_status(self, server_name, status):
        # Update the status of a server in the UI - thread-safe
        def _update():
            try:
                current_list = self.get_current_server_list()
                if current_list:
                    update_server_status_in_treeview(current_list, server_name, status)
                    self.root.update_idletasks()
            except Exception as e:
                logger.error(f"Error updating server status: {str(e)}")

        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)

    def open_server_directory(self):
        # Open the server's installation directory in file explorer
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        try:
            if not self.server_manager:
                messagebox.showerror("Error", "Server manager not available")
                return

            server_config = self.server_manager.get_server_config(server_name)

            if not server_config:
                messagebox.showerror("Error", f"Server configuration not found: {server_name}")
                return

            install_dir = server_config.get('InstallDir', '')

            if not install_dir:
                messagebox.showerror("Error", "Server installation directory not configured.")
                return

            success, message = open_directory_in_explorer(install_dir)
            if success:
                logger.info(f"Opened directory for server '{server_name}': {install_dir}")
            else:
                messagebox.showerror("Error", message)

        except Exception as e:
            logger.error(f"Error opening server directory: {str(e)}")
            messagebox.showerror("Error", f"Failed to open server directory: {str(e)}")

    def remove_server(self):
        # Remove the selected server configuration and optionally files
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected_items[0])['values'][0]

        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return

        try:
            if self.server_manager:
                success, message = self.server_manager.uninstall_server(
                    server_name, remove_files=False
                )
            else:
                success = False
                message = "Server manager not initialised"

            if success:
                self.update_server_list(force_refresh=True)
                messagebox.showinfo("Success", message)
            else:
                messagebox.showerror("Error", message)

        except Exception as e:
            logger.error(f"Error removing server: {str(e)}")
            messagebox.showerror("Error", f"Failed to remove server: {str(e)}")

    def import_server(self):
        # Enhanced import server functionality with support for exported configurations
        try:
            import_dialog = tk.Toplevel(self.root)
            import_dialog.title("Import Server")
            import_dialog.transient(self.root)
            import_dialog.grab_set()

            main_frame = ttk.Frame(import_dialog, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            ttk.Label(main_frame, text="Select Import Method:", font=("Segoe UI", 12, "bold")).pack(pady=10)

            import_type = tk.StringVar(value="directory")

            ttk.Radiobutton(main_frame, text="Import from existing directory",
                          variable=import_type, value="directory").pack(anchor=tk.W, pady=5)

            ttk.Radiobutton(main_frame, text="Import from exported configuration file",
                          variable=import_type, value="exported").pack(anchor=tk.W, pady=5)

            button_frame = ttk.Frame(main_frame)
            button_frame.pack(pady=20)

            def proceed_import():
                import_dialog.destroy()
                if import_type.get() == "directory":
                    self.import_server_from_directory()
                else:
                    self.import_server_from_export()

            ttk.Button(button_frame, text="Continue", command=proceed_import, width=15).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Cancel", command=import_dialog.destroy, width=15).pack(side=tk.LEFT, padx=(0, 10))

            centre_window(import_dialog, 400, 300, self.root)

        except Exception as e:
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to open import dialog: {str(e)}")

    def import_server_from_directory(self):
        # Import an existing server from a directory
        import_server_from_directory_dialog(
            self.root, self.paths, self.server_manager_dir,
            update_callback=lambda: self.update_server_list(force_refresh=True),
            dashboard_server_manager=self.server_manager
        )

    def import_server_from_export(self):
        # Import server from exported configuration file
        import_server_from_export_dialog(
            self.root, self.paths, self.server_manager_dir,
            update_callback=lambda: self.update_server_list(force_refresh=True)
        )

    def export_server(self):
        # Export server configuration for use on other hosts or clusters
        current_list = self.get_current_server_list()
        if current_list:
            export_server_dialog(self.root, current_list, self.paths)

    def refresh_all(self):
        # Refresh all dashboard data
        try:
            logger.info("Refreshing all dashboard data")

            # Clean stale process metadata before rebuilding the UI list.
            if self.server_manager:
                cleanup_orphaned_process_entries(self.server_manager, logger)
            cleanup_orphaned_relay_files(logger)

            if self.console_manager and hasattr(self.console_manager, 'prune_stale_consoles'):
                self.console_manager.prune_stale_consoles()

            self.update_system_info()
            self.update_server_list(force_refresh=True)
            self.update_webserver_status()
        except Exception as e:
            logger.error(f"Error refreshing dashboard: {str(e)}")
            messagebox.showerror("Error", f"Failed to refresh dashboard: {str(e)}")

    def check_server_updates(self):
        # Check for updates for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected[0])['values'][0]

        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return

        if not self.server_manager:
            messagebox.showerror("Error", "Server manager not available.")
            return

        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return

        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Update checking is only available for Steam servers.")
            return

        progress_dialog = create_progress_dialog_with_console(self.root, f"Checking Updates - {server_name}")

        def update_check_worker():
            try:
                def progress_callback(message):
                    try:
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        else:
                            print(message)
                    except (tk.TclError, AttributeError):
                        print(message)

                if self.update_manager:
                    success, message, has_updates = self.update_manager.check_for_updates(
                        server_name, server_config['AppID'], progress_callback=progress_callback
                    )
                else:
                    success, message, has_updates = False, "Update manager not available", False

                if success:
                    status = "Updates available!" if has_updates else "Server is up to date"
                    progress_callback(f"[RESULT] {status}")

                    def show_result():
                        if has_updates:
                            result = messagebox.askyesno("Updates Available",
                                f"Updates are available for {server_name}.\n\nWould you like to update now?")
                            progress_dialog.complete("Check completed", auto_close=True)
                            if result:
                                self.update_server_now(server_name, server_config)
                        else:
                            messagebox.showinfo("No Updates", f"{server_name} is up to date.")
                            progress_dialog.complete("Check completed", auto_close=True)

                    self.root.after(0, show_result)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Check Failed", message)
                        progress_dialog.complete("Check failed", auto_close=True)
                    self.root.after(0, show_error)

            except Exception as e:
                error_msg = f"Update check failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    progress_dialog.complete("Check failed", auto_close=True)
                self.root.after(0, show_exception_error)

        check_thread = threading.Thread(target=update_check_worker, daemon=True)
        check_thread.start()

    def update_server(self):
        # Update the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected[0])['values'][0]

        if not self.server_manager:
            messagebox.showerror("Error", "Server manager not available.")
            return

        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return

        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Updates are only available for Steam servers.")
            return

        result = messagebox.askyesno("Confirm Update",
            f"Are you sure you want to update {server_name}?\n\n"
            "The server will be stopped during the update process if it's currently running.")

        if result:
            self.update_server_now(server_name, server_config)

    def update_server_now(self, server_name, server_config):
        # Perform server update with progress dialog
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return

        progress_dialog = create_progress_dialog_with_console(self.root, f"Updating Server - {server_name}")

        def update_worker():
            try:
                progress_callback = self._make_progress_callback(progress_dialog)

                if self.update_manager:
                    success, message = self.update_manager.update_server(
                        server_name, server_config, progress_callback=progress_callback, scheduled=False
                    )
                else:
                    success, message = False, "Update manager not available"

                if success:
                    progress_callback(f"[SUCCESS] {message}")
                    def show_success():
                        messagebox.showinfo("Update Complete", f"{server_name} has been updated successfully!")
                        progress_dialog.complete("Update completed", auto_close=True)
                        self.update_server_list()
                    self.root.after(0, show_success)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Failed", message)
                        progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_error)

            except Exception as e:
                error_msg = f"Server update failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    progress_dialog.complete("Update failed", auto_close=True)
                self.root.after(0, show_exception_error)

        update_thread = threading.Thread(target=update_worker, daemon=True)
        update_thread.start()

    def update_all_servers(self, scheduled=False):
        # Update all Steam servers
        if not self.update_manager:
            if not scheduled:
                messagebox.showerror("Error", "Update manager not available.")
            return

        if not scheduled:
            result = messagebox.askyesno("Confirm Update All",
                "Are you sure you want to update all Steam servers?\n\n"
                "This will stop all running Steam servers during the update process.")
            if not result:
                return

        progress_dialog = None
        if not scheduled:
            progress_dialog = create_progress_dialog_with_console(self.root, "Updating All Steam Servers")

        def update_all_worker():
            try:
                progress_callback = self._make_progress_callback(progress_dialog, scheduled=scheduled)

                if self.update_manager:
                    results = self.update_manager.update_all_steam_servers(progress_callback=progress_callback, scheduled=scheduled)
                else:
                    results = {"error": (False, "Update manager not available")}

                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])

                if progress_callback:
                    progress_callback(f"\n[SUMMARY] Updates complete: {successes} successful, {failures} failed")

                def show_results():
                    if not scheduled:
                        if failures > 0:
                            failed_servers = [name for name, (success, _) in results.items() if not success]
                            messagebox.showwarning("Some Updates Failed",
                                f"Update completed with some failures.\n\n"
                                f"Successful: {successes}\nFailed: {failures}\n\n"
                                f"Failed servers: {', '.join(failed_servers)}")
                        else:
                            messagebox.showinfo("Updates Complete",
                                f"All Steam servers updated successfully!\n\nUpdated {successes} servers.")

                        if progress_dialog:
                            progress_dialog.complete("Updates completed", auto_close=True)
                    else:
                        if failures > 0:
                            failed_servers = [name for name, (success, _) in results.items() if not success]
                            logger.warning(f"Scheduled update completed with failures. Successful: {successes}, Failed: {failures}. Failed servers: {', '.join(failed_servers)}")
                        else:
                            logger.info(f"Scheduled update completed successfully. Updated {successes} servers.")

                    self.update_server_list()

                self.root.after(0, show_results)

            except Exception as e:
                error_msg = f"Batch update failed: {str(e)}"
                logger.error(error_msg)
                if not scheduled:
                    def show_exception_error():
                        messagebox.showerror("Error", error_msg)
                        if progress_dialog:
                            progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_exception_error)

        update_thread = threading.Thread(target=update_all_worker, daemon=True)
        update_thread.start()

    def restart_all_servers(self):
        # Restart all servers
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return

        all_servers = []
        if self.server_manager:
            servers = self.server_manager.get_all_servers()
            all_servers = list(servers.keys())

        if not all_servers:
            messagebox.showinfo("No Servers", "No servers found to restart.")
            return

        result = messagebox.askyesno("Confirm Batch Restart",
            f"Restart all {len(all_servers)} servers?\n\n"
            f"Servers to restart: {', '.join(all_servers)}")

        if not result:
            return

        progress_dialog = create_progress_dialog_with_console(self.root, "Restarting All Servers")

        def restart_all_worker():
            try:
                progress_callback = self._make_progress_callback(progress_dialog)

                if self.update_manager:
                    results = self.update_manager.restart_all_servers(progress_callback=progress_callback, scheduled=False)
                else:
                    results = {"error": (False, "Update manager not available")}

                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])

                progress_callback(f"\n[SUMMARY] Restarts complete: {successes} successful, {failures} failed")

                def show_results():
                    if failures > 0:
                        failed_servers = [name for name, (success, _) in results.items() if not success]
                        messagebox.showwarning("Some Restarts Failed",
                            f"Restart completed with some failures.\n\n"
                            f"Successful: {successes}\nFailed: {failures}\n\n"
                            f"Failed servers: {', '.join(failed_servers)}")
                    else:
                        messagebox.showinfo("Restarts Complete",
                            f"All servers restarted successfully!\n\nRestarted {successes} servers.")

                    progress_dialog.complete("Restarts completed", auto_close=True)
                    self.update_server_list()

                self.root.after(0, show_results)

            except Exception as e:
                error_msg = f"Batch restart failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    progress_dialog.complete("Restart failed", auto_close=True)
                self.root.after(0, show_exception_error)

        restart_thread = threading.Thread(target=restart_all_worker, daemon=True)
        restart_thread.start()

    def kill_server_process(self):
        # Kill the process for the selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected = current_list.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select a server first.")
            return

        server_name = current_list.item(selected[0])['values'][0]

        if not messagebox.askyesno("Kill Process",
                                 f"Are you sure you want to forcefully kill the process for '{server_name}'?\n\nThis action cannot be undone and may cause data loss.",
                                 parent=self.root):
            return

        # Try to kill via console manager first
        if self.console_manager and hasattr(self.console_manager, 'kill_process'):
            if self.console_manager.kill_process(server_name):
                if self.server_manager:
                    try:
                        server_config = self.server_manager.get_server_config(server_name)
                        if server_config:
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            self.server_manager.update_server(server_name, server_config)
                    except Exception as e:
                        logger.warning(f"Failed to clear PID from config after kill: {e}")

                messagebox.showinfo("Success", f"Process for '{server_name}' has been killed.", parent=self.root)
                self.update_server_list()
                return

        # Fallback: try to find and kill the process directly
        try:
            if self.server_manager:
                server_config = self.server_manager.get_server_config(server_name)
                if server_config:
                    exe_path = server_config.get('ExecutablePath', '')
                    if exe_path and os.path.exists(exe_path):
                        import psutil
                        exe_name = os.path.basename(exe_path)

                        killed = False
                        for proc in psutil.process_iter(['pid', 'name', 'exe']):
                            try:
                                if proc.info['name'] == exe_name or (proc.info['exe'] and os.path.basename(proc.info['exe']) == exe_name):
                                    logger.info(f"Killing process {proc.info['pid']} for {server_name}")
                                    proc.kill()
                                    killed = True
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue

                        if killed:
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            self.server_manager.update_server(server_name, server_config)

                            if self.console_manager:
                                try:
                                    self.console_manager.cleanup_console_on_stop(server_name)
                                except Exception:
                                    pass

                            messagebox.showinfo("Success", f"Process for '{server_name}' has been killed.", parent=self.root)
                            self.update_server_list()
                            return

            messagebox.showerror("Error", f"Could not find or kill process for '{server_name}'.", parent=self.root)

        except Exception as e:
            logger.error(f"Error killing process for {server_name}: {e}")
            messagebox.showerror("Error", f"Failed to kill process: {str(e)}", parent=self.root)