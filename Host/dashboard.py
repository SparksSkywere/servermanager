# -*- coding: utf-8 -*-
# Main dashboard GUI - Tkinter-based server management interface
import os
import sys
from typing import Optional, Any

# Early crash logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.core.common import setup_module_path
setup_module_path()
from Modules.core.server_logging import early_crash_log

early_crash_log("Dashboard", f"Module loading - Python {sys.version}")

# Prevents scaling issues with UI elements
if sys.platform == 'win32':
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            early_crash_log("Dashboard", "DPI awareness set to PROCESS_SYSTEM_DPI_AWARE")
        except AttributeError:
            ctypes.windll.user32.SetProcessDPIAware()
            early_crash_log("Dashboard", "DPI awareness set using SetProcessDPIAware")
        except Exception as e:
            early_crash_log("Dashboard", f"DPI awareness failed: {e}")
    except Exception as e:
        early_crash_log("Dashboard", f"DPI setup failed: {e}")

try:
    import argparse
    import threading
    import time
    import datetime

    import tkinter as tk
    from tkinter import messagebox, ttk
    early_crash_log("Dashboard", "Standard library imports successful")

    from Modules.Database.user_database import initialise_user_manager
    early_crash_log("Dashboard", "User database import successful")

    from Modules.server.server_manager import ServerManager
    early_crash_log("Dashboard", "Server management imports successful")

    from Modules.core.server_logging import (
        get_dashboard_logger, configure_dashboard_logging,
        log_dashboard_event
    )
    early_crash_log("Dashboard", "All imports successful")

except Exception as e:
    import traceback
    early_crash_log("Dashboard", f"FATAL IMPORT ERROR: {e}")
    early_crash_log("Dashboard", f"Traceback: {traceback.format_exc()}")
    raise

# Import scheduling components
from Modules.services.scheduler import SchedulerManager

# Import update management
from Modules.updates.server_updates import ServerUpdateManager

# Import core infrastructure
from Modules.core.common import ServerManagerModule, initialise_registry_values
from Modules.ui.theme import get_theme_preference, apply_theme as apply_shared_theme
from Modules.ui.color_palettes import get_palette
from Modules.Database.cluster_database import get_cluster_database

# Import UI components
from Host.dashboard_ui import setup_ui, setup_menu_bar, expand_all_categories, collapse_all_categories, show_server_context_menu, on_server_list_click, on_server_double_click

# Dashboard utility functions
from Host.dashboard_functions import (
    load_dashboard_config, update_system_info_threaded, centre_window,
    load_appid_scanner_list, load_minecraft_scanner_list, load_minecraft_modded_scanner_list,
    get_current_server_list, get_current_subhost, reattach_to_running_servers,
    update_server_list_for_subhost, refresh_all_subhost_servers,
    refresh_current_subhost_servers, refresh_subhost_servers,
    add_server_dialog, init_temperature_service, stop_temperature_service
)

# Import cluster management
from Modules.ui.agents import AgentManager, show_agent_management_dialog

# Import mixin modules for dashboard functionality
from Host.dashboard_server_config import ServerConfigMixin
from Host.dashboard_server_ops import ServerOpsMixin
from Host.dashboard_dialogs import DashboardDialogsMixin
from Host.dashboard_settings import DashboardSettingsMixin

# Import console management
from Modules.server.server_console import ConsoleManager

# Import authentication
from Host.admin_dashboard import admin_login_with_root

import logging

# Get dashboard logger
logger: logging.Logger = get_dashboard_logger()

class ServerManagerDashboard(ServerConfigMixin, ServerOpsMixin, DashboardDialogsMixin, DashboardSettingsMixin, ServerManagerModule):
    def __init__(self, debug_mode=False):
        super().__init__("ServerManagerDashboard")

        self.steam_cmd_path = None
        self.servers = []
        self.debug_mode = debug_mode
        self.user_manager = None
        self.current_user = None
        self.install_process = None
        self._refreshing_server_list = False

        # Initialize UI-related attributes (created in setup_ui)
        self.loading_frame: Optional[Any] = None
        self.server_lists: dict = {}
        self.main_pane: Optional[Any] = None
        self.system_frame: Optional[Any] = None
        self.system_toggle_btn: Optional[Any] = None
        self.webserver_status: Optional[Any] = None
        self.metric_labels: dict = {}
        self.metric_frames: dict = {}
        self.system_name: Optional[Any] = None
        self.os_info: Optional[Any] = None
        self.system_uptime_label: Optional[Any] = None
        self.loading_status_label: Optional[Any] = None
        self.loading_progress: Optional[Any] = None
        self.loading_percentage_label: Optional[Any] = None

        # Additional UI attributes
        self.top_frame: Optional[Any] = None
        self.add_server_btn: Optional[Any] = None
        self.start_server_btn: Optional[Any] = None
        self.stop_server_btn: Optional[Any] = None
        self.import_server_btn: Optional[Any] = None
        self.update_all_button: Optional[Any] = None
        self.schedules_button: Optional[Any] = None
        self.console_button: Optional[Any] = None
        self.cluster_button: Optional[Any] = None
        self.automation_button: Optional[Any] = None
        self.container_frame: Optional[Any] = None
        self.servers_frame: Optional[Any] = None
        self.tab_nav_frame: Optional[Any] = None
        self.left_arrow: Optional[Any] = None
        self.right_arrow: Optional[Any] = None
        self.category_frame: Optional[Any] = None
        self.expand_all_btn: Optional[Any] = None
        self.collapse_all_btn: Optional[Any] = None
        self.server_notebook: Optional[Any] = None
        self.tab_frames: dict = {}
        self.server_context_menu: Optional[Any] = None
        self.system_info_visible: Optional[bool] = None
        self.collapse_frame: Optional[Any] = None
        self.system_header: Optional[Any] = None
        self.system_title_row: Optional[Any] = None
        self.webserver_frame: Optional[Any] = None
        self.offline_check: Optional[Any] = None
        self.metrics_frame: Optional[Any] = None
        self.menubar: Optional[Any] = None

        # Load dashboard configuration from JSON file (use inherited config from base class)
        dashboard_config = load_dashboard_config(self.server_manager_dir)

        # Update the base config with dashboard-specific settings
        self._config_manager.config.update(dashboard_config)

        # Load AppID/server info from database (not JSON)
        self.dedicated_servers, self.appid_metadata = load_appid_scanner_list(self.server_manager_dir)

        # Load Minecraft server info from database
        self.minecraft_servers, self.minecraft_metadata = load_minecraft_scanner_list(self.server_manager_dir)

        # Load modded pack info from database (ATLauncher, FTB, Technic, CurseForge)
        self.modded_packs, self.modded_metadata = load_minecraft_modded_scanner_list(self.server_manager_dir)

        # Initialise runtime variables from config
        try:
            main_config = get_cluster_database().get_main_config()
        except Exception as e:
            logger.debug(f"Failed loading main_config for temperature settings: {e}")
            main_config = {}

        self.variables = {
            "previousNetworkStats": {},
            "previousNetworkTime": datetime.datetime.now(),
            "lastServerListUpdate": datetime.datetime.min,
            "lastFullUpdate": datetime.datetime.min,
            "networkAdapters": [],
            "lastNetworkStats": {},
            "lastNetworkStatsTime": datetime.datetime.now(),
            "systemInfo": {},
            "diskInfo": [],
            "gpuInfo": None,
            "lastProcessUpdate": datetime.datetime.min,
            "processStatHistory": {},
            "failedProcessRestarts": {},
            # Load configuration values
            "debugMode": self.config.get("configuration", {}).get("debugMode", False),
            "systemRefreshInterval": self.config.get("configuration", {}).get("systemRefreshInterval", 4),
            "processMonitoringInterval": self.config.get("configuration", {}).get("processMonitoringInterval", 5),
            "maxProcessHistoryPoints": self.config.get("configuration", {}).get("maxProcessHistoryPoints", 20),
            "networkUpdateInterval": self.config.get("configuration", {}).get("networkUpdateInterval", 5),
            "serverListUpdateInterval": self.config.get("configuration", {}).get("serverListUpdateInterval", 45),
            "systemInfoUpdateInterval": self.config.get("configuration", {}).get("systemInfoUpdateInterval", 10),
            "processMonitorUpdateInterval": self.config.get("configuration", {}).get("processMonitorUpdateInterval", 15),
            "webserverStatusUpdateInterval": self.config.get("configuration", {}).get("webserverStatusUpdateInterval", 30),
            "updateCheckInterval": self.config.get("configuration", {}).get("updateCheckInterval", 300),
            # Temperature collection settings (stored in DB main_config)
            "temperatureMode": main_config.get("temperatureMode", self.config.get("temperature", {}).get("mode", "auto")),
            "temperaturePollInterval": main_config.get("temperaturePollInterval", self.config.get("temperature", {}).get("pollInterval", 10)),
            "iloHost": main_config.get("iloHost", self.config.get("temperature", {}).get("iloHost", "")),
            "iloUsername": main_config.get("iloUsername", self.config.get("temperature", {}).get("iloUsername", "")),
            "iloPassword": main_config.get("iloPassword", self.config.get("temperature", {}).get("iloPassword", "")),
            "iloVerifyTLS": main_config.get("iloVerifyTLS", self.config.get("temperature", {}).get("iloVerifyTLS", False)),
            "iloTimeout": main_config.get("iloTimeout", self.config.get("temperature", {}).get("iloTimeout", 4)),
            "idracHost": main_config.get("idracHost", self.config.get("temperature", {}).get("idracHost", "")),
            "idracUsername": main_config.get("idracUsername", self.config.get("temperature", {}).get("idracUsername", "")),
            "idracPassword": main_config.get("idracPassword", self.config.get("temperature", {}).get("idracPassword", "")),
            "idracVerifyTLS": main_config.get("idracVerifyTLS", self.config.get("temperature", {}).get("idracVerifyTLS", False)),
            "idracTimeout": main_config.get("idracTimeout", self.config.get("temperature", {}).get("idracTimeout", 4)),
            # UI state
            "systemInfoVisible": self.config.get("ui", {}).get("systemInfoVisible", True),
            # Runtime vars
            "formDisplayed": self.config.get("runtime", {}).get("formDisplayed", False),
            "verificationInProgress": self.config.get("runtime", {}).get("verificationInProgress", False),
            "webserverStatus": self.config.get("runtime", {}).get("webserverStatus", "Disconnected"),
        }

        # Init paths from registry
        success, self.steam_cmd_path, webserver_port, self.registry_values = initialise_registry_values(self.registry_path)
        if success:
            self.variables["defaultSteamPath"] = self.steam_cmd_path or ""
            self.variables["webserverPort"] = webserver_port
            if self.steam_cmd_path:
                self.variables["defaultSteamInstallDir"] = self.steam_cmd_path
            else:
                self.variables["defaultSteamInstallDir"] = ""
            if self.server_manager_dir:
                self.variables["defaultServerManagerInstallDir"] = os.path.join(self.server_manager_dir, "servers")
            else:
                self.variables["defaultServerManagerInstallDir"] = ""
        else:
            logger.error("Registry init failed")
            sys.exit(1)

        # Start dedicated temperature collection service during boot.
        try:
            init_temperature_service(self.variables)
        except Exception as e:
            logger.debug(f"Could not initialise temperature service at boot: {e}")

        # Initialise user management system
        try:
            engine, self.user_manager = initialise_user_manager()
        except Exception as e:
            logger.error(f"Failed to initialise user management: {e}")
            messagebox.showerror("Database Error", f"Failed to connect to user database:\n{str(e)}")
            sys.exit(1)

        # Initialise server manager
        try:
            self.server_manager = ServerManager()
            logger.debug("Server manager initialised")
        except Exception as e:
            logger.error(f"Failed to initialise server manager: {e}")
            # Continue without server manager but show warning
            self.server_manager = None
            messagebox.showwarning("Server Manager Warning",
                                 f"Server manager failed to initialise:\n{str(e)}\n\n"
                                 "Some server operations may not be available.")

        # Initialise server console manager
        try:
            self.console_manager = ConsoleManager(self.server_manager)
            logger.debug("Server console manager initialised")
        except Exception as e:
            logger.error(f"Failed to initialise server console manager: {e}")
            self.console_manager = None

        # Configure dashboard logging after paths are initialised
        configure_dashboard_logging(self.debug_mode, self.config)

        # Create root window (temporarily hidden for login)
        self.root = tk.Tk()
        self.root.resizable(True, True)

        # Calculate DPI scaling factor for proper UI sizing
        self._init_dpi_scaling()

        # Apply global ttk style padding to reduce clipped button/text issues on high-DPI displays.
        try:
            style = ttk.Style(self.root)
            style.configure("TButton", padding=(10, 6))
            style.configure("TCombobox", padding=(6, 4))
            style.configure("Treeview", rowheight=max(24, int(self.scale_value(24))))
        except Exception as e:
            logger.debug(f"Could not apply global ttk style adjustments: {e}")

        # Apply saved dashboard theme before UI construction.
        try:
            self.apply_theme(self.get_saved_theme())
        except Exception as e:
            logger.debug(f"Could not apply saved theme: {e}")

        # On Windows, when launched from trayicon (detached process), ensure proper window handling
        if os.name == 'nt' and '--debug' not in sys.argv:
            try:
                # Force the window to be properly initialised
                self.root.update_idletasks()
                # Don't withdraw initially - let the login dialog handle visibility
            except Exception as e:
                logger.warning(f"Window initialisation issue (likely from trayicon launch): {e}")
                # Continue anyway
        # Pass our existing root window to avoid multiple Tkinter root windows
        try:
            # Use the version that accepts existing root to avoid conflicts
            user = admin_login_with_root(self.root, self.user_manager)

            if not user:
                logger.info("Login cancelled or failed, exiting application")
                self.root.destroy()
                sys.exit(0)
            self.current_user = user
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            messagebox.showerror("Login Error", f"Failed to authenticate: {str(e)}\n\nThe application will exit.")
            self.root.destroy()
            sys.exit(1)

        # Now configure the UI with user information
        username = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
        self.root.title(f"Server Manager Dashboard (Logged in as: {username})")

        # Set dynamic minimum size based on screen size and DPI scaling
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Calculate DPI-aware minimum sizes
        base_min_width = self.scale_value(800)
        base_min_height = self.scale_value(600)

        min_width = min(base_min_width, int(screen_width * 0.6))
        min_height = min(base_min_height, int(screen_height * 0.6))
        self.root.minsize(min_width, min_height)

        # Ensure the main window is properly visible
        self.root.deiconify()
        logger.debug("Dashboard window deiconified")

        # Bring window to front and give it focus
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))
        logger.debug("Dashboard window brought to front")

        # Centre the main window on screen with adaptive sizing
        width = max(min_width, int(screen_width * 0.85))
        height = max(min_height, int(screen_height * 0.85))
        # Cap at 90% to leave some space for taskbar/other UI elements
        width = min(width, int(screen_width * 0.9))
        height = min(height, int(screen_height * 0.9))
        centre_window(self.root, width, height)
        logger.debug("Dashboard window centered")

        setup_ui(self)

        # Re-apply theme now that all widgets exist – force=True ensures the
        # walker runs even though current_theme is already set (the Text/Canvas
        # widgets inside the system panel were just created and need styling).
        try:
            self.apply_theme(getattr(self, "current_theme", self.get_saved_theme()), force=True)
        except Exception as e:
            logger.debug(f"Could not re-apply theme after UI setup: {e}")

        # Lift loading overlay to ensure it's on top after all UI is created
        if hasattr(self, 'loading_frame'):
            self.loading_frame.lift() # type: ignore

        # Write PID file
        self.write_pid_file("dashboard", os.getpid())

        # Initialise timer manager (now using SchedulerManager)
        self.timer_manager = SchedulerManager(self)

        # Set agent manager for database syncing
        if hasattr(self, 'agent_manager') and self.agent_manager:
            self.timer_manager.set_agent_manager(self.agent_manager)

        # Initialise server update manager
        try:
            self.update_manager = ServerUpdateManager(self.server_manager_dir, self.config)
            self.update_manager.set_server_manager(self.server_manager)
            self.update_manager.set_steam_cmd_path(self.steam_cmd_path)
            self.timer_manager.set_update_manager(self.update_manager)
            logger.debug("Server update manager initialised")
        except Exception as e:
            logger.error(f"Failed to initialise server update manager: {str(e)}")
            self.update_manager = None

        # Initialise cluster manager
        try:
            # Use database-backed cluster management (no longer using JSON)
            agents_config_path = None
            self.agent_manager = AgentManager(agents_config_path)
            logger.debug("Cluster manager initialised")
        except Exception as e:
            logger.error(f"Failed to initialise cluster manager: {str(e)}")
            self.agent_manager = None

        # Get supported server types from server manager
        if self.server_manager:
            self.supported_server_types = self.server_manager.get_supported_server_types()
        else:
            self.supported_server_types = ["Steam", "Minecraft", "Other"]

    def _init_dpi_scaling(self):
        # Initialise DPI scaling factors for proper UI sizing across different displays
        try:
            # Get DPI from the root window
            dpi = self.root.winfo_fpixels('1i')

            # Standard DPI is 96 on Windows
            self.dpi_scale = dpi / 96.0

            # Clamp scaling factor to reasonable range (avoid extreme values)
            self.dpi_scale = max(1.0, min(self.dpi_scale, 3.0))

            logger.debug(f"DPI scaling initialised: DPI={dpi}, scale_factor={self.dpi_scale:.2f}")
        except Exception as e:
            logger.warning(f"Could not calculate DPI scaling: {e}")
            self.dpi_scale = 1.0

    def scale_value(self, value):
        # Scale a value according to the current DPI scaling factor
        return int(value * getattr(self, 'dpi_scale', 1.0))

    def get_saved_theme(self) -> str:
        # Load persisted theme preference from shared theme module.
        try:
            return get_theme_preference("light")
        except Exception as e:
            logger.debug(f"Failed loading saved theme preference: {e}")
            return "light"

    def apply_theme(self, theme_name: str, force: bool = False):
        # Apply shared style and store current selection.
        if not hasattr(self, 'root') or self.root is None:
            return

        normalised = str(theme_name or "").strip().lower()
        if not force and getattr(self, "current_theme", None) == normalised:
            return

        applied = apply_shared_theme(self.root, theme_name, getattr(self, 'dpi_scale', 1.0))
        self.current_theme = applied

        # Rebuild themed custom menu strip after palette changes.
        try:
            setup_menu_bar(self)
        except Exception as e:
            logger.debug(f"Could not refresh custom menu strip: {e}")

        # tk.Text widgets (CPU/Memory/Disk/Temperature panels)
        try:
            self._retheme_metric_text_widgets()
            self.root.after(150, self._retheme_metric_text_widgets)
            self.root.after(350, self._retheme_metric_text_widgets)
        except Exception:
            pass

    def _retheme_metric_text_widgets(self):
        # Explicitly recolour tk.Text metric widgets and their plain tk.Frame
        try:
            from Modules.ui.color_palettes import get_palette
            palette = get_palette(getattr(self, "current_theme", "light"))
            text_bg = palette.get("text_bg")
            text_fg = palette.get("text_fg")
            border = palette.get("border")
            bg = palette.get("bg")
            canvas_bg = palette.get("canvas_bg")

            # Re-style each metric panel LabelFrame, its plain-Frame containers,
            # and the Text/Canvas widgets inside them.
            for name, frame in getattr(self, "metric_frames", {}).items():
                try:
                    if not frame.winfo_exists():
                        continue
                    frame.configure(style="TLabelframe")
                    for child in frame.winfo_children():
                        try:
                            if not child.winfo_exists():
                                continue
                            klass = str(child.winfo_class())
                            # Plain tk.Frame containers (disk_container/network_container)
                            if klass == "Frame":
                                child.configure(bg=bg)
                                # Also re-theme grandchildren (Text, Canvas inside)
                                for grandchild in child.winfo_children():
                                    try:
                                        if not grandchild.winfo_exists():
                                            continue
                                        gklass = str(grandchild.winfo_class())
                                        if gklass == "Text":
                                            grandchild.configure(
                                                bg=text_bg, fg=text_fg,
                                                insertbackground=text_fg,
                                                highlightbackground=border,
                                                highlightcolor=border,
                                            )
                                        elif gklass == "Canvas":
                                            grandchild.configure(bg=canvas_bg)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                except Exception:
                    pass

            # Also directly re-style metric_labels entries (belt + suspenders).
            for widget in getattr(self, "metric_labels", {}).values():
                try:
                    if isinstance(widget, dict):
                        canvas = widget.get("canvas")
                        if canvas is not None and canvas.winfo_exists():
                            canvas.configure(bg=canvas_bg)
                        continue
                    if not widget.winfo_exists():
                        continue
                    if str(widget.winfo_class()) == "Text":
                        widget.configure(
                            bg=text_bg, fg=text_fg,
                            insertbackground=text_fg,
                            highlightbackground=border,
                            highlightcolor=border,
                        )
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"_retheme_metric_text_widgets error: {e}")

    def expand_all_categories(self):
        # Expand all categories in the current server list
        expand_all_categories(self)

    def collapse_all_categories(self):
        # Collapse all categories in the current server list
        collapse_all_categories(self)

    def get_current_server_list(self):
        # Get the server list for the currently active tab
        return get_current_server_list(self)

    def get_current_subhost(self):
        # Get the name of the currently active subhost
        return get_current_subhost(self)

    def update_server_list_for_subhost(self, subhost_name, servers_data):
        # Update the server list for a specific subhost
        update_server_list_for_subhost(subhost_name, servers_data, self.server_lists, self.server_manager_dir, logger)

    def refresh_all_subhost_servers(self):
        # Refresh servers for all subhost tabs
        refresh_all_subhost_servers(self.server_lists, self.server_manager, self.server_manager_dir, logger)

    def refresh_current_subhost_servers(self):
        # Refresh servers for the currently active subhost tab
        refresh_current_subhost_servers(self.get_current_subhost, self.server_manager, self.server_lists, self.server_manager_dir, logger)

    def refresh_subhost_servers(self, subhost_name):
        # Refresh servers for a specific subhost
        refresh_subhost_servers(subhost_name, self.server_manager, self.server_lists, self.server_manager_dir, logger)

    def show_server_context_menu(self, event):
        # Show context menu on right-click in server list
        show_server_context_menu(self, event)

    def on_server_list_click(self, event):
        # Handle left-click on server list - deselect all if clicking on empty space
        on_server_list_click(self, event)

    def on_server_double_click(self, event):
        # Handle double-click on server list - open configuration dialog
        on_server_double_click(self, event)

    def _move_server_to_category(self, server_name, new_category):
        # Move a server to a new category by updating its configuration
        try:
            # Get server config from database/memory
            if not self.server_manager:
                logger.error("Server manager not available")
                return

            server_config = self.server_manager.get_server_config(server_name)
            if not server_config:
                logger.error(f"Server config not found: {server_name}")
                return

            server_config['Category'] = new_category

            # Save to database
            self.server_manager.update_server(server_name, server_config)

            # Update in-memory cache
            self.server_manager.reload_server(server_name)

            logger.info(f"Updated category for server '{server_name}' to '{new_category}'")

        except Exception as e:
            logger.error(f"Error updating server category: {str(e)}")
            raise

    def add_server(self):
        # Add a new game server (Steam, Minecraft, or Other)
        add_server_dialog(self)

    def update_server_list(self, force_refresh=False):
        # Update server list from configuration files
        from Host.dashboard_functions import update_server_list_logic
        update_server_list_logic(self, force_refresh)

    def _hide_loading_overlay(self):
        # Hide the loading overlay
        try:
            if hasattr(self, 'loading_frame') and self.loading_frame.winfo_exists():  # type: ignore
                self.loading_frame.destroy()  # type: ignore
            logger.debug("Loading overlay hidden")
        except Exception as e:
            logger.debug(f"Error hiding loading overlay: {e}")

    def toggle_system_info(self):
        # Toggle visibility of the system information panel
        self.system_info_visible = not self.system_info_visible

        if self.system_info_visible:
            # Show the system info panel - add back to pane
            pane_weight = int(getattr(self, 'system_pane_weight', 0))
            self.main_pane.add(self.system_frame, weight=pane_weight)  # type: ignore
            self.system_toggle_btn.config(text="◀")  # type: ignore
            # Restore fixed-pixel sash after the panel is rendered
            if callable(getattr(self, '_update_main_pane_sash', None)):
                self.root.after(50, self._update_main_pane_sash)  # type: ignore
        else:
            # Hide the system info panel - remove from pane
            self.main_pane.forget(self.system_frame)  # type: ignore
            self.system_toggle_btn.config(text="▶")  # type: ignore

        # Save state to database
        self.variables["systemInfoVisible"] = self.system_info_visible
        try:
            from Modules.Database.cluster_database import get_cluster_database
            db = get_cluster_database()
            db.set_dashboard_config("ui.systemInfoVisible", self.system_info_visible, "boolean", "ui")
            logger.debug(f"System info visibility saved: {self.system_info_visible}")
        except Exception as e:
            logger.error(f"Error saving system info visibility state: {e}")

    def scroll_tabs_left(self):
        # Scroll tabs to the left
        from Host.dashboard_ui import scroll_tabs_left
        scroll_tabs_left(self)

    def scroll_tabs_right(self):
        # Scroll tabs to the right
        from Host.dashboard_ui import scroll_tabs_right
        scroll_tabs_right(self)

    def update_webserver_status(self):
        # Update the web server status display - non-blocking
        import threading

        def _check_status():
            try:
                from Host.dashboard_functions import check_webserver_status
                status = check_webserver_status(self.paths, self.variables)

                def _apply_status():
                    try:
                        if self.webserver_status is None:
                            return
                        palette = get_palette(getattr(self, "current_theme", self.get_saved_theme()))
                        self.webserver_status.config(text=status)
                        if status == "Running":
                            self.webserver_status.config(foreground=palette.get("success_fg"))
                        elif status == "Stopped":
                            self.webserver_status.config(foreground=palette.get("error_fg"))
                        else:
                            self.webserver_status.config(foreground=palette.get("text_disabled_fg"))
                    except Exception as e:
                        logger.error(f"Error applying webserver status to UI: {e}")

                self.root.after(0, _apply_status)
            except Exception as e:
                logger.error(f"Error checking webserver status: {e}")

        thread = threading.Thread(target=_check_status, daemon=True, name="WebserverStatusCheck")
        thread.start()

    def update_system_info(self):
        # Update system information using background threading to prevent UI freezing
        def _update():
            try:
                # Update web server status (this is lightweight)
                self.update_webserver_status()

                # Use the threaded version from dashboard_functions for heavy system monitoring
                update_system_info_threaded(
                    self.metric_labels,
                    self.system_name,
                    self.os_info,
                    self.system_uptime_label,
                    temperature_settings=self.variables,
                )

            except Exception as e:
                logger.error(f"Error in update_system_info: {str(e)}")

        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)

    def periodic_server_list_refresh(self):
        # Periodic refresh of server list to clean up orphaned processes and update status
        try:
            # Only refresh if not already refreshing
            if not hasattr(self, '_refreshing_server_list') or not self._refreshing_server_list:
                # update_server_list handles its own background threading
                self.update_server_list(force_refresh=True)
            else:
                log_dashboard_event("PERIODIC_REFRESH", "Skipping periodic refresh - update already in progress", "DEBUG")
        except Exception as e:
            logger.error(f"Error in periodic server list refresh: {str(e)}")

    def run(self):
        # Run the dashboard application
        logger.info("Starting dashboard run method")

        # Install Tkinter exception handler to catch unhandled exceptions
        def tkinter_exception_handler(exc_type, exc_value, exc_traceback):
            logger.error("Unhandled exception in Tkinter", exc_info=(exc_type, exc_value, exc_traceback))
            try:
                messagebox.showerror("Dashboard Error", f"An unexpected error occurred:\n{exc_value}")
            except Exception:
                pass
            # Keep the dashboard alive for recoverable callback exceptions.
            # Closing the whole app here causes console/UI callback races to look like crashes.
            return

        # Override Tkinter's exception handling for this root instance.
        self.root.report_callback_exception = tkinter_exception_handler

        try:
            # Show the window first
            logger.info("Setting up window protocol and showing window")
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.variables["formDisplayed"] = True

            # Keep loading overlay visible during initial load
            # Update loading status text
            if hasattr(self, 'loading_status_label'):
                try:
                    self.loading_status_label.config(text="Loading servers...")  # type: ignore
                except tk.TclError:
                    pass

            # Schedule background initialization without blocking UI
            def background_init_thread():
                # Import once at the start
                from Host.dashboard_functions import get_servers_display_data, update_server_list_for_subhost

                try:
                    logger.info("Starting background initialisation")

                    # Update loading status and progress
                    def update_loading_status(text, progress_value):
                        try:
                            if hasattr(self, 'loading_status_label') and self.loading_status_label.winfo_exists():  # type: ignore
                                self.loading_status_label.config(text=text)  # type: ignore
                            if hasattr(self, 'loading_progress') and self.loading_progress.winfo_exists():  # type: ignore
                                self.loading_progress['value'] = progress_value  # type: ignore
                            if hasattr(self, 'loading_percentage_label') and self.loading_percentage_label.winfo_exists():  # type: ignore
                                self.loading_percentage_label.config(text=f"{progress_value}%")  # type: ignore
                        except tk.TclError:
                            pass

                    # System info (lightweight, UI update only)
                    self.root.after(0, lambda: update_loading_status("Loading system info...", 10))
                    try:
                        logger.debug("Running system info update...")
                        if hasattr(self, 'update_system_info') and callable(self.update_system_info):
                            self.root.after(0, lambda: self._safe_call(self.update_system_info))
                    except Exception as e:
                        logger.error(f"Error in system info init: {str(e)}")

                    logger.debug("Init step 1 complete - system info")

                    # Server list update - do heavy work HERE in background thread
                    self.root.after(0, lambda: update_loading_status("Loading server list...", 15))
                    time.sleep(0.1)
                    try:
                        logger.debug("Init step 2 - server list update...")
                        # Get server data in background thread (heavy psutil operations)
                        if self.server_manager:
                            self.root.after(0, lambda: update_loading_status("Scanning server processes...", 20))
                            servers_data = get_servers_display_data(self.server_manager, logger)
                            logger.debug(f"Got server data for {len(servers_data)} servers")
                            # Only the UI update goes on main thread
                            def update_ui():
                                try:
                                    update_server_list_for_subhost("Local Host", servers_data, self.server_lists, self.server_manager_dir, logger)
                                except Exception as e:
                                    logger.error(f"Error updating server list UI: {str(e)}")
                            self.root.after(0, update_ui)
                    except Exception as e:
                        logger.error(f"Error in server list init: {str(e)}")

                    logger.debug("Init step 2 complete - server list")

                    # Only do quick PID-based reattachment
                    self.root.after(0, lambda: update_loading_status("Detecting running servers...", 40))
                    time.sleep(0.1)
                    try:
                        logger.debug("Init step 3 - quick reattach to running servers...")
                        # This runs entirely in background thread - no root.after for the heavy work
                        if self.server_manager and self.console_manager:
                            # Only do the quick PID-based check, skip heavy process discovery
                            self.root.after(0, lambda: update_loading_status("Cleaning up orphaned processes...", 50))
                            from Host.dashboard_functions import cleanup_orphaned_process_entries, cleanup_orphaned_relay_files
                            cleanup_orphaned_process_entries(self.server_manager, logger)
                            cleanup_orphaned_relay_files(logger)
                            # Run on the next periodic refresh
                        logger.debug("Init step 3 complete - quick reattach")
                    except Exception as e:
                        logger.error(f"Error in reattach init: {str(e)}")

                    # Final server list refresh to show updated statuses
                    self.root.after(0, lambda: update_loading_status("Finalising...", 80))
                    time.sleep(0.1)
                    try:
                        logger.debug("Init step 4 - final refresh...")
                        if self.server_manager:
                            servers_data = get_servers_display_data(self.server_manager, logger)
                            def final_update_ui():
                                try:
                                    update_server_list_for_subhost("Local Host", servers_data, self.server_lists, self.server_manager_dir, logger)
                                except Exception as e:
                                    logger.error(f"Error in final server list UI update: {str(e)}")
                            self.root.after(0, final_update_ui)
                    except Exception as e:
                        logger.error(f"Error in final refresh: {str(e)}")

                    # Start timers for periodic updates (after initial load is complete)
                    def start_timers():
                        try:
                            if hasattr(self, 'timer_manager') and self.timer_manager:
                                self.timer_manager.start_timers()
                                logger.debug("Timer manager started")
                        except Exception as e:
                            logger.error(f"Error starting timers: {str(e)}")
                    self.root.after(500, start_timers)

                    # Deferred full reattach to running servers (runs after UI is responsive)
                    def deferred_full_reattach():
                        try:
                            logger.debug("Starting deferred full reattach to running servers...")
                            if self.server_manager and self.console_manager:
                                reattach_to_running_servers(self.server_manager, self.console_manager, logger)
                                logger.debug("Deferred full reattach completed")
                        except Exception as e:
                            logger.error(f"Error in deferred reattach: {str(e)}")
                    # Run full reattach after a short delay so it doesn't block UI
                    self.root.after(2000, lambda: threading.Thread(target=deferred_full_reattach, daemon=True).start())

                    # Complete
                    self.root.after(0, lambda: update_loading_status("Complete!", 100))

                    # Hide loading overlay after everything is done
                    time.sleep(0.2)
                    self.root.after(0, self._hide_loading_overlay)

                    logger.info("Background initialisation completed")
                except Exception as e:
                    logger.error(f"Error in background init thread: {str(e)}")
                    # Still hide overlay on error
                    self.root.after(0, self._hide_loading_overlay)

            # Start background init in a daemon thread so it doesn't block
            init_thread = threading.Thread(target=background_init_thread, daemon=True, name="BackgroundInit")
            init_thread.start()

            # Ensure window is visible before starting mainloop
            self.root.update()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            logger.info("Window visibility ensured before mainloop")

            # Start main loop immediately - UI is responsive right away
            logger.info("Starting Tkinter mainloop")
            try:
                self.root.mainloop()
            except KeyboardInterrupt:
                logger.info("Mainloop interrupted by keyboard (Ctrl+C)")
                raise
            except Exception as e:
                logger.error(f"Exception in mainloop: {str(e)}")
                logger.error(f"Exception type: {type(e).__name__}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise
            finally:
                logger.info("Tkinter mainloop exited - checking why")
                # Check if window still exists
                try:
                    if self.root and hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
                        logger.info("Window still exists when mainloop exited")
                    else:
                        logger.info("Window was destroyed when mainloop exited")
                except tk.TclError:
                    logger.info("Window was destroyed when mainloop exited (TclError)")
                except Exception as e:
                    logger.info(f"Could not check window state: {str(e)}")
        except Exception as e:
            # Check if this is the expected "application has been destroyed" error
            error_msg = str(e)
            if "application has been destroyed" in error_msg:
                logger.info("Dashboard closed normally (window destroyed)")
                self.on_close()
            else:
                logger.error(f"Error starting dashboard: {error_msg}")
                # Try to show error and exit gracefully
                try:
                    messagebox.showerror("Dashboard Error", f"Failed to start dashboard: {error_msg}")
                except tk.TclError:
                    pass
                self.on_close()

    def on_close(self):
        # Handle window close event
        logger.info("Dashboard on_close() called - window is being closed")

        # Check if window already destroyed
        try:
            if not self.root or not self.root.winfo_exists():
                logger.debug("Window already destroyed, skipping cleanup")
                return
        except tk.TclError:
            logger.debug("TclError checking window - already destroyed")
            return

        # Clean up resources
        try:
            # Save all console states first for crash recovery
            if hasattr(self, 'console_manager') and self.console_manager:
                self.console_manager.save_all_console_states()
                logger.debug("Saved all console states")

            # Close all console windows
            if hasattr(self, 'console_manager') and self.console_manager:
                self.console_manager.cleanup_all_consoles()
                logger.debug("Closed all console windows")

            # Cluster management cleanup (no specific cleanup needed)
            if hasattr(self, 'agent_manager') and self.agent_manager:
                logger.debug("Cluster manager cleanup completed")

            # Remove PID file
            self.remove_pid_file("dashboard")

            # Close any open processes
            if hasattr(self, 'install_process') and self.install_process:
                try:
                    self.install_process.terminate()
                    logger.debug("Terminated installation process")
                except (OSError, ProcessLookupError):
                    pass

            # Stop background temperature service.
            stop_temperature_service()
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

        # Close the window (only if it still exists)
        try:
            if self.root and self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass

    def _safe_call(self, func, *args, **kwargs):
        # Safely call a function with error handling
        try:
            if callable(func):
                return func(*args, **kwargs)
            else:
                logger.warning(f"Function {func} is not callable")
        except Exception as e:
            logger.error(f"Error in safe_call for {func}: {str(e)}")
            import traceback
            logger.debug(f"Safe call traceback: {traceback.format_exc()}")

    def add_agent(self):
        try:
            if self.agent_manager is None:
                logger.error("Cluster manager not initialised")
                messagebox.showerror("Error", "Cluster manager not initialised. Cannot access cluster management.")
                return

            # Show the cluster management dialog
            show_agent_management_dialog(self.root, self.agent_manager)

        except Exception as e:
            logger.error(f"Error in cluster management: {str(e)}")
            messagebox.showerror("Error", f"Failed to open cluster management: {str(e)}")
    def show_schedule_manager(self):
        # Show unified schedule manager
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()

    def show_server_schedule(self):
        # Show schedule manager for the selected server
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        self.timer_manager.show_schedules_manager()

def is_dashboard_already_running():
    # Check if another dashboard instance is already running using a lock file with PID
    import tempfile
    import psutil

    lock_file = os.path.join(tempfile.gettempdir(), 'servermanager_dashboard.lock')
    current_pid = os.getpid()

    try:
        # Check if lock file exists
        if os.path.exists(lock_file):
            try:
                with open(lock_file, 'r', encoding='utf-8') as f:
                    stored_pid = int(f.read().strip())

                # Check if the stored PID is still running and is a dashboard process
                if psutil.pid_exists(stored_pid) and stored_pid != current_pid:
                    try:
                        proc = psutil.Process(stored_pid)
                        proc_name = proc.name().lower()
                        cmdline = ' '.join(proc.cmdline()).lower()

                        # Check if it's actually a dashboard process
                        if 'python' in proc_name or 'pythonw' in proc_name:
                            if 'dashboard' in cmdline:
                                # Another dashboard is running
                                return True, stored_pid
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass

                # PID doesn't exist or isn't dashboard - stale lock file
            except (ValueError, IOError):
                pass

        # Write our PID to the lock file
        with open(lock_file, 'w', encoding='utf-8') as f:
            f.write(str(current_pid))

        return False, None

    except Exception as e:
        early_crash_log("Dashboard", f"Single-instance check failed: {e}")
        return False, None

def cleanup_dashboard_lock():
    # Clean up the lock file when dashboard exits
    import tempfile

    lock_file = os.path.join(tempfile.gettempdir(), 'servermanager_dashboard.lock')
    try:
        if os.path.exists(lock_file):
            with open(lock_file, 'r', encoding='utf-8') as f:
                stored_pid = int(f.read().strip())

            # Only remove if it's our lock file
            if stored_pid == os.getpid():
                os.remove(lock_file)
    except Exception:
        pass

def bring_existing_dashboard_to_front(pid):
    # Try to bring the existing dashboard window to the front (Windows only)
    if sys.platform != 'win32':
        return False

    try:
        import ctypes
        from ctypes import wintypes

        # Windows API functions
        user32 = ctypes.windll.user32

        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        SetForegroundWindow = user32.SetForegroundWindow
        ShowWindow = user32.ShowWindow
        IsWindowVisible = user32.IsWindowVisible

        SW_RESTORE = 9
        target_hwnd = None

        def enum_callback(hwnd, lparam):
            nonlocal target_hwnd
            window_pid = wintypes.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))

            if window_pid.value == pid and IsWindowVisible(hwnd):
                target_hwnd = hwnd
                return False
            return True

        EnumWindows(EnumWindowsProc(enum_callback), 0)

        if target_hwnd:
            ShowWindow(target_hwnd, SW_RESTORE)
            SetForegroundWindow(target_hwnd)
            return True

    except Exception as e:
        early_crash_log("Dashboard", f"Could not bring existing window to front: {e}")

    return False

def main():
    import traceback as tb
    import atexit
    from Modules.core.server_logging import early_crash_log

    early_crash_log("Dashboard", "Startup initiated")

    # Check for existing dashboard instance
    already_running, existing_pid = is_dashboard_already_running()
    if already_running:
        early_crash_log("Dashboard", f"Another dashboard instance is already running (PID: {existing_pid})")

        # Try to bring the existing window to front
        brought_to_front = bring_existing_dashboard_to_front(existing_pid)

        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()

            if brought_to_front:
                messagebox.showinfo("Dashboard Already Running",
                                   f"The Server Manager Dashboard is already running.\n\n"
                                   f"The existing window has been brought to the front.")
            else:
                messagebox.showwarning("Dashboard Already Running",
                                      f"The Server Manager Dashboard is already running (PID: {existing_pid}).\n\n"
                                      f"Please use the existing instance.")
            root.destroy()
        except Exception:
            pass

        return

    # Register cleanup on exit
    atexit.register(cleanup_dashboard_lock)

    try:
        parser = argparse.ArgumentParser(description='Server Manager Dashboard')
        parser.add_argument('--debug', action='store_true', help='Enable debug logging')
        args = parser.parse_args()

        dashboard = ServerManagerDashboard(debug_mode=args.debug)
        early_crash_log("Dashboard", "Started successfully")

        dashboard.run()
        early_crash_log("Dashboard", "Closed normally")

    except Exception as e:
        early_crash_log("Dashboard", f"FATAL ERROR: {e}")
        early_crash_log("Dashboard", f"Traceback: {tb.format_exc()}")

        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Dashboard Startup Error", f"Failed to start dashboard:\n\n{e}\n\nCheck logs/components/Dashboard.log for details.")
            root.destroy()
        except Exception:
            pass

        raise
    finally:
        # Ensure lock is cleaned up
        cleanup_dashboard_lock()

main()