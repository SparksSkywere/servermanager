# -*- coding: utf-8 -*-
# Dashboard settings - Settings dialog, all settings tabs, save logic
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Any, Dict, Optional

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_dashboard_logger
from Host.dashboard_functions import centre_window

if TYPE_CHECKING:
    from Modules.server_manager import ServerManager

logger = get_dashboard_logger()


class DashboardSettingsMixin:
    """Mixin providing the settings dialog and all settings tabs."""

    # Type stubs for attributes provided by ServerManagerDashboard at runtime
    if TYPE_CHECKING:
        root: tk.Tk
        server_manager: Optional[ServerManager]
        variables: Dict[str, Any]

    def show_settings_dialog(self):
        """Show settings dialog for editing configuration."""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("800x600")
        settings_window.resizable(True, True)
        centre_window(settings_window, 800, 600, self.root)

        notebook = ttk.Notebook(settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        dashboard_frame = ttk.Frame(notebook)
        notebook.add(dashboard_frame, text="Dashboard")

        cluster_frame = ttk.Frame(notebook)
        notebook.add(cluster_frame, text="Cluster")

        update_frame = ttk.Frame(notebook)
        notebook.add(update_frame, text="Updates")

        steam_frame = ttk.Frame(notebook)
        notebook.add(steam_frame, text="Steam")

        system_frame = ttk.Frame(notebook)
        notebook.add(system_frame, text="System")

        try:
            from Modules.Database.cluster_database import ClusterDatabase
            db = ClusterDatabase()
            dashboard_config = db.get_dashboard_config()
            update_config = db.get_update_config()
            main_config = db.get_main_config()
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to load settings: {e}")
            settings_window.destroy()
            return

        self._create_dashboard_settings_tab(dashboard_frame, dashboard_config, db)
        self._create_cluster_settings_tab(cluster_frame, db)
        self._create_update_settings_tab(update_frame, update_config, db)
        self._create_steam_settings_tab(steam_frame, db)
        self._create_system_settings_tab(system_frame, main_config, db)

        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(button_frame, text="Save",
                   command=lambda: self._save_settings(settings_window, db)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel",
                   command=settings_window.destroy).pack(side=tk.RIGHT)

        self.settings_window = settings_window

    # ── Tabs ─────────────────────────────────────────────────────────────

    def _create_dashboard_settings_tab(self, parent, config, db):
        """Create dashboard settings controls."""
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        settings = [
            ("Debug Mode", "configuration.debugMode",
             config.get("configuration.debugMode", False), "boolean"),
            ("Offline Mode", "configuration.offlineMode",
             config.get("configuration.offlineMode", False), "boolean"),
            ("Hide Server Consoles", "configuration.hideServerConsoles",
             config.get("configuration.hideServerConsoles", True), "boolean"),
            ("System Refresh Interval", "configuration.systemRefreshInterval",
             config.get("configuration.systemRefreshInterval", 4), "integer"),
            ("Process Monitoring Interval", "configuration.processMonitoringInterval",
             config.get("configuration.processMonitoringInterval", 5), "integer"),
            ("Network Update Interval", "configuration.networkUpdateInterval",
             config.get("configuration.networkUpdateInterval", 5), "integer"),
            ("Server List Update Interval", "configuration.serverListUpdateInterval",
             config.get("configuration.serverListUpdateInterval", 30), "integer"),
            ("Window Width", "ui.windowWidth",
             config.get("ui.windowWidth", 1200), "integer"),
            ("Window Height", "ui.windowHeight",
             config.get("ui.windowHeight", 700), "integer"),
        ]
        self._create_settings_controls(scrollable_frame, settings, "dashboard")

    def _create_cluster_settings_tab(self, parent, db):
        """Create cluster settings controls."""
        from Modules.common import REGISTRY_PATH, get_registry_value, set_registry_value

        main_frame = ttk.Frame(parent, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Cluster Configuration",
                  font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 15))

        ttk.Label(main_frame,
                  text="Configure this installation's role in a Server Manager cluster.\n"
                       "Changes require a restart to take effect.",
                  wraplength=700).pack(anchor=tk.W, pady=(0, 15))

        current_role = get_registry_value(REGISTRY_PATH, "HostType", "Host")
        current_host_address = get_registry_value(REGISTRY_PATH, "HostAddress", "")

        role_frame = ttk.LabelFrame(main_frame, text="Cluster Role", padding=10)
        role_frame.pack(fill=tk.X, pady=(0, 15))

        self.cluster_role_var = tk.StringVar(value=current_role)

        ttk.Radiobutton(role_frame, text="Host (Master)",
                        variable=self.cluster_role_var, value="Host").pack(anchor=tk.W, pady=2)
        ttk.Label(role_frame,
                  text="This installation manages subhosts and accepts cluster join requests.",
                  foreground="gray").pack(anchor=tk.W, padx=(20, 0), pady=(0, 10))

        ttk.Radiobutton(role_frame, text="Subhost (Slave)",
                        variable=self.cluster_role_var, value="Subhost").pack(anchor=tk.W, pady=2)
        ttk.Label(role_frame,
                  text="This installation connects to a master host for centralized management.",
                  foreground="gray").pack(anchor=tk.W, padx=(20, 0), pady=(0, 5))

        master_frame = ttk.Frame(role_frame)
        master_frame.pack(fill=tk.X, padx=(20, 0), pady=(5, 0))

        ttk.Label(master_frame, text="Master Host IP:").pack(side=tk.LEFT)
        self.master_ip_var = tk.StringVar(value=current_host_address)
        self.master_ip_entry = ttk.Entry(master_frame, textvariable=self.master_ip_var, width=20)
        self.master_ip_entry.pack(side=tk.LEFT, padx=(10, 0))

        def update_master_ip_state(*_args):
            state = "normal" if self.cluster_role_var.get() == "Subhost" else "disabled"
            self.master_ip_entry.configure(state=state)

        self.cluster_role_var.trace_add("write", update_master_ip_state)
        update_master_ip_state()

        # Pending join requests (Host-only section)
        if current_role == "Host":
            self._create_pending_requests_section(main_frame, db)

        def save_cluster_settings():
            new_role = self.cluster_role_var.get()
            new_host_address = self.master_ip_var.get().strip() if new_role == "Subhost" else ""
            if new_role == "Subhost" and not new_host_address:
                messagebox.showerror("Validation Error",
                                     "Master Host IP is required for Subhost mode.")
                return False
            try:
                set_registry_value(REGISTRY_PATH, "HostType", new_role)
                set_registry_value(REGISTRY_PATH, "HostAddress", new_host_address)
                logger.info(f"Cluster settings updated – Role: {new_role}, Master: {new_host_address}")
                messagebox.showinfo("Settings Saved",
                    "Cluster settings saved successfully.\n"
                    "Please restart the application for changes to take effect.")
                return True
            except Exception as e:
                logger.error(f"Failed to save cluster settings: {e}")
                messagebox.showerror("Error", f"Failed to save cluster settings: {e}")
                return False

        ttk.Button(main_frame, text="Save Cluster Settings",
                   command=save_cluster_settings).pack(anchor=tk.E, pady=(10, 0))

    def _create_pending_requests_section(self, parent, db):
        """Build the pending join-requests treeview (Host only)."""
        requests_frame = ttk.LabelFrame(parent, text="Pending Join Requests", padding=10)
        requests_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        columns = ("id", "machine", "ip", "requested")
        requests_tree = ttk.Treeview(requests_frame, columns=columns,
                                     show="headings", height=5)
        for col, heading, width in [("id", "ID", 150), ("machine", "Machine Name", 150),
                                     ("ip", "IP Address", 120), ("requested", "Requested At", 150)]:
            requests_tree.heading(col, text=heading)
            requests_tree.column(col, width=width)

        scroll = ttk.Scrollbar(requests_frame, orient=tk.VERTICAL, command=requests_tree.yview)
        requests_tree.configure(yscrollcommand=scroll.set)
        requests_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _load():
            for item in requests_tree.get_children():
                requests_tree.delete(item)
            try:
                for req in db.get_pending_requests():
                    if req['status'] == 'pending':
                        requests_tree.insert("", tk.END, values=(
                            req['node_name'],
                            req.get('machine_name', 'Unknown'),
                            req.get('ip_address', 'Unknown'),
                            req.get('requested_at', 'Unknown')))
            except Exception as e:
                logger.error(f"Failed to load pending requests: {e}")

        _load()

        btn_frame = ttk.Frame(requests_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        def _approve():
            selection = requests_tree.selection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a request to approve.")
                return
            for item in selection:
                node_name = requests_tree.item(item, 'values')[0]
                try:
                    pending = db.get_pending_requests()
                    request_id = next(
                        (r['id'] for r in pending
                         if r['node_name'] == node_name and r['status'] == 'pending'), None)
                    if request_id is None:
                        messagebox.showerror("Error",
                            f"Could not find pending request for {node_name}")
                        continue
                    import secrets
                    token = secrets.token_urlsafe(32)
                    if db.approve_request(request_id, "admin", token):
                        req_data = next((r for r in pending if r['id'] == request_id), None)
                        if req_data:
                            db.add_cluster_node(
                                name=node_name,
                                ip_address=req_data.get('ip_address', ''),
                                port=req_data.get('port', 8080),
                                node_type='subhost',
                                cluster_token=token,
                                hostname=req_data.get('machine_name', ''))
                        requests_tree.delete(item)
                        messagebox.showinfo("Approved",
                            f"Request from {node_name} has been approved.")
                    else:
                        messagebox.showerror("Error",
                            f"Failed to approve request from {node_name}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to approve: {e}")

        def _reject():
            selection = requests_tree.selection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a request to reject.")
                return
            for item in selection:
                node_name = requests_tree.item(item, 'values')[0]
                try:
                    pending = db.get_pending_requests()
                    request_id = next(
                        (r['id'] for r in pending
                         if r['node_name'] == node_name and r['status'] == 'pending'), None)
                    if request_id is None:
                        messagebox.showerror("Error",
                            f"Could not find pending request for {node_name}")
                        continue
                    if db.reject_request(request_id, "admin"):
                        requests_tree.delete(item)
                        messagebox.showinfo("Rejected",
                            f"Request from {node_name} has been rejected.")
                    else:
                        messagebox.showerror("Error",
                            f"Failed to reject request from {node_name}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to reject: {e}")

        ttk.Button(btn_frame, text="Approve", command=_approve).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Reject", command=_reject).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Refresh", command=_load).pack(side=tk.LEFT)
        ttk.Label(btn_frame, text="Auto-refresh: 10s",
                  foreground="gray").pack(side=tk.RIGHT, padx=(10, 0))

        def _auto():
            try:
                if requests_frame.winfo_exists():
                    _load()
                    requests_frame.after(10000, _auto)
            except Exception:
                pass

        requests_frame.after(10000, _auto)

    def _create_update_settings_tab(self, parent, config, db):
        """Create update settings controls."""
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(scrollable_frame, text="Update Configuration (JSON):",
                  font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))

        text_frame = ttk.Frame(scrollable_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        text_widget = tk.Text(text_frame, height=20, wrap=tk.WORD)
        text_scrollbar = ttk.Scrollbar(text_frame, command=text_widget.yview)
        text_widget.configure(yscrollcommand=text_scrollbar.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        full_config = config.get("full_config", {})
        if isinstance(full_config, str):
            try:
                full_config = json.loads(full_config)
            except (json.JSONDecodeError, ValueError):
                full_config = {}

        text_widget.insert(tk.END, json.dumps(full_config, indent=2))
        self.update_config_text = text_widget

    def _create_steam_settings_tab(self, parent, db):
        """Create Steam credentials settings tab."""
        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="\U0001F3AE Steam Credentials",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 5))

        ttk.Label(main_frame,
                  text="Configure your Steam credentials for automatic login during "
                       "server installations and updates. Credentials are stored locally "
                       "with encryption.",
                  wraplength=700, foreground="gray").pack(anchor=tk.W, pady=(0, 20))

        stored_creds = db.get_steam_credentials() or {}

        # Status indicator
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 15))

        if stored_creds.get('use_anonymous'):
            status_text, status_color = "\u2713 Using Anonymous Login", "blue"
        elif stored_creds.get('username'):
            status_text = f"\u2713 Credentials saved for: {stored_creds['username']}"
            status_color = "green"
        else:
            status_text, status_color = "\u25CB No credentials configured", "gray"

        self.steam_status_label = ttk.Label(status_frame, text=status_text,
                                            foreground=status_color,
                                            font=("Segoe UI", 11))
        self.steam_status_label.pack(anchor=tk.W)

        if stored_creds.get('steam_guard_secret'):
            ttk.Label(status_frame, text="\u2713 Steam Guard (2FA) configured",
                      foreground="green").pack(anchor=tk.W)

        # Credentials frame
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=15)
        config_frame.pack(fill=tk.X, pady=(0, 15))

        self.steam_anon_var = tk.BooleanVar(value=stored_creds.get('use_anonymous', False))
        ttk.Checkbutton(config_frame,
                        text="Use Anonymous Login (limited to free games)",
                        variable=self.steam_anon_var).pack(anchor=tk.W, pady=(0, 15))

        # Username
        user_frame = ttk.Frame(config_frame)
        user_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(user_frame, text="Username:", width=15, anchor=tk.W).pack(side=tk.LEFT)
        self.steam_username_var = tk.StringVar(value=stored_creds.get('username', ''))
        self.steam_username_entry = ttk.Entry(user_frame, textvariable=self.steam_username_var, width=30)
        self.steam_username_entry.pack(side=tk.LEFT, padx=(10, 0))

        # Password
        pass_frame = ttk.Frame(config_frame)
        pass_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(pass_frame, text="Password:", width=15, anchor=tk.W).pack(side=tk.LEFT)
        self.steam_password_var = tk.StringVar(value=stored_creds.get('password', ''))
        self.steam_password_entry = ttk.Entry(pass_frame, textvariable=self.steam_password_var,
                                              width=30, show="*")
        self.steam_password_entry.pack(side=tk.LEFT, padx=(10, 0))

        self.show_steam_pass_var = tk.BooleanVar(value=False)

        def toggle_pass_visibility():
            self.steam_password_entry.config(
                show="" if self.show_steam_pass_var.get() else "*")

        ttk.Checkbutton(pass_frame, text="Show",
                        variable=self.show_steam_pass_var,
                        command=toggle_pass_visibility).pack(side=tk.LEFT, padx=(10, 0))

        # Steam Guard section
        guard_frame = ttk.LabelFrame(main_frame, text="Steam Guard (2FA)", padding=15)
        guard_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(guard_frame,
                  text="Enter your Steam Guard shared secret to automatically generate "
                       "2FA codes during login.",
                  wraplength=650, foreground="gray").pack(anchor=tk.W, pady=(0, 10))

        secret_frame = ttk.Frame(guard_frame)
        secret_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(secret_frame, text="Shared Secret:", width=15, anchor=tk.W).pack(side=tk.LEFT)
        self.steam_guard_var = tk.StringVar(value=stored_creds.get('steam_guard_secret', ''))
        self.steam_guard_entry = ttk.Entry(secret_frame, textvariable=self.steam_guard_var, width=35)
        self.steam_guard_entry.pack(side=tk.LEFT, padx=(10, 0))

        def test_steam_guard():
            secret = self.steam_guard_var.get().strip()
            if not secret:
                messagebox.showwarning("No Secret",
                    "Please enter a Steam Guard shared secret first.")
                return
            try:
                import pyotp
                code = pyotp.TOTP(secret).now()
                messagebox.showinfo("Steam Guard Test",
                    f"Current 2FA Code: {code}\n\nThis code changes every 30 seconds.")
            except ImportError:
                messagebox.showerror("Missing Package",
                    "pyotp package is required for Steam Guard.\n"
                    "Install with: pip install pyotp")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid secret: {e}")

        ttk.Button(secret_frame, text="Test Code",
                   command=test_steam_guard).pack(side=tk.LEFT, padx=(10, 0))

        def update_field_states(*_args):
            state = 'disabled' if self.steam_anon_var.get() else 'normal'
            self.steam_username_entry.config(state=state)
            self.steam_password_entry.config(state=state)
            self.steam_guard_entry.config(state=state)

        self.steam_anon_var.trace_add("write", update_field_states)
        update_field_states()

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        def save_steam_credentials():
            success = db.save_steam_credentials(
                username=self.steam_username_var.get().strip(),
                password=self.steam_password_var.get(),
                steam_guard_secret=self.steam_guard_var.get().strip(),
                use_anonymous=self.steam_anon_var.get())
            if success:
                self.steam_status_label.config(
                    text="\u2713 Credentials saved successfully!", foreground="green")
                messagebox.showinfo("Success", "Steam credentials saved successfully!")
            else:
                messagebox.showerror("Error", "Failed to save Steam credentials.")

        def clear_steam_credentials():
            if messagebox.askyesno("Confirm",
                    "Are you sure you want to delete saved Steam credentials?"):
                db.delete_steam_credentials()
                self.steam_username_var.set("")
                self.steam_password_var.set("")
                self.steam_guard_var.set("")
                self.steam_anon_var.set(False)
                self.steam_status_label.config(
                    text="\u25CB No credentials configured", foreground="gray")

        ttk.Button(button_frame, text="Save Steam Credentials",
                   command=save_steam_credentials).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Clear Credentials",
                   command=clear_steam_credentials).pack(side=tk.RIGHT)

    def _create_system_settings_tab(self, parent, config, db):
        """Create system settings controls."""
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        settings = [
            ("Version", "version", config.get("version", "0.1"), "string"),
            ("Web Port", "web_port", config.get("web_port", 8080), "integer"),
            ("Enable Auto Updates", "enable_auto_updates",
             config.get("enable_auto_updates", True), "boolean"),
            ("Enable Tray Icon", "enable_tray_icon",
             config.get("enable_tray_icon", True), "boolean"),
            ("Check Updates Interval", "check_updates_interval",
             config.get("check_updates_interval", 3600), "integer"),
            ("Log Level", "log_level", config.get("log_level", "INFO"), "string"),
            ("Max Log Size", "max_log_size",
             config.get("max_log_size", 10485760), "integer"),
            ("Max Log Files", "max_log_files",
             config.get("max_log_files", 10), "integer"),
        ]
        self._create_settings_controls(scrollable_frame, settings, "main")

    # ── Shared helpers ───────────────────────────────────────────────────

    def _create_settings_controls(self, parent, settings, config_type):
        """Create form controls for a list of settings."""
        self.settings_vars = getattr(self, 'settings_vars', {})
        self.settings_vars[config_type] = {}

        for label_text, key, default_value, value_type in settings:
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, padx=10, pady=2)

            ttk.Label(frame, text=f"{label_text}:", width=25, anchor=tk.W).pack(side=tk.LEFT)

            if value_type == "boolean":
                var = tk.BooleanVar(value=default_value)
                ttk.Checkbutton(frame, variable=var).pack(side=tk.LEFT)
            elif value_type == "integer":
                var = tk.StringVar(value=str(default_value))
                ttk.Entry(frame, textvariable=var, width=20).pack(side=tk.LEFT)
            else:
                var = tk.StringVar(value=str(default_value))
                ttk.Entry(frame, textvariable=var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.settings_vars[config_type][key] = (var, value_type)

    def _save_settings(self, window, db):
        """Save all settings to database."""
        try:
            if "dashboard" in getattr(self, 'settings_vars', {}):
                for key, (var, value_type) in self.settings_vars["dashboard"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    else:
                        value = var.get()
                    db.set_dashboard_config(key, value, value_type, "settings")

            if hasattr(self, 'update_config_text'):
                try:
                    config_data = json.loads(
                        self.update_config_text.get(1.0, tk.END))
                    db.set_update_config("full_config", config_data, "json", "settings")
                except json.JSONDecodeError as e:
                    messagebox.showerror("JSON Error",
                        f"Invalid JSON in update config: {e}")
                    return

            if "main" in getattr(self, 'settings_vars', {}):
                for key, (var, value_type) in self.settings_vars["main"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    else:
                        value = var.get()
                    db.set_main_config(key, value, value_type, "settings")

            messagebox.showinfo("Settings Saved",
                                "Settings have been saved successfully!")
            window.destroy()

        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save settings: {e}")
