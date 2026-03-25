# -*- coding: utf-8 -*-
# Dashboard utility functions - Config loading, system info, dialogs, server ops
import os
import sys
import json
import logging
import datetime
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Dict, Any, Optional
import platform
import psutil
import requests
import subprocess
import threading
from collections import deque

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path, centre_window
setup_module_path()
from Modules.core.server_logging import get_dashboard_logger, log_dashboard_event
from Modules.core.theme import get_theme_preference
from Modules.core.color_palettes import get_palette
from Modules.services.temperatures import create_temperature_service

logger: logging.Logger = get_dashboard_logger()

def _resolve_theme_name(context_widget=None):
    # Resolve the active theme
    try:
        if context_widget is not None and hasattr(context_widget, "current_theme"):
            theme_name = getattr(context_widget, "current_theme", None)
            if theme_name:
                return str(theme_name)
    except Exception:
        pass

    try:
        if context_widget is not None and hasattr(context_widget, "winfo_toplevel"):
            top = context_widget.winfo_toplevel()
            if hasattr(top, "current_theme"):
                theme_name = getattr(top, "current_theme", None)
                if theme_name:
                    return str(theme_name)
    except Exception:
        pass

    return get_theme_preference("light")

def _get_active_palette(context_widget=None):
    # Return the palette for the currently active theme.
    return get_palette(_resolve_theme_name(context_widget))

def make_canvas_width_updater(canvas):
    # Create a callback that updates canvas window width on resize.
    def update_canvas_width(event=None):
        try:
            if canvas.winfo_width() > 1:
                canvas.itemconfig(1, width=canvas.winfo_width())
        except tk.TclError:
            pass
    return update_canvas_width

def populate_server_tree(server_tree, dedicated_servers, search_var):
    # Populate a server treeview with filter support and wire up search binding.
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
    return populate_servers

def format_speed(bytes_per_sec):
    # Format bytes/sec to human-readable speed string
    if bytes_per_sec >= 1024**3:
        return f"{bytes_per_sec / (1024**3):.1f}GB/s"
    elif bytes_per_sec >= 1024**2:
        return f"{bytes_per_sec / (1024**2):.1f}MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.1f}KB/s"
    else:
        return f"{bytes_per_sec:.1f}B/s"

def set_metric_widget_text(widget, text):
    # Set metric text for either label-like widgets or read-only Text widgets.
    try:
        if isinstance(widget, dict):
            text_widget = widget.get("text")
            if text_widget is not None:
                set_metric_widget_text(text_widget, text)
            return
        if hasattr(widget, "delete") and hasattr(widget, "insert"):
            # tk.Text path (used for long disk output)
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
            widget.configure(state=tk.DISABLED)
            return
        widget.config(text=text)
    except Exception:
        try:
            widget.config(text=text)
        except Exception:
            pass

# CPU process cache for accurate non-blocking readings
_cpu_process_cache: Dict[int, psutil.Process] = {}

def cleanup_cpu_cache():
    # Remove dead processes from cache
    global _cpu_process_cache
    stale_pids = []
    for pid, proc in _cpu_process_cache.items():
        try:
            if not proc.is_running():
                stale_pids.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            stale_pids.append(pid)
    for pid in stale_pids:
        _cpu_process_cache.pop(pid, None)

def load_dashboard_config(server_manager_dir):
    # Load config from database-migrates from JSON if needed
    try:
        from Modules.Database.cluster_database import get_cluster_database
        db = get_cluster_database()

        flat_config = db.get_dashboard_config()

        # Convert flattened config back to nested structure
        config = {}
        for key, value in flat_config.items():
            keys = key.split('.')
            current = config
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value

        # Migrate from JSON if database is empty
        if not config:
            config_path = os.path.join(server_manager_dir, "data", "dashboard.json")
            if os.path.exists(config_path):
                logger.info("Migrating dashboard config from JSON to database")
                db.migrate_dashboard_config_from_json(config_path)
                flat_config = db.get_dashboard_config()
                config = {}
                for key, value in flat_config.items():
                    keys = key.split('.')
                    current = config
                    for k in keys[:-1]:
                        if k not in current:
                            current[k] = {}
                        current = current[k]
                    current[keys[-1]] = value

        return config

    except Exception as e:
        logger.error(f"Error loading dashboard config from database: {e}")
        return {}

def load_categories(server_manager_dir):
    try:
        from Modules.Database.cluster_database import get_cluster_database
        db = get_cluster_database()
        return db.get_categories()
    except Exception as e:
        logger.error(f"Error loading categories from database: {e}")
        return ["Uncategorized"]

def create_server_type_selection_dialog(root, supported_server_types):
    type_dialog = tk.Toplevel(root)
    type_dialog.title("Select Server Type")
    type_dialog.transient(root)
    type_dialog.grab_set()

    main_frame = ttk.Frame(type_dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)

    title_label = ttk.Label(main_frame, text="Select Server Type:", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 20))

    type_var = tk.StringVar(value="")

    for stype in supported_server_types:
        ttk.Radiobutton(main_frame, text=stype, variable=type_var, value=stype).pack(anchor=tk.W, pady=5)

    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(20, 0))

    def proceed():
        if not type_var.get():
            messagebox.showwarning("No Selection", "Please select a server type.")
            return
        type_dialog.destroy()

    def cancel():
        type_var.set("")
        type_dialog.destroy()

    def on_dialog_close():
        type_var.set("")
        type_dialog.destroy()

    type_dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)

    ttk.Button(button_frame, text="Cancel", command=cancel, width=12).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Next", command=proceed, width=12).pack(side=tk.RIGHT)

    centre_window(type_dialog, 380, 280, root)

    root.wait_window(type_dialog)
    return type_var.get()

def get_steam_credentials(root, use_stored=True):
    # Loads saved credentials first if use_stored=True, otherwise shows dialog
    from Modules.Database.cluster_database import ClusterDatabase

    credentials = {"anonymous": False, "username": "", "password": "", "steam_guard_code": ""}

    if use_stored:
        try:
            db = ClusterDatabase()
            stored_creds = db.get_steam_credentials()
            if stored_creds:
                if stored_creds.get('use_anonymous'):
                    return {"anonymous": True, "username": "", "password": "", "steam_guard_code": ""}
                elif stored_creds.get('username') and stored_creds.get('password'):
                    # Use stored credentials
                    creds = {
                        "anonymous": False,
                        "username": stored_creds['username'],
                        "password": stored_creds['password'],
                        "steam_guard_code": ""
                    }
                    # Generate SteamGuard code if secret is stored
                    if stored_creds.get('steam_guard_secret'):
                        try:
                            import pyotp
                            totp = pyotp.TOTP(stored_creds['steam_guard_secret'])
                            creds['steam_guard_code'] = totp.now()
                        except ImportError:
                            logger.debug("pyotp not available for SteamGuard code generation")
                        except Exception as e:
                            logger.debug(f"Failed to generate SteamGuard code: {e}")
                    return creds
        except Exception as e:
            logger.debug(f"Could not load stored Steam credentials: {e}")

    dialog = tk.Toplevel(root)
    dialog.title("Steam Login")
    dialog.geometry("400x380")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    main_frame = ttk.Frame(dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main_frame, text="Steam Credentials", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 15))

    ttk.Label(main_frame, text="Username:").pack(anchor=tk.W, pady=(0, 5))
    username_var = tk.StringVar()
    username_entry = ttk.Entry(main_frame, textvariable=username_var, width=35)
    username_entry.pack(fill=tk.X, pady=(0, 10))

    ttk.Label(main_frame, text="Password:").pack(anchor=tk.W, pady=(0, 5))
    password_var = tk.StringVar()
    password_entry = ttk.Entry(main_frame, textvariable=password_var, width=35, show="*")
    password_entry.pack(fill=tk.X, pady=(0, 10))

    # Steam Guard code field (optional)
    ttk.Label(main_frame, text="Steam Guard Code (optional):").pack(anchor=tk.W, pady=(0, 5))
    guard_var = tk.StringVar()
    guard_entry = ttk.Entry(main_frame, textvariable=guard_var, width=35)
    guard_entry.pack(fill=tk.X, pady=(0, 10))

    save_var = tk.BooleanVar(value=True)
    save_check = ttk.Checkbutton(main_frame, text="Save credentials for future use", variable=save_var)
    save_check.pack(anchor=tk.W, pady=(0, 15))

    result = {"success": False}

    def on_login():
        credentials["username"] = username_var.get()
        credentials["password"] = password_var.get()
        credentials["steam_guard_code"] = guard_var.get()
        credentials["anonymous"] = False
        result["success"] = True

        if save_var.get() and credentials["username"]:
            try:
                db = ClusterDatabase()
                db.save_steam_credentials(
                    username=credentials["username"],
                    password=credentials["password"],
                    use_anonymous=False
                )
            except Exception as e:
                logger.debug(f"Failed to save Steam credentials: {e}")

        dialog.destroy()

    def on_anonymous():
        credentials["anonymous"] = True
        result["success"] = True

        if save_var.get():
            try:
                db = ClusterDatabase()
                db.save_steam_credentials(use_anonymous=True)
            except Exception as e:
                logger.debug(f"Failed to save anonymous preference: {e}")

        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(10, 0))

    ttk.Button(button_frame, text="Login", command=on_login, width=12).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(button_frame, text="Anonymous", command=on_anonymous, width=12).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT)

    dialog.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - dialog.winfo_width()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")

    username_entry.focus_set()

    root.wait_window(dialog)

    return credentials if result["success"] else None

def load_appid_scanner_list(server_manager_dir):
    # Load the AppID list from database only (NO FALLBACKS)
    try:
        from Modules.Database.scanners.AppIDScanner import AppIDScanner

        scanner = AppIDScanner(use_database=True, debug_mode=False)

        try:
            servers = scanner.get_dedicated_servers_from_database()

            if not servers:
                logger.warning("No Steam dedicated servers found in database")
                return [], {}

            metadata = {
                "total_servers": len(servers),
                "source": "database",
                "last_updated": datetime.datetime.now().isoformat()
            }

            logger.info(f"Loaded {len(servers)} Steam dedicated servers from database")
            return servers, metadata

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Steam database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Steam database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to load Steam AppID list from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)

def load_minecraft_scanner_list(server_manager_dir):
    # Load the Minecraft server list from database (NO FALLBACKS)
    try:
        from Modules.Database.scanners.MinecraftIDScanner import MinecraftIDScanner

        scanner = MinecraftIDScanner(use_database=True, debug_mode=False)

        try:
            servers = scanner.get_servers_from_database(
                modloader=None,
                dedicated_only=True,
                filter_snapshots=True
            )

            if not servers:
                logger.warning("No Minecraft servers found in database")
                return [], {}

            metadata = {
                "total_servers": len(servers),
                "source": "database",
                "last_updated": datetime.datetime.now().isoformat()
            }

            logger.info(f"Loaded {len(servers)} Minecraft servers from database")
            return servers, metadata

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Minecraft database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Minecraft database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to load Minecraft scanner list from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)

def get_minecraft_versions_from_database(modloader=None, dedicated_only=True):
    # Get Minecraft versions from database filtered by modloader - NO FALLBACKS
    try:
        from Modules.Database.scanners.MinecraftIDScanner import MinecraftIDScanner

        scanner = MinecraftIDScanner(use_database=True, debug_mode=False)

        try:
            versions = scanner.get_servers_from_database(
                modloader=modloader,
                dedicated_only=dedicated_only,
                filter_snapshots=True
            )

            if not versions:
                logger.warning(f"No Minecraft versions found in database for modloader '{modloader}'")
                return []

            formatted_versions = []
            for version in versions:
                formatted_versions.append({
                    "version_id": version["version_id"],
                    "modloader": version["modloader"] or modloader or "vanilla",
                    "java_requirement": version["java_requirement"] or 17
                })

            logger.info(f"Retrieved {len(formatted_versions)} Minecraft versions from database")
            return formatted_versions

        finally:
            scanner.close()

    except ImportError as e:
        error_msg = f"Database modules not available: {e}"
        logger.error(error_msg)
        raise Exception(f"Minecraft database unavailable: {error_msg}")

    except Exception as e:
        error_msg = f"Failed to retrieve Minecraft versions from database: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)

def create_minecraft_version_browser_dialog(parent, modloader="Vanilla"):
    dialog = tk.Toplevel(parent)
    dialog.title(f"Browse {modloader} Minecraft Versions")
    dialog.geometry("700x500")
    dialog.transient(parent)
    dialog.grab_set()

    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)

    title_label = ttk.Label(main_frame, text=f"Select {modloader} Minecraft Version", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 15))

    list_frame = ttk.LabelFrame(main_frame, text="Available Versions", padding=10)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

    columns = ("version", "type", "modloader_version", "java", "date")
    version_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

    version_tree.heading("version", text="Version")
    version_tree.heading("type", text="Type")
    version_tree.heading("modloader_version", text="Modloader Version")
    version_tree.heading("java", text="Java")
    version_tree.heading("date", text="Release Date")

    version_tree.column("version", width=120, minwidth=100)
    version_tree.column("type", width=80, minwidth=60)
    version_tree.column("modloader_version", width=150, minwidth=100)
    version_tree.column("java", width=60, minwidth=50)
    version_tree.column("date", width=120, minwidth=100)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=version_tree.yview)
    version_tree.configure(yscrollcommand=scrollbar.set)

    version_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Load versions from database
    try:
        versions = get_minecraft_versions_from_database(modloader.lower(), dedicated_only=True)

        for version_data in versions:
            version_tree.insert("", tk.END, values=(
                version_data.get("version_id", ""),
                "Release",
                modloader,
                f"Java {version_data.get('java_requirement', 17)}",
                "Database"  # Source indicator
            ))

    except Exception as e:
        logger.error(f"Error loading versions for browser dialog: {e}")
        messagebox.showerror("Error", f"Failed to load versions: {str(e)}")

    selected_version: Dict[str, Optional[Dict[str, Any]]] = {"version": None}

    def on_select():
        selection = version_tree.selection()
        if selection:
            item = version_tree.item(selection[0])
            values = item['values']
            selected_version["version"] = {
                "version_id": values[0],
                "modloader": modloader.lower(),
                "java_requirement": int(values[3].replace("Java ", "")) if "Java" in values[3] else 17
            }
            dialog.destroy()
        else:
            messagebox.showinfo("No Selection", "Please select a version.")

    def on_cancel():
        dialog.destroy()

    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)

    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Select", command=on_select).pack(side=tk.RIGHT)

    version_tree.bind("<Double-1>", lambda e: on_select())

    centre_window(dialog, 700, 500, parent)

    parent.wait_window(dialog)

    return selected_version["version"]

def create_steam_appid_browser_dialog(parent, server_manager_dir):
    dialog = tk.Toplevel(parent)
    dialog.title("Select Steam Dedicated Server")
    dialog.geometry("700x540")
    dialog.transient(parent)
    dialog.grab_set()

    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)

    title_label = ttk.Label(main_frame, text="Select Steam Dedicated Server", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(0, 15))

    search_frame = ttk.Frame(main_frame)
    search_frame.pack(fill=tk.X, pady=(0, 10))

    ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
    search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
    search_entry.pack(side=tk.LEFT, padx=(5, 10))

    # Load dedicated servers from scanner's AppID list
    try:
        dedicated_servers_data, metadata = load_appid_scanner_list(server_manager_dir)

        if not dedicated_servers_data:
            error_msg = "Scanner AppID list not available - database must be populated first"
            logger.error(error_msg)
            messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
            dialog.destroy()
            return None

        # Use scanner data - convert to compatible format
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
        palette = _get_active_palette(parent)
        muted_fg = palette.get("text_disabled_fg")

        # Add refresh info to dialog
        if metadata.get('last_updated'):
            last_updated = metadata['last_updated']
            if 'T' in last_updated:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                    ttk.Label(search_frame, text=f"Data last updated: {formatted_date}",
                            foreground=muted_fg, font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
                except (ValueError, TypeError):
                    pass

    except Exception as e:
        error_msg = f"Failed to load AppID scanner data from database: {e}"
        logger.error(error_msg)
        messagebox.showerror("Database Error", f"{error_msg}\n\nThe database must be available and populated with AppID scanner data.")
        dialog.destroy()
        return None

    list_frame = ttk.LabelFrame(main_frame, text="Available Servers", padding=10)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

    columns = ("name", "appid", "developer", "type")
    server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)

    server_tree.heading("name", text="Server Name")
    server_tree.heading("appid", text="App ID")
    server_tree.heading("developer", text="Developer")
    server_tree.heading("type", text="Type")

    server_tree.column("name", width=300, minwidth=200)
    server_tree.column("appid", width=80, minwidth=60)
    server_tree.column("developer", width=150, minwidth=100)
    server_tree.column("type", width=120, minwidth=80)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
    server_tree.configure(yscrollcommand=scrollbar.set)

    server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    populate_server_tree(server_tree, dedicated_servers, search_var)

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
                tooltip = tk.Toplevel(dialog)
                tooltip.wm_overrideredirect(True)
                tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")

                desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")

                palette = _get_active_palette(dialog)
                label = tk.Label(
                    tooltip,
                    text=f"{selected_server['name']}\n\n{desc}",
                    background=palette.get("panel_bg"),
                    foreground=palette.get("text_fg"),
                    highlightbackground=palette.get("border"),
                    highlightcolor=palette.get("border"),
                    relief="solid",
                    borderwidth=1,
                    wraplength=300,
                    justify=tk.LEFT,
                    font=("Segoe UI", 9),
                )
                label.pack()

                # Auto-hide after 3 seconds
                tooltip.after(3000, tooltip.destroy)

    server_tree.bind('<Double-1>', show_server_info)

    selected_appid: Dict[str, Optional[str]] = {"appid": None}

    def on_select():
        selection = server_tree.selection()
        if selection:
            item = server_tree.item(selection[0])
            appid = item['values'][1]
            selected_appid["appid"] = appid
            dialog.destroy()
        else:
            messagebox.showinfo("No Selection", "Please select a server from the list.")

    def on_cancel():
        dialog.destroy()

    button_frame = ttk.Frame(main_frame, padding=(0, 6, 0, 2))
    button_frame.pack(fill=tk.X)

    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Select Server", command=on_select).pack(side=tk.RIGHT)

    # Size to actual content and DPI so action buttons are never clipped.
    try:
        tk_scaling = float(dialog.tk.call('tk', 'scaling'))
    except Exception:
        tk_scaling = 1.0
    dpi_scale = max(1.0, min(tk_scaling / 1.3333, 3.0))

    dialog.update_idletasks()
    required_w = dialog.winfo_reqwidth() + 24
    required_h = dialog.winfo_reqheight() + 24

    target_w = max(int(700 * dpi_scale), required_w)
    target_h = max(int(540 * dpi_scale), required_h)

    max_w = int(dialog.winfo_screenwidth() * 0.95)
    max_h = int(dialog.winfo_screenheight() * 0.92)
    target_w = min(target_w, max_w)
    target_h = min(target_h, max_h)

    dialog.geometry(f"{target_w}x{target_h}")
    dialog.minsize(min(target_w, max_w), min(target_h, max_h))
    centre_window(dialog, target_w, target_h, parent)

    parent.wait_window(dialog)

    return selected_appid["appid"]

def check_appid_in_database(appid):
    if not appid:
        return None

    try:
        # For now, return basic info since database integration is complex
        logger.info(f"Checking AppID {appid} - database integration disabled for now")
        return {"exists": True, "name": f"Server {appid}", "type": "Steam"}

    except Exception as e:
        logger.error(f"Error checking AppID in database: {e}")
        return None

def detect_server_type_from_appid(appid):
    if not appid:
        return "Other"

    app_info = check_appid_in_database(appid)
    if app_info and app_info.get('exists'):
        return "Steam"

    return "Other"

def detect_server_type_from_directory(directory_path):
    if not directory_path or not os.path.exists(directory_path):
        return "Other"

    try:
        files = os.listdir(directory_path)
        files_lower = [f.lower() for f in files]

        # Check for Minecraft indicators
        minecraft_indicators = ['server.jar', 'minecraft_server.jar', 'forge-installer.jar', 'fabric-server-launch.jar']
        if any(indicator in files_lower for indicator in minecraft_indicators):
            return "Minecraft"

        # Check for Steam indicators
        steam_indicators = ['steamapps', 'steam.exe', 'steamcmd.exe']
        if any(indicator in files_lower for indicator in steam_indicators):
            return "Steam"

        return "Other"

    except Exception as e:
        logger.error(f"Error detecting server type from directory: {e}")
        return "Other"

def perform_server_installation(server_type, server_name, install_dir, app_id=None,
                               minecraft_version=None, credentials=None,
                               server_manager=None, progress_callback=None, console_callback=None,
                               steam_cmd_path=None):
    # Perform server installation with progress tracking and console output
    try:
        if not server_manager:
            error_msg = "Server manager not available"
            if console_callback:
                console_callback(f"[ERROR] {error_msg}")
            return False, error_msg

        # Get SteamCMD path if not provided and server type is Steam
        if server_type == "Steam" and not steam_cmd_path:
            from Modules.core.common import get_registry_value
            steam_cmd_path = get_registry_value("HKEY_CURRENT_USER\\Software\\SkywereIndustries\\ServerManager", "SteamCmdPath")
            if not steam_cmd_path:
                steam_cmd_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD")
                if console_callback:
                    console_callback(f"[WARN] SteamCMD path not found in registry, using default: {steam_cmd_path}")

            if not os.path.exists(os.path.join(steam_cmd_path, "steamcmd.exe")):
                error_msg = f"SteamCMD not found at {steam_cmd_path}. Please install SteamCMD or configure the correct path."
                if console_callback:
                    console_callback(f"[ERROR] {error_msg}")
                return False, error_msg

        if console_callback:
            console_callback(f"[INFO] Starting installation of {server_type} server '{server_name}'")
            console_callback(f"[INFO] Installation directory: {install_dir}")

        server_config = {
            'Name': server_name,
            'Type': server_type,
            'InstallDir': install_dir
        }

        if server_type == "Steam" and app_id:
            server_config['AppId'] = app_id
            if console_callback:
                console_callback(f"[INFO] Steam App ID: {app_id}")

        if server_type == "Minecraft" and minecraft_version:
            server_config['MinecraftVersion'] = minecraft_version.get('version_id', '')
            server_config['Modloader'] = minecraft_version.get('modloader', 'vanilla')
            server_config['JavaRequirement'] = minecraft_version.get('java_requirement', 17)
            if console_callback:
                console_callback(f"[INFO] Minecraft Version: {minecraft_version.get('version_id', '')}")
                console_callback(f"[INFO] Modloader: {minecraft_version.get('modloader', 'vanilla')}")

        if progress_callback:
            progress_callback("Creating server configuration...")
        if console_callback:
            console_callback("[INFO] Creating server configuration...")

        if console_callback:
            console_callback("[INFO] Calling server manager to install server...")

        success, message = server_manager.install_server_complete(
            server_name=server_name,
            server_type=server_type,
            install_dir=install_dir,
            executable_path="",
            startup_args="",
            app_id=app_id or "",
            version=minecraft_version.get('version_id', '') if minecraft_version else "",
            modloader=minecraft_version.get('modloader', 'vanilla') if minecraft_version else "",
            steam_cmd_path=steam_cmd_path or "",
            credentials=credentials or {"anonymous": True},
            progress_callback=console_callback,
            cancel_flag=None
        )

        if success:
            success_msg = message or f"Server '{server_name}' installed successfully"
            if progress_callback:
                progress_callback("Server installation completed successfully")
            if console_callback:
                console_callback(f"[SUCCESS] {success_msg}")
            return True, success_msg
        else:
            error_msg = message or f"Failed to install server '{server_name}'"
            if console_callback:
                console_callback(f"[ERROR] {error_msg}")
            return False, error_msg

    except Exception as e:
        error_msg = f"Installation failed: {str(e)}"
        logger.error(f"Error performing server installation: {str(e)}")
        if progress_callback:
            progress_callback(error_msg)
        if console_callback:
            console_callback(f"[ERROR] {error_msg}")
        return False, error_msg

def update_webserver_status(webserver_status_label, offline_var, paths, variables):
    try:
        palette = _get_active_palette(webserver_status_label)
        status = check_webserver_status(paths, variables)
        webserver_status_label.config(text=status)

        if status == "Running":
            webserver_status_label.config(foreground=palette.get("success_fg"))
        elif status == "Stopped":
            webserver_status_label.config(foreground=palette.get("error_fg"))
        else:
            webserver_status_label.config(foreground=palette.get("text_disabled_fg"))
    except Exception as e:
        logger.error(f"Error updating webserver status: {e}")
        palette = _get_active_palette(webserver_status_label)
        webserver_status_label.config(text="Unknown", foreground=palette.get("text_disabled_fg"))

# Global variables for network monitoring
_previous_network_stats = None
_previous_network_time = None
_network_up_history = deque(maxlen=90)
_network_down_history = deque(maxlen=90)
_network_history_last_reset = 0.0
_memory_sticks_cache = None
_memory_sticks_cache_time = 0.0
_temperature_service = None
_temperature_service_lock = threading.Lock()

def _format_frequency_ghz(mhz_value):
    # Convert a MHz numeric value to a compact GHz display string.
    try:
        mhz = float(mhz_value)
        if mhz <= 0:
            return "N/A"
        return f"{mhz / 1000.0:.2f}GHz"
    except Exception:
        return "N/A"

def _collect_memory_sticks_info():
    # Collect physical memory module details, cached to avoid frequent WMI calls.
    global _memory_sticks_cache, _memory_sticks_cache_time

    now = time.time()
    if _memory_sticks_cache is not None and (now - _memory_sticks_cache_time) < 300:
        return _memory_sticks_cache

    summary_only = "Physical RAM sticks: details unavailable"

    if platform.system() != "Windows":
        _memory_sticks_cache = summary_only
        _memory_sticks_cache_time = now
        return _memory_sticks_cache

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

        result = subprocess.run(
            [
                "wmic",
                "memorychip",
                "get",
                "BankLabel,Capacity,ConfiguredClockSpeed,Manufacturer,PartNumber",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0 or not result.stdout.strip():
            _memory_sticks_cache = summary_only
            _memory_sticks_cache_time = now
            return _memory_sticks_cache

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) <= 1:
            _memory_sticks_cache = summary_only
            _memory_sticks_cache_time = now
            return _memory_sticks_cache

        stick_lines = []
        # CSV order: Node,BankLabel,Capacity,ConfiguredClockSpeed,Manufacturer,PartNumber
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue

            bank = parts[1] or "Slot"
            capacity_gb = "N/A"
            try:
                capacity_gb = f"{int(parts[2]) / (1024 ** 3):.1f}GB"
            except Exception:
                pass

            speed = _format_frequency_ghz(parts[3])
            manufacturer = parts[4] or "Unknown"
            part_number = parts[5] or "Unknown"

            stick_lines.append(f"{bank}: {capacity_gb} @ {speed} ({manufacturer} {part_number})")

        if not stick_lines:
            _memory_sticks_cache = summary_only
        else:
            _memory_sticks_cache = "\n".join(stick_lines)

        _memory_sticks_cache_time = now
        return _memory_sticks_cache

    except Exception as e:
        logger.debug(f"Failed to collect RAM module details: {e}")
        _memory_sticks_cache = summary_only
        _memory_sticks_cache_time = now
        return _memory_sticks_cache

def _extract_temperature_settings(variables: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # Build temperature service settings from runtime variables/config values.
    source = variables or {}
    result: Dict[str, Any] = {}

    direct_keys = [
        "temperatureMode", "temperature_mode",
        "temperaturePollInterval", "temperature_poll_interval",
        "iloHost", "ilo_host", "iloUsername", "ilo_username", "iloPassword", "ilo_password", "iloVerifyTLS", "ilo_verify_tls", "iloTimeout", "ilo_timeout",
        "idracHost", "idrac_host", "idracUsername", "idrac_username", "idracPassword", "idrac_password", "idracVerifyTLS", "idrac_verify_tls", "idracTimeout", "idrac_timeout",
    ]
    for key in direct_keys:
        if key in source:
            result[key] = source.get(key)

    nested = source.get("temperature")
    if isinstance(nested, dict):
        for key, value in nested.items():
            result[key] = value

    return result


def init_temperature_service(variables: Optional[Dict[str, Any]] = None):
    # Start the dedicated background temperature service (safe to call multiple times).
    global _temperature_service

    settings = _extract_temperature_settings(variables)

    with _temperature_service_lock:
        should_replace = False
        if _temperature_service is None:
            should_replace = True
        else:
            try:
                current_settings = getattr(_temperature_service, "settings", {})
                if current_settings != settings:
                    _temperature_service.stop()
                    should_replace = True
            except Exception:
                should_replace = True

        if should_replace:
            _temperature_service = create_temperature_service(settings)
            _temperature_service.start()

    return _temperature_service


def stop_temperature_service():
    # Stop the dedicated temperature background service.
    global _temperature_service
    with _temperature_service_lock:
        if _temperature_service is not None:
            try:
                _temperature_service.stop()
            except Exception as e:
                logger.debug(f"Failed stopping temperature service: {e}")
            _temperature_service = None


def _get_temperature_info_text(variables: Optional[Dict[str, Any]] = None) -> str:
    # Read the most recent temperature snapshot from the background service.
    try:
        service = init_temperature_service(variables)
        if service is None:
            return "Temperature sensors not available"
        return service.get_latest_text()
    except Exception as e:
        logger.error(f"Error reading temperature service snapshot: {e}")
        return "Temperature sensors not available"

def _get_network_palette(canvas):
    # Build graph colours from central theme palette only.
    palette = _get_active_palette(canvas)
    return {
        "bg": palette.get("field_bg"),
        "grid": palette.get("border"),
        "upload": palette.get("warning_fg"),
        "download": palette.get("info_fg"),
        "legend": palette.get("text_fg"),
    }

def update_network_graph(metric_widget, sent_bps, recv_bps):
    # Draw task-manager style upload/download line graph and update text summary.
    try:
        global _network_history_last_reset

        if not isinstance(metric_widget, dict):
            set_metric_widget_text(metric_widget, f"Network: Up {format_speed(sent_bps)} Down {format_speed(recv_bps)}")
            return

        canvas = metric_widget.get("canvas")
        text_widget = metric_widget.get("text")

        if canvas is None:
            if text_widget is not None:
                set_metric_widget_text(text_widget, f"Network: Up {format_speed(sent_bps)} Down {format_speed(recv_bps)}")
            return

        now = time.time()
        # Periodically clear graph history so old spikes do not flatten the signal over long sessions.
        if _network_history_last_reset == 0.0:
            _network_history_last_reset = now
        elif (now - _network_history_last_reset) >= 900:
            _network_up_history.clear()
            _network_down_history.clear()
            _network_history_last_reset = now

        # Prime with a flat baseline so first visible draw starts as a straight line.
        if not _network_up_history and not _network_down_history:
            _network_up_history.extend([0.0] * (_network_up_history.maxlen - 1))
            _network_down_history.extend([0.0] * (_network_down_history.maxlen - 1))

        _network_up_history.append(max(0.0, float(sent_bps)))
        _network_down_history.append(max(0.0, float(recv_bps)))

        try:
            width = max(10, int(canvas.winfo_width()))
            height = max(10, int(canvas.winfo_height()))
        except Exception:
            width, height = 120, 72

        palette = _get_network_palette(canvas)
        canvas.configure(background=palette["bg"])
        canvas.delete("all")

        if len(_network_up_history) < 2 or len(_network_down_history) < 2:
            if text_widget is not None:
                set_metric_widget_text(text_widget, "Network: Initialising...")
            return

        max_rate = max(max(_network_up_history), max(_network_down_history), 1.0)
        points_count = min(len(_network_up_history), len(_network_down_history))

        if points_count <= 1:
            return

        x_step = width / (points_count - 1)

        def make_points(series):
            points = []
            plot_top = 16
            plot_bottom = 8
            plot_height = max(4, height - (plot_top + plot_bottom))
            for i in range(points_count):
                value = series[-points_count + i]
                x = i * x_step
                y = plot_top + (plot_height - ((value / max_rate) * plot_height))
                points.extend([x, y])
            return points

        up_points = make_points(list(_network_up_history))
        down_points = make_points(list(_network_down_history))

        canvas.create_line(0, height - 8, width, height - 8, fill=palette["grid"])
        canvas.create_line(*up_points, fill=palette["upload"], width=2)
        canvas.create_line(*down_points, fill=palette["download"], width=2)

        # Legend (top-left) so Upload/Download colours are always clear.
        canvas.create_line(6, 7, 22, 7, fill=palette["upload"], width=2)
        canvas.create_text(26, 7, text="Upload", anchor="w", fill=palette["legend"], font=("Segoe UI", 8))
        canvas.create_line(76, 7, 92, 7, fill=palette["download"], width=2)
        canvas.create_text(96, 7, text="Download", anchor="w", fill=palette["legend"], font=("Segoe UI", 8))

        latest_up = _network_up_history[-1]
        latest_down = _network_down_history[-1]

        if text_widget is not None:
            set_metric_widget_text(
                text_widget,
                f"Up {format_speed(latest_up)} | Down {format_speed(latest_down)} | Peak {format_speed(max_rate)}"
            )

    except Exception as e:
        logger.debug(f"Error updating network graph: {e}")
        try:
            set_metric_widget_text(metric_widget, f"Network: Up {format_speed(sent_bps)} Down {format_speed(recv_bps)}")
        except Exception:
            pass

def update_system_info(metric_labels, system_name, os_info, variables, uptime_label=None):
    global _previous_network_stats, _previous_network_time

    try:
        # Update system name and OS info
        try:
            system_name_text = platform.node()
            if not system_name_text:
                system_name_text = "Unknown System"
            system_name.config(text=system_name_text)
        except Exception as e:
            logger.error(f"Error getting system name: {e}")
            system_name.config(text="Unknown System")

        try:
            os_info_text = f"{platform.system()} {platform.release()} ({platform.machine()})"
            os_info.config(text=os_info_text)
        except Exception as e:
            logger.error(f"Error getting OS info: {e}")
            os_info.config(text="Unknown OS")

        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            set_metric_widget_text(metric_labels["cpu"], f"CPU: {cpu_percent:.1f}%")
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            set_metric_widget_text(metric_labels["cpu"], "CPU: N/A")

        try:
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)
            set_metric_widget_text(metric_labels["memory"], f"Memory: {memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB ({memory_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            set_metric_widget_text(metric_labels["memory"], "Memory: N/A")

        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_used_gb = disk.used / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            set_metric_widget_text(metric_labels["disk"], f"Disk: {disk_used_gb:.1f}GB / {disk_total_gb:.1f}GB ({disk_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            set_metric_widget_text(metric_labels["disk"], "Disk: N/A")

        try:
            current_time = time.time()
            network_stats = psutil.net_io_counters()

            if network_stats:
                if _previous_network_stats is not None and _previous_network_time is not None:
                    # Calculate time difference
                    time_diff = current_time - _previous_network_time

                    if time_diff > 0:
                        # Calculate current transfer rates (bytes per second)
                        bytes_sent_per_sec = (network_stats.bytes_sent - _previous_network_stats.bytes_sent) / time_diff
                        bytes_recv_per_sec = (network_stats.bytes_recv - _previous_network_stats.bytes_recv) / time_diff

                        sent_display = format_speed(bytes_sent_per_sec)
                        recv_display = format_speed(bytes_recv_per_sec)

                        set_metric_widget_text(metric_labels["network"], f"Network: ↑{sent_display} ↓{recv_display}")
                    else:
                        set_metric_widget_text(metric_labels["network"], "Network: Calculating...")
                else:
                    set_metric_widget_text(metric_labels["network"], "Network: Initialising...")

                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                set_metric_widget_text(metric_labels["network"], "Network: N/A")
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            set_metric_widget_text(metric_labels["network"], "Network: N/A")

        # Update GPU info - use direct nvidia-smi with CREATE_NO_WINDOW to prevent console popup
        try:
            gpu_info = "GPU: Not detected"

            try:
                from distutils import spawn
                nvidia_smi = spawn.find_executable('nvidia-smi')
                if nvidia_smi is None and platform.system() == "Windows":
                    nvidia_smi = os.path.join(os.environ.get('systemdrive', 'C:'),
                                             "Program Files", "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
                    if not os.path.exists(nvidia_smi):
                        nvidia_smi = None

                if nvidia_smi:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0

                    result = subprocess.run(
                        [nvidia_smi, "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        lines = result.stdout.strip().split('\n')
                        if len(lines) == 1:
                            parts = [p.strip() for p in lines[0].split(',')]
                            if len(parts) >= 5:
                                name = parts[1]
                                mem_used = int(float(parts[3]))
                                mem_total = int(float(parts[2]))
                                gpu_info = f"GPU: {name} ({mem_used}MB/{mem_total}MB)"
                        else:
                            gpu_names = lines[0].split(',')[1].strip() if lines and len(lines[0].split(',')) > 1 else "Unknown"
                            gpu_info = f"GPU: {len(lines)} GPUs ({gpu_names[:20]}...)"
                else:
                    gpu_info = "GPU: nvidia-smi not found"
            except subprocess.TimeoutExpired:
                gpu_info = "GPU: Detection timeout"
            except Exception:
                gpu_info = "GPU: Not detected"

            set_metric_widget_text(metric_labels["gpu"], gpu_info)
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            set_metric_widget_text(metric_labels["gpu"], "GPU: Error")

        try:
            uptime_seconds = time.time() - psutil.boot_time()
            uptime_str = format_uptime_from_start_time(uptime_seconds)
            if uptime_label is not None:
                uptime_label.config(text=f"Uptime: {uptime_str}")
        except Exception as e:
            logger.error(f"Error getting uptime info: {e}")
            if uptime_label is not None:
                uptime_label.config(text="Uptime: N/A")

        try:
            set_metric_widget_text(metric_labels["temperature"], _get_temperature_info_text(variables))
        except Exception as e:
            logger.error(f"Error getting temperature info: {e}")
            set_metric_widget_text(metric_labels["temperature"], "Temperature: N/A")

    except Exception as e:
        logger.error(f"Error updating system info: {e}")
        # Set all labels to error state
        for label_name in metric_labels:
            set_metric_widget_text(metric_labels[label_name], f"{label_name.title()}: Error")

def collect_system_info_data(temperature_settings: Optional[Dict[str, Any]] = None):
    # Collect system information data in a thread-safe manner (no UI updates)
    global _previous_network_stats, _previous_network_time

    logger.debug("[SUBPROCESS_TRACE] collect_system_info_data() called")
    data = {}

    try:
        try:
            data['system_name'] = platform.node()
            if not data['system_name']:
                data['system_name'] = "Unknown System"
        except Exception as e:
            logger.error(f"Error getting system name: {e}")
            data['system_name'] = "Unknown System"

        try:
            data['os_info'] = f"{platform.system()} {platform.release()} ({platform.machine()})"
        except Exception as e:
            logger.error(f"Error getting OS info: {e}")
            data['os_info'] = "Unknown OS"

        # CPU usage and per-core frequencies
        try:
            per_core_cpu = psutil.cpu_percent(percpu=True, interval=0.5)
            overall_cpu = sum(per_core_cpu) / len(per_core_cpu) if per_core_cpu else 0

            overall_freq = psutil.cpu_freq()
            overall_freq_text = _format_frequency_ghz(overall_freq.current) if overall_freq else "N/A"

            per_core_freq = []
            try:
                per_core_freq = psutil.cpu_freq(percpu=True) or []
            except Exception:
                per_core_freq = []

            cpu_lines = [f"Overall: {overall_cpu:.1f}% @ {overall_freq_text}"]
            for index, usage in enumerate(per_core_cpu):
                freq_text = "N/A"
                if index < len(per_core_freq) and per_core_freq[index] is not None:
                    freq_text = _format_frequency_ghz(per_core_freq[index].current)
                cpu_lines.append(f"Core {index:02d}: {usage:5.1f}% @ {freq_text}")

            data['cpu_percent'] = "\n".join(cpu_lines)

        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            data['cpu_percent'] = None

        try:
            memory = psutil.virtual_memory()
            data['memory_percent'] = memory.percent
            data['memory_used_gb'] = memory.used / (1024**3)
            data['memory_total_gb'] = memory.total / (1024**3)
            data['memory_modules'] = _collect_memory_sticks_info()
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            data['memory_percent'] = None
            data['memory_used_gb'] = None
            data['memory_total_gb'] = None
            data['memory_modules'] = "Physical RAM sticks: unavailable"

        # Disk usage - detect all drive letters on Windows
        try:
            import string
            disk_info_lines = []

            if platform.system() == "Windows":
                # Get all drive letters on Windows
                drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
                for drive in drives:
                    try:
                        disk = psutil.disk_usage(drive)
                        used_gb = disk.used / (1024**3)
                        total_gb = disk.total / (1024**3)
                        percent = disk.percent
                        drive_letter = drive[0].upper()
                        disk_info_lines.append(f"{drive_letter}: {used_gb:.1f}GB/{total_gb:.1f}GB ({percent:.1f}%)")
                    except Exception as e:
                        logger.debug(f"Error getting disk info for {drive}: {e}")
                        continue
            else:
                # For non-Windows systems, use the root filesystem
                disk = psutil.disk_usage('/')
                used_gb = disk.used / (1024**3)
                total_gb = disk.total / (1024**3)
                percent = disk.percent
                disk_info_lines.append(f"Root: {used_gb:.1f}GB/{total_gb:.1f}GB ({percent:.1f}%)")

            data['disk_info'] = "\n".join(disk_info_lines)

        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            data['disk_info'] = "Disk: Error"

        try:
            current_time = time.time()
            network_stats = psutil.net_io_counters()

            if network_stats:
                data['network_stats'] = network_stats
                data['network_time'] = current_time

                if _previous_network_stats is not None and _previous_network_time is not None:
                    time_diff = current_time - _previous_network_time

                    if time_diff > 0:
                        bytes_sent_per_sec = (network_stats.bytes_sent - _previous_network_stats.bytes_sent) / time_diff
                        bytes_recv_per_sec = (network_stats.bytes_recv - _previous_network_stats.bytes_recv) / time_diff

                        data['network_sent_display'] = format_speed(bytes_sent_per_sec)
                        data['network_recv_display'] = format_speed(bytes_recv_per_sec)
                        data['network_sent_bps'] = max(0.0, bytes_sent_per_sec)
                        data['network_recv_bps'] = max(0.0, bytes_recv_per_sec)
                    else:
                        data['network_display'] = "Network: Calculating..."
                        data['network_sent_bps'] = 0.0
                        data['network_recv_bps'] = 0.0
                else:
                    data['network_display'] = "Network: Initialising..."
                    data['network_sent_bps'] = 0.0
                    data['network_recv_bps'] = 0.0

                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                data['network_display'] = "Network: N/A"
                data['network_sent_bps'] = 0.0
                data['network_recv_bps'] = 0.0
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            data['network_display'] = "Network: N/A"
            data['network_sent_bps'] = 0.0
            data['network_recv_bps'] = 0.0

        # GPU info (this is the heavy operation that needs threading)
        try:
            gpu_info = "GPU: Not detected"
            # Direct nvidia-smi call with CREATE_NO_WINDOW to prevent console flash
            try:
                from distutils import spawn
                nvidia_smi = spawn.find_executable('nvidia-smi')
                if nvidia_smi is None and platform.system() == "Windows":
                    # Try default NVIDIA installation path
                    nvidia_smi = os.path.join(os.environ.get('systemdrive', 'C:'),
                                             "Program Files", "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
                    if not os.path.exists(nvidia_smi):
                        nvidia_smi = None

                if nvidia_smi:
                    # Use CREATE_NO_WINDOW to prevent console flash
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE

                    result = subprocess.run(
                        [nvidia_smi, "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        lines = result.stdout.strip().split('\n')
                        if len(lines) == 1:
                            # Single GPU
                            parts = [p.strip() for p in lines[0].split(',')]
                            if len(parts) >= 5:
                                name = parts[1]
                                mem_total = float(parts[2])
                                mem_used = float(parts[3])
                                gpu_util = float(parts[4])
                                mem_util = (mem_used / mem_total * 100) if mem_total > 0 else 0
                                gpu_info = f"GPU: {name}\n{int(mem_used)}MB/{int(mem_total)}MB ({mem_util:.1f}%)"
                        else:
                            # Multiple GPUs
                            gpu_info = f"GPU: {len(lines)} GPUs detected"
                            for line in lines:
                                parts = [p.strip() for p in line.split(',')]
                                if len(parts) >= 5:
                                    name = parts[1].replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "")
                                    mem_used = int(float(parts[3]))
                                    mem_total = int(float(parts[2]))
                                    gpu_info += f"\n• {name} ({mem_used}MB/{mem_total}MB)"
                    else:
                        gpu_info = "GPU: nvidia-smi failed"
                else:
                    gpu_info = "GPU: nvidia-smi not found"
            except subprocess.TimeoutExpired:
                gpu_info = "GPU: Detection timeout"
            except Exception as e:
                logger.debug(f"nvidia-smi GPU detection failed: {e}")
                gpu_info = "GPU: Not detected"

            data['gpu_info'] = gpu_info
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            data['gpu_info'] = "GPU: Error"

        try:
            data['uptime_seconds'] = time.time() - psutil.boot_time()
        except Exception as e:
            logger.error(f"Error getting uptime info: {e}")
            data['uptime_seconds'] = None

        try:
            data['temperature_info'] = _get_temperature_info_text(temperature_settings)
        except Exception as e:
            logger.error(f"Error getting temperature info: {e}")
            data['temperature_info'] = "Temperature sensors not available"

    except Exception as e:
        logger.error(f"Error collecting system info data: {e}")
        data['error'] = str(e)

    return data

def update_system_info_threaded(metric_labels, system_name, os_info, uptime_label=None, callback=None, temperature_settings: Optional[Dict[str, Any]] = None):
    # Update system information using background threading to prevent UI freezing
    import threading

    def background_update():
        try:
            data = collect_system_info_data(temperature_settings)

            def update_ui():
                try:
                    if 'system_name' in data:
                        system_name.config(text=data['system_name'])
                    if 'os_info' in data:
                        os_info.config(text=data['os_info'])

                    if data.get('cpu_percent') is not None:
                        set_metric_widget_text(metric_labels["cpu"], data['cpu_percent'])
                    else:
                        set_metric_widget_text(metric_labels["cpu"], "CPU: N/A")

                    if all(k in data for k in ['memory_used_gb', 'memory_total_gb', 'memory_percent']):
                        memory_lines = [
                            f"Total Usage: {data['memory_used_gb']:.1f}GB / {data['memory_total_gb']:.1f}GB ({data['memory_percent']:.1f}%)",
                            "",
                            "RAM Sticks:",
                            data.get('memory_modules', "Physical RAM sticks: unavailable")
                        ]
                        set_metric_widget_text(
                            metric_labels["memory"],
                            "\n".join(memory_lines)
                        )
                    else:
                        set_metric_widget_text(metric_labels["memory"], "Memory: N/A")

                    if 'disk_info' in data:
                        set_metric_widget_text(metric_labels["disk"], data['disk_info'])
                    else:
                        set_metric_widget_text(metric_labels["disk"], "Disk: N/A")

                    sent_bps = data.get('network_sent_bps', 0.0)
                    recv_bps = data.get('network_recv_bps', 0.0)
                    update_network_graph(metric_labels["network"], sent_bps, recv_bps)

                    if 'gpu_info' in data:
                        set_metric_widget_text(metric_labels["gpu"], data['gpu_info'])
                    else:
                        set_metric_widget_text(metric_labels["gpu"], "GPU: Error")

                    set_metric_widget_text(metric_labels["temperature"], data.get('temperature_info', "Temperature sensors not available"))

                    if data.get('uptime_seconds') is not None:
                        uptime_str = format_uptime_from_start_time(data['uptime_seconds'])
                        if uptime_label is not None:
                            uptime_label.config(text=f"Uptime: {uptime_str}")
                    elif uptime_label is not None:
                        uptime_label.config(text="Uptime: N/A")

                    if callback:
                        callback()

                except Exception as e:
                    logger.error(f"Error updating UI with system data: {e}")
                    # Set all labels to error state
                    for label_name in metric_labels:
                        set_metric_widget_text(metric_labels[label_name], f"{label_name.title()}: Error")

            if hasattr(system_name, 'after'):
                system_name.after(0, update_ui)
            elif hasattr(system_name, 'root') and hasattr(system_name.root, 'after'):
                system_name.root.after(0, update_ui)

        except Exception as e:
            logger.error(f"Error in background system info update: {e}")

    thread = threading.Thread(target=background_update, daemon=True)
    thread.start()

# Server list and subhost helper functions for dashboard.py
def get_current_server_list(dashboard):
    current_tab_id = dashboard.server_notebook.select()
    if not current_tab_id:
        return None

    for subhost_name, tab_frame in dashboard.tab_frames.items():
        if str(tab_frame) in current_tab_id:
            return dashboard.server_lists.get(subhost_name)

    return None

def get_current_subhost(dashboard):
    current_tab_id = dashboard.server_notebook.select()
    if not current_tab_id:
        return "Local Host"

    for subhost_name, tab_frame in dashboard.tab_frames.items():
        if str(tab_frame) in current_tab_id:
            return subhost_name

    return "Local Host"

def format_uptime_from_start_time(start_time):
    # Format uptime from either a timestamp string or seconds since epoch
    try:
        if isinstance(start_time, str):
            # Handle timestamp string
            try:
                start_dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                uptime_seconds = (datetime.datetime.now(datetime.timezone.utc) - start_dt).total_seconds()
            except (ValueError, TypeError):
                return "N/A"
        elif isinstance(start_time, (int, float)):
            # Handle seconds directly
            uptime_seconds = start_time
        else:
            return "N/A"

        if uptime_seconds < 0:
            return "N/A"

        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    except Exception as e:
        logger.error(f"Error formatting uptime: {e}")
        return "N/A"

def update_server_status_in_treeview(server_list, server_name, status):
    try:
        for item in server_list.get_children():
            item_values = server_list.item(item, 'values')
            if item_values and len(item_values) > 0 and item_values[0] == server_name:
                status_text = str(status or "").strip().lower()
                reset_metrics = status_text in {
                    "stopped", "stop", "stopping", "not running", "offline", "error", "killed"
                }

                # Update the status (index 1); clear live metrics for stopped-like states.
                updated_values = (
                    item_values[0],
                    status,
                    '' if reset_metrics else (item_values[2] if len(item_values) > 2 else ''),
                    '0%' if reset_metrics else (item_values[3] if len(item_values) > 3 else '0%'),
                    '0 MB' if reset_metrics else (item_values[4] if len(item_values) > 4 else '0 MB'),
                    '00:00:00' if reset_metrics else (item_values[5] if len(item_values) > 5 else '00:00:00')
                )
                server_list.item(item, values=updated_values)
                break
    except Exception as e:
        logger.error(f"Error updating server status in treeview: {e}")

def open_directory_in_explorer(directory_path):
    try:
        import subprocess
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(f'explorer "{directory_path}"',
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return True, "Directory opened"
    except Exception as e:
        return False, str(e)

def import_server_from_directory_dialog(root, paths, server_manager_dir, update_callback=None, dashboard_server_manager=None):
    try:
        dialog = tk.Toplevel(root)
        dialog.title("Import Server from Directory")
        dialog.geometry("700x620")
        dialog.minsize(640, 560)
        centre_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()

        result = {'success': False, 'message': 'Dialog cancelled'}

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(main_frame, text="Select Server Directory:").grid(row=0, column=0, sticky="w", pady=(0, 5))

        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        dir_frame.columnconfigure(0, weight=1)

        dir_var = tk.StringVar()
        dir_entry = ttk.Entry(dir_frame, textvariable=dir_var, state='readonly')
        dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def browse_directory():
            directory = filedialog.askdirectory(title="Select Server Directory")
            if directory:
                dir_var.set(directory)

        ttk.Button(dir_frame, text="Browse", command=browse_directory).grid(row=0, column=1)

        ttk.Label(main_frame, text="Server Name:").grid(row=2, column=0, sticky="w", pady=(10, 5))
        name_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=name_var).grid(row=3, column=0, sticky="ew", pady=(0, 10))

        # Server type selection (manual)
        ttk.Label(main_frame, text="Server Type:").grid(row=4, column=0, sticky="w", pady=(0, 5))

        try:
            from Modules.server.server_manager import ServerManager
            temp_manager = ServerManager()
            supported_types = temp_manager.get_supported_server_types()
        except Exception:
            supported_types = ["Steam", "Minecraft", "Other"]

        type_var = tk.StringVar(value="Other")  # Default to Other
        type_combo = ttk.Combobox(main_frame, textvariable=type_var, values=supported_types, state="readonly")
        type_combo.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        # Steam App ID field (initially hidden)
        steam_frame = ttk.Frame(main_frame)
        steam_frame.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        steam_frame.grid_remove()  # Initially hidden

        ttk.Label(steam_frame, text="Steam App ID:").grid(row=0, column=0, sticky="w", pady=(0, 5))

        appid_frame = ttk.Frame(steam_frame)
        appid_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        appid_frame.columnconfigure(0, weight=1)

        app_id_var = tk.StringVar()
        app_id_entry = ttk.Entry(appid_frame, textvariable=app_id_var)
        app_id_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def browse_appid():
            selected_appid = create_steam_appid_browser_dialog(dialog, server_manager_dir)
            if selected_appid:
                app_id_var.set(selected_appid)

        ttk.Button(appid_frame, text="Browse", command=browse_appid, width=10).grid(row=0, column=1)

        # Minecraft configuration (initially hidden)
        minecraft_frame = ttk.Frame(main_frame)
        minecraft_frame.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        minecraft_frame.grid_remove()  # Initially hidden

        ttk.Label(minecraft_frame, text="Modloader:").grid(row=0, column=0, sticky="w", pady=(0, 5))
        modloader_var = tk.StringVar(value="Vanilla")
        modloader_combo = ttk.Combobox(minecraft_frame, textvariable=modloader_var,
                                     values=["Vanilla", "Forge", "Fabric", "Spigot", "Paper"],
                                     state="readonly")
        modloader_combo.grid(row=1, column=0, sticky="ew", pady=(0, 5))

        ttk.Label(minecraft_frame, text="Minecraft Version:").grid(row=2, column=0, sticky="w", pady=(0, 5))

        version_frame = ttk.Frame(minecraft_frame)
        version_frame.grid(row=3, column=0, sticky="ew", pady=(0, 5))
        version_frame.columnconfigure(0, weight=1)

        version_var = tk.StringVar()
        version_entry = ttk.Entry(version_frame, textvariable=version_var)
        version_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def browse_minecraft_version():
            selected_version = create_minecraft_version_browser_dialog(dialog, modloader_var.get())
            if selected_version:
                version_var.set(selected_version.get("version_id", ""))
                # Update modloader if it was changed in the browser
                if selected_version.get("modloader"):
                    modloader_var.set(selected_version["modloader"].title())

        ttk.Button(version_frame, text="Browse", command=browse_minecraft_version, width=10).grid(row=0, column=1)

        def on_type_change(*args):
            # Show/hide fields based on server type
            server_type = type_var.get()

            if server_type == "Steam":
                steam_frame.grid()
                minecraft_frame.grid_remove()
            elif server_type == "Minecraft":
                steam_frame.grid_remove()
                minecraft_frame.grid()
            else:  # Other
                steam_frame.grid_remove()
                minecraft_frame.grid_remove()

        type_var.trace_add('write', on_type_change)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=8, column=0, sticky="ew", pady=(20, 0))

        def import_server():
            directory = dir_var.get()
            server_name = name_var.get().strip()
            server_type = type_var.get()

            if not directory or not os.path.exists(directory):
                messagebox.showerror("Error", "Please select a valid directory")
                return

            if not server_name:
                messagebox.showerror("Error", "Please enter a server name")
                return

            if not server_type:
                messagebox.showerror("Error", "Please select a server type")
                return

            try:
                if dashboard_server_manager is None:
                    from Modules.server.server_manager import ServerManager
                    server_manager = ServerManager()
                else:
                    server_manager = dashboard_server_manager

                app_id = app_id_var.get().strip() if server_type == "Steam" else ""
                minecraft_version = version_var.get().strip() if server_type == "Minecraft" else ""
                modloader = modloader_var.get() if server_type == "Minecraft" else ""

                success = server_manager.import_server_config(
                    server_name=server_name,
                    server_type=server_type,
                    install_dir=directory,
                    executable_path="",
                    startup_args="",
                    app_id=app_id
                )

                if success:
                    # Reload server list to include the newly imported server
                    server_manager.load_servers()

                    # For Minecraft servers, update the configuration with version/modloader
                    if server_type == "Minecraft" and (minecraft_version or modloader):
                        try:
                            # Update the server config in database
                            server_config = server_manager.get_server_config(server_name)
                            if server_config:
                                if minecraft_version:
                                    server_config["minecraft_version"] = minecraft_version
                                if modloader:
                                    server_config["modloader"] = modloader

                                # Save updated config to database
                                server_manager.update_server(server_name, server_config)
                        except Exception as e:
                            logger.warning(f"Could not update Minecraft config: {e}")

                    result['success'] = True
                    result['message'] = f"Server '{server_name}' imported successfully from {directory}"

                    if update_callback:
                        update_callback()

                    dialog.destroy()
                    messagebox.showinfo("Success", result['message'])
                else:
                    messagebox.showerror("Error", f"Failed to import server '{server_name}'")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to import server: {str(e)}")

        ttk.Button(button_frame, text="Import", command=import_server).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        steam_frame.columnconfigure(0, weight=1)
        minecraft_frame.columnconfigure(0, weight=1)
        appid_frame.columnconfigure(0, weight=1)
        version_frame.columnconfigure(0, weight=1)

        dialog.wait_window()
        return result

    except Exception as e:
        logger.error(f"Error in import server from directory dialog: {e}")
        return {'success': False, 'message': str(e)}

def import_server_from_export_dialog(root, paths, server_manager_dir, update_callback=None):
    try:
        file_path = filedialog.askopenfilename(
            title="Select Server Export File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not file_path:
            return {'success': False, 'message': 'No file selected'}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            server_name = config.get('Name', os.path.splitext(os.path.basename(file_path))[0])

            confirm = messagebox.askyesno(
                "Confirm Import",
                f"Import server configuration '{server_name}'?\n\n"
                f"Type: {config.get('Type', 'Unknown')}\n"
                f"Original Path: {config.get('InstallDir', 'Unknown')}"
            )

            if confirm:
                if update_callback:
                    update_callback()

                return {
                    'success': True,
                    'message': f"Server '{server_name}' imported successfully from export file"
                }
            else:
                return {'success': False, 'message': 'Import cancelled'}

        except json.JSONDecodeError:
            messagebox.showerror("Error", "Invalid JSON file format")
            return {'success': False, 'message': 'Invalid JSON file'}

    except Exception as e:
        logger.error(f"Error in import server from export dialog: {e}")
        return {'success': False, 'message': str(e)}

def export_server_dialog(root, current_list, paths):
    try:
        if not current_list.selection():
            messagebox.showwarning("No Selection", "Please select a server to export")
            return {'success': False, 'message': 'No server selected'}

        item = current_list.selection()[0]
        server_name = current_list.item(item, "values")[0]

        dialog = tk.Toplevel(root)
        dialog.title(f"Export Server: {server_name}")
        dialog.geometry("620x420")
        dialog.minsize(580, 380)
        centre_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()

        result = {'success': False, 'message': 'Export cancelled'}

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(main_frame, text="Export Options:").grid(row=0, column=0, sticky="w", pady=(0, 10))

        include_files_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            main_frame,
            text="Include server files (creates larger archive)",
            variable=include_files_var
        ).grid(row=1, column=0, sticky="w", pady=(0, 5))

        ttk.Label(main_frame, text="Export Location:").grid(row=2, column=0, sticky="w", pady=(10, 5))

        location_frame = ttk.Frame(main_frame)
        location_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        location_frame.columnconfigure(0, weight=1)

        location_var = tk.StringVar()
        location_entry = ttk.Entry(location_frame, textvariable=location_var, state='readonly')
        location_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def browse_export_location():
            filename = filedialog.asksaveasfilename(
                title="Save Export As",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=f"{server_name}_export.json"
            )
            if filename:
                location_var.set(filename)

        ttk.Button(location_frame, text="Browse", command=browse_export_location).grid(row=0, column=1)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(20, 0))

        def perform_export():
            export_path = location_var.get()

            if not export_path:
                messagebox.showerror("Error", "Please select an export location")
                return

            try:
                # Get the actual server configuration from database
                from Modules.Database.server_configs_database import get_server_config_manager
                manager = get_server_config_manager()
                server_config = manager.get_server(server_name)

                if not server_config:
                    messagebox.showerror("Error", f"Server configuration not found for {server_name}")
                    return

                export_config = server_config.copy()
                export_config['ExportDate'] = datetime.datetime.now().isoformat()
                export_config['IncludeFiles'] = include_files_var.get()

                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(export_config, f, indent=2)

                result['success'] = True
                result['message'] = f"Server '{server_name}' exported successfully to {export_path}"

                dialog.destroy()
                messagebox.showinfo("Export Complete", result['message'])

            except Exception as e:
                messagebox.showerror("Error", f"Failed to export server: {str(e)}")

        ttk.Button(button_frame, text="Export", command=perform_export).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        dialog.wait_window()
        return result

    except Exception as e:
        logger.error(f"Error in export server dialog: {e}")
        return {'success': False, 'message': str(e)}

def create_progress_dialog_with_console(parent, title="Progress"):
    # Create a progress dialog with console output for long-running operations
    class ProgressDialog:
        def __init__(self, parent, title):
            self.dialog = tk.Toplevel(parent)
            self.dialog.title(title)
            self.dialog.geometry("720x500")
            self.dialog.minsize(640, 440)
            centre_window(self.dialog, parent=parent)
            self.dialog.transient(parent)
            self.dialog.grab_set()

            main_frame = ttk.Frame(self.dialog, padding="10")
            main_frame.pack(fill=tk.BOTH, expand=True)

            self.progress_var = tk.StringVar(value="Running...")
            ttk.Label(main_frame, textvariable=self.progress_var).pack(pady=(0, 5))

            self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
            self.progress_bar.pack(fill=tk.X, pady=(0, 10))
            self.progress_bar.start()

            ttk.Label(main_frame, text="Console Output:").pack(anchor=tk.W)

            console_frame = ttk.Frame(main_frame)
            console_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 10))

            self.console_text = scrolledtext.ScrolledText(
                console_frame,
                height=15,
                wrap=tk.WORD,
                font=('Consolas', 9)
            )
            self.console_text.pack(fill=tk.BOTH, expand=True)

            # Close button (initially disabled)
            self.close_button = ttk.Button(
                main_frame,
                text="Close",
                command=self.close_dialog,
                state=tk.DISABLED
            )
            self.close_button.pack(pady=(10, 0))

            self.is_closed = False

        def update_progress(self, message):
            if not self.is_closed:
                self.progress_var.set(message)
                self.dialog.update_idletasks()

        def update_console(self, message):
            if not self.is_closed:
                self.console_text.insert(tk.END, message + "\n")
                self.console_text.see(tk.END)
                self.dialog.update_idletasks()

        def complete(self, message="Operation completed", auto_close=False):
            if not self.is_closed:
                self.progress_bar.stop()
                self.progress_var.set(message)
                if auto_close:
                    # For auto-updates or when auto-close is requested, close immediately
                    self.update_console(f"[COMPLETE] {message}")
                    self.dialog.after(500, self.close_dialog)  # Small delay to show completion
                else:
                    self.close_button.config(state=tk.NORMAL)
                    self.update_console(f"[COMPLETE] {message}")

        def close_dialog(self):
            self.is_closed = True
            self.dialog.destroy()

        def show(self):
            # Show the dialog and return self for method chaining
            return self

        def __contains__(self, key):
            return key in ['console_text', 'console_callback']

        def __getitem__(self, key):
            if key == 'console_text':
                return self.console_text
            elif key == 'console_callback':
                return self.update_console
            else:
                raise KeyError(f"Key '{key}' not found")

    return ProgressDialog(parent, title)

def rename_server_configuration(server_name, new_name, server_manager):
    try:
        if not new_name or not new_name.strip():
            return False, "New server name cannot be empty"

        new_name = new_name.strip()

        if new_name == server_name:
            return False, "New name is the same as current name"

        servers = server_manager.get_servers()
        if new_name in servers:
            return False, f"Server '{new_name}' already exists"

        success = server_manager.rename_server(server_name, new_name)
        if success:
            return True, f"Server renamed from '{server_name}' to '{new_name}'"
        else:
            return False, f"Failed to rename server '{server_name}'"

    except Exception as e:
        logger.error(f"Error renaming server: {e}")
        return False, f"Error renaming server: {str(e)}"

def batch_update_server_types(paths):
    # Iterate all server configs, detect actual type, and update mismatches
    try:
        from Modules.server.server_manager import ServerManager
        server_manager = ServerManager()

        updated_count = 0
        updated_servers = []

        servers = server_manager.get_servers()
        if not servers:
            logger.info("No server configurations found for batch type update")
            return 0, []

        for server_name, config in servers.items():
            try:
                old_type = config.get('Type', 'Other')
                detected_type = None

                # Detect from AppID (Steam servers)
                app_id = config.get('AppId') or config.get('AppID')
                if app_id:
                    detected_type = detect_server_type_from_appid(app_id)

                # Detect from installation directory contents
                install_dir = config.get('InstallDir', '')
                if (not detected_type or detected_type == 'Other') and install_dir:
                    detected_type = detect_server_type_from_directory(install_dir)

                # Detect from executable path
                if (not detected_type or detected_type == 'Other'):
                    exe_path = config.get('ExecutablePath', '') or config.get('Executable', '')
                    if exe_path:
                        exe_lower = exe_path.lower()
                        if 'java' in exe_lower or exe_lower.endswith('.jar'):
                            detected_type = 'Minecraft'
                        elif 'steamcmd' in exe_lower:
                            detected_type = 'Steam'

                if not detected_type:
                    detected_type = 'Other'

                # Update if the detected type differs from current
                if detected_type != old_type:
                    config['PreviousType'] = old_type
                    config['Type'] = detected_type
                    server_manager.update_server(server_name, config)
                    updated_count += 1
                    updated_servers.append({
                        'name': server_name,
                        'old_type': old_type,
                        'new_type': detected_type
                    })
                    logger.info(f"Updated server type for '{server_name}': {old_type} -> {detected_type}")

            except Exception as e:
                logger.warning(f"Error detecting type for server '{server_name}': {e}")

        logger.info(f"Batch server type update completed: {updated_count} server(s) updated")
        return updated_count, updated_servers

    except Exception as e:
        logger.error(f"Error in batch update server types: {e}")
        return 0, []

def is_process_running(pid):
    try:
        return psutil.pid_exists(pid)
    except (psutil.Error, OSError):
        return False

def is_port_open(host, port, timeout=1):
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except OSError:
        return False

def check_webserver_status(paths, variables):
    try:
        webserver_port = variables.get("webserverPort", 8080)
        if is_port_open("localhost", webserver_port):
            return "Running"
        else:
            return "Stopped"
    except Exception as e:
        logger.error(f"Error checking webserver status: {e}")
        return "Unknown"

def _get_ssl_verify_setting():
    # Determine SSL verification: use local cert if available, fall back to system CA bundle
    local_cert = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ssl', 'server.crt')
    if os.path.exists(local_cert):
        return local_cert
    logger.warning("No local SSL certificate found at ssl/server.crt - using system CA bundle for verification")
    return True

def test_remote_host_connection(host, port, username, password, use_ssl=False, timeout=10):
    # Test connectivity and authentication to a remote Server Manager host
    try:
        protocol = "https" if use_ssl else "http"
        base_url = f"{protocol}://{host}:{port}"
        test_url = f"{base_url}/api/status"

        ssl_verify = _get_ssl_verify_setting() if use_ssl else True

        response = requests.get(test_url, timeout=timeout, verify=ssl_verify)

        if response.status_code == 200:
            auth_url = f"{base_url}/cluster/api/auth/login"
            auth_data = {"username": username, "password": password}
            auth_response = requests.post(auth_url, json=auth_data, timeout=timeout, verify=ssl_verify)

            if auth_response.status_code == 200:
                return True, "Connection and authentication successful"
            else:
                return False, "Authentication failed - check username/password"
        else:
            return False, f"Server responded with status {response.status_code}"

    except requests.exceptions.ConnectionError:
        return False, "Could not connect to remote host - check host/port"
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except Exception as e:
        return False, f"Connection error: {str(e)}"
class RemoteHostManager:
    # Manages connections to remote Server Manager hosts
    def __init__(self):
        self.active_connections = {}
        self.session_cache = {}

    def connect(self, host, port, username, password, use_ssl=False, timeout=10):
        # Establish authenticated session with remote host
        try:
            protocol = "https" if use_ssl else "http"
            base_url = f"{protocol}://{host}:{port}"
            connection_id = f"{host}:{port}"

            session = requests.Session()
            session.verify = _get_ssl_verify_setting() if use_ssl else True

            auth_url = f"{base_url}/cluster/api/auth/login"
            auth_data = {"username": username, "password": password}

            auth_response = session.post(auth_url, json=auth_data, timeout=timeout)

            if auth_response.status_code == 200:
                self.active_connections[connection_id] = {
                    "host": host,
                    "port": port,
                    "base_url": base_url,
                    "session": session,
                    "authenticated": True,
                    "use_ssl": use_ssl,
                    "timeout": timeout
                }
                return True, "Connected successfully"
            else:
                return False, "Authentication failed"

        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def disconnect(self, host, port):
        connection_id = f"{host}:{port}"
        if connection_id in self.active_connections:
            try:
                session = self.active_connections[connection_id]["session"]
                base_url = self.active_connections[connection_id]["base_url"]
                session.post(f"{base_url}/api/auth/logout", timeout=5)
            except (requests.RequestException, OSError):
                pass
            del self.active_connections[connection_id]
            return True
        return False

    def get_servers(self, host, port):
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"

        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]

            response = session.get(f"{base_url}/api/servers", timeout=timeout)

            if response.status_code == 200:
                servers_data = response.json()
                return True, servers_data
            else:
                return False, f"Failed to get servers: {response.status_code}"

        except Exception as e:
            return False, f"Error getting servers: {str(e)}"

    def start_server(self, host, port, server_name):
        return self._server_action(host, port, server_name, "start")

    def stop_server(self, host, port, server_name):
        return self._server_action(host, port, server_name, "stop")

    def restart_server(self, host, port, server_name):
        return self._server_action(host, port, server_name, "restart")

    def _server_action(self, host, port, server_name, action):
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"

        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]

            response = session.post(f"{base_url}/api/servers/{server_name}/{action}", timeout=timeout)

            if response.status_code == 200:
                result = response.json()
                return True, result.get("message", f"Server {action} successful")
            else:
                return False, f"Failed to {action} server: {response.status_code}"

        except Exception as e:
            return False, f"Error performing {action}: {str(e)}"

    def get_server_status(self, host, port, server_name):
        connection_id = f"{host}:{port}"
        if connection_id not in self.active_connections:
            return False, "Not connected to remote host"

        try:
            conn = self.active_connections[connection_id]
            session = conn["session"]
            base_url = conn["base_url"]
            timeout = conn["timeout"]

            response = session.get(f"{base_url}/api/servers/{server_name}/status", timeout=timeout)

            if response.status_code == 200:
                status_data = response.json()
                return True, status_data
            else:
                return False, f"Failed to get server status: {response.status_code}"

        except Exception as e:
            return False, f"Error getting server status: {str(e)}"

# Global remote host manager instance
_remote_host_manager = RemoteHostManager()

def cleanup_orphaned_process_entries(server_manager, logger):
    # Clean up orphaned process entries from server configurations
    try:
        if not server_manager:
            return

        logger.debug("Cleaning up orphaned and stale process entries...")

        server_configs = server_manager.get_servers()
        cleaned_count = 0

        for server_name, server_config in server_configs.items():
            try:
                # Enhanced: Run corruption detection first
                recovery_needed, recovery_actions, recovery_errors = server_manager.detect_and_recover_system_corruption(
                    server_name, server_config
                )

                if recovery_needed:
                    logger.debug(f"Corruption recovery performed for {server_name}: {recovery_actions}")
                    cleaned_count += 1

                if recovery_errors:
                    logger.debug(f"Corruption recovery errors for {server_name}: {recovery_errors}")

                # Reload config after potential recovery
                server_config = server_manager.get_server_config(server_name)

                pid = server_config.get('ProcessId') or server_config.get('PID')
                if pid:
                    # This checks CWD, executable, cmdline, and creation time - not just pid_exists
                    if hasattr(server_manager, 'is_server_process_valid'):
                        is_valid, _ = server_manager.is_server_process_valid(server_name, pid, server_config)
                        if not is_valid:
                            logger.debug(f"Cleaning up stale/invalid PID {pid} for server {server_name}")

                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            server_config['LastUpdate'] = datetime.datetime.now().isoformat()

                            server_manager.update_server(server_name, server_config)
                            cleaned_count += 1
                    else:
                        # Fallback to basic pid_exists check
                        try:
                            if not psutil.pid_exists(pid):
                                logger.debug(f"Cleaning up orphaned PID {pid} for server {server_name}")

                                server_config.pop('ProcessId', None)
                                server_config.pop('PID', None)
                                server_config.pop('StartTime', None)
                                server_config.pop('ProcessCreateTime', None)
                                server_config['LastUpdate'] = datetime.datetime.now().isoformat()

                                server_manager.update_server(server_name, server_config)
                                cleaned_count += 1

                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            logger.debug(f"Cleaning up invalid PID {pid} for server {server_name}")

                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            server_config['LastUpdate'] = datetime.datetime.now().isoformat()

                            server_manager.update_server(server_name, server_config)
                            cleaned_count += 1

                        except Exception as e:
                            logger.debug(f"Error checking PID {pid} for server {server_name}: {e}")

            except Exception as e:
                logger.error(f"Error cleaning up process entries for server {server_name}: {e}")

        if cleaned_count > 0:
            logger.debug(f"Cleaned up {cleaned_count} stale/orphaned process entries and corruption issues")

    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_process_entries: {e}")

def cleanup_orphaned_relay_files(logger):
    # Clean up orphaned stdin relay files from crashed dashboards
    try:
        from pathlib import Path

        temp_dir = Path(__file__).parent.parent / "temp"
        if not temp_dir.exists():
            return

        cleaned_count = 0

        for file_path in temp_dir.glob("relay_*.json"):
            try:
                if file_path.exists():
                    relay_info = json.loads(file_path.read_text())

                    server_pid = relay_info.get('server_pid')
                    dashboard_pid = relay_info.get('dashboard_pid')

                    server_running = False
                    if server_pid:
                        try:
                            server_running = psutil.pid_exists(server_pid)
                        except (psutil.Error, OSError):
                            pass

                    dashboard_running = False
                    if dashboard_pid:
                        try:
                            dashboard_running = psutil.pid_exists(dashboard_pid)
                        except (psutil.Error, OSError):
                            pass

                    # If neither server nor dashboard is running, clean up the relay file
                    if not server_running and not dashboard_running:
                        file_path.unlink()
                        logger.debug(f"Cleaned up orphaned relay file: {file_path.name}")
                        cleaned_count += 1
                    elif not dashboard_running and server_running:
                        # Dashboard crashed but server is still running - relay is dead
                        file_path.unlink()
                        logger.debug(f"Cleaned up stale relay file (dashboard crashed): {file_path.name}")
                        cleaned_count += 1

            except Exception as e:
                logger.debug(f"Error processing relay file {file_path.name}: {e}")
                # Remove corrupted files
                try:
                    file_path.unlink()
                    cleaned_count += 1
                except OSError:
                    pass

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} orphaned relay files")

    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_relay_files: {e}")

def reattach_to_running_servers(server_manager, console_manager, logger):
    # Detect and reattach to running server processes with improved process discovery
    try:
        if not server_manager or not console_manager:
            return

        logger.debug("Detecting running server processes for console reattachment...")

        # First, clean up orphaned process entries
        cleanup_orphaned_process_entries(server_manager, logger)

        # Also clean up orphaned relay files
        cleanup_orphaned_relay_files(logger)

        server_configs = server_manager.get_servers()

        # Try stored PIDs first
        reattached_by_pid = 0
        for server_name, server_config in server_configs.items():
            try:
                pid = server_config.get('ProcessId') or server_config.get('PID')
                if pid:
                    try:
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            if process.is_running():
                                # Prefer is_server_process_valid which uses ProcessCreateTime
                                is_valid = False
                                if hasattr(server_manager, 'is_server_process_valid'):
                                    is_valid, _ = server_manager.is_server_process_valid(server_name, pid, server_config)
                                else:
                                    is_valid = _process_matches_server(process, server_name, server_config)

                                if not is_valid:
                                    logger.debug(f"PID {pid} for {server_name} is now a different process ({process.name()}), clearing stale PID")
                                    server_config.pop('ProcessId', None)
                                    server_config.pop('PID', None)
                                    server_config.pop('StartTime', None)
                                    server_config.pop('ProcessCreateTime', None)
                                    server_manager.update_server(server_name, server_config)
                                    try:
                                        console_manager.cleanup_console_on_stop(server_name)
                                    except Exception:
                                        pass
                                    continue

                                logger.debug(f"Found running server process for {server_name} (PID: {pid})")

                                # Ensure StartTime and ProcessCreateTime are set from process creation time if missing
                                config_updated = False
                                if 'StartTime' not in server_config or not server_config.get('StartTime'):
                                    try:
                                        create_time = process.create_time()
                                        start_dt = datetime.datetime.fromtimestamp(create_time)
                                        server_config['StartTime'] = start_dt.isoformat()
                                        server_config['ProcessCreateTime'] = create_time
                                        config_updated = True
                                        logger.debug(f"Set StartTime and ProcessCreateTime for {server_name} from process creation time")
                                    except Exception as e:
                                        logger.debug(f"Could not get process creation time for {server_name}: {e}")
                                elif 'ProcessCreateTime' not in server_config:
                                    # StartTime exists but ProcessCreateTime doesn't - add it
                                    try:
                                        create_time = process.create_time()
                                        server_config['ProcessCreateTime'] = create_time
                                        config_updated = True
                                        logger.debug(f"Set ProcessCreateTime for {server_name} from running process")
                                    except Exception as e:
                                        logger.debug(f"Could not get process creation time for {server_name}: {e}")

                                if config_updated:
                                    server_manager.update_server(server_name, server_config)

                                success = console_manager.attach_console_to_process(
                                    server_name, process, server_config
                                )

                                if success:
                                    logger.debug(f"Reattached console to {server_name}")
                                    reattached_by_pid += 1
                                else:
                                    logger.warning(f"Failed to reattach console to {server_name}")
                        else:
                            # PID exists but process is not running - clear stale data
                            logger.debug(f"PID {pid} for {server_name} is no longer running, clearing stale PID")
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            server_manager.update_server(server_name, server_config)
                            try:
                                console_manager.cleanup_console_on_stop(server_name)
                            except Exception:
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        logger.debug(f"Process {pid} for {server_name} is not accessible: {e}")
                        server_config.pop('ProcessId', None)
                        server_config.pop('PID', None)
                        server_config.pop('StartTime', None)
                        server_config.pop('ProcessCreateTime', None)
                        server_manager.update_server(server_name, server_config)
                    except Exception as e:
                        logger.error(f"Error checking process {pid} for {server_name}: {e}")

            except Exception as e:
                logger.error(f"Error processing server {server_name} for reattachment: {e}")

        # Third, try improved process discovery - scan all processes
        reattached_by_discovery = 0
        try:
            all_processes = psutil.process_iter(['pid', 'name', 'exe', 'cmdline', 'cwd'])

            for proc in all_processes:
                try:
                    # Skip system processes and our own process
                    if proc.info['pid'] == os.getpid():
                        continue

                    for server_name, server_config in server_configs.items():
                        if _process_matches_server(proc, server_name, server_config):
                            # Check if we already reattached this server
                            if hasattr(console_manager, 'consoles') and server_name in console_manager.consoles:
                                logger.debug(f"Server {server_name} already has console attached")
                                continue

                            logger.debug(f"Found running server process for {server_name} (PID: {proc.info['pid']}) via discovery")

                            success = console_manager.attach_console_to_process(
                                server_name, proc, server_config
                            )

                            if success:
                                logger.debug(f"Reattached console to {server_name} via discovery")
                                reattached_by_discovery += 1

                                # Update the server config with the current PID and StartTime
                                server_config['ProcessId'] = proc.info['pid']
                                server_config['PID'] = proc.info['pid']

                                # Store ProcessCreateTime for secure PID validation
                                try:
                                    create_time = proc.create_time()
                                    server_config['ProcessCreateTime'] = create_time
                                    start_dt = datetime.datetime.fromtimestamp(create_time)
                                    server_config['StartTime'] = start_dt.isoformat()
                                    logger.debug(f"Set StartTime and ProcessCreateTime for {server_name} from discovered process")
                                except Exception as e:
                                    logger.debug(f"Could not get process creation time for discovered {server_name}: {e}")

                                server_manager.update_server(server_name, server_config)
                            else:
                                logger.warning(f"Failed to reattach console to discovered process for {server_name}")
                            break  # Found a match, no need to check other servers

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception as e:
                    logger.debug(f"Error checking process {proc.info['pid']}: {e}")
                    continue

        except ImportError:
            logger.warning("psutil not available for enhanced process discovery")
        except Exception as e:
            logger.error(f"Error during enhanced process discovery: {e}")

        total_reattached = reattached_by_pid + reattached_by_discovery
        if total_reattached > 0:
            logger.info(f"Reattached {total_reattached} running server(s)")

    except Exception as e:
        logger.error(f"Error in reattach_to_running_servers: {e}")

def _process_matches_server(process, server_name, server_config):
    try:
        proc_info = process.info
        install_dir = server_config.get('InstallDir', '').lower()
        executable_path = server_config.get('ExecutablePath', '').lower()

        # If we don't have install_dir, we can't reliably match
        if not install_dir:
            return False

        install_dir_norm = os.path.normpath(install_dir)

        # Working directory matches install directory (strongest match)
        if proc_info.get('cwd') and install_dir:
            cwd_norm = os.path.normpath(proc_info['cwd'].lower())
            if cwd_norm == install_dir_norm:
                return True

        # Executable path is inside install directory
        exe_path = proc_info.get('exe', '').lower()
        if exe_path and install_dir:
            exe_norm = os.path.normpath(exe_path)
            if exe_norm.startswith(install_dir_norm + os.sep) or exe_norm == install_dir_norm:
                return True

        # Command line contains install directory path (not just server name)
        cmdline = proc_info.get('cmdline', [])
        if cmdline:
            cmdline_str = ' '.join(cmdline).lower()

            # Check for install directory in command line (more reliable than server name)
            if install_dir and install_dir in cmdline_str:
                return True

            # Check for executable path from config (if it's an absolute path within install dir)
            if executable_path:
                if os.path.isabs(executable_path):
                    exe_config_norm = os.path.normpath(executable_path)
                    if exe_config_norm.startswith(install_dir_norm + os.sep):
                        if executable_path in cmdline_str:
                            return True
                else:
                    # Relative executable - check if full path is in cmdline
                    full_exe = os.path.normpath(os.path.join(install_dir, executable_path))
                    if full_exe.lower() in cmdline_str:
                        return True

        # Type-specific validation with stricter requirements
        proc_name = proc_info.get('name', '').lower()
        server_type = server_config.get('Type', '').lower()

        # Minecraft servers - require install directory in cmdline, not just any java process
        if server_type == 'minecraft' and ('java' in proc_name or 'javaw' in proc_name):
            if cmdline:
                cmdline_str = ' '.join(cmdline).lower()
                # Must have BOTH a jar file AND the install directory in cmdline
                has_jar = any('.jar' in arg.lower() for arg in cmdline)
                has_install_dir = install_dir in cmdline_str
                if has_jar and has_install_dir:
                    return True
        return False

    except Exception as e:
        logger.debug(f"Error matching process {process.pid} to server {server_name}: {e}")
        return False

def update_server_list_for_subhost(subhost_name, servers_data, server_lists, server_manager_dir, logger):
    # Update the server list for a specific subhost with enhanced selection preservation and categorization
    logger.debug(f"Updating server list for subhost {subhost_name} with {len(servers_data)} servers")

    if subhost_name not in server_lists:
        return

    server_list = server_lists[subhost_name]

    # Preserve current selection - handle multiple selections
    current_selection = server_list.selection()
    selected_server_names = []
    if current_selection:
        for item_id in current_selection:
            try:
                selected_item = server_list.item(item_id)
                if selected_item and 'values' in selected_item and len(selected_item['values']) > 0:
                    server_name = selected_item['values'][0]
                    selected_server_names.append(server_name)
            except Exception as e:
                logger.debug(f"Error getting selection info for item {item_id}: {e}")

    if selected_server_names:
        logger.debug(f"Preserving selection for servers: {selected_server_names}")

    # Preserve category expanded/collapsed states before clearing
    category_states = {}
    for item in server_list.get_children():
        try:
            item_values = server_list.item(item)['values']
            if item_values and not item_values[1]:
                category_name = item_values[0]
                is_open = server_list.item(item, 'open')
                category_states[category_name] = is_open
                logger.debug(f"Preserved category state: {category_name} -> {'expanded' if is_open else 'collapsed'}")
        except Exception as e:
            logger.debug(f"Error preserving category state: {e}")

    for item in server_list.get_children():
        server_list.delete(item)

    # Load all categories from persistence (including empty ones)
    all_categories = load_categories(server_manager_dir)

    categories = {}
    for category in all_categories:
        categories[category] = []

    for server_name, server_info in servers_data.items():
        category = server_info.get('category', 'Uncategorized')
        if category not in categories:
            categories[category] = []
        categories[category].append((server_name, server_info))

    selected_item_ids = []
    for category_name in all_categories:
        servers = categories.get(category_name, [])

        # Determine if category should be open (restore previous state, default to True for new)
        should_be_open = category_states.get(category_name, True)

        # Insert category as parent (even if empty)
        category_item = server_list.insert("", tk.END, text=category_name,
                                         values=(category_name, "", "", "", "", ""),
                                         open=should_be_open, tags=('category',))

        for server_name, server_info in servers:
            try:
                status = server_info.get('status', 'Unknown')
                pid = server_info.get('pid', '')
                cpu = server_info.get('cpu', '0%')
                memory = server_info.get('memory', '0 MB')
                uptime = server_info.get('uptime', '00:00:00')

                item_id = server_list.insert(category_item, tk.END, values=(
                    server_name, status, pid, cpu, memory, uptime
                ), tags=('server',))

                # Track the item ID if this server was previously selected
                if server_name in selected_server_names:
                    selected_item_ids.append(item_id)

            except Exception as e:
                logger.error(f"Error adding server {server_name} to list: {e}")

    # Restore selection for all previously selected servers that still exist
    if selected_item_ids:
        try:
            server_list.selection_set(*selected_item_ids)
            if len(selected_item_ids) == 1:
                server_list.focus(selected_item_ids[0])
            logger.debug(f"Restored selection for {len(selected_item_ids)} servers")
        except Exception as e:
            logger.debug(f"Error restoring selection: {e}")
    else:
        logger.debug("No servers to restore selection for")

def get_servers_display_data(server_manager, logger):
    # Get processed server data for display with status, pid, cpu, memory, uptime
    try:
        servers_data = {}
        raw_servers = server_manager.get_all_servers()

        logger.debug(f"get_servers_display_data: Processing {len(raw_servers)} raw servers")

        # Periodically cleanup stale CPU cache entries
        cleanup_cpu_cache()

        def _clear_stale_process_fields(server_name, server_config):
            try:
                pid_value = server_config.get('ProcessId') or server_config.get('PID')
                try:
                    stale_pid = int(pid_value) if pid_value else None
                except (TypeError, ValueError):
                    stale_pid = None

                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                server_manager.update_server(server_name, server_config)

                if stale_pid:
                    _cpu_process_cache.pop(stale_pid, None)
            except Exception as e:
                logger.debug(f"Failed to clear stale process fields for {server_name}: {e}")

        def _get_pid_health_status(server_name, server_config):
            pid = server_config.get('ProcessId') or server_config.get('PID')
            if not pid:
                return 'Stopped', None

            try:
                pid = int(pid)
            except (TypeError, ValueError):
                _clear_stale_process_fields(server_name, server_config)
                return 'Stopped', None

            # Validation path prevents PID reuse from being shown as a running server.
            try:
                if hasattr(server_manager, 'is_server_process_valid'):
                    is_valid, _ = server_manager.is_server_process_valid(server_name, pid, server_config)
                    if not is_valid:
                        _clear_stale_process_fields(server_name, server_config)
                        return 'Stopped', None
            except Exception as e:
                logger.debug(f"PID validation fallback for {server_name} ({pid}): {e}")

            is_alive = False
            responsive = False
            try:
                proc = psutil.Process(pid)
                is_alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
                if is_alive:
                    # A lightweight probe that commonly fails for dead/zombie/unreachable processes.
                    _ = proc.create_time()
                    _ = proc.cpu_times()
                    responsive = True
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                is_alive = False
            except (psutil.AccessDenied, OSError, ValueError):
                # Treat inaccessible process as not responsive and perform a second liveness check.
                responsive = False
            except Exception as e:
                logger.debug(f"Process probe failed for {server_name} ({pid}): {e}")

            if is_alive and responsive:
                return 'Running', pid

            # Second check: only mark as stopped once we can confirm it is no longer alive.
            still_alive = False
            try:
                if hasattr(server_manager, 'is_server_process_valid'):
                    still_alive, _ = server_manager.is_server_process_valid(server_name, pid, server_config)
                else:
                    still_alive = psutil.pid_exists(pid) and psutil.Process(pid).is_running()
            except Exception:
                still_alive = False

            if still_alive:
                return 'Not Responding', pid

            _clear_stale_process_fields(server_name, server_config)
            return 'Stopped', None

        for server_name, server_config in raw_servers.items():
            try:
                server_config = raw_servers.get(server_name)
                if not server_config:
                    display_status = 'Not Found'
                    pid = None
                else:
                    display_status, pid = _get_pid_health_status(server_name, server_config)

                display_data = {
                    'status': display_status,
                    'pid': str(pid) if pid else '',
                    'cpu': '0%',
                    'memory': '0 MB',
                    'uptime': '00:00:00',
                    'category': server_config.get('Category') or 'Uncategorized' if server_config else 'Uncategorized'
                }

                # Get CPU and memory usage if server is running
                if display_status == 'Running' and pid:
                    try:
                        # Use cached process object for accurate CPU readings
                        global _cpu_process_cache

                        if pid not in _cpu_process_cache:
                            # Create new process object and Initialise CPU tracking
                            try:
                                proc = psutil.Process(pid)
                                proc.cpu_percent(interval=None)
                                _cpu_process_cache[pid] = proc
                                # Show 0% on first reading, next refresh will be accurate
                                cpu_percent = 0.0
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                cpu_percent = 0.0
                        else:
                            # Use cached process for non-blocking accurate reading
                            try:
                                process = _cpu_process_cache[pid]
                                if process.is_running():
                                    cpu_percent = process.cpu_percent(interval=None)
                                else:
                                    del _cpu_process_cache[pid]
                                    cpu_percent = 0.0
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                _cpu_process_cache.pop(pid, None)
                                cpu_percent = 0.0

                        display_data['cpu'] = f"{cpu_percent:.1f}%"

                        # Get memory usage (can use the cached process or create new)
                        try:
                            process = _cpu_process_cache.get(pid) or psutil.Process(pid)
                            memory_info = process.memory_info()
                            server_type = server_config.get('Type', '').lower() if server_config else ''

                            # Detect Java processes via cmdline or server type config
                            is_java_process = False
                            try:
                                cmdline = process.cmdline()
                                is_java_process = any('java' in arg.lower() or 'javaw' in arg.lower() for arg in cmdline)
                            except (psutil.AccessDenied, psutil.ZombieProcess):
                                # Cmdline unavailable, fall back to server type from config
                                if server_type == 'minecraft':
                                    is_java_process = True

                            if is_java_process:
                                # Use VMS for Java/Minecraft servers (includes JVM heap allocation)
                                memory_mb = memory_info.vms / (1024 * 1024)
                                display_data['memory'] = f"{memory_mb:.1f} MB (JVM)"
                            elif server_type == 'steam':
                                # Use RSS for Steam dedicated servers (native processes)
                                memory_mb = memory_info.rss / (1024 * 1024)
                                display_data['memory'] = f"{memory_mb:.1f} MB"
                            else:
                                # Use RSS for other/unknown server types
                                memory_mb = memory_info.rss / (1024 * 1024)
                                display_data['memory'] = f"{memory_mb:.1f} MB"

                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                        # Calculate uptime - try StartTime first, then fall back to process creation time
                        uptime_calculated = False
                        if 'StartTime' in server_config and server_config['StartTime']:
                            try:
                                start_time_str = server_config['StartTime']
                                if isinstance(start_time_str, str):
                                    start_time = datetime.datetime.fromisoformat(start_time_str)
                                else:
                                    start_time = start_time_str

                                uptime = datetime.datetime.now() - start_time
                                total_seconds = int(uptime.total_seconds())
                                if total_seconds >= 0:
                                    days, remainder = divmod(total_seconds, 86400)
                                    hours, remainder = divmod(remainder, 3600)
                                    minutes, seconds = divmod(remainder, 60)
                                    if days > 0:
                                        display_data['uptime'] = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
                                    else:
                                        display_data['uptime'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                                    uptime_calculated = True
                            except Exception as e:
                                logger.debug(f"Could not calculate uptime from StartTime for {server_name}: {e}")

                        # Fall back to process creation time if StartTime not available
                        if not uptime_calculated:
                            try:
                                process = _cpu_process_cache.get(pid) or psutil.Process(pid)
                                create_time = process.create_time()
                                start_time = datetime.datetime.fromtimestamp(create_time)
                                uptime = datetime.datetime.now() - start_time
                                total_seconds = int(uptime.total_seconds())
                                if total_seconds >= 0:
                                    days, remainder = divmod(total_seconds, 86400)
                                    hours, remainder = divmod(remainder, 3600)
                                    minutes, seconds = divmod(remainder, 60)
                                    if days > 0:
                                        display_data['uptime'] = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
                                    else:
                                        display_data['uptime'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                            except Exception as e:
                                logger.debug(f"Could not calculate uptime from process for {server_name}: {e}")

                    except Exception as e:
                        logger.debug(f"Could not get process details for {server_name} (PID {pid}): {e}")

                servers_data[server_name] = display_data

            except Exception as e:
                logger.error(f"Error processing server {server_name}: {e}")
                # Add with default stopped status
                servers_data[server_name] = {
                    'status': 'Error',
                    'pid': '',
                    'cpu': '0%',
                    'memory': '0 MB',
                    'uptime': '00:00:00'
                }

        logger.debug(f"get_servers_display_data returning {len(servers_data)} servers")
        if 'Hytale' in servers_data:
            logger.debug(f"Hytale in final result: {servers_data['Hytale']}")
        else:
            logger.debug("Hytale NOT in final result")

        return servers_data

    except Exception as e:
        logger.error(f"Error getting servers display data: {e}")
        return {}

def refresh_subhost_servers(subhost_name, server_manager, server_lists, server_manager_dir, logger):
    try:
        if subhost_name == "Local Host":
            _refresh_local_subhost_async(server_manager, server_lists, server_manager_dir, logger)
        else:
            _refresh_remote_subhost_async(subhost_name, server_lists, server_manager_dir, logger)

    except Exception as e:
        logger.error(f"Error refreshing servers for subhost {subhost_name}: {e}")

def _refresh_local_subhost_async(server_manager, server_lists, server_manager_dir, logger):
    import threading

    def async_refresh():
        try:
            # Heavy psutil operations run in background thread
            servers = get_servers_display_data(server_manager, logger)

            # Schedule UI update on main thread
            import tkinter as tk
            root = None
            if "Local Host" in server_lists:
                widget = server_lists["Local Host"]
                if isinstance(widget, tk.Widget):
                    root = widget.winfo_toplevel()

            if not root:
                for widget_list in server_lists.values():
                    if isinstance(widget_list, tk.Widget):
                        root = widget_list.winfo_toplevel()
                        break

            def update_ui():
                try:
                    update_server_list_for_subhost("Local Host", servers, server_lists, server_manager_dir, logger)
                except Exception as e:
                    logger.error(f"Error updating Local Host server list UI: {e}")

            if root:
                root.after(0, update_ui)
            else:
                # Fallback: try direct update (caller must be on main thread)
                update_server_list_for_subhost("Local Host", servers, server_lists, server_manager_dir, logger)

        except Exception as e:
            logger.error(f"Error in async Local Host refresh: {e}")

    thread = threading.Thread(target=async_refresh, daemon=True, name="LocalHostRefresh")
    thread.start()

def _refresh_remote_subhost_async(subhost_name, server_lists, server_manager_dir, logger):
    import threading

    def async_refresh():
        try:
            from Modules.ui.agents import AgentManager
            agent_manager = AgentManager()

            if subhost_name not in agent_manager.nodes:
                logger.warning(f"Node {subhost_name} not found in agent manager")
                return

            node = agent_manager.nodes[subhost_name]

            servers = None
            import requests
            try:
                response = requests.get(f"http://{node.ip}:8080/api/servers", timeout=5)  # Reduced timeout
                if response.status_code == 200:
                    servers = response.json().get('servers', [])
                else:
                    logger.warning(f"Failed to get servers from node {subhost_name}: HTTP {response.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout getting servers from node {subhost_name}")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error getting servers from node {subhost_name}")
            except Exception as e:
                logger.error(f"Error getting servers from node {subhost_name}: {e}")

            converted_servers = {}
            if servers:
                if isinstance(servers, dict):
                    for server_name, server_info in servers.items():
                        converted_servers[server_name] = {
                            'status': server_info.get('status', 'Unknown'),
                            'pid': server_info.get('pid', ''),
                            'cpu': server_info.get('cpu', '0%'),
                            'memory': server_info.get('memory', '0 MB'),
                            'uptime': server_info.get('uptime', '00:00:00')
                        }
                elif isinstance(servers, list):
                    for server_info in servers:
                        if isinstance(server_info, dict) and 'name' in server_info:
                            server_name = server_info['name']
                            converted_servers[server_name] = {
                                'status': server_info.get('status', 'Unknown'),
                                'pid': server_info.get('pid', ''),
                                'cpu': server_info.get('cpu', '0%'),
                                'memory': server_info.get('memory', '0 MB'),
                                'uptime': server_info.get('uptime', '00:00:00')
                            }

            # Update the UI on the main thread
            def update_ui():
                try:
                    update_server_list_for_subhost(subhost_name, converted_servers, server_lists, server_manager_dir, logger)
                except Exception as e:
                    logger.error(f"Error updating UI for subhost {subhost_name}: {e}")

            import tkinter as tk
            root = None
            for widget_list in server_lists.values():
                for widget in widget_list:
                    if isinstance(widget, tk.Widget):
                        root = widget.winfo_toplevel()
                        break
                if root:
                    break

            if root:
                root.after(0, update_ui)
            else:
                logger.warning(f"Could not find root window for UI update of subhost {subhost_name}")

        except Exception as e:
            logger.error(f"Error in async refresh for subhost {subhost_name}: {e}")

    thread = threading.Thread(target=async_refresh, daemon=True)
    thread.start()

def refresh_all_subhost_servers(server_lists, server_manager, server_manager_dir, logger):
    for subhost_name in server_lists.keys():
        try:
            refresh_subhost_servers(subhost_name, server_manager, server_lists, server_manager_dir, logger)
        except Exception as e:
            logger.error(f"Error initiating refresh for subhost {subhost_name}: {e}")

def refresh_current_subhost_servers(current_subhost_func, server_manager, server_lists, server_manager_dir, logger):
    current_subhost = current_subhost_func()
    if current_subhost:
        refresh_subhost_servers(current_subhost, server_manager, server_lists, server_manager_dir, logger)
        return False

def update_server_list_logic(dashboard, force_refresh=False):
    # Update server list from configuration files - runs heavy work in background thread to prevent freezing the Tkinter main thread
    try:
        if hasattr(dashboard, '_refreshing_server_list') and dashboard._refreshing_server_list:
            if force_refresh:
                # Queue one follow-up refresh after the current pass completes.
                dashboard._pending_force_refresh = True
                log_dashboard_event("SERVER_LIST_UPDATE", "Queued force refresh while update in progress", "DEBUG")
            else:
                log_dashboard_event("SERVER_LIST_UPDATE", "Skipping update - refresh already in progress", "DEBUG")
            return

        # Skip update if it's been less than configured interval since the last update and force_refresh isn't specified
        update_interval = dashboard.variables.get("serverListUpdateInterval", 30)
        if not force_refresh and \
           (dashboard.variables["lastServerListUpdate"] != datetime.datetime.min) and \
           (datetime.datetime.now() - dashboard.variables["lastServerListUpdate"]).total_seconds() < update_interval:
            log_dashboard_event("SERVER_LIST_UPDATE", f"Skipping update - last update was less than {update_interval} seconds ago", "DEBUG")
            return

        dashboard._refreshing_server_list = True

        import threading

        def _background_server_list_update():
            try:
                # Periodically check for running servers that need console reattachment
                if hasattr(dashboard, 'server_manager') and hasattr(dashboard, 'console_manager'):
                    if dashboard.server_manager and dashboard.console_manager:
                        try:
                            _check_and_reattach_running_servers(dashboard.server_manager, dashboard.console_manager, logger)
                        except Exception as e:
                            logger.debug(f"Error in periodic reattach check: {e}")

                # Collect server data for all Local Host servers in background
                local_servers_data = None
                if dashboard.server_manager:
                    try:
                        local_servers_data = get_servers_display_data(dashboard.server_manager, logger)
                    except Exception as e:
                        logger.error(f"Error getting server display data in background: {e}")

                # Schedule UI updates on the main thread
                def _update_ui():
                    try:
                        if local_servers_data is not None:
                            update_server_list_for_subhost(
                                "Local Host", local_servers_data,
                                dashboard.server_lists, dashboard.server_manager_dir, logger
                            )

                        # Refresh remote subhosts (these already use async internally)
                        for subhost_name in list(dashboard.server_lists.keys()):
                            if subhost_name != "Local Host":
                                try:
                                    refresh_subhost_servers(
                                        subhost_name, dashboard.server_manager,
                                        dashboard.server_lists, dashboard.server_manager_dir, logger
                                    )
                                except Exception as e:
                                    logger.error(f"Error refreshing remote subhost {subhost_name}: {e}")

                        dashboard.variables["lastServerListUpdate"] = datetime.datetime.now()
                    except Exception as e:
                        logger.error(f"Error updating server list UI: {e}")
                    finally:
                        dashboard._refreshing_server_list = False
                        if getattr(dashboard, '_pending_force_refresh', False):
                            dashboard._pending_force_refresh = False
                            try:
                                dashboard.root.after(100, lambda: update_server_list_logic(dashboard, force_refresh=True))
                            except Exception as e:
                                logger.debug(f"Could not run queued force refresh: {e}")

                if hasattr(dashboard, 'root') and dashboard.root:
                    dashboard.root.after(0, _update_ui)
                else:
                    dashboard._refreshing_server_list = False

            except Exception as e:
                logger.error(f"Error in background server list update: {e}")
                dashboard._refreshing_server_list = False

        thread = threading.Thread(target=_background_server_list_update, daemon=True, name="ServerListUpdate")
        thread.start()

    except Exception as e:
        logger.error(f"Error in update_server_list: {str(e)}")
        dashboard._refreshing_server_list = False

# Track which servers have already been reattached to avoid repeated attach calls and log spam
_reattached_servers: set = set()

# Track which servers are currently being stopped so reattach does not interfere
_stopping_servers: set = set()

def _check_and_reattach_running_servers(server_manager, console_manager, logger):
    # Quick check for running servers that don't have console attached
    global _reattached_servers
    try:
        server_configs = server_manager.get_servers()
        current_running = set()

        for server_name, server_config in server_configs.items():
            try:
                pid = server_config.get('ProcessId') or server_config.get('PID')
                if not pid:
                    continue

                if not psutil.pid_exists(pid):
                    # Server no longer running, remove from tracked set
                    _reattached_servers.discard(server_name)
                    continue

                current_running.add(server_name)

                # Skip servers that are currently being stopped to avoid lock contention
                if server_name in _stopping_servers:
                    continue

                # Check if console is already active
                if hasattr(console_manager, 'consoles') and server_name in console_manager.consoles:
                    console = console_manager.consoles.get(server_name)
                    if console and console.is_active:
                        # Console is active, mark as reattached and skip
                        _reattached_servers.add(server_name)
                        continue

                # Skip if we already reattached this server and haven't seen it stop
                if server_name in _reattached_servers:
                    continue

                try:
                    process = psutil.Process(pid)
                    if not process.is_running():
                        _reattached_servers.discard(server_name)
                        continue

                    # Validate this is still the correct process using ProcessCreateTime
                    is_valid = False
                    if hasattr(server_manager, 'is_server_process_valid'):
                        is_valid, _ = server_manager.is_server_process_valid(server_name, pid, server_config)
                    else:
                        is_valid = _process_matches_server(process, server_name, server_config)

                    if not is_valid:
                        continue

                    # Server is running but no console attached - reattach
                    logger.debug(f"Reattaching console to running server: {server_name} (PID: {pid})")
                    success = console_manager.attach_console_to_process(server_name, process, server_config, lock_timeout=5)
                    if success:
                        _reattached_servers.add(server_name)
                        logger.info(f"Reattached console to {server_name}")

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            except Exception as e:
                logger.debug(f"Error checking server {server_name} for reattachment: {e}")

        # Clean up tracked set for servers that are no longer running
        _reattached_servers = _reattached_servers & current_running

    except Exception as e:
        logger.debug(f"Error in _check_and_reattach_running_servers: {e}")

# These functions are used by both dashboard.py and server_console.py to avoid code duplication
def start_server_operation(server_name, server_manager, console_manager=None,
                          status_callback=None, completion_callback=None, parent_window=None):
    import threading

    def start_in_background():
        try:
            if server_manager is None:
                if completion_callback:
                    completion_callback(False, "Server manager not initialised.")
                return

            success, result = server_manager.start_server_advanced(
                server_name,
                callback=status_callback
            )

            # If successful and we got a process object, attach console
            if success and hasattr(result, 'pid'):
                if console_manager:
                    try:
                        console_manager.attach_console_to_process(server_name, result)
                    except Exception as e:
                        logger.warning(f"Failed to attach console after start: {e}")
                message = f"Server '{server_name}' started successfully with PID {result.pid}."
            else:
                message = result if isinstance(result, str) else "Server started successfully"

            if completion_callback:
                completion_callback(success, message)

        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            if completion_callback:
                completion_callback(False, f"Failed to start server: {str(e)}")

    start_thread = threading.Thread(target=start_in_background, daemon=True)
    start_thread.start()
    return start_thread

def stop_server_operation(server_name, server_manager, console_manager=None,
                         status_callback=None, completion_callback=None, parent_window=None):
    import threading

    # Mark server as stopping so reattach checks skip it during shutdown
    _stopping_servers.add(server_name)

    def stop_in_background():
        try:
            if server_manager is None:
                if completion_callback:
                    completion_callback(False, "Server manager not initialised.")
                return

            success, message = server_manager.stop_server_advanced(
                server_name,
                callback=status_callback
            )

            # Clean up console state when server is stopped
            # This prevents old PID data from causing issues with reused PIDs
            if success and console_manager:
                try:
                    console_manager.cleanup_console_on_stop(server_name)
                except Exception as e:
                    logger.warning(f"Failed to cleanup console on stop: {e}")

            # Clear reattach and stopping tracking so server can be reattached after restart
            global _reattached_servers
            _reattached_servers.discard(server_name)
            _stopping_servers.discard(server_name)

            if completion_callback:
                completion_callback(success, message if message else "Server stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            _stopping_servers.discard(server_name)
            if completion_callback:
                completion_callback(False, f"Failed to stop server: {str(e)}")

    stop_thread = threading.Thread(target=stop_in_background, daemon=True)
    stop_thread.start()
    return stop_thread

def restart_server_operation(server_name, server_manager, console_manager=None,
                            status_callback=None, completion_callback=None, parent_window=None):
    import threading

    # Mark server as stopping during the stop phase of restart
    _stopping_servers.add(server_name)

    def restart_in_background():
        try:
            if server_manager is None:
                if completion_callback:
                    completion_callback(False, "Server manager not initialised.")
                return

            success, result = server_manager.restart_server_advanced(
                server_name,
                callback=status_callback
            )

            # Clear stopping tracking now that restart is complete
            _stopping_servers.discard(server_name)

            # If successful and we got a process object, attach console
            if success and hasattr(result, 'pid'):
                if console_manager:
                    try:
                        console_manager.attach_console_to_process(server_name, result)
                    except Exception as e:
                        logger.warning(f"Failed to attach console after restart: {e}")
                message = f"Server '{server_name}' restarted successfully with PID {result.pid}."
            else:
                message = result if isinstance(result, str) else "Server restarted successfully"

            if completion_callback:
                completion_callback(success, message)

        except Exception as e:
            logger.error(f"Error restarting server: {str(e)}")
            _stopping_servers.discard(server_name)
            if completion_callback:
                completion_callback(False, f"Failed to restart server: {str(e)}")

    restart_thread = threading.Thread(target=restart_in_background, daemon=True)
    restart_thread.start()
    return restart_thread

def add_server_dialog(dashboard):
    # Add a new game server (Steam, Minecraft, or Other)
    if dashboard.server_manager is None:
        messagebox.showerror("Error", "Server manager not initialised.")
        return

    server_type = create_server_type_selection_dialog(dashboard.root, dashboard.supported_server_types)
    if not server_type:
        return

    credentials = None
    if server_type == "Steam":
        credentials = get_steam_credentials(dashboard.root)
        if not credentials:
            return

    dialog = tk.Toplevel(dashboard.root)
    dialog.title(f"Create {server_type} Server")
    dialog.transient(dashboard.root)
    dialog.grab_set()
    dialog_width = min(950, int(dashboard.root.winfo_screenwidth() * 0.9))
    dialog_height = min(700, int(dashboard.root.winfo_screenheight() * 0.8))
    dialog.minsize(dialog_width, dialog_height)

    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Installation control
    dashboard.install_cancelled = tk.BooleanVar(value=False)

    # Paned window for top-bottom split layout
    paned_window = ttk.PanedWindow(main_frame, orient=tk.VERTICAL)
    paned_window.pack(fill=tk.BOTH, expand=True)

    # Top frame for setup information
    top_frame = ttk.Frame(paned_window)
    paned_window.add(top_frame, weight=1)

    canvas = tk.Canvas(top_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    update_canvas_width = make_canvas_width_updater(canvas)
    canvas.bind("<Configure>", update_canvas_width)

    # Configure scrollable frame grid with proper column weights
    scrollable_frame.columnconfigure(0, weight=0, minsize=150)
    scrollable_frame.columnconfigure(1, weight=1, minsize=200)
    scrollable_frame.columnconfigure(2, weight=0, minsize=100)

    form_vars = {
        'name': tk.StringVar(),
        'app_id': tk.StringVar(),
        'install_dir': tk.StringVar(),
        'minecraft_version': tk.StringVar(),
        'modloader': tk.StringVar(value="Vanilla")
    }

    ttk.Label(scrollable_frame, text="Server Name:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=15, pady=15, sticky=tk.W)
    name_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['name'], width=35, font=("Segoe UI", 10))
    name_entry.grid(row=0, column=1, columnspan=2, padx=15, pady=15, sticky=tk.EW)

    ttk.Label(scrollable_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, padx=15, pady=10, sticky=tk.W)
    ttk.Label(scrollable_frame, text=server_type, font=("Segoe UI", 10)).grid(row=1, column=1, padx=15, pady=10, sticky=tk.W)

    current_row = 2

    # Minecraft-specific fields with two-dropdown interface
    if server_type == "Minecraft":
        try:
            available_modloaders = ["Vanilla", "Forge", "Fabric", "NeoForge"]

            # Modloader selection (positioned above version dropdown)
            ttk.Label(scrollable_frame, text="Modloader:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            modloader_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['modloader'],
                                         values=available_modloaders, state="readonly", width=32, font=("Segoe UI", 10))
            modloader_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            current_row += 1

            # Minecraft version dropdown (positioned below modloader)
            ttk.Label(scrollable_frame, text="Minecraft Version:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
            version_combo = ttk.Combobox(scrollable_frame, textvariable=form_vars['minecraft_version'],
                                       values=[], state="readonly", width=32, font=("Segoe UI", 10))
            version_combo.grid(row=current_row, column=1, columnspan=2, padx=15, pady=10, sticky=tk.EW)
            current_row += 1

            def update_version_list(*args):
                try:
                    selected_modloader = form_vars['modloader'].get().lower()
                    if selected_modloader == "vanilla":
                        selected_modloader = "vanilla"

                    versions = get_minecraft_versions_from_database(
                        modloader=selected_modloader
                    )

                    version_options = []
                    version_map = {}

                    for version_data in versions:
                        version_id = version_data.get("version_id", "")
                        display_text = version_id
                        version_options.append(display_text)
                        version_map[display_text] = version_data

                    version_combo['values'] = version_options
                    if version_options:
                        form_vars['minecraft_version'].set(version_options[0])
                    else:
                        form_vars['minecraft_version'].set("")

                    # Store version mapping for later use
                    setattr(dialog, 'version_map', version_map)

                except Exception as e:
                    logger.error(f"Error updating version list: {e}")
                    version_combo['values'] = []
                    form_vars['minecraft_version'].set("")

            form_vars['modloader'].trace('w', update_version_list)
            update_version_list()

        except Exception as e:
            messagebox.showerror("Error", f"Minecraft support not available: {str(e)}")
            dialog.destroy()
            return

    # App ID (Steam only)
    if server_type == "Steam":
        ttk.Label(scrollable_frame, text="App ID:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
        app_id_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['app_id'], width=25, font=("Segoe UI", 10))
        app_id_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)

        def browse_appid():
            appid_dialog = tk.Toplevel(dialog)
            appid_dialog.title("Select Dedicated Server")
            appid_dialog.transient(dialog)
            appid_dialog.grab_set()
            appid_dialog.geometry("680x560")
            appid_dialog.minsize(660, 540)

            search_frame = ttk.Frame(appid_dialog, padding=10)
            search_frame.pack(fill=tk.X)

            ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
            search_var = tk.StringVar()
            search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
            search_entry.pack(side=tk.LEFT, padx=(5, 10))

            # Load dedicated servers from scanner's AppID list
            try:
                dedicated_servers_data, metadata = load_appid_scanner_list(dashboard.server_manager_dir)

                if not dedicated_servers_data:
                    error_msg = "Scanner AppID list not available - database must be populated first"
                    logger.error(error_msg)
                    messagebox.showerror("Database Error", f"{error_msg}\n\nPlease ensure the AppID scanner has been run to populate the database.")
                    return

                # Use scanner data - convert to compatible format
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

                palette = _get_active_palette(dashboard)
                muted_fg = palette.get("text_disabled_fg")

                # Create lookup dictionary for faster server access
                server_dict = {server["appid"]: server for server in dedicated_servers}

                # Add refresh info to dialog
                if metadata.get('last_updated'):
                    last_updated = metadata['last_updated']
                    if 'T' in last_updated:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                            formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                            ttk.Label(search_frame, text=f"Data last updated: {formatted_date}",
                                    foreground=muted_fg, font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
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
            server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
            server_tree.heading("name", text="Server Name")
            server_tree.heading("appid", text="App ID")
            server_tree.heading("developer", text="Developer")
            server_tree.heading("type", text="Type")
            server_tree.column("name", width=300)
            server_tree.column("appid", width=80)
            server_tree.column("developer", width=150)
            server_tree.column("type", width=120)

            tree_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
            server_tree.configure(yscrollcommand=tree_scrollbar.set)

            tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            populate_server_tree(server_tree, dedicated_servers, search_var)

            def show_server_info(event):
                item = server_tree.selection()
                if item:
                    item_values = server_tree.item(item[0])['values']
                    selected_server = server_dict.get(str(item_values[1]))

                    if selected_server and selected_server.get("description"):
                        tooltip = tk.Toplevel(appid_dialog)
                        tooltip.wm_overrideredirect(True)
                        tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")

                        desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")

                        palette = _get_active_palette(dashboard)
                        label = tk.Label(
                            tooltip,
                            text=f"{selected_server['name']}\n\n{desc}",
                            background=palette.get("panel_bg"),
                            foreground=palette.get("text_fg"),
                            highlightbackground=palette.get("border"),
                            highlightcolor=palette.get("border"),
                            relief="solid",
                            borderwidth=1,
                            wraplength=300,
                            justify=tk.LEFT,
                            font=("Segoe UI", 9),
                        )
                        label.pack()

                        # Auto-hide after 3 seconds
                        tooltip.after(3000, tooltip.destroy)

            server_tree.bind('<Double-1>', show_server_info)

            button_frame = ttk.Frame(appid_dialog, padding=10)
            button_frame.pack(fill=tk.X)

            def select_server():
                selected = server_tree.selection()
                if selected:
                    item = server_tree.item(selected[0])
                    appid = item['values'][1]
                    form_vars['app_id'].set(appid)
                    appid_dialog.destroy()
                else:
                    messagebox.showinfo("No Selection", "Please select a server from the list.")

            def cancel_selection():
                appid_dialog.destroy()

            ttk.Button(button_frame, text="Cancel", command=cancel_selection, width=12).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Select Server", command=select_server, width=15).pack(side=tk.RIGHT)

            # Ensure the action buttons are never clipped on high-DPI displays.
            try:
                scale = float(getattr(dashboard, "dpi_scale", 1.0) or 1.0)
            except Exception:
                scale = 1.0
            scale = max(1.0, min(scale, 3.0))

            appid_dialog.update_idletasks()
            required_w = appid_dialog.winfo_reqwidth() + 24
            required_h = appid_dialog.winfo_reqheight() + 24

            target_w = max(int(680 * scale), required_w)
            target_h = max(int(560 * scale), required_h)

            max_w = int(appid_dialog.winfo_screenwidth() * 0.95)
            max_h = int(appid_dialog.winfo_screenheight() * 0.92)
            target_w = min(target_w, max_w)
            target_h = min(target_h, max_h)

            appid_dialog.geometry(f"{target_w}x{target_h}")
            appid_dialog.minsize(min(target_w, max_w), min(target_h, max_h))
            centre_window(appid_dialog, target_w, target_h, dialog)

        ttk.Button(scrollable_frame, text="Browse", command=browse_appid, width=12).grid(row=current_row, column=2, padx=15, pady=10)
        current_row += 1

        palette = _get_active_palette(dashboard)
        ttk.Label(scrollable_frame, text="(Enter Steam App ID or use Browse to select from list)", foreground=palette.get("text_disabled_fg"), font=("Segoe UI", 9)).grid(row=current_row, column=1, columnspan=2, padx=15, sticky=tk.W)
        current_row += 1

    ttk.Label(scrollable_frame, text="Install Directory:", font=("Segoe UI", 10, "bold")).grid(row=current_row, column=0, padx=15, pady=10, sticky=tk.W)
    install_dir_entry = ttk.Entry(scrollable_frame, textvariable=form_vars['install_dir'], width=25, font=("Segoe UI", 10))
    install_dir_entry.grid(row=current_row, column=1, padx=15, pady=10, sticky=tk.EW)

    def browse_directory():
        directory = filedialog.askdirectory(title="Select Installation Directory")
        if directory:
            form_vars['install_dir'].set(directory)
    ttk.Button(scrollable_frame, text="Browse", command=browse_directory, width=12).grid(row=current_row, column=2, padx=15, pady=10)
    current_row += 1

    # Set default installation directory help text based on server type
    if server_type == "Steam":
        help_text = "(Leave blank for SteamCMD default location)"
    else:  # Minecraft or Other
        default_location = dashboard.variables.get("defaultServerManagerInstallDir", "")
        if default_location:
            help_text = f"(Leave blank for default: {default_location}\\ServerName)"
        else:
            help_text = "(Please specify installation directory)"

    # Create a wrapping label for the help text with better wrapping
    palette = _get_active_palette(dashboard)
    help_label = ttk.Label(scrollable_frame, text=help_text, foreground=palette.get("text_disabled_fg"),
                         font=("Segoe UI", 9), wraplength=500, justify=tk.LEFT)
    help_label.grid(row=current_row, column=1, columnspan=2, padx=15, pady=(0, 5), sticky="ew")

    scrollable_frame.grid_columnconfigure(1, weight=1)
    current_row += 1

    current_row += 1

    button_container = ttk.Frame(top_frame)
    button_container.pack(fill=tk.X, pady=(10, 5))

    create_button = ttk.Button(button_container, text="Create Server", width=18)
    create_button.pack(side=tk.LEFT, padx=(0, 10))

    cancel_button = ttk.Button(button_container, text="Cancel Installation", width=18, state=tk.DISABLED)
    cancel_button.pack(side=tk.LEFT, padx=(0, 10))

    close_button = ttk.Button(button_container, text="Close", width=12)
    close_button.pack(side=tk.RIGHT)

    status_container = ttk.Frame(top_frame)
    status_container.pack(fill=tk.X, pady=(5, 10))

    status_var = tk.StringVar(value="Ready to create server...")
    status_label = ttk.Label(status_container, textvariable=status_var, font=("Segoe UI", 10))
    status_label.pack(anchor=tk.W, pady=(0, 5))

    progress = ttk.Progressbar(status_container, mode="indeterminate")
    progress.pack(fill=tk.X)

    # Bottom frame for console log (50% of space)
    bottom_frame = ttk.Frame(paned_window)
    paned_window.add(bottom_frame, weight=1)

    console_container = ttk.LabelFrame(bottom_frame, text="Installation Log", padding=10)
    console_container.pack(fill=tk.BOTH, expand=True)

    palette = _get_active_palette(dashboard)
    console_output = scrolledtext.ScrolledText(
        console_container,
        width=60,
        height=12,
        background=palette.get("text_bg"),
        foreground=palette.get("text_fg"),
        insertbackground=palette.get("text_fg"),
        selectbackground=palette.get("text_selection_bg"),
        selectforeground=palette.get("text_selection_fg"),
        font=("Consolas", 9),
    )
    console_output.pack(fill=tk.BOTH, expand=True)
    console_output.config(state=tk.DISABLED)

    def append_console(text):
        try:
            if not dialog.winfo_exists():
                return
            console_output.config(state=tk.NORMAL)
            console_output.insert(tk.END, text + "\n")
            console_output.see(tk.END)
            console_output.config(state=tk.DISABLED)
        except (tk.TclError, AttributeError):
            # Widget was destroyed, ignore
            pass

    append_console(f"[INFO] Ready to create {server_type} server...")
    append_console(f"[INFO] Please fill in the required fields above and click 'Create Server' to begin.")

    def install_server():
        try:
            # Check if dialog still exists before accessing widgets
            if not dialog.winfo_exists():
                return

            server_name = form_vars['name'].get().strip()
            install_dir = form_vars['install_dir'].get().strip()

            if not server_name:
                messagebox.showerror("Validation Error", "Server name is required.")
                return

            # Set default install directory if not provided
            if not install_dir:
                if server_type == "Steam":
                    install_dir = dashboard.variables.get("defaultSteamInstallDir", "")
                    if not install_dir:
                        messagebox.showerror("Validation Error", "SteamCMD path not configured. Please set the installation directory manually.")
                        return
                else:  # Minecraft or Other
                    default_base = dashboard.variables.get("defaultServerManagerInstallDir", "")
                    if default_base:
                        install_dir = os.path.join(default_base, server_name)
                    else:
                        messagebox.showerror("Validation Error", "Default installation directory not configured. Please set the installation directory manually.")
                        return

            # Validate server type specific fields
            if server_type == "Steam":
                app_id = form_vars.get('app_id', tk.StringVar()).get().strip()
                if not app_id:
                    messagebox.showerror("Validation Error", "Steam App ID is required for Steam servers.")
                    return
                if not app_id.isdigit():
                    messagebox.showerror("Validation Error", "Steam App ID must be a number.")
                    return

            elif server_type == "Minecraft":
                minecraft_version = form_vars['minecraft_version'].get().strip()
                if not minecraft_version:
                    messagebox.showerror("Validation Error", "Minecraft version must be selected.")
                    return

            # Check for invalid characters in server name
            invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
            if any(char in server_name for char in invalid_chars):
                messagebox.showerror("Validation Error",
                                   "Server name contains invalid characters. Please use only letters, numbers, spaces, and underscores.")
                return

            if dashboard.server_manager:
                existing_config = dashboard.server_manager.get_server_config(server_name)
                if existing_config:
                    messagebox.showerror("Validation Error", f"A server with the name '{server_name}' already exists.")
                    return

            create_button.config(state=tk.DISABLED)
            cancel_button.config(state=tk.NORMAL)
            progress.start(10)
            status_var.set("Starting installation...")

            def safe_status_callback(msg):
                try:
                    if dialog.winfo_exists():
                        status_var.set(msg)
                except (tk.TclError, AttributeError):
                    pass

            def safe_console_callback(msg):
                try:
                    if dialog.winfo_exists():
                        append_console(msg)
                except (tk.TclError, AttributeError):
                    pass

            # Prepare minecraft version data if applicable
            minecraft_version_data = None
            if server_type == "Minecraft":
                selected_version = form_vars['minecraft_version'].get()
                version_map = getattr(dialog, 'version_map', {})
                minecraft_version_data = version_map.get(selected_version)

            # Use the existing installation function from dashboard_functions
            success, message = perform_server_installation(
                server_type=server_type,
                server_name=server_name,
                install_dir=install_dir,
                app_id=form_vars.get('app_id', tk.StringVar()).get() if server_type == "Steam" else None,
                minecraft_version=minecraft_version_data,
                credentials=credentials,
                server_manager=dashboard.server_manager,
                progress_callback=safe_status_callback,
                console_callback=safe_console_callback,
                steam_cmd_path=dashboard.steam_cmd_path
            )

            # Check if dialog still exists before updating UI
            if not dialog.winfo_exists():
                return

            if success:
                append_console(f"[SUCCESS] {message}")
                status_var.set("Installation completed successfully!")
                dashboard.update_server_list(force_refresh=True)
                messagebox.showinfo("Success", message)
                dialog.destroy()
            else:
                append_console(f"[ERROR] {message}")
                status_var.set("Installation failed!")

                # Show detailed error dialog for installation failures
                try:
                    messagebox.showerror("Installation Failed",
                                       f"Server installation failed:\n\n{message}\n\n"
                                       "Please check the console output for more details.")
                except tk.TclError:
                    # Dialog might be destroyed
                    pass

                create_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.DISABLED)

        except tk.TclError:
            # Dialog was destroyed while thread was running - this is normal
            logger.info("Installation dialog was closed while installation was in progress")
            return
        except Exception as e:
            logger.error(f"Error during server installation: {str(e)}")
            if dialog.winfo_exists():
                append_console(f"[ERROR] {str(e)}")
                status_var.set("Installation failed!")
                create_button.config(state=tk.NORMAL)
                cancel_button.config(state=tk.DISABLED)
        finally:
            try:
                if dialog.winfo_exists():
                    progress.stop()
            except (tk.TclError, AttributeError):
                # Widget was destroyed, ignore
                pass

    def start_installation():
        installation_thread = threading.Thread(target=install_server)
        installation_thread.daemon = True
        installation_thread.start()

    def cancel_installation():
        dashboard.install_cancelled.set(True)
        cancel_button.config(state=tk.DISABLED)
        status_var.set("Cancelling installation...")
        append_console("[INFO] Cancellation requested, stopping installation process...")

    def close_dialog():
        # Cancel any running installation
        if hasattr(dashboard, 'install_cancelled'):
            dashboard.install_cancelled.set(True)
        dialog.destroy()

    create_button.config(command=start_installation)
    cancel_button.config(command=cancel_installation)
    close_button.config(command=close_dialog)

    def on_close():
        # Handle window close (X button) - check if installation is running
        if hasattr(dashboard, 'install_cancelled') and hasattr(cancel_button, 'instate'):
            try:
                if cancel_button.instate(['!disabled']):
                    result = messagebox.askyesno("Confirm Exit",
                                               "An installation is in progress. Do you want to cancel it?",
                                               icon=messagebox.QUESTION)
                    if result:
                        dashboard.install_cancelled.set(True)
                        dialog.destroy()
                    # If they chose not to cancel, don't close the dialog
                    return
            except tk.TclError:
                # Widget was destroyed, just close
                pass

        # Cancel any running installation and close
        if hasattr(dashboard, 'install_cancelled'):
            dashboard.install_cancelled.set(True)
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", on_close)

    centre_window(dialog, dialog_width, dialog_height, dashboard.root)
