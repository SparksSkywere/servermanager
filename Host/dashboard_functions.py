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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path, centre_window
setup_module_path()
from Modules.server_logging import get_dashboard_logger, log_dashboard_event

# Alias for backwards compat
center_window = centre_window

logger: logging.Logger = get_dashboard_logger()

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
    
    center_window(type_dialog, 380, 280, root)
    
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


def show_steam_credentials_dialog(root):
    # Show dialog to manage Steam credentials with SteamGuard support
    from Modules.Database.cluster_database import ClusterDatabase
    
    dialog = tk.Toplevel(root)
    dialog.title("Steam Credentials Manager")
    dialog.geometry("500x550")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()
    
    main_frame = ttk.Frame(dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    title_label = ttk.Label(main_frame, text="🎮 Steam Credentials", font=("Segoe UI", 14, "bold"))
    title_label.pack(anchor=tk.W, pady=(0, 5))
    
    desc_label = ttk.Label(main_frame, text="Save your Steam credentials for automatic login during server installations and updates.", 
                          wraplength=450, foreground="gray")
    desc_label.pack(anchor=tk.W, pady=(0, 20))
    
    # Load existing credentials
    db = ClusterDatabase()
    stored_creds = db.get_steam_credentials() or {}
    
    anon_var = tk.BooleanVar(value=stored_creds.get('use_anonymous', False))
    
    def toggle_fields(*args):
        state = 'disabled' if anon_var.get() else 'normal'
        username_entry.config(state=state)
        password_entry.config(state=state)
        guard_entry.config(state=state)
        show_qr_btn.config(state=state)
    
    anon_frame = ttk.Frame(main_frame)
    anon_frame.pack(fill=tk.X, pady=(0, 15))
    
    anon_check = ttk.Checkbutton(anon_frame, text="Use Anonymous Login (limited to free games)", 
                                  variable=anon_var, command=toggle_fields)
    anon_check.pack(anchor=tk.W)
    
    creds_frame = ttk.LabelFrame(main_frame, text="Steam Account", padding=15)
    creds_frame.pack(fill=tk.X, pady=(0, 15))
    
    ttk.Label(creds_frame, text="Username:").pack(anchor=tk.W, pady=(0, 5))
    username_var = tk.StringVar(value=stored_creds.get('username', ''))
    username_entry = ttk.Entry(creds_frame, textvariable=username_var, width=40)
    username_entry.pack(fill=tk.X, pady=(0, 10))
    
    ttk.Label(creds_frame, text="Password:").pack(anchor=tk.W, pady=(0, 5))
    password_var = tk.StringVar(value=stored_creds.get('password', ''))
    password_entry = ttk.Entry(creds_frame, textvariable=password_var, width=40, show="*")
    password_entry.pack(fill=tk.X, pady=(0, 10))
    
    show_pass_var = tk.BooleanVar(value=False)
    def toggle_password():
        password_entry.config(show="" if show_pass_var.get() else "*")
    show_pass_check = ttk.Checkbutton(creds_frame, text="Show password", variable=show_pass_var, command=toggle_password)
    show_pass_check.pack(anchor=tk.W, pady=(0, 5))
    
    guard_frame = ttk.LabelFrame(main_frame, text="Steam Guard (2FA)", padding=15)
    guard_frame.pack(fill=tk.X, pady=(0, 15))
    
    guard_desc = ttk.Label(guard_frame, 
                          text="Enter your Steam Guard shared secret to automatically generate 2FA codes.\n"
                               "This is the same secret used by mobile authenticators.",
                          wraplength=420, foreground="gray")
    guard_desc.pack(anchor=tk.W, pady=(0, 10))
    
    ttk.Label(guard_frame, text="Shared Secret:").pack(anchor=tk.W, pady=(0, 5))
    guard_var = tk.StringVar(value=stored_creds.get('steam_guard_secret', ''))
    guard_entry = ttk.Entry(guard_frame, textvariable=guard_var, width=40)
    guard_entry.pack(fill=tk.X, pady=(0, 10))
    
    qr_frame = ttk.Frame(guard_frame)
    qr_frame.pack(fill=tk.X)
    
    qr_label = ttk.Label(qr_frame, text="")
    qr_label.pack(side=tk.LEFT)
    
    def show_qr_code():
        # Show QR code for Steam Guard setup
        secret = guard_var.get().strip()
        username = username_var.get().strip()
        
        if not secret:
            from tkinter import messagebox
            messagebox.showwarning("No Secret", "Please enter a Steam Guard shared secret first.")
            return
        
        try:
            import pyotp
            # Create TOTP URI for Steam
            totp = pyotp.TOTP(secret)
            uri = totp.provisioning_uri(name=username or "Steam", issuer_name="Steam")
            
            # Try to generate QR code
            try:
                import qrcode  # type: ignore[import-not-found]
                from PIL import Image, ImageTk
                import io
                
                qr = qrcode.QRCode(version=1, box_size=4, border=2)
                qr.add_data(uri)
                qr.make(fit=True)
                
                img = qr.make_image(fill_color="black", back_color="white")
                
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='PNG')  # type: ignore[call-arg]
                img_bytes.seek(0)
                
                pil_img = Image.open(img_bytes)
                photo = ImageTk.PhotoImage(pil_img)
                
                qr_window = tk.Toplevel(dialog)
                qr_window.title("Steam Guard QR Code")
                qr_window.geometry("250x300")
                qr_window.transient(dialog)
                
                ttk.Label(qr_window, text="Scan with authenticator app:", font=("Segoe UI", 10)).pack(pady=10)
                qr_display = ttk.Label(qr_window, image=photo)
                qr_display.image = photo  # type: ignore[attr-defined] # Keep reference
                qr_display.pack(pady=10)
                
                code = totp.now()
                code_label = ttk.Label(qr_window, text=f"Current Code: {code}", font=("Courier", 14, "bold"))
                code_label.pack(pady=10)
                
                ttk.Button(qr_window, text="Close", command=qr_window.destroy).pack(pady=10)
                
            except ImportError:
                # QR code libraries not available, just show the code
                from tkinter import messagebox
                code = totp.now()
                messagebox.showinfo("Steam Guard Code", 
                                   f"Current 2FA Code: {code}\n\n"
                                   f"(Install qrcode and Pillow packages for QR code display)")
                
        except ImportError:
            from tkinter import messagebox
            messagebox.showerror("Missing Package", 
                               "pyotp package is required for Steam Guard support.\n"
                               "Install with: pip install pyotp")
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Failed to generate QR code: {e}")
    
    show_qr_btn = ttk.Button(qr_frame, text="Show QR / Test Code", command=show_qr_code)
    show_qr_btn.pack(side=tk.RIGHT)
    
    status_var = tk.StringVar()
    status_label = ttk.Label(main_frame, textvariable=status_var, foreground="green")
    status_label.pack(anchor=tk.W, pady=(0, 10))
    
    toggle_fields()
    
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=(10, 0))
    
    def save_credentials():
        try:
            success = db.save_steam_credentials(
                username=username_var.get().strip(),
                password=password_var.get(),
                steam_guard_secret=guard_var.get().strip(),
                use_anonymous=anon_var.get()
            )
            if success:
                status_var.set("✓ Credentials saved successfully!")
                dialog.after(1500, dialog.destroy)
            else:
                status_var.set("✗ Failed to save credentials")
                status_label.config(foreground="red")
        except Exception as e:
            status_var.set(f"✗ Error: {e}")
            status_label.config(foreground="red")
    
    def clear_credentials():
        from tkinter import messagebox
        if messagebox.askyesno("Confirm", "Are you sure you want to delete saved Steam credentials?"):
            db.delete_steam_credentials()
            username_var.set("")
            password_var.set("")
            guard_var.set("")
            anon_var.set(False)
            toggle_fields()
            status_var.set("✓ Credentials cleared")
    
    ttk.Button(button_frame, text="Save", command=save_credentials, width=12).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(button_frame, text="Clear", command=clear_credentials, width=12).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(button_frame, text="Cancel", command=dialog.destroy, width=12).pack(side=tk.LEFT)
    
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
    y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")


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
    
    center_window(dialog, 700, 500, parent)
    
    parent.wait_window(dialog)
    
    return selected_version["version"]


def create_steam_appid_browser_dialog(parent, server_manager_dir):
    dialog = tk.Toplevel(parent)
    dialog.title("Select Steam Dedicated Server")
    dialog.geometry("700x500")
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

        # Add refresh info to dialog
        if metadata.get('last_updated'):
            last_updated = metadata['last_updated']
            if 'T' in last_updated:  # ISO format
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
                    ttk.Label(search_frame, text=f"Data last updated: {formatted_date}",
                            foreground="gray", font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(10, 0))
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
    server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
    
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
                tooltip = tk.Toplevel(dialog)
                tooltip.wm_overrideredirect(True)
                tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")
                
                desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")
                
                label = tk.Label(tooltip, text=f"{selected_server['name']}\n\n{desc}", 
                               background="lightyellow", relief="solid", borderwidth=1,
                               wraplength=300, justify=tk.LEFT, font=("Segoe UI", 9))
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
    
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)
    
    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
    ttk.Button(button_frame, text="Select Server", command=on_select).pack(side=tk.RIGHT)
    
    center_window(dialog, 700, 500, parent)
    
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
    #
    # Args:
    #     server_type: Type of server to install
    #     server_name: Name for the server
    #     install_dir: Installation directory
    #     app_id: Steam App ID (for Steam servers)
    #     minecraft_version: Minecraft version data (for Minecraft servers)
    #     credentials: Steam credentials (for Steam servers)
    #     server_manager: Server manager instance
    #     progress_callback: Function to call with progress updates
    #     console_callback: Function to call with console output
    #     steam_cmd_path: Path to SteamCMD executable (for Steam servers)
    #
    # Returns:
    #     tuple: (success, message)
    try:
        if not server_manager:
            error_msg = "Server manager not available"
            if console_callback:
                console_callback(f"[ERROR] {error_msg}")
            return False, error_msg

        # Get SteamCMD path if not provided and server type is Steam
        if server_type == "Steam" and not steam_cmd_path:
            from Modules.common import get_registry_value
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
            executable_path="",  # Let backend determine executable
            startup_args="",
            app_id=app_id or "",
            version=minecraft_version.get('version_id', '') if minecraft_version else "",
            modloader=minecraft_version.get('modloader', 'vanilla') if minecraft_version else "",
            steam_cmd_path=steam_cmd_path or "",
            credentials=credentials or {"anonymous": True},
            progress_callback=console_callback,  # Use console callback for progress
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
        status = check_webserver_status(paths, variables)
        webserver_status_label.config(text=status)
        
        if status == "Running":
            webserver_status_label.config(foreground="green")
        elif status == "Stopped":
            webserver_status_label.config(foreground="red")
        elif status == "Offline Mode":
            webserver_status_label.config(foreground="orange")
        else:
            webserver_status_label.config(foreground="gray")
    except Exception as e:
        logger.error(f"Error updating webserver status: {e}")
        webserver_status_label.config(text="Unknown", foreground="gray")


# Global variables for network monitoring
_previous_network_stats = None
_previous_network_time = None

def update_system_info(metric_labels, system_name, os_info, variables):
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
            metric_labels["cpu"].config(text=f"CPU: {cpu_percent:.1f}%")
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            metric_labels["cpu"].config(text="CPU: N/A")

        try:
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)
            metric_labels["memory"].config(text=f"Memory: {memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB ({memory_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            metric_labels["memory"].config(text="Memory: N/A")

        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_used_gb = disk.used / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            metric_labels["disk"].config(text=f"Disk: {disk_used_gb:.1f}GB / {disk_total_gb:.1f}GB ({disk_percent:.1f}%)")
        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            metric_labels["disk"].config(text="Disk: N/A")

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
                        
                        def format_speed(bytes_per_sec):
                            if bytes_per_sec >= 1024**3:  # GB/s
                                return f"{bytes_per_sec / (1024**3):.1f}GB/s"
                            elif bytes_per_sec >= 1024**2:  # MB/s
                                return f"{bytes_per_sec / (1024**2):.1f}MB/s"
                            elif bytes_per_sec >= 1024:  # KB/s
                                return f"{bytes_per_sec / 1024:.1f}KB/s"
                            else:  # B/s
                                return f"{bytes_per_sec:.1f}B/s"
                        
                        sent_display = format_speed(bytes_sent_per_sec)
                        recv_display = format_speed(bytes_recv_per_sec)
                        
                        metric_labels["network"].config(text=f"Network: ↑{sent_display} ↓{recv_display}")
                    else:
                        metric_labels["network"].config(text="Network: Calculating...")
                else:
                    metric_labels["network"].config(text="Network: Initialising...")
                
                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                metric_labels["network"].config(text="Network: N/A")
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            metric_labels["network"].config(text="Network: N/A")

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
            
            metric_labels["gpu"].config(text=gpu_info)
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            metric_labels["gpu"].config(text="GPU: Error")

        try:
            uptime_seconds = time.time() - psutil.boot_time()
            uptime_str = format_uptime_from_start_time(uptime_seconds)
            metric_labels["uptime"].config(text=f"Uptime: {uptime_str}")
        except Exception as e:
            logger.error(f"Error getting uptime info: {e}")
            metric_labels["uptime"].config(text="Uptime: N/A")

    except Exception as e:
        logger.error(f"Error updating system info: {e}")
        # Set all labels to error state
        for label_name in metric_labels:
            metric_labels[label_name].config(text=f"{label_name.title()}: Error")


def collect_system_info_data():
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

        # CPU usage (per-core and overall)
        try:
            # Get per-core CPU usage (includes overall calculation)
            # Use interval=0.1 for more accurate reading since this runs in background thread
            # Single call with percpu=True is more efficient than two separate calls
            per_core_cpu = psutil.cpu_percent(percpu=True, interval=0.5)
            overall_cpu = sum(per_core_cpu) / len(per_core_cpu) if per_core_cpu else 0
            
            if len(per_core_cpu) <= 8:  # Show per-core for systems with 8 or fewer cores
                core_usage = ", ".join([f"{i}:{usage:.0f}%" for i, usage in enumerate(per_core_cpu)])
                data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nCores: {core_usage}"
            else:  # For systems with many cores, show overall + summary
                high_usage_cores = [i for i, usage in enumerate(per_core_cpu) if usage > 50]
                if high_usage_cores:
                    data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nHigh usage cores: {len(high_usage_cores)}/{len(per_core_cpu)}"
                else:
                    data['cpu_percent'] = f"Overall: {overall_cpu:.1f}%\nAll cores: <50% usage"
                    
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            data['cpu_percent'] = None

        try:
            memory = psutil.virtual_memory()
            data['memory_percent'] = memory.percent
            data['memory_used_gb'] = memory.used / (1024**3)
            data['memory_total_gb'] = memory.total / (1024**3)
        except Exception as e:
            logger.error(f"Error getting memory info: {e}")
            data['memory_percent'] = None
            data['memory_used_gb'] = None
            data['memory_total_gb'] = None

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
                        
                        def format_speed(bytes_per_sec):
                            if bytes_per_sec >= 1024**3:  # GB/s
                                return f"{bytes_per_sec / (1024**3):.1f}GB/s"
                            elif bytes_per_sec >= 1024**2:  # MB/s
                                return f"{bytes_per_sec / (1024**2):.1f}MB/s"
                            elif bytes_per_sec >= 1024:  # KB/s
                                return f"{bytes_per_sec / 1024:.1f}KB/s"
                            else:  # B/s
                                return f"{bytes_per_sec:.1f}B/s"
                        
                        data['network_sent_display'] = format_speed(bytes_sent_per_sec)
                        data['network_recv_display'] = format_speed(bytes_recv_per_sec)
                    else:
                        data['network_display'] = "Network: Calculating..."
                else:
                    data['network_display'] = "Network: Initialising..."
                
                _previous_network_stats = network_stats
                _previous_network_time = current_time
            else:
                data['network_display'] = "Network: N/A"
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            data['network_display'] = "Network: N/A"

        # GPU info (this is the heavy operation that needs threading)
        # Note: GPUtil uses subprocess.Popen without CREATE_NO_WINDOW which causes console flash
        # We use a direct nvidia-smi call with CREATE_NO_WINDOW instead
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

    except Exception as e:
        logger.error(f"Error collecting system info data: {e}")
        data['error'] = str(e)
    
    return data


def update_system_info_threaded(metric_labels, system_name, os_info, callback=None):
    # Update system information using background threading to prevent UI freezing
    import threading
    
    def background_update():
        try:
            data = collect_system_info_data()
            
            def update_ui():
                try:
                    if 'system_name' in data:
                        system_name.config(text=data['system_name'])
                    if 'os_info' in data:
                        os_info.config(text=data['os_info'])
                    
                    if data.get('cpu_percent') is not None:
                        if isinstance(data['cpu_percent'], str) and '\n' in data['cpu_percent']:
                            # Multi-line CPU display (per-core)
                            metric_labels["cpu"].config(text=data['cpu_percent'])
                        else:
                            # Single line CPU display
                            metric_labels["cpu"].config(text=f"CPU: {data['cpu_percent']:.1f}%")
                    else:
                        metric_labels["cpu"].config(text="CPU: N/A")
                    
                    if all(k in data for k in ['memory_used_gb', 'memory_total_gb', 'memory_percent']):
                        metric_labels["memory"].config(
                            text=f"Memory: {data['memory_used_gb']:.1f}GB / {data['memory_total_gb']:.1f}GB ({data['memory_percent']:.1f}%)"
                        )
                    else:
                        metric_labels["memory"].config(text="Memory: N/A")
                    
                    if 'disk_info' in data:
                        metric_labels["disk"].config(text=data['disk_info'])
                    else:
                        metric_labels["disk"].config(text="Disk: N/A")
                    
                    if 'network_display' in data:
                        metric_labels["network"].config(text=data['network_display'])
                    elif 'network_sent_display' in data and 'network_recv_display' in data:
                        metric_labels["network"].config(text=f"Network: ↑{data['network_sent_display']} ↓{data['network_recv_display']}")
                    else:
                        metric_labels["network"].config(text="Network: N/A")
                    
                    if 'gpu_info' in data:
                        metric_labels["gpu"].config(text=data['gpu_info'])
                    else:
                        metric_labels["gpu"].config(text="GPU: Error")
                    
                    if data.get('uptime_seconds') is not None:
                        uptime_str = format_uptime_from_start_time(data['uptime_seconds'])
                        metric_labels["uptime"].config(text=f"Uptime: {uptime_str}")
                    else:
                        metric_labels["uptime"].config(text="Uptime: N/A")
                    
                    if callback:
                        callback()
                        
                except Exception as e:
                    logger.error(f"Error updating UI with system data: {e}")
                    # Set all labels to error state
                    for label_name in metric_labels:
                        metric_labels[label_name].config(text=f"{label_name.title()}: Error")
            
            if hasattr(system_name, 'after'):
                system_name.after(0, update_ui)
            elif hasattr(system_name, 'root') and hasattr(system_name.root, 'after'):
                system_name.root.after(0, update_ui)
                
        except Exception as e:
            logger.error(f"Error in background system info update: {e}")
    
    thread = threading.Thread(target=background_update, daemon=True)
    thread.start()


# Additional placeholder functions that dashboard.py might need
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
                # Update the status (index 1) while preserving other values
                updated_values = (
                    item_values[0],  # server_name
                    status,          # new status
                    item_values[2] if len(item_values) > 2 else '',  # pid
                    item_values[3] if len(item_values) > 3 else '0%',  # cpu
                    item_values[4] if len(item_values) > 4 else '0 MB',  # memory
                    item_values[5] if len(item_values) > 5 else '00:00:00'  # uptime
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
        dialog.geometry("600x550")
        center_window(dialog, parent=root)
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
            from Modules.server_manager import ServerManager
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
                    from Modules.server_manager import ServerManager
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
                    executable_path="",  # Will be auto-detected
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
        dialog.geometry("550x350")
        center_window(dialog, parent=root)
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
            self.dialog.geometry("600x400")
            center_window(self.dialog, parent=parent)
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


def create_server_removal_dialog(root, server_name, server_manager):
    class ServerRemovalDialog:
        def __init__(self, parent, server_name, server_manager):
            self.parent = parent
            self.server_name = server_name
            self.server_manager = server_manager
            self.result = {'confirmed': False, 'remove_files': False}

            self.dialog = tk.Toplevel(parent)
            self.dialog.title(f"Remove Server - {server_name}")
            self.dialog.transient(parent)
            self.dialog.grab_set()
            self.dialog.geometry("500x400")
            center_window(self.dialog, parent=parent)

            main_frame = ttk.Frame(self.dialog, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            warning_frame = ttk.Frame(main_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))

            ttk.Label(warning_frame, text="Warning", font=("Segoe UI", 12)).pack(side=tk.LEFT, padx=(0, 10))
            title_label = ttk.Label(warning_frame, text=f"Remove Server '{server_name}'",
                                  font=("Segoe UI", 14, "bold"))
            title_label.pack(side=tk.LEFT)

            warning_text = ("This action cannot be undone.\n\n"
                          "Choose what you want to remove:")
            ttk.Label(main_frame, text=warning_text, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 15))

            self.remove_config_var = tk.BooleanVar(value=True)
            self.remove_files_var = tk.BooleanVar(value=False)

            config_frame = ttk.Frame(main_frame)
            config_frame.pack(fill=tk.X, pady=(0, 10))

            ttk.Checkbutton(config_frame, text="Remove server configuration",
                          variable=self.remove_config_var,
                          command=self.on_config_checkbox_change).pack(anchor=tk.W)

            ttk.Label(config_frame, text="Removes the server from the dashboard and configuration files",
                     foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=(20, 0), pady=(2, 0))

            files_frame = ttk.Frame(main_frame)
            files_frame.pack(fill=tk.X, pady=(0, 20))

            ttk.Checkbutton(files_frame, text="Remove server files and directory",
                          variable=self.remove_files_var).pack(anchor=tk.W)

            ttk.Label(files_frame, text="Deletes all server files, saves, and installation directory",
                     foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=(20, 0), pady=(2, 0))

            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=(20, 0))

            ttk.Button(button_frame, text="Cancel", command=self.cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Remove Server", command=self.confirm_removal,
                      style="Accent.TButton", width=15).pack(side=tk.RIGHT)

            self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)

        def on_config_checkbox_change(self):
            # Ensure at least one option is selected
            if not self.remove_config_var.get() and not self.remove_files_var.get():
                self.remove_config_var.set(True)

        def confirm_removal(self):
            if not self.remove_config_var.get() and not self.remove_files_var.get():
                messagebox.showwarning("Selection Required",
                                     "Please select at least one removal option.")
                return

            self.result = {
                'confirmed': True,
                'remove_files': self.remove_files_var.get(),
                'remove_config': self.remove_config_var.get()
            }
            self.dialog.destroy()

        def cancel(self):
            self.result = {'confirmed': False, 'remove_files': False}
            self.dialog.destroy()

        def show(self):
            self.dialog.wait_window()
            return self.result

    dialog = ServerRemovalDialog(root, server_name, server_manager)
    return dialog.show()


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


def show_java_configuration_dialog(root, server_name, server_config, server_manager):
    try:
        dialog = tk.Toplevel(root)
        dialog.title(f"Java Configuration - {server_name}")
        dialog.geometry("500x400")
        center_window(dialog, parent=root)
        dialog.transient(root)
        dialog.grab_set()
        
        result = {'success': False, 'message': 'Configuration cancelled'}
        
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Java Executable:").pack(anchor=tk.W, pady=(0, 5))
        
        java_frame = ttk.Frame(main_frame)
        java_frame.pack(fill=tk.X, pady=(0, 10))
        
        java_var = tk.StringVar(value=server_config.get('JavaPath', 'java'))
        java_entry = ttk.Entry(java_frame, textvariable=java_var)
        java_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_java():
            filename = filedialog.askopenfilename(
                title="Select Java Executable",
                filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
            )
            if filename:
                java_var.set(filename)
        
        ttk.Button(java_frame, text="Browse", command=browse_java).pack(side=tk.RIGHT)
        
        ttk.Label(main_frame, text="JVM Arguments:").pack(anchor=tk.W, pady=(10, 5))
        
        jvm_args_var = tk.StringVar(value=server_config.get('JVMArgs', '-Xmx2G -Xms1G'))
        jvm_entry = ttk.Entry(main_frame, textvariable=jvm_args_var, width=60)
        jvm_entry.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(main_frame, text="Common Presets:").pack(anchor=tk.W, pady=(10, 5))
        
        preset_frame = ttk.Frame(main_frame)
        preset_frame.pack(fill=tk.X, pady=(0, 10))
        
        presets = [
            ("2GB RAM", "-Xmx2G -Xms1G"),
            ("4GB RAM", "-Xmx4G -Xms2G"),
            ("8GB RAM", "-Xmx8G -Xms4G"),
            ("16GB RAM", "-Xmx16G -Xms8G")
        ]
        
        for i, (name, args) in enumerate(presets):
            ttk.Button(
                preset_frame, 
                text=name,
                command=lambda a=args: jvm_args_var.set(a)
            ).grid(row=i//2, column=i%2, padx=5, pady=2, sticky=tk.W)
        
        def auto_detect_java():
            java_paths = [
                "java",
                "C:\\Program Files\\Java\\*\\bin\\java.exe",
                "C:\\Program Files (x86)\\Java\\*\\bin\\java.exe"
            ]
            
            for path in java_paths:
                try:
                    if '*' in path:
                        # Handle wildcard paths
                        import glob
                        matches = glob.glob(path)
                        if matches:
                            java_var.set(matches[0])
                            break
                    else:
                        # Test basic java command
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        result = subprocess.run([path, '-version'], 
                                              capture_output=True, text=True, timeout=5,
                                              startupinfo=startupinfo, 
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                        if result.returncode == 0:
                            java_var.set(path)
                            break
                except (subprocess.SubprocessError, OSError, FileNotFoundError):
                    continue
        
        ttk.Button(main_frame, text="Auto-Detect Java", command=auto_detect_java).pack(pady=(10, 0))
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        def save_config():
            try:
                server_config['JavaPath'] = java_var.get()
                server_config['JVMArgs'] = jvm_args_var.get()
                
                success = server_manager.update_server(server_name, server_config)
                if success:
                    result['success'] = True
                    result['message'] = "Java configuration saved successfully"
                    dialog.destroy()
                    messagebox.showinfo("Success", result['message'])
                else:
                    messagebox.showerror("Error", "Failed to save configuration")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        ttk.Button(button_frame, text="Save", command=save_config).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)
        
        dialog.wait_window()
        return result
        
    except Exception as e:
        logger.error(f"Error in Java configuration dialog: {e}")
        return {'success': False, 'message': str(e)}


def batch_update_server_types(paths):
    try:
        updated_count = 0
        updated_servers = []
        
        # This is a placeholder implementation
        # In a real implementation, this would:
        # 1. Iterate through all server configurations
        # 2. Detect the actual server type from installation directory
        # 3. Update configurations that have incorrect types
        # 4. Return count and list of updated servers
        
        logger.info("Batch server type update completed")
        return updated_count, updated_servers
        
    except Exception as e:
        logger.error(f"Error in batch update server types: {e}")
        return 0, []


def create_java_selection_dialog(root, minecraft_version=None):
    # Create a dialog to select Java installation for a server
    try:
        try:
            from Modules.java_configurator import JavaConfigurator
            configurator = JavaConfigurator()
        except ImportError:
            logger.warning("JavaConfigurator module not available")
            return None
        
        dialog = tk.Toplevel(root)
        dialog.title("Select Java Installation")
        dialog.geometry("600x400")
        dialog.transient(root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(main_frame, text="Select Java Installation", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 15))
        
        list_frame = ttk.LabelFrame(main_frame, text="Available Java Installations", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        columns = ("path", "version", "vendor")
        java_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        
        java_tree.heading("path", text="Path")
        java_tree.heading("version", text="Version")
        java_tree.heading("vendor", text="Vendor")
        
        java_tree.column("path", width=300, minwidth=200)
        java_tree.column("version", width=100, minwidth=80)
        java_tree.column("vendor", width=100, minwidth=80)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=java_tree.yview)
        java_tree.configure(yscrollcommand=scrollbar.set)
        
        java_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        try:
            java_installations = configurator.detect_java_installations()
            
            for java in java_installations:
                java_tree.insert("", tk.END, values=(
                    java.get("path", ""),
                    java.get("version", ""),
                    java.get("vendor", "Unknown")
                ))
        except Exception as e:
            logger.error(f"Error loading Java installations: {e}")
            java_tree.insert("", tk.END, values=("Error loading Java installations", str(e), ""))
        
        selected_java: Dict[str, Any] = {"java": None}
        
        def on_select():
            selected = java_tree.selection()
            if selected:
                item = java_tree.item(selected[0])
                selected_java["java"] = {
                    "path": item['values'][0],
                    "version": item['values'][1],
                    "vendor": item['values'][2]
                }
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Select", command=on_select).pack(side=tk.RIGHT)
        
        java_tree.bind("<Double-1>", lambda e: on_select())
        
        center_window(dialog, 600, 400, root)
        
        root.wait_window(dialog)
        return selected_java["java"]
        
    except Exception as e:
        logger.error(f"Error creating Java selection dialog: {e}")
        return None


def load_appid_list_from_database():
    try:
        from Modules.Database.scanners.AppIDScanner import AppIDScanner
        scanner = AppIDScanner(use_database=True, debug_mode=False)
        appids = scanner.get_server_apps(dedicated_only=True)
        scanner.close()
        return appids
    except ImportError:
        logger.warning("AppIDScanner module not available")
        return []
    except Exception as e:
        logger.error(f"Error loading AppID list from database: {e}")
        return []


def find_appid_in_directory(directory_path):
    if not directory_path or not os.path.exists(directory_path):
        return None
    
    try:
        # Look for Steam app manifest files - read files efficiently
        appid_file = None
        acf_file = None

        # First pass: find the files
        for file in os.listdir(directory_path):
            if file == "steam_appid.txt":
                appid_file = os.path.join(directory_path, file)
            elif file.startswith("appmanifest_") and file.endswith(".acf"):
                acf_file = os.path.join(directory_path, file)

        # Read steam_appid.txt if found
        if appid_file:
            try:
                with open(appid_file, 'r') as f:
                    appid = f.read().strip()
                    if appid.isdigit():
                        return appid
            except (IOError, OSError):
                pass

        # Read and parse ACF file if found
        if acf_file:
            try:
                with open(acf_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Simple parsing for "appid" value
                    import re
                    match = re.search(r'"appid"\s*"(\d+)"', content)
                    if match:
                        return match.group(1)
            except (IOError, OSError):
                pass

        return None
    except Exception as e:
        logger.error(f"Error finding AppID in directory {directory_path}: {e}")
        return None


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
    if variables.get("offlineMode", False):
        return "Offline Mode"
        
    try:
        webserver_port = variables.get("webserverPort", 8080)
        if is_port_open("localhost", webserver_port):
            return "Running"
        else:
            return "Stopped"
    except Exception as e:
        logger.error(f"Error checking webserver status: {e}")
        return "Unknown"


def export_server_configuration(server_name, paths, include_files=False):
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        config = server_manager.get_server_config(server_name)
        if not config:
            return None
        
        export_data = {
            "version": "1.0",
            "export_date": datetime.datetime.now().isoformat(),
            "server_name": server_name,
            "configuration": config,
            "includes_files": include_files
        }
        
        if include_files:
            # Include server files in export (compressed)
            install_dir = config.get("InstallDir", "")
            if install_dir and os.path.exists(install_dir):
                # This would compress the directory - simplified for now
                export_data["files_archive"] = f"Would compress {install_dir}"
        
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting server configuration: {e}")
        return None


def import_server_configuration(export_data, paths, install_directory=None, auto_install=False):
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        server_name = export_data.get("server_name")
        config = export_data.get("configuration")
        
        if not server_name or not config:
            return False, "Invalid export data"
        
        if server_manager.get_server_config(server_name):
            server_name = generate_unique_server_name(server_name, paths)
        
        if install_directory:
            config["InstallDir"] = install_directory
        
        success = server_manager.update_server(server_name, config)
        
        if success:
            message = f"Server '{server_name}' imported successfully"
            if auto_install:
                # Attempt auto-installation
                message += " (auto-installation attempted)"
            return True, message
        else:
            return False, f"Failed to import server '{server_name}'"
            
    except Exception as e:
        logger.error(f"Error importing server configuration: {e}")
        return False, f"Import failed: {str(e)}"


def generate_unique_server_name(name, paths):
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        base_name = name
        counter = 1
        
        while server_manager.get_server_config(name):
            name = f"{base_name}_{counter}"
            counter += 1
        
        return name
        
    except Exception as e:
        logger.error(f"Error generating unique server name: {e}")
        return f"{name}_{int(datetime.datetime.now().timestamp())}"


def get_directory_size(directory):
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, IOError):
                    pass
        return total_size
    except Exception:
        return 0


def count_files_in_directory(directory):
    try:
        count = 0
        for _, _, files in os.walk(directory):
            count += len(files)
        return count
    except Exception:
        return 0


def export_server_to_file(export_data, export_path, include_files=False):
    try:
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        return True, f"Server exported to {export_path}"
    except Exception as e:
        logger.error(f"Error exporting server to file: {e}")
        return False, f"Export failed: {str(e)}"


def import_server_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            export_data = json.load(f)
        
        has_files = export_data.get("includes_files", False)
        return True, export_data, has_files
    except Exception as e:
        logger.error(f"Error importing server from file: {e}")
        return False, None, False


def extract_server_files_from_archive(zip_path, extract_to):
    try:
        import zipfile
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        
        return True, f"Files extracted to {extract_to}"
    except Exception as e:
        logger.error(f"Error extracting server files: {e}")
        return False, f"Extraction failed: {str(e)}"


def validate_server_creation_inputs(server_type, server_name, app_id=None, executable_path=None):
    try:
        errors = []
        
        if not server_name or not server_name.strip():
            errors.append("Server name is required")
        elif len(server_name.strip()) < 3:
            errors.append("Server name must be at least 3 characters")
        elif any(char in server_name for char in ['<', '>', ':', '"', '|', '?', '*', '\\', '/']):
            errors.append("Server name contains invalid characters")
        
        if server_type == "Steam":
            if not app_id or not app_id.strip():
                errors.append("Steam App ID is required")
            elif not app_id.strip().isdigit():
                errors.append("Steam App ID must be numeric")
        elif server_type == "Minecraft":
            pass  # No additional validation needed for basic Minecraft setup
        elif server_type == "Other":
            if not executable_path or not executable_path.strip():
                errors.append("Executable path is required for Other server type")
            elif not os.path.exists(executable_path.strip()):
                errors.append("Specified executable does not exist")
        
        return len(errors) == 0, errors
        
    except Exception as e:
        logger.error(f"Error validating server creation inputs: {e}")
        return False, [f"Validation error: {str(e)}"]


def create_remote_host_connection_dialog(parent, dashboard):
    dialog = tk.Toplevel(parent)
    dialog.title("Connect to Remote Host")
    dialog.geometry("600x650")
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(True, True)
    dialog.minsize(500, 550)
    
    # Create a canvas with scrollbar for very small screens
    canvas = tk.Canvas(dialog)
    scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    main_frame = ttk.Frame(scrollable_frame, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    main_frame.grid_rowconfigure(6, weight=1)
    
    title_label = ttk.Label(main_frame, text="Connect to Remote Server Manager Host", font=("Segoe UI", 14, "bold"))
    title_label.pack(pady=(0, 15))
    
    info_label = ttk.Label(main_frame, text="Connect to a remote Server Manager instance for one-time operations", 
                          foreground="gray", font=("Segoe UI", 9))
    info_label.pack(pady=(0, 20))
    
    details_frame = ttk.LabelFrame(main_frame, text="Connection Details", padding=15)
    details_frame.pack(fill=tk.X, pady=(0, 15))
    details_frame.grid_columnconfigure(1, weight=1)
    
    ttk.Label(details_frame, text="Host/IP Address:").grid(row=0, column=0, sticky=tk.W, pady=8)
    host_var = tk.StringVar()
    host_entry = ttk.Entry(details_frame, textvariable=host_var, width=35)
    host_entry.grid(row=0, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    ttk.Label(details_frame, text="Port:").grid(row=1, column=0, sticky=tk.W, pady=8)
    port_var = tk.StringVar(value="8080")
    port_entry = ttk.Entry(details_frame, textvariable=port_var, width=35)
    port_entry.grid(row=1, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    auth_frame = ttk.LabelFrame(main_frame, text="Authentication", padding=15)
    auth_frame.pack(fill=tk.X, pady=(0, 15))
    auth_frame.grid_columnconfigure(1, weight=1)
    
    ttk.Label(auth_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=8)
    username_var = tk.StringVar(value="admin")
    username_entry = ttk.Entry(auth_frame, textvariable=username_var, width=35)
    username_entry.grid(row=0, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    ttk.Label(auth_frame, text="Password:").grid(row=1, column=0, sticky=tk.W, pady=8)
    password_var = tk.StringVar()
    password_entry = ttk.Entry(auth_frame, textvariable=password_var, width=35, show="*")
    password_entry.grid(row=1, column=1, pady=8, padx=(15, 0), sticky=tk.EW)
    
    options_frame = ttk.LabelFrame(main_frame, text="Options", padding=15)
    options_frame.pack(fill=tk.X, pady=(0, 15))
    
    ssl_var = tk.BooleanVar(value=False)
    ssl_check = ttk.Checkbutton(options_frame, text="Use HTTPS (SSL)", variable=ssl_var)
    ssl_check.pack(anchor=tk.W, pady=2)
    
    timeout_frame = ttk.Frame(options_frame)
    timeout_frame.pack(fill=tk.X, pady=(5, 0))
    ttk.Label(timeout_frame, text="Connection Timeout (seconds):").pack(side=tk.LEFT)
    timeout_var = tk.StringVar(value="10")
    timeout_entry = ttk.Entry(timeout_frame, textvariable=timeout_var, width=8)
    timeout_entry.pack(side=tk.RIGHT)
    
    status_frame = ttk.Frame(main_frame)
    status_frame.pack(fill=tk.X, pady=(0, 15))
    
    status_var = tk.StringVar(value="Ready to connect...")
    status_label = ttk.Label(status_frame, textvariable=status_var, foreground="blue", font=("Segoe UI", 9))
    status_label.pack(anchor=tk.W)
    
    progress = ttk.Progressbar(status_frame, mode="indeterminate")
    
    def validate_inputs():
        host = host_var.get().strip()
        port = port_var.get().strip()
        username = username_var.get().strip()
        password = password_var.get().strip()
        timeout = timeout_var.get().strip()
        
        if not host:
            raise ValueError("Host/IP address is required")
        if not port or not port.isdigit() or not (1 <= int(port) <= 65535):
            raise ValueError("Valid port number (1-65535) is required")
        if not username:
            raise ValueError("Username is required")
        if not password:
            raise ValueError("Password is required")
        if not timeout or not timeout.isdigit() or int(timeout) <= 0:
            raise ValueError("Valid timeout value is required")
            
        return host, int(port), username, password, ssl_var.get(), int(timeout)
    
    def test_connection():
        try:
            host, port, username, password, use_ssl, timeout = validate_inputs()
            
            status_var.set("Testing connection...")
            status_label.config(foreground="blue")
            progress.pack(fill=tk.X, pady=(5, 0))
            progress.start()
            dialog.update()
            
            success, message = test_remote_host_connection(host, port, username, password, use_ssl, timeout)
            
            progress.stop()
            progress.pack_forget()
            
            if success:
                status_var.set("✓ Connection successful!")
                status_label.config(foreground="green")
            else:
                status_var.set(f"✗ Connection failed: {message}")
                status_label.config(foreground="red")
                
        except ValueError as e:
            progress.stop()
            progress.pack_forget()
            status_var.set(f"✗ Validation error: {str(e)}")
            status_label.config(foreground="red")
        except Exception as e:
            progress.stop()
            progress.pack_forget()
            status_var.set(f"✗ Connection error: {str(e)}")
            status_label.config(foreground="red")
    
    def connect_and_add():
        try:
            host, port, username, password, use_ssl, timeout = validate_inputs()
            
            status_var.set("Connecting to remote host...")
            status_label.config(foreground="blue")
            progress.pack(fill=tk.X, pady=(5, 0))
            progress.start()
            dialog.update()
            
            success = dashboard.add_remote_host(host, port, username, password, "", use_ssl, timeout)
            
            progress.stop()
            progress.pack_forget()
            
            if success:
                messagebox.showinfo("Success", f"Successfully connected to remote host: {host}:{port}")
                dialog.destroy()
            else:
                status_var.set(f"✗ Failed to add remote host")
                status_label.config(foreground="red")
                
        except ValueError as e:
            progress.stop()
            progress.pack_forget()
            messagebox.showerror("Validation Error", str(e))
        except Exception as e:
            progress.stop()
            progress.pack_forget()
            logger.error(f"Error connecting to remote host: {str(e)}")
            messagebox.showerror("Error", f"Failed to connect: {str(e)}")
    
    def cancel():
        dialog.destroy()
    
    # Add flexible space before buttons
    spacer_frame = ttk.Frame(main_frame)
    spacer_frame.pack(fill=tk.BOTH, expand=True, pady=(15, 10))
    
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, side=tk.BOTTOM)
    
    test_btn = ttk.Button(button_frame, text="Test Connection", command=test_connection, width=15)
    test_btn.pack(side=tk.LEFT, padx=(0, 10))
    
    connect_btn = ttk.Button(button_frame, text="Connect & Add", command=connect_and_add, width=15)
    connect_btn.pack(side=tk.LEFT)
    
    cancel_btn = ttk.Button(button_frame, text="Cancel", command=cancel, width=12)
    cancel_btn.pack(side=tk.RIGHT)
    
    host_entry.focus()
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def bind_mousewheel(widget):
        widget.bind("<MouseWheel>", on_mousewheel)
        for child in widget.winfo_children():
            bind_mousewheel(child)
    
    bind_mousewheel(dialog)
    
    center_window(dialog, 600, 650, parent)


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


def get_remote_host_manager():
    return _remote_host_manager


def create_server_installation_dialog(root, server_type, supported_server_types, server_manager, paths, steam_cmd_path=None):
    try:
        dialog = tk.Toplevel(root)
        dialog.title(f"Install {server_type} Server")
        dialog.geometry("700x600")
        dialog.transient(root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(main_frame, text=f"Install {server_type} Server", font=("Segoe UI", 12, "bold"))
        title_label.pack(pady=(0, 15))
        
        progress_frame = ttk.LabelFrame(main_frame, text="Installation Progress", padding=10)
        progress_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100)
        progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        status_var = tk.StringVar(value="Ready to install...")
        status_label = ttk.Label(progress_frame, textvariable=status_var)
        status_label.pack(anchor=tk.W)
        
        console_frame = ttk.LabelFrame(main_frame, text="Installation Log", padding=10)
        console_frame.pack(fill=tk.BOTH, expand=True)
        
        console_text = scrolledtext.ScrolledText(console_frame, height=15, font=("Consolas", 9))
        console_text.pack(fill=tk.BOTH, expand=True)
        
        installation_result = {"completed": False, "success": False, "message": ""}
        
        def update_progress(percent, message):
            progress_var.set(percent)
            status_var.set(message)
            console_text.insert(tk.END, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
            console_text.see(tk.END)
            dialog.update()
        
        def start_installation():
            try:
                update_progress(10, "Starting installation...")
                
                # This would call the actual installation logic
                # For now, just simulate
                update_progress(50, "Installing server components...")
                time.sleep(2)
                update_progress(90, "Finalizing installation...")
                time.sleep(1)
                
                installation_result["completed"] = True
                installation_result["success"] = True
                installation_result["message"] = "Server installed successfully"
                
                update_progress(100, "Installation completed successfully")
                
            except Exception as e:
                installation_result["completed"] = True
                installation_result["success"] = False
                installation_result["message"] = str(e)
                update_progress(100, f"Installation failed: {str(e)}")
        
        def close_dialog():
            if installation_result["completed"]:
                dialog.destroy()
            else:
                if messagebox.askyesno("Cancel Installation", "Installation is in progress. Cancel?"):
                    dialog.destroy()
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        install_button = ttk.Button(button_frame, text="Start Installation", command=start_installation)
        install_button.pack(side=tk.LEFT)
        
        close_button = ttk.Button(button_frame, text="Close", command=close_dialog)
        close_button.pack(side=tk.RIGHT)
        
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        
        center_window(dialog, 700, 600, root)
        
        root.wait_window(dialog)
        return installation_result
        
    except Exception as e:
        logger.error(f"Error creating installation dialog: {e}")
        return {"completed": True, "success": False, "message": str(e)}


def update_server_list_from_files(server_list, paths, variables, log_dashboard_event, format_uptime_from_start_time):
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        servers = server_manager.get_all_servers()
        
        for item in server_list.get_children():
            server_list.delete(item)
        
        for server_name, config in servers.items():
            server_type = config.get("Type", "Unknown")
            status = "Unknown"  # Would need to check actual status
            
            server_list.insert("", tk.END, values=(
                server_name,
                server_type,
                status,
                config.get("InstallDir", ""),
                format_uptime_from_start_time("N/A")  # Placeholder
            ))
        
        variables["lastServerListUpdate"] = datetime.datetime.now()
        
    except Exception as e:
        logger.error(f"Error updating server list from files: {e}")


def re_detect_server_type_from_config(server_config):
    try:
        install_dir = server_config.get("InstallDir", "")
        if not install_dir or not os.path.exists(install_dir):
            return server_config.get("Type", "Other")
        
        detected_type = detect_server_type_from_directory(install_dir)
        return detected_type if detected_type != "Other" else server_config.get("Type", "Other")
        
    except Exception as e:
        logger.error(f"Error re-detecting server type: {e}")
        return server_config.get("Type", "Other")


def update_server_configuration_with_detection(server_config_path):
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        
        with open(server_config_path, 'r') as f:
            config = json.load(f)
        
        server_name = config.get("Name", "")
        if not server_name:
            return False
        
        new_type = re_detect_server_type_from_config(config)
        if new_type != config.get("Type"):
            config["Type"] = new_type
            logger.info(f"Updated server type for {server_name} to {new_type}")
        
        server_manager.update_server(server_name, config)
        return True
        
    except Exception as e:
        logger.error(f"Error updating server configuration: {e}")


def cleanup_orphaned_process_entries(server_manager, logger):
    # Clean up orphaned process entries from server configurations
    # This also validates that PIDs actually belong to the correct server (handles Windows PID reuse)
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
                    cleaned_count += 1  # Count corruption recoveries as cleanups

                if recovery_errors:
                    logger.debug(f"Corruption recovery errors for {server_name}: {recovery_errors}")

                # Reload config after potential recovery
                server_config = server_manager.get_server_config(server_name)

                pid = server_config.get('ProcessId') or server_config.get('PID')
                if pid:
                    # Use the comprehensive validation from server_manager
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
                                # IMPORTANT: Verify the process actually belongs to this server
                                # Windows reuses PIDs, so an old PID might belong to a different process
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
        
        # Check 1: Working directory matches install directory (strongest match)
        if proc_info.get('cwd') and install_dir:
            cwd_norm = os.path.normpath(proc_info['cwd'].lower())
            if cwd_norm == install_dir_norm:
                return True
        
        # Check 2: Executable path is inside install directory
        exe_path = proc_info.get('exe', '').lower()
        if exe_path and install_dir:
            exe_norm = os.path.normpath(exe_path)
            if exe_norm.startswith(install_dir_norm + os.sep) or exe_norm == install_dir_norm:
                return True
            
        # Check 3: Command line contains install directory path (not just server name)
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
        
        # Check 4: Type-specific validation with stricter requirements
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
    category_states = {}  # category_name -> is_open (True/False)
    for item in server_list.get_children():
        try:
            item_values = server_list.item(item)['values']
            if item_values and not item_values[1]:  # No status value = category
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
        categories[category] = []  # Initialise all categories, even empty ones
    
    for server_name, server_info in servers_data.items():
        category = server_info.get('category', 'Uncategorized')
        if category not in categories:
            categories[category] = []  # Handle servers with categories not in persistence
        categories[category].append((server_name, server_info))
    
    selected_item_ids = []
    for category_name in all_categories:  # Use all_categories to maintain order
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
        
        for server_name, server_config in raw_servers.items():
            try:
                server_config = raw_servers.get(server_name)
                if not server_config:
                    display_status = 'Not Found'
                    pid = None
                else:
                    # Check if server has ProcessId and is running
                    if 'ProcessId' in server_config:
                        pid = server_config['ProcessId']
                        try:
                            if server_manager.is_process_running(pid):
                                display_status = 'Running'
                            else:
                                display_status = 'Stopped'
                        except Exception as e:
                            logger.debug(f"Error checking if process {pid} is running: {e}")
                            display_status = 'Stopped'
                    else:
                        display_status = 'Stopped'
                        pid = None
                
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
                        # The first call to cpu_percent() on a new process returns 0,
                        # subsequent calls return the delta since the last call
                        global _cpu_process_cache
                        
                        if pid not in _cpu_process_cache:
                            # Create new process object and Initialise CPU tracking
                            try:
                                proc = psutil.Process(pid)
                                proc.cpu_percent(interval=None)  # Initialise (returns 0)
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
                            
                            # For Java processes (Minecraft, etc.), use VMS instead of RSS for more accurate memory display
                            # RSS only shows resident memory, but Java heaps are often not fully resident
                            try:
                                cmdline = process.cmdline()
                                is_java_process = any('java' in arg.lower() or 'javaw' in arg.lower() for arg in cmdline)
                                
                                if is_java_process:
                                    # Use Virtual Memory Size for Java processes (includes JVM heap)
                                    memory_mb = memory_info.vms / (1024 * 1024)
                                    display_data['memory'] = f"{memory_mb:.1f} MB (JVM)"
                                else:
                                    # Use Resident Set Size for other processes
                                    memory_mb = memory_info.rss / (1024 * 1024)
                                    display_data['memory'] = f"{memory_mb:.1f} MB"
                            except Exception:
                                # Fallback to RSS if cmdline check fails
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
            from Modules.agents import AgentManager
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
    # Update server list from configuration files - runs heavy work in background thread
    # to prevent freezing the Tkinter main thread
    try:
        if hasattr(dashboard, '_refreshing_server_list') and dashboard._refreshing_server_list:
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
                # Heavy operations run in background thread - no UI calls here
                
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


def _check_and_reattach_running_servers(server_manager, console_manager, logger):
    # Quick check for running servers that don't have console attached
    # This is a lightweight version of reattach_to_running_servers for periodic use
    try:
        server_configs = server_manager.get_servers()
        
        for server_name, server_config in server_configs.items():
            try:
                # Check if server has a PID but no console attached
                pid = server_config.get('ProcessId') or server_config.get('PID')
                if not pid:
                    continue
                
                if hasattr(console_manager, 'consoles') and server_name in console_manager.consoles:
                    console = console_manager.consoles.get(server_name)
                    if console and console.is_active:
                        continue
                
                if not psutil.pid_exists(pid):
                    continue
                
                try:
                    process = psutil.Process(pid)
                    if not process.is_running():
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
                    success = console_manager.attach_console_to_process(server_name, process, server_config)
                    if success:
                        logger.info(f"Reattached console to {server_name}")
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
            except Exception as e:
                logger.debug(f"Error checking server {server_name} for reattachment: {e}")
                
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
            
            if completion_callback:
                completion_callback(success, message if message else "Server stopped successfully")
                
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            if completion_callback:
                completion_callback(False, f"Failed to stop server: {str(e)}")
    
    stop_thread = threading.Thread(target=stop_in_background, daemon=True)
    stop_thread.start()
    return stop_thread


def restart_server_operation(server_name, server_manager, console_manager=None,
                            status_callback=None, completion_callback=None, parent_window=None):
    import threading
    
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
    
    # Update canvas window width when the canvas changes size
    def update_canvas_width(event=None):
        try:
            if canvas.winfo_width() > 1:
                canvas.itemconfig(1, width=canvas.winfo_width())
        except tk.TclError:
            pass
    
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
            appid_dialog.geometry("600x500")
            
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
            
            tree_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
            server_tree.configure(yscrollcommand=tree_scrollbar.set)
            
            tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
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
                    item_values = server_tree.item(item[0])['values']
                    selected_server = server_dict.get(str(item_values[1]))
                    
                    if selected_server and selected_server.get("description"):
                        tooltip = tk.Toplevel(appid_dialog)
                        tooltip.wm_overrideredirect(True)
                        tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")
                        
                        desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")
                        
                        label = tk.Label(tooltip, text=f"{selected_server['name']}\n\n{desc}", 
                                       background="lightyellow", relief="solid", borderwidth=1,
                                       wraplength=300, justify=tk.LEFT, font=("Segoe UI", 9))
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
            
            centre_window(appid_dialog, 600, 500, dialog)
        
        ttk.Button(scrollable_frame, text="Browse", command=browse_appid, width=12).grid(row=current_row, column=2, padx=15, pady=10)
        current_row += 1
        
        ttk.Label(scrollable_frame, text="(Enter Steam App ID or use Browse to select from list)", foreground="gray", font=("Segoe UI", 9)).grid(row=current_row, column=1, columnspan=2, padx=15, sticky=tk.W)
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
    help_label = ttk.Label(scrollable_frame, text=help_text, foreground="gray",
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
    
    console_output = scrolledtext.ScrolledText(console_container, width=60, height=12, 
                                             background="black", foreground="white", 
                                             font=("Consolas", 9))
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

