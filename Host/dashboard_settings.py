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
import ssl

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path
setup_module_path()

from Modules.core.server_logging import get_dashboard_logger
from Modules.ui.theme import persist_theme_preference
from Modules.ui.theme import get_theme_preference
from Modules.ui.color_palettes import list_themes, get_palette
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

    def _get_active_palette(self):
        theme_name = getattr(self, "current_theme", None) or get_theme_preference("light")
        return get_palette(theme_name)

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

        # Force theme pass so the new Toplevel gets current palette/titlebar styling.
        try:
            if hasattr(self, "apply_theme") and callable(getattr(self, "apply_theme")):
                self.apply_theme(getattr(self, "current_theme", get_theme_preference("light")), force=True)
        except Exception as e:
            logger.debug(f"Could not apply theme to settings window: {e}")

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

        hardware_frame = ttk.Frame(notebook)
        notebook.add(hardware_frame, text="Hardware")

        cluster_frame = ttk.Frame(notebook)
        notebook.add(cluster_frame, text="Cluster")

        minecraft_frame = ttk.Frame(notebook)
        notebook.add(minecraft_frame, text="Minecraft")

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
        self._create_hardware_settings_tab(hardware_frame, main_config, db)
        self._create_cluster_settings_tab(cluster_frame, db)
        self._create_minecraft_settings_tab(minecraft_frame)

        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(button_frame, text="Save",
                   command=lambda: self._save_settings(settings_window, db)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel",
                   command=settings_window.destroy).pack(side=tk.RIGHT)

        self.settings_window = settings_window

    def _create_themed_canvas(self, parent):
        # Create a canvas with palette-based background and border to avoid bright default outlines.
        try:
            theme_name = getattr(self, "current_theme", None) or get_theme_preference("light")
            palette = get_palette(theme_name)
        except Exception:
            palette = get_palette("light")

        return tk.Canvas(
            parent,
            bg=palette.get("canvas_bg"),
            highlightthickness=1,
            highlightbackground=palette.get("border"),
            highlightcolor=palette.get("border"),
            bd=0,
        )

    # Tabs
    def _create_dashboard_settings_tab(self, parent, config, db):
        # Create dashboard settings controls
        canvas = self._create_themed_canvas(parent)
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

        palette = self._get_active_palette()
        muted_fg = palette.get("text_disabled_fg")

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
                  foreground=muted_fg).pack(anchor=tk.W, padx=(20, 0), pady=(0, 10))

        ttk.Radiobutton(role_frame, text="Subhost (Slave)",
                        variable=self.cluster_role_var, value="Subhost").pack(anchor=tk.W, pady=2)
        ttk.Label(role_frame,
                  text="This installation connects to a master host for centralized management.",
                  foreground=muted_fg).pack(anchor=tk.W, padx=(20, 0), pady=(0, 5))

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
        palette = self._get_active_palette()
        ttk.Label(btn_frame, text="Auto-refresh: 10s",
              foreground=palette.get("text_disabled_fg")).pack(side=tk.RIGHT, padx=(10, 0))

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
        palette = self._get_active_palette()

        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="ServerManager Updates",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(main_frame,
                  text="Check GitHub releases for a newer ServerManager version and launch the updater tool.",
                  wraplength=700, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W, pady=(0, 15))

        current_version = self._get_current_build_label(main_config)
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
        ttk.Label(details_frame, textvariable=self.sm_release_url_var, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W)

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

        # Keep startup non-blocking: background worker fills branch/sha shortly after dialog opens.
        return "Detecting local build..."

    def _run_git_command(self, args):
        # Execute git command in repository and return stdout text, or None on failure
        try:
            popen_kwargs = {
                "cwd": self.server_manager_dir,
                "stderr": subprocess.DEVNULL,
                "text": True,
            }

            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            output = subprocess.check_output(["git"] + args, **popen_kwargs)
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
        palette = self._get_active_palette()

        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Steam Credentials",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 5))

        ttk.Label(main_frame,
                  text="Configure your Steam credentials for automatic login during "
                       "server installations and updates. Credentials are stored locally "
                       "with encryption.",
                   wraplength=700, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W, pady=(0, 20))

        stored_creds = db.get_steam_credentials() or {}

        # Status indicator
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 15))

        if stored_creds.get('use_anonymous'):
            status_text, status_color = "Using Anonymous Login", palette.get("info_fg")
        elif stored_creds.get('username'):
            status_text = f"Credentials saved for: {stored_creds['username']}"
            status_color = palette.get("success_fg")
        else:
            status_text, status_color = "No credentials configured", palette.get("text_disabled_fg")

        self.steam_status_label = ttk.Label(status_frame, text=status_text,
                                            foreground=status_color,
                                            font=("Segoe UI", 11))
        self.steam_status_label.pack(anchor=tk.W)

        if stored_creds.get('steam_guard_secret'):
            ttk.Label(status_frame, text="Steam Guard (2FA) configured",
                      foreground=palette.get("success_fg")).pack(anchor=tk.W)

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
                   wraplength=650, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W, pady=(0, 10))

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
                    text="Credentials saved successfully", foreground=palette.get("success_fg"))
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
                    text="No credentials configured", foreground=palette.get("text_disabled_fg"))

        ttk.Button(button_frame, text="Save Steam Credentials",
                   command=save_steam_credentials).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Clear Credentials",
                   command=clear_steam_credentials).pack(side=tk.RIGHT)

    def _create_system_settings_tab(self, parent, config, db):
        # Create system settings controls
        canvas = self._create_themed_canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        settings = [
            ("Theme", "theme", config.get("theme", "light"), "theme_choice"),
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

    def _create_hardware_settings_tab(self, parent, config, db):
        # Create hardware integrations settings controls
        canvas = self._create_themed_canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            scrollable_frame,
            text="Temperature providers and BMC integration settings",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W, padx=10, pady=(8, 6))

        settings = [
            ("Temperature Mode", "temperatureMode", config.get("temperatureMode", "auto"), "temperature_mode_choice"),
            ("Temperature Poll Interval (s)", "temperaturePollInterval", config.get("temperaturePollInterval", 10), "integer"),
            ("iLO Host", "iloHost", config.get("iloHost", ""), "string"),
            ("iLO Username", "iloUsername", config.get("iloUsername", ""), "string"),
            ("iLO Password", "iloPassword", config.get("iloPassword", ""), "secure_string"),
            ("iLO Verify TLS", "iloVerifyTLS", config.get("iloVerifyTLS", False), "boolean"),
            ("iLO Timeout (s)", "iloTimeout", config.get("iloTimeout", 4), "integer"),
            ("iDRAC Host", "idracHost", config.get("idracHost", ""), "string"),
            ("iDRAC Username", "idracUsername", config.get("idracUsername", ""), "string"),
            ("iDRAC Password", "idracPassword", config.get("idracPassword", ""), "secure_string"),
            ("iDRAC Verify TLS", "idracVerifyTLS", config.get("idracVerifyTLS", False), "boolean"),
            ("iDRAC Timeout (s)", "idracTimeout", config.get("idracTimeout", 4), "integer"),
        ]
        self._create_settings_controls(scrollable_frame, settings, "hardware")

        test_frame = ttk.LabelFrame(scrollable_frame, text="Connection Tests", padding=10)
        test_frame.pack(fill=tk.X, padx=10, pady=(10, 8))

        self.hardware_test_status_var = tk.StringVar(value="Use the buttons below to test BMC access.")
        palette = self._get_active_palette()
        self.hardware_test_status_label = ttk.Label(
            test_frame,
            textvariable=self.hardware_test_status_var,
            foreground=palette.get("text_disabled_fg")
        )
        self.hardware_test_status_label.pack(anchor=tk.W, pady=(0, 8))

        button_row = ttk.Frame(test_frame)
        button_row.pack(fill=tk.X)

        self.ilo_test_button = ttk.Button(button_row, text="Test iLO", command=lambda: self._test_hardware_connection("ilo"))
        self.ilo_test_button.pack(side=tk.LEFT, padx=(0, 6))
        self.idrac_test_button = ttk.Button(button_row, text="Test iDRAC", command=lambda: self._test_hardware_connection("idrac"))
        self.idrac_test_button.pack(side=tk.LEFT)

        # Live mode switching for provider-specific settings.
        hardware_vars = getattr(self, 'settings_vars', {}).get("hardware", {})
        mode_info = hardware_vars.get("temperatureMode")
        if mode_info:
            mode_var, _ = mode_info
            mode_var.trace_add("write", lambda *_: self._update_hardware_field_states())
        self._update_hardware_field_states()

    # Shared helpers
    def _create_minecraft_settings_tab(self, parent):
        # Create Minecraft / modded launcher settings tab (e.g. CurseForge API key)
        from Modules.core.common import REGISTRY_PATH, get_registry_value, set_registry_value

        palette = self._get_active_palette()

        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Minecraft & Modded Launcher Settings",
                  font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, pady=(0, 5))

        ttk.Label(main_frame,
                  text="Configure API keys and options used when browsing and installing "
                       "modded Minecraft server packs.",
                  wraplength=700, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W, pady=(0, 20))

        # CurseForge section
        cf_frame = ttk.LabelFrame(main_frame, text="CurseForge", padding=15)
        cf_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(cf_frame,
                  text="A CurseForge API key is required to browse and install CurseForge modpacks. "
                       "You can obtain a free key from https://console.curseforge.com/",
                  wraplength=650, foreground=palette.get("text_disabled_fg")).pack(anchor=tk.W, pady=(0, 12))

        key_row = ttk.Frame(cf_frame)
        key_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(key_row, text="API Key:", width=12, anchor=tk.W).pack(side=tk.LEFT)
        current_key = get_registry_value(REGISTRY_PATH, "CurseForgeAPIKey", "")
        self.curseforge_key_var = tk.StringVar(value=current_key)
        key_entry = ttk.Entry(key_row, textvariable=self.curseforge_key_var, width=50, show="*")
        key_entry.pack(side=tk.LEFT, padx=(10, 8))

        show_var = tk.BooleanVar(value=False)

        def _toggle_show():
            key_entry.config(show="" if show_var.get() else "*")

        ttk.Checkbutton(key_row, text="Show", variable=show_var,
                        command=_toggle_show).pack(side=tk.LEFT)

        # Status indicator
        cf_status_var = tk.StringVar(value="Key saved" if current_key else "No API key configured")
        cf_status_color = palette.get("success_fg") if current_key else palette.get("text_disabled_fg")
        self.cf_status_label = ttk.Label(cf_frame, textvariable=cf_status_var,
                                         foreground=cf_status_color)
        self.cf_status_label.pack(anchor=tk.W, pady=(0, 8))

        btn_row = ttk.Frame(cf_frame)
        btn_row.pack(fill=tk.X)

        def _save_cf_key():
            new_key = self.curseforge_key_var.get().strip()
            set_registry_value(REGISTRY_PATH, "CurseForgeAPIKey", new_key)
            if new_key:
                cf_status_var.set("API key saved")
                self.cf_status_label.config(foreground=palette.get("success_fg"))
                messagebox.showinfo("Saved", "CurseForge API key saved successfully.")
            else:
                cf_status_var.set("No API key configured")
                self.cf_status_label.config(foreground=palette.get("text_disabled_fg"))
                messagebox.showinfo("Cleared", "CurseForge API key removed.")

        def _clear_cf_key():
            if messagebox.askyesno("Confirm", "Remove the saved CurseForge API key?"):
                self.curseforge_key_var.set("")
                set_registry_value(REGISTRY_PATH, "CurseForgeAPIKey", "")
                cf_status_var.set("No API key configured")
                self.cf_status_label.config(foreground=palette.get("text_disabled_fg"))

        ttk.Button(btn_row, text="Save API Key", command=_save_cf_key).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Clear Key", command=_clear_cf_key).pack(side=tk.LEFT)

    def _create_settings_controls(self, parent, settings, config_type):
        # Create form controls for a list of settings
        self.settings_vars = getattr(self, 'settings_vars', {})
        self.settings_vars[config_type] = {}
        self.settings_widgets = getattr(self, 'settings_widgets', {})
        self.settings_widgets[config_type] = {}

        for label_text, key, default_value, value_type in settings:
            frame = ttk.Frame(parent)
            frame.pack(fill=tk.X, padx=10, pady=2)

            ttk.Label(frame, text=f"{label_text}:", width=25, anchor=tk.W).pack(side=tk.LEFT)

            if value_type == "boolean":
                var = tk.BooleanVar(value=default_value)
                control = ttk.Checkbutton(frame, variable=var)
                control.pack(side=tk.LEFT)
            elif value_type == "integer":
                var = tk.StringVar(value=str(default_value))
                control = ttk.Entry(frame, textvariable=var, width=20)
                control.pack(side=tk.LEFT)
            elif value_type == "theme_choice":
                normalised = str(default_value).strip().lower()
                available_themes = list_themes()
                if normalised not in available_themes:
                    normalised = "light"
                var = tk.StringVar(value=normalised)
                control = ttk.Combobox(
                    frame,
                    textvariable=var,
                    state="readonly",
                    values=available_themes,
                    width=18
                )
                control.pack(side=tk.LEFT)
            elif value_type == "temperature_mode_choice":
                normalised = str(default_value).strip().lower()
                available_modes = ["auto", "local", "ilo", "idrac"]
                if normalised not in available_modes:
                    normalised = "auto"
                var = tk.StringVar(value=normalised)
                control = ttk.Combobox(
                    frame,
                    textvariable=var,
                    state="readonly",
                    values=available_modes,
                    width=18
                )
                control.pack(side=tk.LEFT)
            elif value_type == "secure_string":
                var = tk.StringVar(value=str(default_value or ""))
                control = ttk.Entry(frame, textvariable=var, width=30, show="*")
                control.pack(side=tk.LEFT, fill=tk.X, expand=True)
            else:
                var = tk.StringVar(value=str(default_value))
                control = ttk.Entry(frame, textvariable=var, width=30)
                control.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.settings_vars[config_type][key] = (var, value_type)
            self.settings_widgets[config_type][key] = control

    def _update_hardware_field_states(self):
        # Dynamically toggle iLO/iDRAC controls based on selected temperature mode.
        hardware_vars = getattr(self, 'settings_vars', {}).get("hardware", {})
        hardware_widgets = getattr(self, 'settings_widgets', {}).get("hardware", {})

        mode_info = hardware_vars.get("temperatureMode")
        if not mode_info:
            return

        mode_var, _ = mode_info
        mode = str(mode_var.get() or "auto").strip().lower()

        ilo_keys = ["iloHost", "iloUsername", "iloPassword", "iloVerifyTLS", "iloTimeout"]
        idrac_keys = ["idracHost", "idracUsername", "idracPassword", "idracVerifyTLS", "idracTimeout"]

        if mode in {"auto"}:
            ilo_state = "normal"
            idrac_state = "normal"
            status_text = "Auto mode: local sensors first, then iLO/iDRAC if configured."
            status_level = "muted"
        elif mode in {"local", "windows"}:
            ilo_state = "disabled"
            idrac_state = "disabled"
            status_text = "Local mode: remote iLO/iDRAC settings are disabled."
            status_level = "muted"
        elif mode == "ilo":
            ilo_state = "normal"
            idrac_state = "disabled"
            status_text = "iLO mode: only iLO settings are active."
            status_level = "muted"
        elif mode == "idrac":
            ilo_state = "disabled"
            idrac_state = "normal"
            status_text = "iDRAC mode: only iDRAC settings are active."
            status_level = "muted"
        else:
            ilo_state = "normal"
            idrac_state = "normal"
            status_text = "Unknown mode: all remote settings enabled."
            status_level = "warning"

        for key in ilo_keys:
            widget = hardware_widgets.get(key)
            if widget is not None:
                widget.configure(state=ilo_state)

        for key in idrac_keys:
            widget = hardware_widgets.get(key)
            if widget is not None:
                widget.configure(state=idrac_state)

        if hasattr(self, 'ilo_test_button') and self.ilo_test_button:
            self.ilo_test_button.configure(state=("normal" if ilo_state == "normal" else "disabled"))
        if hasattr(self, 'idrac_test_button') and self.idrac_test_button:
            self.idrac_test_button.configure(state=("normal" if idrac_state == "normal" else "disabled"))

        self._set_hardware_status(status_text, status_level)

        last_mode = getattr(self, '_hardware_last_mode', None)
        if mode != last_mode:
            self._hardware_last_mode = mode
            if mode == "auto":
                self._auto_detect_hardware_provider()
            elif mode == "ilo":
                self._auto_validate_hardware_connection("ilo")
            elif mode == "idrac":
                self._auto_validate_hardware_connection("idrac")

    def _set_hardware_status(self, message: str, level: str = "muted"):
        palette = self._get_active_palette()
        color_map = {
            "muted": palette.get("text_disabled_fg"),
            "success": palette.get("success_fg"),
            "warning": palette.get("warning_fg"),
            "error": palette.get("error_fg"),
            "info": palette.get("text_fg"),
        }

        if hasattr(self, 'hardware_test_status_var'):
            self.hardware_test_status_var.set(message)
        if hasattr(self, 'hardware_test_status_label') and self.hardware_test_status_label:
            self.hardware_test_status_label.configure(foreground=color_map.get(level, palette.get("text_disabled_fg")))

    def _auto_detect_hardware_provider(self):
        # In auto mode, infer vendor and quickly probe the expected BMC endpoint.
        hardware_vars = getattr(self, 'settings_vars', {}).get("hardware", {})

        def _get_field(key, default=""):
            info = hardware_vars.get(key)
            if not info:
                return default
            var, _ = info
            return var.get()

        def _detect_vendor() -> str:
            try:
                output = subprocess.check_output(
                    ["wmic", "computersystem", "get", "manufacturer"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                lines = [line.strip() for line in output.splitlines() if line.strip() and "manufacturer" not in line.lower()]
                manufacturer = lines[0].lower() if lines else ""
            except Exception:
                manufacturer = ""

            if any(token in manufacturer for token in ("hewlett", "hpe", "hp")):
                return "ilo"
            if "dell" in manufacturer:
                return "idrac"
            return ""

        def _probe_redfish(host: str, verify_tls: bool) -> bool:
            host = str(host or "").strip()
            if not host:
                return False

            if host.startswith("https://"):
                base = host
            elif host.startswith("http://"):
                base = "https://" + host.split("://", 1)[1]
            else:
                base = f"https://{host}"

            try:
                # Always verify certificates to avoid MITM-prone insecure TLS contexts.
                context = ssl.create_default_context()

                request = urllib.request.Request(
                    url=f"{base.rstrip('/')}/redfish/v1",
                    method="GET",
                    headers={"User-Agent": "ServerManager/1.0"},
                )
                with urllib.request.urlopen(request, timeout=2.0, context=context):
                    return True
            except ssl.SSLError:
                return False
            except urllib.error.HTTPError as e:
                return e.code in {200, 401, 403, 404}
            except Exception:
                return False

        self._set_hardware_status("Auto mode: checking server vendor and BMC endpoint...", "muted")

        def _worker():
            vendor_target = _detect_vendor()
            if vendor_target == "ilo":
                host = _get_field("iloHost", "")
                verify_tls = bool(_get_field("iloVerifyTLS", False))
                found = _probe_redfish(host, verify_tls)
                if found:
                    message = "Auto mode: HP detected, iLO endpoint found."
                    level = "success"
                else:
                    message = "iLO not found, select type manually"
                    level = "error"
            elif vendor_target == "idrac":
                host = _get_field("idracHost", "")
                verify_tls = bool(_get_field("idracVerifyTLS", False))
                found = _probe_redfish(host, verify_tls)
                if found:
                    message = "Auto mode: Dell detected, iDRAC endpoint found."
                    level = "success"
                else:
                    message = "iDRAC not found, select type manually"
                    level = "error"
            else:
                message = "Auto mode: vendor not HP/Dell; using local sensors unless remote type is selected."
                level = "muted"

            self.root.after(0, lambda: self._set_hardware_status(message, level))

        threading.Thread(target=_worker, daemon=True, name="HardwareAutoDetect").start()

    def _auto_validate_hardware_connection(self, provider_name: str):
        # Trigger a lightweight check when switching into a remote hardware mode.
        self._test_hardware_connection(provider_name, interactive=False, popup_on_failure=True)

    def _test_hardware_connection(self, provider_name: str, interactive: bool = True, popup_on_failure: bool = True):
        # Validate BMC connectivity for iLO/iDRAC without blocking the UI.
        try:
            from Modules.services.temperatures import IloTemperatureProvider, IdracTemperatureProvider
        except Exception as e:
            if interactive or popup_on_failure:
                messagebox.showerror("Import Error", f"Could not load hardware providers: {e}")
            return

        settings = getattr(self, 'settings_vars', {}).get("hardware", {})
        if not settings:
            if interactive or popup_on_failure:
                messagebox.showwarning("Unavailable", "Hardware settings are not available in this dialog.")
            return

        def _field(key, default=""):
            info = settings.get(key)
            if not info:
                return default
            var, _ = info
            return var.get()

        if provider_name == "ilo":
            host = str(_field("iloHost", "")).strip()
            username = str(_field("iloUsername", "")).strip()
            password = str(_field("iloPassword", ""))
            verify_tls = bool(_field("iloVerifyTLS", False))
            timeout = float(_field("iloTimeout", 4) or 4)
            provider = IloTemperatureProvider(host=host, username=username, password=password, verify_tls=verify_tls, timeout_seconds=timeout)
            label = "iLO"
        else:
            host = str(_field("idracHost", "")).strip()
            username = str(_field("idracUsername", "")).strip()
            password = str(_field("idracPassword", ""))
            verify_tls = bool(_field("idracVerifyTLS", False))
            timeout = float(_field("idracTimeout", 4) or 4)
            provider = IdracTemperatureProvider(host=host, username=username, password=password, verify_tls=verify_tls, timeout_seconds=timeout)
            label = "iDRAC"

        if not host or not username or not password:
            if interactive:
                messagebox.showwarning("Missing Fields", f"Please fill {label} host, username, and password before testing.")
            elif hasattr(self, 'hardware_test_status_var'):
                self._set_hardware_status(f"{label} auto-check skipped: missing host/username/password.", "warning")
            return

        self._set_hardware_status(f"Testing {label} connection...", "muted")

        def _worker():
            try:
                output = provider.collect()
                ok = bool(output)
                if ok:
                    first_line = (output.splitlines()[0] if output else "Connected")
                    message = f"{label} test succeeded: {first_line}"
                else:
                    message = f"{label} test failed: no thermal data returned."
            except Exception as e:
                ok = False
                message = f"{label} test failed: {e}"

            def _apply():
                self._set_hardware_status(message, "success" if ok else "error")
                if ok and interactive:
                    messagebox.showinfo("Hardware Test", message)
                elif not ok and (interactive or popup_on_failure):
                    messagebox.showwarning("Hardware Test", message)

            self.root.after(0, _apply)

        threading.Thread(target=_worker, daemon=True, name=f"HardwareTest-{provider_name}").start()

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
                selected_theme = None
                for key, (var, value_type) in self.settings_vars["main"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    elif value_type == "theme_choice":
                        value = str(var.get()).strip().lower()
                        if value not in list_themes():
                            value = "light"
                        if key == "theme":
                            selected_theme = value
                    elif value_type == "temperature_mode_choice":
                        value = str(var.get()).strip().lower()
                        if value not in {"auto", "local", "ilo", "idrac"}:
                            value = "auto"
                    elif value_type == "secure_string":
                        value = str(var.get())
                    else:
                        value = var.get()
                    if value_type in {"theme_choice", "temperature_mode_choice"}:
                        db_type = "string"
                    elif value_type == "secure_string":
                        db_type = "secure"
                    else:
                        db_type = value_type
                    db.set_main_config(key, value, db_type, "settings")

                if selected_theme and hasattr(self, "apply_theme") and callable(getattr(self, "apply_theme")):
                    try:
                        persist_theme_preference(selected_theme, write_registry=True)
                        self.apply_theme(selected_theme)
                    except Exception as theme_error:
                        logger.warning(f"Failed to apply theme after save: {theme_error}")

            if "hardware" in getattr(self, 'settings_vars', {}):
                for key, (var, value_type) in self.settings_vars["hardware"].items():
                    if value_type == "boolean":
                        value = var.get()
                    elif value_type == "integer":
                        try:
                            value = int(var.get())
                        except ValueError:
                            value = 0
                    elif value_type == "temperature_mode_choice":
                        value = str(var.get()).strip().lower()
                        if value not in {"auto", "local", "ilo", "idrac"}:
                            value = "auto"
                    elif value_type == "secure_string":
                        value = str(var.get())
                    else:
                        value = var.get()

                    if value_type == "temperature_mode_choice":
                        db_type = "string"
                    elif value_type == "secure_string":
                        db_type = "secure"
                    else:
                        db_type = value_type

                    db.set_main_config(key, value, db_type, "hardware")

            window.destroy()

        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save settings: {e}")