# -*- coding: utf-8 -*-
# Dashboard settings - Settings dialog, all settings tabs, save logic

import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Any, Dict, Optional
import threading
import subprocess
import urllib.request
import urllib.error

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path
setup_module_path()

from Modules.core.server_logging import get_dashboard_logger
from Host.dashboard_functions import centre_window

if TYPE_CHECKING:
    from Modules.server.server_manager import ServerManager

logger = get_dashboard_logger()

class DashboardSettingsMixin:
    # Type stubs for attributes provided by ServerManagerDashboard at runtime
    if TYPE_CHECKING:
        root: tk.Tk
        server_manager: Optional[ServerManager]
        variables: Dict[str, Any]

    def show_settings_dialog(self):
        # Show settings dialog for editing configuration
        if hasattr(self, 'settings_window') and self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("800x600")
        settings_window.resizable(True, True)
        settings_window.transient(self.root)
        settings_window.grab_set()
        centre_window(settings_window, 800, 600, self.root)
        settings_window.lift()
        settings_window.focus_force()

        notebook = ttk.Notebook(settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        dashboard_frame = ttk.Frame(notebook)
        notebook.add(dashboard_frame, text="Dashboard")

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
        self._create_update_settings_tab(update_frame, update_config, main_config, db)
        self._create_steam_settings_tab(steam_frame, db)
        self._create_system_settings_tab(system_frame, main_config, db)

        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(button_frame, text="Save",
                   command=lambda: self._save_settings(settings_window, db)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel",
                   command=settings_window.destroy).pack(side=tk.RIGHT)

        self.settings_window = settings_window

    # Tabs
    def _create_dashboard_settings_tab(self, parent, config, db):
        # Create dashboard settings controls
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
        # Create cluster settings controls
        from Modules.core.common import REGISTRY_PATH, get_registry_value, set_registry_value

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
        # Build the pending join-requests treeview (Host only)
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

    def _create_update_settings_tab(self, parent, config, main_config, db):
        # Create ServerManager update controls
        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="ServerManager Updates",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(main_frame,
                  text="Check GitHub releases for a newer ServerManager version and launch the updater tool.",
                  wraplength=700, foreground="gray").pack(anchor=tk.W, pady=(0, 15))

        configured_version = str(main_config.get("version", "")).strip()
        if configured_version and configured_version.lower() not in {"0.1", "unknown", "none"}:
            current_version = configured_version
        else:
            current_version = "Detecting local build..."
        self.sm_current_version = current_version
        self.sm_current_build_var = tk.StringVar(value=f"Current build: {current_version}")
        ttk.Label(main_frame, textvariable=self.sm_current_build_var,
                  font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 4))

        source_frame = ttk.Frame(main_frame)
        source_frame.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(source_frame, text="Update source:").pack(side=tk.LEFT)
        self.sm_update_source_var = tk.StringVar(value="Stable Releases")
        self.sm_update_source_combo = ttk.Combobox(
            source_frame,
            textvariable=self.sm_update_source_var,
            state="readonly",
            values=["Stable Releases", "Development Branch"],
            width=22
        )
        self.sm_update_source_combo.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(source_frame, text="Branch:").pack(side=tk.LEFT, padx=(16, 0))
        default_branch = "main"
        self.sm_dev_branch_var = tk.StringVar(value=default_branch)
        self.sm_dev_branch_entry = ttk.Entry(source_frame, textvariable=self.sm_dev_branch_var, width=16)
        self.sm_dev_branch_entry.pack(side=tk.LEFT, padx=(8, 0))

        def _on_source_changed(*_args):
            state = "normal" if self.sm_update_source_var.get() == "Development Branch" else "disabled"
            self.sm_dev_branch_entry.config(state=state)

        self.sm_update_source_var.trace_add("write", _on_source_changed)
        _on_source_changed()

        self.sm_update_status_var = tk.StringVar(value="Click 'Check for Updates' to check the selected source.")
        status_label = ttk.Label(main_frame, textvariable=self.sm_update_status_var,
                                 font=("Segoe UI", 10, "bold"))
        status_label.pack(anchor=tk.W, pady=(0, 12))

        details_frame = ttk.LabelFrame(main_frame, text="Release Details", padding=10)
        details_frame.pack(fill=tk.X, pady=(0, 12))
        self.sm_latest_version_var = tk.StringVar(value="Latest release: Unknown")
        self.sm_release_url_var = tk.StringVar(value="Release URL: N/A")
        ttk.Label(details_frame, textvariable=self.sm_latest_version_var).pack(anchor=tk.W, pady=(0, 4))
        ttk.Label(details_frame, textvariable=self.sm_release_url_var, foreground="gray").pack(anchor=tk.W)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(5, 0))

        self.sm_check_updates_btn = ttk.Button(button_frame, text="Check for Updates",
                                               command=self._check_servermanager_updates_async)
        self.sm_check_updates_btn.pack(side=tk.LEFT)

        ttk.Button(button_frame, text="Run ServerManager Updater",
                   command=self._launch_servermanager_updater).pack(side=tk.LEFT, padx=(8, 0))

        # Resolve local git branch/build without blocking settings dialog creation
        parent.after(50, self._populate_local_build_info_async)

    def _populate_local_build_info_async(self):
        # Fill local branch and build label in a background thread to keep settings opening responsive
        def _worker():
            branch = self._get_local_git_branch()
            short_sha = self._get_local_git_short_sha()

            if branch and short_sha:
                build_label = f"{branch}@{short_sha}"
            elif short_sha:
                build_label = short_sha
            else:
                build_label = None

            def _update_ui():
                if branch and hasattr(self, 'sm_dev_branch_var'):
                    # Keep user-entered value if they already changed it.
                    current = self.sm_dev_branch_var.get().strip()
                    if current in {"", "main"}:
                        self.sm_dev_branch_var.set(branch)

                if build_label and hasattr(self, 'sm_current_build_var'):
                    self.sm_current_version = build_label
                    self.sm_current_build_var.set(f"Current build: {build_label}")
                elif hasattr(self, 'sm_current_build_var') and self.sm_current_version == "Detecting local build...":
                    self.sm_current_version = "Unknown"
                    self.sm_current_build_var.set("Current build: Unknown")

            self.root.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True, name="SMBuildInfo").start()

    def _get_current_build_label(self, main_config: Dict[str, Any]) -> str:
        # Prefer configured version, fall back to git branch + commit for dev builds
        configured = str(main_config.get("version", "")).strip()
        if configured and configured.lower() not in {"0.1", "unknown", "none"}:
            return configured

        branch = self._get_local_git_branch()
        short_sha = self._get_local_git_short_sha()
        if branch and short_sha:
            return f"{branch}@{short_sha}"
        if short_sha:
            return short_sha
        return configured or "Unknown"

    def _run_git_command(self, args):
        # Execute git command in repository and return stdout text, or None on failure
        try:
            output = subprocess.check_output(
                ["git"] + args,
                cwd=self.server_manager_dir,
                stderr=subprocess.DEVNULL,
                text=True
            )
            return output.strip()
        except Exception:
            return None

    def _get_local_git_branch(self) -> Optional[str]:
        return self._run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])

    def _get_local_git_sha(self) -> Optional[str]:
        return self._run_git_command(["rev-parse", "HEAD"])

    def _get_local_git_short_sha(self) -> Optional[str]:
        return self._run_git_command(["rev-parse", "--short", "HEAD"])

    def _github_json(self, api_url: str) -> Dict[str, Any]:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "ServerManagerDashboard/1.0",
                "Accept": "application/vnd.github+json"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _parse_version_tuple(self, version_text: str):
        # Convert a version string like v1.2.3 into a tuple of ints for comparison
        clean = (version_text or "").strip().lower().lstrip("v")
        numeric_part = clean.split("-")[0]
        pieces = []
        for part in numeric_part.split('.'):
            digits = ''.join(ch for ch in part if ch.isdigit())
            if digits == "":
                pieces.append(0)
            else:
                pieces.append(int(digits))
        while len(pieces) < 3:
            pieces.append(0)
        return tuple(pieces[:3])

    def _check_servermanager_updates_async(self):
        # Check selected update source without blocking the UI
        selected_source = self.sm_update_source_var.get()
        branch_name = (self.sm_dev_branch_var.get().strip() or "main")
        self.sm_check_updates_btn.config(state=tk.DISABLED)
        if selected_source == "Development Branch":
            self.sm_update_status_var.set(f"Checking branch '{branch_name}'...")
        else:
            self.sm_update_status_var.set("Checking stable releases...")

        def _worker():
            latest_label = "Unknown"
            release_url = ""
            try:
                if selected_source == "Stable Releases":
                    payload = self._github_json(
                        "https://api.github.com/repos/SparksSkywere/servermanager/releases/latest"
                    )
                    latest_label = str(payload.get("tag_name") or payload.get("name") or "Unknown").strip()
                    release_url = str(payload.get("html_url") or "").strip()

                    try:
                        current_tuple = self._parse_version_tuple(self.sm_current_version)
                        latest_tuple = self._parse_version_tuple(latest_label)
                        has_update = latest_tuple > current_tuple
                    except Exception:
                        has_update = False

                    def _update_ui_success():
                        self.sm_latest_version_var.set(f"Latest release: {latest_label}")
                        self.sm_release_url_var.set(f"Release URL: {release_url or 'N/A'}")
                        if has_update:
                            self.sm_update_status_var.set("Updates available")
                        else:
                            self.sm_update_status_var.set("ServerManager is up to date")
                        self.sm_check_updates_btn.config(state=tk.NORMAL)

                    self.root.after(0, _update_ui_success)
                else:
                    commit_payload = self._github_json(
                        f"https://api.github.com/repos/SparksSkywere/servermanager/commits/{branch_name}"
                    )
                    remote_sha = str(commit_payload.get("sha") or "").strip()
                    latest_label = remote_sha[:7] if remote_sha else "Unknown"
                    release_url = f"https://github.com/SparksSkywere/servermanager/archive/refs/heads/{branch_name}.zip"

                    local_sha = self._get_local_git_sha()
                    has_update = bool(local_sha and remote_sha and local_sha != remote_sha)
                    behind_count = None

                    if local_sha and remote_sha and local_sha != remote_sha:
                        try:
                            compare_payload = self._github_json(
                                f"https://api.github.com/repos/SparksSkywere/servermanager/compare/{local_sha}...{branch_name}"
                            )
                            behind_count = int(compare_payload.get("behind_by", 0))
                        except Exception:
                            behind_count = None

                    def _update_ui_dev_success():
                        self.sm_latest_version_var.set(
                            f"Latest commit ({branch_name}): {latest_label}"
                        )
                        self.sm_release_url_var.set(f"Download URL: {release_url}")
                        if not local_sha:
                            self.sm_update_status_var.set(
                                "Could not determine local git commit; dev update status unavailable"
                            )
                        elif has_update:
                            if behind_count is not None and behind_count > 0:
                                self.sm_update_status_var.set(
                                    f"Updates available ({behind_count} commit(s) ahead on {branch_name})"
                                )
                            else:
                                self.sm_update_status_var.set("Updates available")
                        else:
                            self.sm_update_status_var.set("Development branch is up to date")
                        self.sm_check_updates_btn.config(state=tk.NORMAL)

                    self.root.after(0, _update_ui_dev_success)
            except urllib.error.HTTPError as e:
                error_code = getattr(e, "code", None)

                if selected_source == "Stable Releases" and error_code == 404:
                    def _update_ui_no_releases():
                        self.sm_latest_version_var.set("Latest release: None published")
                        self.sm_release_url_var.set(
                            "Release URL: https://github.com/SparksSkywere/servermanager/releases"
                        )
                        self.sm_update_status_var.set("No stable releases published yet")
                        self.sm_check_updates_btn.config(state=tk.NORMAL)

                    self.root.after(0, _update_ui_no_releases)
                    return

                error_text = f"HTTP {error_code}" if error_code else str(e)

                def _update_ui_http_error():
                    self.sm_latest_version_var.set(f"Latest release: {latest_label}")
                    self.sm_release_url_var.set(f"Release URL: {release_url or 'N/A'}")
                    self.sm_update_status_var.set(f"Update check failed: {error_text}")
                    self.sm_check_updates_btn.config(state=tk.NORMAL)

                self.root.after(0, _update_ui_http_error)
            except urllib.error.URLError as e:
                error_text = getattr(e, "reason", str(e))

                def _update_ui_network_error():
                    self.sm_latest_version_var.set(f"Latest release: {latest_label}")
                    self.sm_release_url_var.set(f"Release URL: {release_url or 'N/A'}")
                    self.sm_update_status_var.set(f"Update check failed: {error_text}")
                    self.sm_check_updates_btn.config(state=tk.NORMAL)

                self.root.after(0, _update_ui_network_error)
            except Exception as e:
                error_text = str(e)

                def _update_ui_error():
                    self.sm_latest_version_var.set(f"Latest release: {latest_label}")
                    self.sm_release_url_var.set(f"Release URL: {release_url or 'N/A'}")
                    self.sm_update_status_var.set(f"Update check failed: {error_text}")
                    self.sm_check_updates_btn.config(state=tk.NORMAL)

                self.root.after(0, _update_ui_error)

        threading.Thread(target=_worker, daemon=True, name="SMUpdateCheck").start()

    def _launch_servermanager_updater(self):
        # Launch the existing updater script
        updater_path = os.path.join(self.server_manager_dir, "Update-ServerManager.pyw")
        if not os.path.exists(updater_path):
            messagebox.showerror("Updater Not Found",
                                 f"Could not find updater script:\n{updater_path}")
            return

        try:
            if os.name == 'nt':
                python_exe = sys.executable
                if python_exe.lower().endswith("python.exe"):
                    pythonw_exe = python_exe[:-4] + "w.exe"
                    if os.path.exists(pythonw_exe):
                        python_exe = pythonw_exe

                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

                subprocess.Popen(
                    [python_exe, updater_path],
                    cwd=self.server_manager_dir,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False
                )
            else:
                subprocess.Popen([sys.executable, updater_path], start_new_session=True)
            self.sm_update_status_var.set("Updater launched")
            if hasattr(self, 'settings_window') and self.settings_window and self.settings_window.winfo_exists():
                self.settings_window.lift()
                self.settings_window.focus_force()
        except Exception as e:
            messagebox.showerror("Launch Error", f"Failed to launch updater: {e}")

    def _create_steam_settings_tab(self, parent, db):
        # Create Steam credentials settings tab
        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Steam Credentials",
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
            status_text, status_color = "Using Anonymous Login", "blue"
        elif stored_creds.get('username'):
            status_text = f"Credentials saved for: {stored_creds['username']}"
            status_color = "green"
        else:
            status_text, status_color = "No credentials configured", "gray"

        self.steam_status_label = ttk.Label(status_frame, text=status_text,
                                            foreground=status_color,
                                            font=("Segoe UI", 11))
        self.steam_status_label.pack(anchor=tk.W)

        if stored_creds.get('steam_guard_secret'):
            ttk.Label(status_frame, text="Steam Guard (2FA) configured",
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
                    text="Credentials saved successfully", foreground="green")
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
                    text="No credentials configured", foreground="gray")

        ttk.Button(button_frame, text="Save Steam Credentials",
                   command=save_steam_credentials).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Clear Credentials",
                   command=clear_steam_credentials).pack(side=tk.RIGHT)

    def _create_system_settings_tab(self, parent, config, db):
        # Create system settings controls
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

    # Shared helpers
    def _create_settings_controls(self, parent, settings, config_type):
        # Create form controls for a list of settings
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
        # Save all settings to database
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
