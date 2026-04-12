# -*- coding: utf-8 -*-
# Dashboard dialogs - Console manager, automation, categories, verification, help/about

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext
from typing import TYPE_CHECKING, Any, Dict, Optional

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path
setup_module_path()

from Modules.core.server_logging import get_dashboard_logger
from Modules.core.color_palettes import get_palette
from Host.dashboard_functions import (
    centre_window, batch_update_server_types, load_categories
)
from Modules.ui.documentation import show_help_dialog, show_about_dialog
from debug.debug import log_exception

if TYPE_CHECKING:
    from Modules.server.server_manager import ServerManager
    from Modules.server.server_console import ConsoleManager

logger = get_dashboard_logger()

class DashboardDialogsMixin:
    # Dialog methods - console manager, automation, categories, verification, database tools, help/about
    if TYPE_CHECKING:
        root: tk.Tk
        server_manager: Optional[ServerManager]
        console_manager: Optional[ConsoleManager]
        variables: Dict[str, Any]

        @property
        def paths(self) -> Dict[str, Any]: ...
        @property
        def server_manager_dir(self) -> str: ...
        @property
        def config(self) -> Dict[str, Any]: ...

        def get_current_server_list(self) -> Optional[ttk.Treeview]: ...
        def update_server_list(self, force_refresh: bool = False) -> None: ...

    def _get_active_palette(self):
        # Resolve active palette for dialog-specific tk widgets.
        theme_name = getattr(self, "current_theme", None)
        if not theme_name and hasattr(self, "get_saved_theme"):
            try:
                theme_name = self.get_saved_theme()
            except Exception:
                theme_name = "light"
        return get_palette(theme_name or "light")

    def show_console_manager(self):
        # Show console manager dialog with active consoles
        try:
            if not self.console_manager:
                messagebox.showinfo("Console Manager", "Console manager not available.")
                return
            self.console_manager.show_console_manager_window(self.root)
        except Exception as e:
            log_exception(e, "Error showing console manager")
            messagebox.showerror("Console Manager Error",
                                 f"Failed to show console manager:\n{str(e)}")

    def open_automation_settings(self):
        # Open the automation settings window
        try:
            from Modules.ui.automation_ui import open_automation_settings
            open_automation_settings(self.root, self.server_manager)
        except Exception as e:
            log_exception(e, "Error opening automation settings")
            messagebox.showerror("Automation Settings Error",
                                 f"Failed to open automation settings:\n{str(e)}")

    def batch_update_server_types(self):
        # Batch update all server types using database-based detection
        try:
            response = messagebox.askyesno(
                "Update Server Types",
                "This will analyse all server configurations and update their types based on:\n"
                "• Steam AppIDs in the database\n"
                "• Directory contents and files\n"
                "• Executable paths\n\n"
                "This operation is safe and will backup the original type information.\n\n"
                "Do you want to continue?"
            )
            if not response:
                return

            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Updating Server Types")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            centre_window(progress_dialog, 400, 150, self.root)

            progress_frame = ttk.Frame(progress_dialog, padding=20)
            progress_frame.pack(fill=tk.BOTH, expand=True)

            status_var = tk.StringVar(value="Analysing server configurations...")
            ttk.Label(progress_frame, textvariable=status_var).pack(pady=(0, 10))

            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=(0, 20))
            progress_bar.start(10)

            def run_update():
                try:
                    updated_count, updated_servers = batch_update_server_types(self.paths)
                    self.root.after(0, update_complete, updated_count, updated_servers)
                except Exception as e:
                    self.root.after(0, update_error, str(e))

            def update_complete(count, servers):
                progress_bar.stop()
                progress_dialog.destroy()
                if count == 0:
                    messagebox.showinfo("Update Complete",
                        "No server type updates were needed. All servers are already correctly classified.")
                else:
                    result_msg = f"Successfully updated {count} server(s):\n\n"
                    for server in servers[:10]:
                        result_msg += f"• {server['name']}: {server['old_type']} → {server['new_type']}\n"
                    if len(servers) > 10:
                        result_msg += f"... and {len(servers) - 10} more\n"
                    result_msg += "\nPlease refresh the server list to see the changes."
                    messagebox.showinfo("Update Complete", result_msg)
                self.update_server_list(force_refresh=True)

            def update_error(error_msg):
                progress_bar.stop()
                progress_dialog.destroy()
                messagebox.showerror("Update Error",
                    f"Failed to update server types:\n{error_msg}")

            threading.Thread(target=run_update, daemon=True).start()

        except Exception as e:
            log_exception(e, "Error in batch update server types")
            messagebox.showerror("Update Error",
                f"Failed to update server types:\n{str(e)}")

    # Category management
    def create_category(self):
        # Create a new server category
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        category_name = simpledialog.askstring("Create Category",
                                               "Enter category name:",
                                               parent=self.root)
        if not category_name or not category_name.strip():
            return

        category_name = category_name.strip()
        categories = load_categories(self.server_manager_dir)
        if category_name in categories:
            messagebox.showerror("Error", f"Category '{category_name}' already exists.")
            return

        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.add_category(category_name):
            self.refresh_categories()
            logger.info(f"Created category: {category_name}")
        else:
            messagebox.showerror("Error", f"Failed to create category '{category_name}'.")

    def rename_category(self):
        # Rename an existing category
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a category first.")
            return

        item_values = current_list.item(selected_items[0])['values']
        if item_values[1]:
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        current_name = item_values[0]
        new_name = simpledialog.askstring("Rename Category",
                                          "Enter new category name:",
                                          initialvalue=current_name,
                                          parent=self.root)
        if not new_name or not new_name.strip() or new_name.strip() == current_name:
            return

        new_name = new_name.strip()
        categories = load_categories(self.server_manager_dir)
        if new_name in categories:
            messagebox.showerror("Error", f"Category '{new_name}' already exists.")
            return

        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.rename_category(current_name, new_name):
            self._update_servers_category(current_name, new_name)
            self.refresh_categories()
            logger.info(f"Renamed category from '{current_name}' to '{new_name}'")
        else:
            messagebox.showerror("Error", f"Failed to rename category '{current_name}'.")

    def delete_category(self):
        # Delete a category and move servers to Uncategorized
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a category first.")
            return

        item_values = current_list.item(selected_items[0])['values']
        if item_values[1]:
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        category_name = item_values[0]
        if category_name == "Uncategorized":
            messagebox.showerror("Error", "Cannot delete the 'Uncategorized' category.")
            return

        if not messagebox.askyesno("Delete Category",
                f"Are you sure you want to delete the category '{category_name}'?\n\n"
                "All servers in this category will be moved to 'Uncategorized'.",
                parent=self.root):
            return

        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.delete_category(category_name):
            self._update_servers_category(category_name, "Uncategorized")
            self.refresh_categories()
            logger.info(f"Deleted category '{category_name}', moved servers to 'Uncategorized'")
        else:
            messagebox.showerror("Error", f"Failed to delete category '{category_name}'.")

    def _update_servers_category(self, old_category, new_category):
        # Update category for all servers from old_category to new_category
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            all_servers = manager.get_all_servers()
            updated_count = 0

            for server_config in all_servers:
                server_name = server_config.get('Name', 'Unknown')
                try:
                    if server_config.get('Category') == old_category:
                        server_config['Category'] = new_category
                        manager.update_server(server_name, server_config)
                        updated_count += 1
                except Exception as e:
                    logger.error(f"Error updating category for server {server_name}: {str(e)}")

            if updated_count > 0:
                logger.info(f"Updated category from '{old_category}' to '{new_category}' "
                            f"for {updated_count} servers")
        except Exception as e:
            logger.error(f"Error updating server categories: {str(e)}")

    def refresh_categories(self):
        # Refresh category structure in the server list without full refresh
        current_list = self.get_current_server_list()
        if not current_list:
            logger.warning("refresh_categories: No current server list available")
            return

        logger.debug("refresh_categories: Starting category refresh")

        # Preserve existing server data
        current_servers = {}
        for category_item in current_list.get_children():
            try:
                for server_item in current_list.get_children(category_item):
                    try:
                        item = current_list.item(server_item)
                        if item and 'values' in item and len(item['values']) >= 1:
                            values = item['values']
                            server_name = values[0]
                            if server_name and len(values) > 1 and values[1]:
                                current_servers[server_name] = {
                                    'status': values[1] if len(values) > 1 else 'Unknown',
                                    'pid': values[2] if len(values) > 2 else '',
                                    'cpu': values[3] if len(values) > 3 else '0%',
                                    'memory': values[4] if len(values) > 4 else '0 MB',
                                    'uptime': values[5] if len(values) > 5 else '00:00:00',
                                    'category': 'Uncategorized'
                                }
                    except Exception as e:
                        logger.debug(f"Error processing server item {server_item}: {e}")
            except Exception as e:
                logger.debug(f"Error processing category item {category_item}: {e}")

        logger.debug(f"refresh_categories: Found {len(current_servers)} servers to reorganise")

        all_categories = load_categories(self.server_manager_dir)
        logger.debug(f"refresh_categories: Loaded {len(all_categories)} categories from database")

        # Clear existing items
        for item in current_list.get_children():
            current_list.delete(item)

        categories = {cat: [] for cat in all_categories}

        # Assign servers to categories from config
        for server_name in current_servers:
            try:
                if self.server_manager:
                    server_config = self.server_manager.get_server_config(server_name)
                    category = server_config.get('Category', 'Uncategorized') if server_config else 'Uncategorized'
                else:
                    category = 'Uncategorized'
                current_servers[server_name]['category'] = category
            except Exception as e:
                logger.debug(f"Error getting category for {server_name}: {e}")
                current_servers[server_name]['category'] = 'Uncategorized'

        for server_name, server_info in current_servers.items():
            category = server_info.get('category', 'Uncategorized')
            if category not in categories:
                categories[category] = []
            categories[category].append((server_name, server_info))

        # Rebuild treeview
        for category_name in all_categories:
            servers = categories.get(category_name, [])
            category_item = current_list.insert(
                "", tk.END, text=category_name,
                values=(category_name, "", "", "", "", ""),
                open=True, tags=('category',))

            for server_name, server_info in servers:
                try:
                    current_list.insert(category_item, tk.END, values=(
                        server_name,
                        server_info.get('status', 'Unknown'),
                        server_info.get('pid', ''),
                        server_info.get('cpu', '0%'),
                        server_info.get('memory', '0 MB'),
                        server_info.get('uptime', '00:00:00'),
                    ), tags=('server',))
                except Exception as e:
                    logger.error(f"Error adding server {server_name} to category refresh: {e}")

        logger.info(f"Categories refreshed – {len(current_servers)} servers in "
                     f"{len(all_categories)} categories")

    # Verification / diagnostic dialogs
    def find_broken_servers(self):
        # Find and display broken or misconfigured servers
        try:
            if self.server_manager is None:
                messagebox.showerror("Error", "Server manager not available")
                return

            logger.info("Searching for broken servers...")
            broken_servers = []
            all_servers = self.server_manager.get_all_servers()

            for server_name, server_config in all_servers.items():
                issues = []

                install_dir = server_config.get('InstallDir', '')
                if install_dir and not os.path.exists(install_dir):
                    issues.append(f"Directory missing: {install_dir}")

                executable = server_config.get('ExecutablePath', '')
                if executable:
                    full_exe_path = (os.path.join(install_dir, executable)
                                     if not os.path.isabs(executable) and install_dir
                                     else executable)
                    if not os.path.exists(full_exe_path):
                        issues.append(f"Executable missing: {full_exe_path}")

                for field in ['Name', 'Type', 'InstallDir']:
                    if not server_config.get(field):
                        issues.append(f"Missing required field: {field}")

                server_type = server_config.get('Type', '')
                if server_type not in ['Steam', 'Minecraft', 'Other']:
                    issues.append(f"Invalid server type: {server_type}")

                if server_type == 'Steam' and not server_config.get('AppID'):
                    issues.append("Steam server missing AppID")

                pid = server_config.get('ProcessId')
                if pid:
                    try:
                        if not self.server_manager.is_process_running(pid):
                            issues.append(f"Process {pid} not running but recorded as active")
                    except Exception as e:
                        issues.append(f"Error checking process {pid}: {str(e)}")

                if issues:
                    broken_servers.append({
                        'name': server_name,
                        'issues': issues,
                        'config': server_config
                    })

            if broken_servers:
                dialog = tk.Toplevel(self.root)
                dialog.title("Broken Servers Found")
                dialog.geometry("800x600")
                dialog.resizable(True, True)
                dialog.transient(self.root)

                centre_window(dialog, 800, 600, self.root)

                main_frame = ttk.Frame(dialog, padding=10)
                main_frame.pack(fill=tk.BOTH, expand=True)

                ttk.Label(main_frame,
                          text=f"Found {len(broken_servers)} broken server(s)",
                          font=("Segoe UI", 14, "bold")).pack(pady=(0, 10))

                text_widget = scrolledtext.ScrolledText(
                    main_frame, wrap=tk.WORD, font=("Consolas", 10))
                text_widget.pack(fill=tk.BOTH, expand=True)

                palette = self._get_active_palette()
                text_widget.configure(
                    bg=palette.get("text_bg"),
                    fg=palette.get("text_fg"),
                    insertbackground=palette.get("text_fg"),
                    selectbackground=palette.get("text_selection_bg"),
                    selectforeground=palette.get("text_selection_fg"),
                )

                for server in broken_servers:
                    text_widget.insert(tk.END, f"Server: {server['name']}\n", "server_name")
                    text_widget.insert(tk.END,
                        f"Type: {server['config'].get('Type', 'Unknown')}\n")
                    text_widget.insert(tk.END,
                        f"Directory: {server['config'].get('InstallDir', 'Not set')}\n")
                    text_widget.insert(tk.END, "Issues:\n")
                    for issue in server['issues']:
                        text_widget.insert(tk.END, f"  • {issue}\n", "issue")
                    text_widget.insert(tk.END, "\n" + "=" * 50 + "\n\n")

                text_widget.tag_config("server_name", foreground=palette.get("accent"),
                                       font=("Consolas", 10, "bold"))
                text_widget.tag_config("issue", foreground=palette.get("error_fg"))
                text_widget.config(state=tk.DISABLED)

                ttk.Button(main_frame, text="Close",
                           command=dialog.destroy).pack(anchor=tk.E, pady=(10, 0))

                logger.info(f"Found {len(broken_servers)} broken servers")
            else:
                messagebox.showinfo("No Broken Servers",
                    "All servers appear to be configured correctly!")
                logger.info("No broken servers found")

        except Exception as e:
            logger.error(f"Error finding broken servers: {str(e)}")
            messagebox.showerror("Error",
                f"Failed to search for broken servers: {str(e)}")

    def verify_servers(self):
        # Verify server information completeness
        try:
            if self.server_manager is None:
                messagebox.showerror("Error", "Server manager not available")
                return

            logger.info("Verifying server information completeness...")
            incomplete_servers = []
            all_servers = self.server_manager.get_all_servers()

            for server_name, server_config in all_servers.items():
                missing_info = []

                # Some datasets key the name externally (dict key), so use server_name fallback.
                effective_name = server_config.get('Name') or server_config.get('name') or server_name
                if not effective_name or (isinstance(effective_name, str) and effective_name.strip() == ''):
                    missing_info.append("Missing server name")

                required_fields = {
                    'Type': 'Server type (Steam/Minecraft/Other)',
                    'InstallDir': 'Installation directory'
                }
                for field, description in required_fields.items():
                    value = server_config.get(field)
                    if value is None or (isinstance(value, str) and value.strip() == ''):
                        missing_info.append(f"Missing {description}")

                server_type = server_config.get('Type', '')
                if server_type == 'Steam':
                    if not (server_config.get('AppID') or server_config.get('appid')):
                        missing_info.append("Missing Steam AppID")
                    if not server_config.get('ExecutablePath'):
                        missing_info.append("Missing executable path")

                install_dir = server_config.get('InstallDir', '')
                if install_dir and os.path.exists(install_dir):
                    if server_type == 'Minecraft':
                        for config_file in ['server.properties', 'eula.txt']:
                            if not os.path.exists(os.path.join(install_dir, config_file)):
                                missing_info.append(f"Missing Minecraft config: {config_file}")
                    elif server_type == 'Steam':
                        if not any(os.path.exists(os.path.join(install_dir, f))
                                   for f in ['server.cfg', 'serverconfig.xml', 'config.cfg']):
                            missing_info.append("No server configuration file found")

                if missing_info:
                    incomplete_servers.append({
                        'name': server_name,
                        'missing_info': missing_info,
                        'config': server_config
                    })

            if incomplete_servers:
                dialog = tk.Toplevel(self.root)
                dialog.title("Server Information Verification")
                dialog.geometry("800x600")
                dialog.resizable(True, True)
                dialog.transient(self.root)
                centre_window(dialog, 800, 600, self.root)

                main_frame = ttk.Frame(dialog, padding=10)
                main_frame.pack(fill=tk.BOTH, expand=True)

                ttk.Label(main_frame,
                    text=f"Found {len(incomplete_servers)} server(s) with incomplete information",
                    font=("Segoe UI", 14, "bold")).pack(pady=(0, 10))

                text_widget = scrolledtext.ScrolledText(
                    main_frame, wrap=tk.WORD, font=("Consolas", 10))
                text_widget.pack(fill=tk.BOTH, expand=True)

                palette = self._get_active_palette()
                text_widget.configure(
                    bg=palette.get("text_bg"),
                    fg=palette.get("text_fg"),
                    insertbackground=palette.get("text_fg"),
                    selectbackground=palette.get("text_selection_bg"),
                    selectforeground=palette.get("text_selection_fg"),
                )

                for server in incomplete_servers:
                    text_widget.insert(tk.END, f"Server: {server['name']}\n", "server_name")
                    text_widget.insert(tk.END,
                        f"Type: {server['config'].get('Type', 'Unknown')}\n")
                    text_widget.insert(tk.END,
                        f"Directory: {server['config'].get('InstallDir', 'Not set')}\n")
                    text_widget.insert(tk.END, "Missing Information:\n")
                    for info in server['missing_info']:
                        text_widget.insert(tk.END, f"  • {info}\n", "missing")
                    text_widget.insert(tk.END, "\n" + "=" * 50 + "\n\n")

                text_widget.tag_config("server_name", foreground=palette.get("accent"),
                                       font=("Consolas", 10, "bold"))
                text_widget.tag_config("missing", foreground=palette.get("error_fg"))
                text_widget.config(state=tk.DISABLED)

                ttk.Button(main_frame, text="Close",
                           command=dialog.destroy).pack(anchor=tk.E, pady=(10, 0))

                logger.info(f"Found {len(incomplete_servers)} servers with incomplete information")
            else:
                messagebox.showinfo("Server Verification Complete",
                    "All servers have complete information!")
                logger.info("All servers have complete information")

        except Exception as e:
            logger.error(f"Error verifying server information: {str(e)}")
            messagebox.showerror("Error",
                f"Failed to verify server information: {str(e)}")

    # Database tools
    def update_databases(self):
        # Show selection listbox then run chosen scanners
        dialog = tk.Toplevel(self.root)
        dialog.title("Update Databases")
        dialog.geometry("920x760")
        dialog.minsize(860, 700)
        dialog.resizable(True, True)
        dialog.transient(self.root)
        centre_window(dialog, 920, 760, self.root)

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Update Databases",
                  font=("Segoe UI", 14, "bold")).pack(pady=(0, 5))

        ttk.Label(main_frame, text="Select which databases to scan and update:",
                  font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 4))

        # ── Scan target list (add new entries here to extend in future) ───────
        # Each entry: (key, display_label, default_selected)
        SCAN_TARGETS = [
            ("steam",              "Steam dedicated servers  (steam_ID.db)",                 True),
            ("minecraft",          "Minecraft server versions  (minecraft_ID.db)",           True),
            ("modded:atlauncher",  "Modded Minecraft: ATLauncher  (minecraft_modded_ID.db)", True),
            ("modded:ftb",         "Modded Minecraft: FTB  (minecraft_modded_ID.db)",         True),
            ("modded:technic",     "Modded Minecraft: Technic  (minecraft_modded_ID.db)",     True),
            ("modded:modrinth",    "Modded Minecraft: Modrinth  (minecraft_modded_ID.db)",    True),
            ("modded:curseforge",  "Modded Minecraft: CurseForge  (requires API key)",        False),
        ]

        # Auto-tick CurseForge if a key is already saved
        try:
            from Modules.core.common import REGISTRY_PATH, get_registry_value
            if get_registry_value(REGISTRY_PATH, "CurseForgeAPIKey", ""):
                SCAN_TARGETS = [(k, l, True) if k == "modded:curseforge" else (k, l, d)
                                for k, l, d in SCAN_TARGETS]
        except Exception:
            pass

        # Multi-select listbox
        sel_frame = ttk.LabelFrame(
            main_frame,
            text="Databases  (Ctrl+Click or Shift+Click to select multiple)",
            padding=8)
        sel_frame.pack(fill=tk.X, pady=(0, 6))

        listbox = tk.Listbox(sel_frame, selectmode=tk.EXTENDED, height=len(SCAN_TARGETS),
                             font=("Segoe UI", 10), activestyle="none",
                             exportselection=False)
        listbox.pack(fill=tk.X, side=tk.LEFT, expand=True)

        for _key, label, _default in SCAN_TARGETS:
            listbox.insert(tk.END, f"  {label}")

        # Pre-select defaults
        for idx, (_key, _label, default) in enumerate(SCAN_TARGETS):
            if default:
                listbox.selection_set(idx)

        # Select-all / clear buttons
        btn_sel_frame = ttk.Frame(sel_frame)
        btn_sel_frame.pack(side=tk.LEFT, padx=(8, 0), anchor=tk.N)
        ttk.Button(btn_sel_frame, text="All",  width=6,
                   command=lambda: listbox.selection_set(0, tk.END)).pack(pady=(0, 4))
        ttk.Button(btn_sel_frame, text="None", width=6,
                   command=lambda: listbox.selection_clear(0, tk.END)).pack()

        status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=status_var,
              font=("Segoe UI", 10)).pack(pady=(0, 3))

        progress = ttk.Progressbar(main_frame, mode='indeterminate')
        progress.pack(fill=tk.X, pady=(0, 5))

        text_widget = scrolledtext.ScrolledText(
            main_frame, wrap=tk.WORD, font=("Consolas", 10), state=tk.DISABLED)
        text_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        ttk.Label(main_frame, text="Press Update to run the selected database scans.",
                  font=("Segoe UI", 9, "italic")).pack(anchor=tk.W, pady=(0, 4))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(8, 0))

        close_btn = ttk.Button(button_frame, text="Close", command=dialog.destroy)
        close_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=(2, 2))

        update_btn = ttk.Button(button_frame, text="Update", default=tk.ACTIVE)
        update_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=(2, 2))

        def _log(msg):
            def _append():
                text_widget.config(state=tk.NORMAL)
                text_widget.insert(tk.END, msg + "\n")
                text_widget.see(tk.END)
                text_widget.config(state=tk.DISABLED)
            dialog.after(0, _append)

        def _warn(msg):
            _log(f"[WARN] {msg}")

        def _error(msg):
            _log(f"[ERROR] {msg}")

        def _run_scanners():
            selected_indices = listbox.curselection()
            selected_keys = {SCAN_TARGETS[i][0] for i in selected_indices}
            ran_any = False
            try:
                if "steam" in selected_keys:
                    ran_any = True
                    dialog.after(0, lambda: status_var.set("Scanning Steam dedicated servers..."))
                    _log("Starting Steam AppID scan...")
                    try:
                        from Modules.Database.scanners.AppIDScanner import AppIDScanner
                        scanner = AppIDScanner(use_database=True, debug_mode=False)
                        try:
                            scanner.scan_steam_apps(dedicated_only=True)
                            stats = scanner.get_dedicated_servers_from_database()
                            _log(f"Steam scan complete — {len(stats)} dedicated servers in database")
                            if not stats:
                                _warn("Steam scan completed but returned 0 dedicated servers.")
                        finally:
                            scanner.close()
                    except Exception as e:
                        _error(f"Steam scan error: {e}")
                        logger.error(f"Steam scan error during Update Databases: {e}")

                if "minecraft" in selected_keys:
                    ran_any = True
                    dialog.after(0, lambda: status_var.set("Scanning Minecraft server versions..."))
                    _log("\nStarting Minecraft server scan...")
                    try:
                        from Modules.Database.scanners.MinecraftIDScanner import MinecraftIDScanner
                        mc_scanner = MinecraftIDScanner(use_database=True, debug_mode=False)
                        try:
                            mc_scanner.scan_minecraft_servers()
                            mc_stats = mc_scanner.get_servers_from_database(
                                modloader=None, dedicated_only=True, filter_snapshots=True)
                            _log(f"Minecraft scan complete — {len(mc_stats) if mc_stats else 0} server versions in database")
                            if not mc_stats:
                                _warn("Minecraft scan completed but returned 0 server versions.")
                        finally:
                            mc_scanner.close()
                    except Exception as e:
                        _error(f"Minecraft scan error: {e}")
                        logger.error(f"Minecraft scan error during Update Databases: {e}")

                # Collect any modded launcher selections
                launchers = [k.split(":")[1] for k in selected_keys if k.startswith("modded:")]
                if launchers:
                    ran_any = True
                    label = ", ".join(l.capitalize() for l in launchers)
                    dialog.after(0, lambda: status_var.set("Scanning modded Minecraft packs..."))
                    _log(f"\nStarting modded Minecraft pack scan ({label})...")
                    try:
                        from Modules.Database.scanners.MinecraftModdedScanner import MinecraftModdedScanner
                        from Modules.core.common import REGISTRY_PATH, get_registry_value
                        cf_key = str(get_registry_value(REGISTRY_PATH, "CurseForgeAPIKey", "") or "").strip()
                        if "curseforge" in launchers and not cf_key:
                            _warn("CurseForge selected but no API key found in Settings > Minecraft — skipping.")
                            launchers.remove("curseforge")

                        # Probe CurseForge search endpoint to surface key rejection in the UI log.
                        if "curseforge" in launchers:
                            try:
                                import requests
                                probe = requests.get(
                                    "https://api.curseforge.com/v1/mods/search",
                                    params={"gameId": 432, "classId": 4471, "pageSize": 1, "index": 0},
                                    headers={"x-api-key": cf_key},
                                    timeout=15,
                                )
                                if probe.status_code == 403:
                                    _warn("CurseForge API rejected the current key (403 Forbidden) — skipping CurseForge.")
                                    launchers.remove("curseforge")
                                elif probe.status_code >= 400:
                                    _warn(f"CurseForge API probe returned HTTP {probe.status_code} — skipping CurseForge.")
                                    launchers.remove("curseforge")
                            except Exception as probe_error:
                                _warn(f"CurseForge API probe failed: {probe_error} — skipping CurseForge.")
                                launchers.remove("curseforge")

                        if launchers:
                            modded_scanner = MinecraftModdedScanner(curseforge_api_key=cf_key, debug_mode=False)
                            try:
                                results = modded_scanner.scan_packs(launchers=launchers)
                                total = sum(results.values())
                                for lnc, count in results.items():
                                    _log(f"  {lnc}: {count} packs")
                                    if count == 0:
                                        _warn(f"{lnc} scan completed but returned 0 packs.")
                                _log(f"Modded scan complete — {total} packs total in database")
                                if total == 0:
                                    _warn("All selected modded launchers returned 0 packs.")
                            finally:
                                modded_scanner.close()
                        else:
                            _warn("No modded launchers available to scan after validation checks.")
                    except Exception as e:
                        _error(f"Modded Minecraft scan error: {e}")
                        logger.error(f"Modded Minecraft scan error during Update Databases: {e}")

                if ran_any:
                    dialog.after(0, lambda: status_var.set("Update complete"))
                    _log("\nAll selected database updates finished.")
                else:
                    dialog.after(0, lambda: status_var.set("Nothing selected"))
                    _warn("No databases were selected.")

            except Exception as e:
                _error(f"Fatal error: {e}")
                logger.error(f"Update Databases failed: {e}")
                dialog.after(0, lambda: status_var.set("Update failed"))
            finally:
                dialog.after(0, lambda: progress.stop())
                dialog.after(0, lambda: update_btn.config(state=tk.NORMAL))

        def _start_update():
            update_btn.config(state=tk.DISABLED)
            progress.start(15)
            threading.Thread(target=_run_scanners, daemon=True,
                             name="UpdateDatabases").start()

        update_btn.config(command=_start_update)

    def verify_databases(self):
        # Verify database schema and data integrity
        dialog = tk.Toplevel(self.root)
        dialog.title("Verify Databases")
        dialog.geometry("760x560")
        dialog.minsize(700, 520)
        dialog.resizable(True, True)
        dialog.transient(self.root)
        centre_window(dialog, 760, 560, self.root)

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Verify Databases",
                  font=("Segoe UI", 14, "bold")).pack(pady=(0, 5))

        status_var = tk.StringVar(value="Running verification...")
        ttk.Label(main_frame, textvariable=status_var,
                  font=("Segoe UI", 10)).pack(pady=(0, 5))

        progress = ttk.Progressbar(main_frame, mode='indeterminate')
        progress.pack(fill=tk.X, pady=(0, 5))

        text_widget = scrolledtext.ScrolledText(
            main_frame, wrap=tk.WORD, font=("Consolas", 10), state=tk.DISABLED)
        text_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(8, 0))
        close_btn = ttk.Button(button_frame, text="Close",
                               command=dialog.destroy, state=tk.DISABLED)
        close_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=(2, 2))

        def _set_text(content):
            text_widget.config(state=tk.NORMAL)
            text_widget.delete("1.0", tk.END)
            text_widget.insert(tk.END, content)
            text_widget.config(state=tk.DISABLED)

        def _run_verify():
            try:
                from tools.verify_database import DatabaseVerifier
                verifier = DatabaseVerifier(use_database=True, dry_run=False)
                verifier.verify_all()
                summary = verifier.get_summary_text()

                has_issues = any(r['issues'] for r in verifier.results.values())
                final_status = ("Issues found — see details below"
                                if has_issues else "All checks passed")

                dialog.after(0, lambda: status_var.set(final_status))
                dialog.after(0, lambda: _set_text(summary))

            except Exception as e:
                logger.error(f"Verify Databases failed: {e}")
                dialog.after(0, lambda: status_var.set("Verification failed"))
                dialog.after(0, lambda: _set_text(f"Error: {e}"))
            finally:
                dialog.after(0, lambda: progress.stop())
                dialog.after(0, lambda: close_btn.config(state=tk.NORMAL))

        progress.start(15)
        threading.Thread(target=_run_verify, daemon=True,
                         name="VerifyDatabases").start()

    # Help / About dialogs
    def show_help(self):
        # Show help dialog
        show_help_dialog(self.root, logger)

    def show_about(self):
        # Show about dialog
        show_about_dialog(self.root, logger)
