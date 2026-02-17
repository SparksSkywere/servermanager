# -*- coding: utf-8 -*-
# Main dashboard GUI - Tkinter-based server management interface
import os
import sys
from typing import Optional, Any

# Early crash logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()
from Modules.server_logging import early_crash_log

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
    from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
    early_crash_log("Dashboard", "Standard library imports successful")

    from Modules.Database.user_database import initialize_user_manager
    early_crash_log("Dashboard", "User database import successful")

    from Modules.server_manager import ServerManager
    from Modules.minecraft import MinecraftServerManager
    early_crash_log("Dashboard", "Server management imports successful")

    from Modules.server_logging import (
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
from Modules.scheduler import SchedulerManager

# Import update management
from Modules.server_updates import ServerUpdateManager

# Import documentation dialogs
from Modules.documentation import show_help_dialog, show_about_dialog

# Import core infrastructure
from Modules.common import ServerManagerModule, initialise_registry_values

# Import UI components
from Host.dashboard_ui import setup_ui, expand_all_categories, collapse_all_categories, show_server_context_menu, on_server_list_click, on_server_double_click

# Dashboard utility functions
from Host.dashboard_functions import (
    load_dashboard_config, update_webserver_status, update_system_info_threaded, centre_window,
    load_appid_scanner_list, load_minecraft_scanner_list,
    import_server_from_directory_dialog, import_server_from_export_dialog,
    export_server_dialog, create_progress_dialog_with_console, rename_server_configuration, show_java_configuration_dialog, batch_update_server_types,
    update_server_status_in_treeview, open_directory_in_explorer, get_current_server_list, get_current_subhost, reattach_to_running_servers,
    update_server_list_for_subhost, refresh_all_subhost_servers,
    refresh_current_subhost_servers, refresh_subhost_servers,
    load_categories, start_server_operation,
    stop_server_operation, restart_server_operation, add_server_dialog
)

# Import cluster management
from Modules.agents import AgentManager, show_agent_management_dialog

# Import debugging utilities
from debug.debug import (
    get_server_process_details, log_exception, monitor_process_resources
)

# Import console management
from Modules.server_console import ConsoleManager

# Import authentication
from Host.admin_dashboard import admin_login_with_root

import logging

# Get dashboard logger
logger: logging.Logger = get_dashboard_logger()


# =============================================================================
# MAIN DASHBOARD CLASS
# =============================================================================

class ServerManagerDashboard(ServerManagerModule):
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
        self.offline_var: Optional[Any] = None
        self.main_pane: Optional[Any] = None
        self.system_frame: Optional[Any] = None
        self.system_toggle_btn: Optional[Any] = None
        self.webserver_status: Optional[Any] = None
        self.metric_labels: dict = {}
        self.system_name: Optional[Any] = None
        self.os_info: Optional[Any] = None
        self.loading_status_label: Optional[Any] = None
        self.loading_progress: Optional[Any] = None
        self.loading_percentage_label: Optional[Any] = None
        
        # Additional UI attributes
        self.top_frame: Optional[Any] = None
        self.add_server_btn: Optional[Any] = None
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

        # Initialise runtime variables from config
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
            "offlineMode": self.config.get("configuration", {}).get("offlineMode", False),
            "systemRefreshInterval": self.config.get("configuration", {}).get("systemRefreshInterval", 4),
            "processMonitoringInterval": self.config.get("configuration", {}).get("processMonitoringInterval", 5),
            "maxProcessHistoryPoints": self.config.get("configuration", {}).get("maxProcessHistoryPoints", 20),
            "networkUpdateInterval": self.config.get("configuration", {}).get("networkUpdateInterval", 5),
            "serverListUpdateInterval": self.config.get("configuration", {}).get("serverListUpdateInterval", 45),
            "systemInfoUpdateInterval": self.config.get("configuration", {}).get("systemInfoUpdateInterval", 10),
            "processMonitorUpdateInterval": self.config.get("configuration", {}).get("processMonitorUpdateInterval", 15),
            "webserverStatusUpdateInterval": self.config.get("configuration", {}).get("webserverStatusUpdateInterval", 30),
            "updateCheckInterval": self.config.get("configuration", {}).get("updateCheckInterval", 300),
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
        
        # Initialise user management system
        try:
            engine, self.user_manager = initialize_user_manager()
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
        
        min_width = min(base_min_width, int(screen_width * 0.6))  # Max 60% of screen width
        min_height = min(base_min_height, int(screen_height * 0.6))  # Max 60% of screen height
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
        # Use 85% of screen on large screens, but ensure minimum usable size
        width = max(min_width, int(screen_width * 0.85))
        height = max(min_height, int(screen_height * 0.85))
        # Cap at 90% to leave some space for taskbar/other UI elements
        width = min(width, int(screen_width * 0.9))
        height = min(height, int(screen_height * 0.9))
        centre_window(self.root, width, height)
        logger.debug("Dashboard window centered")
        
        setup_ui(self)
        
        # Lift loading overlay to ensure it's on top after all UI is created
        if hasattr(self, 'loading_frame'):
            self.loading_frame.lift()  # type: ignore
        
        # NOTE: Initial server list refresh is now deferred to run() method
        # to avoid blocking during window creation
        
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
            agents_config_path = None  # Migration already done
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
            dpi = self.root.winfo_fpixels('1i')  # Pixels per inch
            
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
    
    def _reattach_to_running_servers(self):
        # Detect and reattach to running server processes
        reattach_to_running_servers(self.server_manager, self.console_manager, logger)

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
        # Update server list from configuration files - thread-safe
        def _update():
            from Host.dashboard_functions import update_server_list_logic
            update_server_list_logic(self, force_refresh)
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def toggle_offline_mode(self):
        # Toggle offline mode
        # Toggle offline mode
        self.variables["offlineMode"] = self.offline_var.get()  # type: ignore
        self.update_webserver_status()
        logger.info(f"Offline mode set to {self.variables['offlineMode']}")
    
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
            self.main_pane.add(self.system_frame, weight=30)  # type: ignore
            self.system_toggle_btn.config(text="◀")  # type: ignore
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
        # Update the web server status display - thread-safe
        def _update():
            try:
                # Use the imported function from dashboard_functions
                update_webserver_status(self.webserver_status, self.offline_var, self.paths, self.variables)
            except Exception as e:
                logger.error(f"Error in update_webserver_status: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def update_system_info(self):
        # Update system information using background threading to prevent UI freezing
        def _update():
            try:
                # Update web server status (this is lightweight)
                self.update_webserver_status()

                # Use the threaded version from dashboard_functions for heavy system monitoring
                update_system_info_threaded(self.metric_labels, self.system_name, self.os_info)

            except Exception as e:
                logger.error(f"Error in update_system_info: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def periodic_server_list_refresh(self):
        # Periodic refresh of server list to clean up orphaned processes and update status
        def _refresh():
            try:
                # Only refresh if not already refreshing and enough time has passed
                if not hasattr(self, '_refreshing_server_list') or not self._refreshing_server_list:
                    # Use the main update method which now has its own protection
                    self.update_server_list(force_refresh=True)
                else:
                    log_dashboard_event("PERIODIC_REFRESH", "Skipping periodic refresh - update already in progress", "DEBUG")
            except Exception as e:
                logger.error(f"Error in periodic server list refresh: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _refresh()
        else:
            self.root.after(0, _refresh)
    
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
            self.on_close()
        
        # Override Tkinter's exception handling
        import tkinter
        tkinter.Tk.report_callback_exception = tkinter_exception_handler

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
                # This runs entirely in a background thread - heavy operations stay here
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
                    
                    # Step 1: System info (lightweight, UI update only) - 10%
                    self.root.after(0, lambda: update_loading_status("Loading system info...", 10))
                    try:
                        logger.debug("Running system info update...")
                        if hasattr(self, 'update_system_info') and callable(self.update_system_info):
                            self.root.after(0, lambda: self._safe_call(self.update_system_info))
                    except Exception as e:
                        logger.error(f"Error in system info init: {str(e)}")
                    
                    logger.debug("Init step 1 complete - system info")
                    
                    # Step 2: Server list update - do heavy work HERE in background thread - 30%
                    self.root.after(0, lambda: update_loading_status("Loading server list...", 15))
                    time.sleep(0.1)  # Allow UI to update
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
                    
                    # Step 3: Reattach to running servers - heavy operations in background - 60%
                    # Skip full process discovery during startup to avoid hanging
                    # Only do quick PID-based reattachment
                    self.root.after(0, lambda: update_loading_status("Detecting running servers...", 40))
                    time.sleep(0.1)  # Allow UI to update
                    try:
                        logger.debug("Init step 3 - quick reattach to running servers...")
                        # This runs entirely in background thread - no root.after for the heavy work
                        if self.server_manager and self.console_manager:
                            # Only do the quick PID-based check, skip heavy process discovery
                            self.root.after(0, lambda: update_loading_status("Cleaning up orphaned processes...", 50))
                            from Host.dashboard_functions import cleanup_orphaned_process_entries, cleanup_orphaned_relay_files
                            cleanup_orphaned_process_entries(self.server_manager, logger)
                            cleanup_orphaned_relay_files(logger)
                            # Full reattach_to_running_servers is too slow for startup
                            # It will run on the next periodic refresh
                        logger.debug("Init step 3 complete - quick reattach")
                    except Exception as e:
                        logger.error(f"Error in reattach init: {str(e)}")
                    
                    # Step 4: Final server list refresh to show updated statuses - 80%
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
                    
                    # Step 5: Start timers for periodic updates (after initial load is complete) - 90%
                    def start_timers():
                        try:
                            if hasattr(self, 'timer_manager') and self.timer_manager:
                                self.timer_manager.start_timers()
                                logger.debug("Timer manager started")
                        except Exception as e:
                            logger.error(f"Error starting timers: {str(e)}")
                    self.root.after(500, start_timers)  # Delay timer start by 500ms
                    
                    # Step 6: Deferred full reattach to running servers (runs after UI is responsive) - 95%
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
                    
                    # Complete - 100%
                    self.root.after(0, lambda: update_loading_status("Complete!", 100))
                    
                    # Hide loading overlay after everything is done
                    time.sleep(0.2)  # Brief delay to let UI updates complete
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
                    pass  # Messagebox might fail if Tkinter is in bad state
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
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

        # Close the window (only if it still exists)
        try:
            if self.root and self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass  # Window already destroyed
    
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
        
        def on_completion(success, message):
            # Update UI on main thread
            def update_ui():
                if not success:
                    messagebox.showerror("Error", message)
                # Always refresh the server list to show current status
                self.update_server_list(force_refresh=True)
            
            self.root.after(0, update_ui)
        
        # Show starting message
        self.update_server_status(server_name, "Starting...")

        # Use shared server operation function
        start_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=on_completion
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
            
        # Confirm server stop
        confirm = messagebox.askyesno("Confirm Stop", 
                                    f"Are you sure you want to stop the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        
        if not confirm:
            return
        
        def on_completion(success, message):
            # Update UI on main thread
            def update_ui():
                if not success:
                    messagebox.showinfo("Info", message)
                # Always refresh the server list to show current status
                self.update_server_list(force_refresh=True)
            
            self.root.after(0, update_ui)
        
        # Show stopping message
        self.update_server_status(server_name, "Stopping...")

        # Use shared server operation function
        stop_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=on_completion
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
        
        # Confirm restart
        confirm = messagebox.askyesno("Confirm Restart", 
                                    f"Are you sure you want to restart the server '{server_name}'?",
                                    icon=messagebox.WARNING)
        
        if not confirm:
            return
        
        def on_completion(success, message):
            # Update UI on main thread
            def update_ui():
                if not success:
                    messagebox.showerror("Error", message)
                # Always refresh the server list to show current status
                self.update_server_list(force_refresh=True)
            
            self.root.after(0, update_ui)
        
        # Show restarting message
        self.update_server_status(server_name, "Restarting...")

        # Use shared server operation function
        restart_server_operation(
            server_name=server_name,
            server_manager=self.server_manager,
            console_manager=self.console_manager,
            status_callback=lambda status: self.update_server_status(server_name, status),
            completion_callback=on_completion
        )
    
    def view_process_details(self):
        # View detailed process information for a server using debug module
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
            # Get server process details from debug module
            process_details = get_server_process_details(server_name)
            
            if "error" in process_details:
                messagebox.showerror("Error", process_details["error"])
                return
            
            # Create detail dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Process Details: {server_name} (PID: {process_details['pid']})")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Create a frame with padding
            main_frame = ttk.Frame(dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Create notebook for organised tabs
            notebook = ttk.Notebook(main_frame)
            notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            
            # Basic Info Tab
            basic_frame = ttk.Frame(notebook)
            notebook.add(basic_frame, text="Basic Info")
            
            # Basic information grid
            info_grid = ttk.Frame(basic_frame)
            info_grid.pack(fill=tk.X, padx=10, pady=10)
            
            # Display basic process information
            info_items = [
                ("PID:", str(process_details["pid"])),
                ("Status:", process_details["status"]),
                ("Name:", process_details["name"]),
                ("Server Uptime:", process_details.get("server_uptime", "Unknown")),
                ("CPU Usage:", f"{process_details['cpu_percent']:.1f}%"),
                ("Memory Usage:", f"{process_details['memory_info']['rss'] / (1024 * 1024):.1f} MB"),
                ("Memory %:", f"{process_details['memory_percent']:.1f}%"),
                ("Threads:", str(process_details["num_threads"]))
            ]
            
            for i, (label, value) in enumerate(info_items):
                row = i // 2
                col = (i % 2) * 2
                ttk.Label(info_grid, text=label, width=15).grid(row=row, column=col, sticky=tk.W, padx=5, pady=2)
                ttk.Label(info_grid, text=value).grid(row=row, column=col+1, sticky=tk.W, padx=5, pady=2)
            
            # Executable path (full width)
            if "exe" in process_details and process_details["exe"] != "Access Denied":
                ttk.Label(info_grid, text="Executable:").grid(row=len(info_items)//2 + 1, column=0, sticky=tk.W, padx=5, pady=2)
                exe_label = ttk.Label(info_grid, text=process_details["exe"])
                exe_label.grid(row=len(info_items)//2 + 1, column=1, columnspan=3, sticky=tk.W, padx=5, pady=2)
            
            # Resources Tab
            resources_frame = ttk.Frame(notebook)
            notebook.add(resources_frame, text="Resources")
            
            # Resource details
            resource_text = scrolledtext.ScrolledText(resources_frame, width=80, height=20)
            resource_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            resource_info = f"""Memory Information:
RSS (Resident Set Size): {process_details['memory_info']['rss'] / (1024 * 1024):.2f} MB
VMS (Virtual Memory Size): {process_details['memory_info']['vms'] / (1024 * 1024):.2f} MB
Memory Percentage: {process_details['memory_percent']:.2f}%

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
                
                # Create child processes list
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
                
                # Add scrollbar
                child_scroll = ttk.Scrollbar(children_frame, orient=tk.VERTICAL, command=child_list.yview)
                child_list.configure(yscrollcommand=child_scroll.set)
                
                child_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                child_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                # Populate child list
                for child in process_details["children"]:
                    child_list.insert("", tk.END, values=(
                        child["pid"],
                        child["name"],
                        child["status"],
                        f"{child['cpu_percent']:.1f}",
                        f"{child['memory_mb']:.1f}"
                    ))
            
            # Network Tab
            if process_details.get("connections"):
                network_frame = ttk.Frame(notebook)
                notebook.add(network_frame, text="Network")
                
                # Create network connections list
                conn_list = ttk.Treeview(network_frame, columns=("family", "type", "local", "remote", "status"), show="headings")
                conn_list.heading("family", text="Family")
                conn_list.heading("type", text="Type")
                conn_list.heading("local", text="Local Address")
                conn_list.heading("remote", text="Remote Address")
                conn_list.heading("status", text="Status")
                
                # Add scrollbar
                conn_scroll = ttk.Scrollbar(network_frame, orient=tk.VERTICAL, command=conn_list.yview)
                conn_list.configure(yscrollcommand=conn_scroll.set)
                
                conn_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                conn_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                # Populate connections list
                for conn in process_details["connections"]:
                    conn_list.insert("", tk.END, values=(
                        conn["family"],
                        conn["type"],
                        conn["local_address"],
                        conn["remote_address"],
                        conn["status"]
                    ))
            
            # Log Files Tab
            server_config = process_details.get("server_config", {})
            if server_config.get("LogStdout") or server_config.get("LogStderr"):
                logs_frame = ttk.Frame(notebook)
                notebook.add(logs_frame, text="Log Files")
                
                log_grid = ttk.Frame(logs_frame)
                log_grid.pack(fill=tk.X, padx=10, pady=10)
                
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
            
            # Refresh button
            def refresh_process_info():
                dialog.destroy()
                self.view_process_details()
            
            ttk.Button(button_frame, text="Refresh", command=refresh_process_info, width=15).pack(side=tk.LEFT, padx=(0, 10))
            
            # Monitor button - shows resource monitoring
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
            
            # Stop process button
            def stop_from_details():
                dialog.destroy()
                self.stop_server()
            
            ttk.Button(button_frame, text="Stop Process", command=stop_from_details, width=15).pack(side=tk.RIGHT, padx=(0, 10))
            
            # Close button
            ttk.Button(button_frame, text="Close", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=(0, 10))
            
            # Centre dialog relative to parent
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
        current_subhost = self.get_current_subhost()
        
        try:
            if not self.console_manager:
                messagebox.showerror("Console Error", "Console manager not available.")
                return
            
            # Get server config from server manager
            server_config = None
            if self.server_manager:
                try:
                    server_config = self.server_manager.get_server_config(server_name)
                except Exception as e:
                    logger.warning(f"Could not get server config for {server_name}: {e}")
            
            # If we can't get config from server manager, create a basic one
            if not server_config:
                server_values = current_list.item(selected_items[0])['values']
                server_config = {
                    'name': server_name,
                    'type': 'Unknown',
                    'pid': server_values[2] if len(server_values) > 2 else None
                }
            
            # Show the console window
            success = self.console_manager.show_console(server_name)
            
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
                    # Force UI update
                    self.root.update_idletasks()
            except Exception as e:
                logger.error(f"Error updating server status: {str(e)}")
        
        # Ensure this runs on the main thread
        if threading.current_thread() == threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)
    
    def _create_scrollable_dialog(self, parent, title, width_ratio=0.9, height_ratio=0.8):
        """Create a scrollable dialog with standard setup"""
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog_width = min(900, int(parent.winfo_screenwidth() * width_ratio))
        dialog_height = min(850, int(parent.winfo_screenheight() * height_ratio))
        dialog.geometry(f"{dialog_width}x{dialog_height}")

        # Create main frame with padding
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create scrollable frame for all content
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack scrollbar first, then canvas
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Update canvas window width when the canvas changes size
        def update_canvas_width(event=None):
            try:
                if canvas.winfo_width() > 1:  # Only update if canvas has a valid width
                    canvas.itemconfig(1, width=canvas.winfo_width())  # Item ID 1 is the scrollable_frame
            except tk.TclError:
                pass

        canvas.bind("<Configure>", update_canvas_width)

        # Configure scrollable_frame columns
        scrollable_frame.columnconfigure(0, weight=1, minsize=200)
        scrollable_frame.columnconfigure(1, weight=1, minsize=200)
        scrollable_frame.columnconfigure(2, weight=1, minsize=200)
        scrollable_frame.columnconfigure(3, weight=1, minsize=200)

        return dialog, scrollable_frame

    def _create_labeled_entry(self, parent, label_text, variable, row, column=0, width=30):
        """Create a labeled entry field"""
        ttk.Label(parent, text=f"{label_text}:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=column, padx=10, pady=5, sticky=tk.W)
        entry = ttk.Entry(parent, textvariable=variable, width=width, font=("Segoe UI", 10))
        entry.grid(row=row, column=column+1, padx=10, pady=5, sticky=tk.EW)
        return entry

    def _create_labeled_combo(self, parent, label_text, variable, values, row, column=0, width=27):
        """Create a labeled combobox"""
        ttk.Label(parent, text=f"{label_text}:", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=column, padx=10, pady=5, sticky=tk.W)
        combo = ttk.Combobox(parent, textvariable=variable, values=values,
                           state="readonly", width=width, font=("Segoe UI", 10))
        combo.grid(row=row, column=column+1, padx=10, pady=5, sticky=tk.W)
        return combo

    def _browse_appid(self, appid_var, parent_dialog):
        """Browse and select Steam dedicated server AppID"""
        # Create AppID selection dialog
        appid_dialog = tk.Toplevel(parent_dialog)
        appid_dialog.title("Select Dedicated Server")
        appid_dialog.transient(parent_dialog)
        appid_dialog.grab_set()
        appid_dialog.geometry("600x500")

        # Create search frame
        search_frame = ttk.Frame(appid_dialog, padding=10)
        search_frame.pack(fill=tk.X)

        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(5, 10))

        # Load dedicated servers from scanner's AppID list (NO FALLBACKS)
        try:
            dedicated_servers_data, metadata = load_appid_scanner_list(self.server_manager_dir)

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
            return

        # Create server list
        list_frame = ttk.Frame(appid_dialog, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Enhanced treeview for server list with additional columns
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

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=server_tree.yview)
        server_tree.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Populate server list with enhanced data
        def populate_servers(filter_text: str = ""):
            # Populate the server tree with filtered dedicated server list
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

        # Enhanced search functionality
        def on_search(*args):
            # Update server list when search text changes
            populate_servers(search_var.get())

        search_var.trace('w', on_search)

        # Add tooltip functionality for descriptions
        def show_server_info(event):
            # Show server description tooltip on mouse hover
            item = server_tree.selection()
            if item:
                selected_server = None
                item_values = server_tree.item(item[0])['values']
                for server in dedicated_servers:
                    if server["appid"] == str(item_values[1]):
                        selected_server = server
                        break

                if selected_server and selected_server.get("description"):
                    # Create a simple tooltip window
                    tooltip = tk.Toplevel(appid_dialog)
                    tooltip.wm_overrideredirect(True)
                    tooltip.geometry(f"+{event.x_root+10}+{event.y_root+10}")

                    # Limit description length
                    desc = selected_server["description"][:200] + ("..." if len(selected_server["description"]) > 200 else "")

                    label = tk.Label(tooltip, text=f"{selected_server['name']}\n\n{desc}",
                                   background="lightyellow", relief="solid", borderwidth=1,
                                   wraplength=300, justify=tk.LEFT, font=("Segoe UI", 9))
                    label.pack()

                    # Auto-hide after 3 seconds
                    tooltip.after(3000, tooltip.destroy)

        server_tree.bind('<Double-1>', show_server_info)

        # Button frame
        button_frame = ttk.Frame(appid_dialog, padding=10)
        button_frame.pack(fill=tk.X)

        def select_server():
            selected = server_tree.selection()

            if selected:
                # Use selected server from list
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

        # Centre dialog
        centre_window(appid_dialog, 600, 500, parent_dialog)

    def _create_startup_configuration_section(self, parent, server_config, install_dir):
        """Create the startup configuration section and return all variables"""
        startup_frame = ttk.LabelFrame(parent, text="Startup Configuration", padding=10)
        startup_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Executable
        exe_var = tk.StringVar(value=server_config.get('ExecutablePath',''))
        exe_entry = self._create_labeled_entry(startup_frame, "Executable", exe_var, 0)
        
        def browse_exe():
            fp = filedialog.askopenfilename(initialdir=install_dir,
                filetypes=[("Executables","*.exe;*.bat;*.cmd;*.ps1;*.sh"),("All Files","*.*")])
            if fp:
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                exe_var.set(rel)
        ttk.Button(startup_frame, text="Browse", command=browse_exe).grid(row=0, column=2, padx=10, pady=5)

        # Stop command
        stop_var = tk.StringVar(value=server_config.get('StopCommand',''))
        self._create_labeled_entry(startup_frame, "Stop Command", stop_var, 1)
        
        # Startup arguments section with radio button choice
        args_frame = ttk.LabelFrame(startup_frame, text="Startup Arguments", padding=5)
        args_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        # Radio button to choose between manual args or config file
        startup_mode_var = tk.StringVar(value="manual" if not server_config.get('UseConfigFile', False) else "config")
        
        manual_radio = ttk.Radiobutton(args_frame, text="Manual Arguments", variable=startup_mode_var, value="manual")
        manual_radio.grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        
        config_radio = ttk.Radiobutton(args_frame, text="Use Configuration File", variable=startup_mode_var, value="config")
        config_radio.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)
        
        # Manual arguments section
        manual_frame = ttk.Frame(args_frame)
        manual_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        ttk.Label(manual_frame, text="Startup Args:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        args_var = tk.StringVar(value=server_config.get('StartupArgs',''))
        args_entry = ttk.Entry(manual_frame, textvariable=args_var, width=35)
        args_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        
        # Config file section
        config_frame = ttk.Frame(args_frame)
        config_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        # Config file path
        ttk.Label(config_frame, text="Config File:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        config_file_var = tk.StringVar(value=server_config.get('ConfigFilePath',''))
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
                rel = os.path.relpath(fp, install_dir) if os.path.commonpath([fp,install_dir])==install_dir else fp
                config_file_var.set(rel)
        ttk.Button(config_frame, text="Browse", command=browse_config, width=10).grid(row=0, column=2, padx=5, pady=2)
        
        # Config file argument format
        ttk.Label(config_frame, text="Config Argument:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        config_arg_var = tk.StringVar(value=server_config.get('ConfigArgument', '--config'))
        config_arg_entry = ttk.Entry(config_frame, textvariable=config_arg_var, width=15)
        config_arg_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(e.g., --config, -c, +exec)", foreground="gray").grid(row=1, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Additional args for config mode
        ttk.Label(config_frame, text="Additional Args:").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        additional_args_var = tk.StringVar(value=server_config.get('AdditionalArgs',''))
        additional_args_entry = ttk.Entry(config_frame, textvariable=additional_args_var, width=25)
        additional_args_entry.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(config_frame, text="(optional)", foreground="gray").grid(row=2, column=2, padx=5, pady=2, sticky=tk.W)
        
        # Configure grid weights
        startup_frame.grid_columnconfigure(0, weight=0, minsize=120)
        startup_frame.grid_columnconfigure(1, weight=1, minsize=200)
        startup_frame.grid_columnconfigure(2, weight=0, minsize=80)
        args_frame.grid_columnconfigure(0, weight=1)
        args_frame.grid_columnconfigure(1, weight=1)
        args_frame.grid_columnconfigure(2, weight=0)
        manual_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(2, weight=0)
        
        # Function to enable/disable widgets based on selection
        def toggle_startup_mode():
            mode = startup_mode_var.get()
            if mode == "manual":
                # Enable manual args, disable config file options
                args_entry.config(state=tk.NORMAL)
                config_file_entry.config(state=tk.DISABLED)
                config_arg_entry.config(state=tk.DISABLED)
                additional_args_entry.config(state=tk.DISABLED)
            else:
                # Disable manual args, enable config file options
                args_entry.config(state=tk.DISABLED)
                config_file_entry.config(state=tk.NORMAL)
                config_arg_entry.config(state=tk.NORMAL)
                additional_args_entry.config(state=tk.NORMAL)
        
        # Bind radio button changes
        startup_mode_var.trace('w', lambda *args: toggle_startup_mode())
        toggle_startup_mode()  # Initial toggle
        
        return exe_var, stop_var, startup_mode_var, args_var, config_file_var, config_arg_var, additional_args_var

    def _create_command_preview_section(self, parent, exe_var, startup_mode_var, args_var, 
                                      config_file_var, config_arg_var, additional_args_var, 
                                      install_dir):
        """Create the command preview section"""
        preview_frame = ttk.LabelFrame(parent, text="Command Preview", padding=10)
        preview_frame.pack(fill=tk.X, pady=(0, 15))
        
        preview_text = tk.Text(preview_frame, height=3, wrap=tk.WORD, background="lightgray", font=("Consolas", 9))
        preview_text.pack(fill=tk.X, padx=5, pady=5)
        
        def update_preview():
            # Update the command preview
            try:
                exe = exe_var.get().strip()
                mode = startup_mode_var.get()
                
                # Build command preview
                cmd_parts = []
                if exe:
                    exe_abs = exe if os.path.isabs(exe) else os.path.join(install_dir, exe)
                    cmd_parts.append(f'"{exe_abs}"')
                
                if mode == "manual":
                    # Manual arguments mode
                    args = args_var.get().strip()
                    if args:
                        cmd_parts.append(args)
                else:
                    # Config file mode
                    config_file_path = config_file_var.get().strip()
                    config_arg = config_arg_var.get().strip()
                    additional_args = additional_args_var.get().strip()
                    
                    # Add additional args first (if any)
                    if additional_args:
                        cmd_parts.append(additional_args)
                    
                    # Add config file argument
                    if config_file_path and config_arg:
                        config_abs = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                        cmd_parts.append(f'{config_arg} "{config_abs}"')
                
                cmd_preview = ' '.join(cmd_parts) if cmd_parts else "No executable specified"
                
                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, cmd_preview)
            except Exception as e:
                preview_text.delete(1.0, tk.END)
                preview_text.insert(1.0, f"Error generating preview: {str(e)}")
        
        # Bind update events
        def on_change(*args):
            update_preview()
        
        exe_var.trace('w', on_change)
        args_var.trace('w', on_change)
        startup_mode_var.trace('w', on_change)
        config_file_var.trace('w', on_change)
        config_arg_var.trace('w', on_change)
        additional_args_var.trace('w', on_change)
        
        # Initial preview update
        update_preview()
        
        return update_preview
        
        return preview_text

    def _create_scheduled_commands_section(self, parent, server_config):
        """Create the scheduled commands section and return all variables"""
        commands_frame = ttk.LabelFrame(parent, text="⏰ Scheduled Commands", padding=10)
        commands_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Save Command
        save_cmd_var = tk.StringVar(value=server_config.get('SaveCommand', ''))
        save_cmd_entry = self._create_labeled_entry(commands_frame, "Save Command", save_cmd_var, 0, width=30)
        ttk.Label(commands_frame, text="Command to save world/data before shutdown (e.g., 'save-all', '/save')", 
                  foreground="gray", font=("Segoe UI", 8)).grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        
        # Start Command (run after server starts)
        start_cmd_var = tk.StringVar(value=server_config.get('StartCommand', ''))
        start_cmd_entry = self._create_labeled_entry(commands_frame, "Start Command", start_cmd_var, 1, width=30)
        ttk.Label(commands_frame, text="Command to run after server starts (e.g., 'say Server is ready!')", 
                  foreground="gray", font=("Segoe UI", 8)).grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        
        # Warning Command
        warning_cmd_var = tk.StringVar(value=server_config.get('WarningCommand', ''))
        warning_cmd_entry = self._create_labeled_entry(commands_frame, "Warning Command", warning_cmd_var, 2, width=30)
        ttk.Label(commands_frame, text="Shutdown/restart warning (use {message} placeholder, e.g., 'broadcast {message}')", 
                  foreground="gray", font=("Segoe UI", 8)).grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)
        
        # Warning Intervals
        warning_intervals_var = tk.StringVar(value=server_config.get('WarningIntervals', '15,10,5,1'))
        warning_intervals_entry = self._create_labeled_entry(commands_frame, "Warning Intervals", warning_intervals_var, 3, width=30)
        ttk.Label(commands_frame, text="Minutes before shutdown to warn (comma-separated, e.g., '15,10,5,1')", 
                  foreground="gray", font=("Segoe UI", 8)).grid(row=3, column=2, padx=5, pady=5, sticky=tk.W)

        # MOTD Command
        motd_cmd_var = tk.StringVar(value=server_config.get('MotdCommand', ''))
        motd_cmd_entry = self._create_labeled_entry(commands_frame, "MOTD Command", motd_cmd_var, 4, width=30)
        ttk.Label(commands_frame, text="Command to broadcast messages (e.g., 'say {message}', 'broadcast {message}')",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=4, column=2, padx=5, pady=5, sticky=tk.W)

        # MOTD Message
        motd_msg_var = tk.StringVar(value=server_config.get('MotdMessage', ''))
        motd_msg_entry = self._create_labeled_entry(commands_frame, "MOTD Message", motd_msg_var, 5, width=30)
        ttk.Label(commands_frame, text="Default message for MOTD broadcasts",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=5, column=2, padx=5, pady=5, sticky=tk.W)

        # MOTD Interval
        motd_interval_var = tk.StringVar(value=str(server_config.get('MotdInterval', 0)))
        motd_interval_entry = self._create_labeled_entry(commands_frame, "MOTD Interval", motd_interval_var, 6, width=30)
        ttk.Label(commands_frame, text="How often to broadcast MOTD (minutes, 0 = disabled)",
                  foreground="gray", font=("Segoe UI", 8)).grid(row=6, column=2, padx=5, pady=5, sticky=tk.W)
        
        # Configure grid weights for commands frame
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

        # Get server configuration from server manager
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return

        install_dir = server_config.get('InstallDir','')
        # Users can update the InstallDir in the configuration dialog

        dialog, scrollable_frame = self._create_scrollable_dialog(
            self.root, f"Configure Server: {server_name}")

        # Server Identity Section
        identity_frame = ttk.LabelFrame(scrollable_frame, text="Server Identity", padding=10)
        identity_frame.pack(fill=tk.X, pady=(0, 15))

        # Server name
        name_var = tk.StringVar(value=server_name)
        name_entry = self._create_labeled_entry(identity_frame, "Server Name", name_var, 0)

        # Server type
        current_server_type = server_config.get('Type', 'Other')
        type_var = tk.StringVar(value=current_server_type)
        type_combo = self._create_labeled_combo(identity_frame, "Server Type", type_var,
                                              ["Steam", "Minecraft", "Other"], 1)

        # AppID (conditionally shown for Steam servers)
        appid_var = tk.StringVar(value=str(server_config.get('appid', server_config.get('AppID', ''))))
        appid_entry = self._create_labeled_entry(identity_frame, "AppID", appid_var, 2, width=15)
        
        def browse_appid():
            self._browse_appid(appid_var, dialog)
        
        appid_browse_btn = ttk.Button(identity_frame, text="Browse", command=browse_appid, width=10)
        appid_browse_btn.grid(row=2, column=2, padx=5, pady=5)
        
        appid_help = ttk.Label(identity_frame, text="(Steam servers only)", foreground="gray", font=("Segoe UI", 8))
        appid_help.grid(row=2, column=3, padx=5, pady=5, sticky=tk.W)
        
        # Install directory (now editable)
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
                # Check if directory changed
                old_dir = install_dir_var.get()
                if old_dir != selected_dir:
                    install_dir_var.set(selected_dir)
                    # Update relative paths when install directory changes
                    update_paths_for_new_install_dir(old_dir, selected_dir)
        
        ttk.Button(identity_frame, text="Browse", command=browse_install_dir, width=8).grid(row=3, column=2, padx=5, pady=5)
        
        def test_install_dir_path():
            # Test if the install directory path exists
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
            # Update relative paths when install directory changes
            try:
                # Only update if both directories exist and are different
                if not old_dir or not new_dir or old_dir == new_dir:
                    return
                
                # Update executable path if it's relative
                exe_path = exe_var.get().strip()
                if exe_path and not os.path.isabs(exe_path):
                    # Try to find the same relative file in the new directory
                    old_full_path = os.path.join(old_dir, exe_path)
                    if os.path.exists(old_full_path):
                        # File exists in old location, keep relative path
                        pass  # Keep the relative path as is
                    else:
                        # File doesn't exist in old location, try to find it in new directory
                        new_full_path = os.path.join(new_dir, os.path.basename(exe_path))
                        if os.path.exists(new_full_path):
                            exe_var.set(os.path.basename(exe_path))
                
                # Update config file path if it's relative
                config_path = config_file_var.get().strip()
                if config_path and not os.path.isabs(config_path):
                    old_config_full = os.path.join(old_dir, config_path)
                    if os.path.exists(old_config_full):
                        # File exists in old location, keep relative path
                        pass  # Keep the relative path as is
                    else:
                        # Try to find config files in new directory
                        for ext in ['.cfg', '.conf', '.ini', '.json', '.yaml', '.yml', '.properties', '.txt']:
                            potential_config = os.path.join(new_dir, f"server{ext}")
                            if os.path.exists(potential_config):
                                config_file_var.set(f"server{ext}")
                                break
                
                # Update preview
                update_preview()
                
            except Exception as e:
                logger.warning(f"Error updating paths for new install directory: {str(e)}")
        
        # Bind install directory change event
        def on_install_dir_change(*args):
            update_preview()
        
        install_dir_var.trace('w', on_install_dir_change)
        
        # Configure grid
        identity_frame.grid_columnconfigure(1, weight=1)
        identity_frame.grid_columnconfigure(2, weight=0)
        identity_frame.grid_columnconfigure(3, weight=0)
        
        def toggle_appid_field():
            # Enable/disable AppID field based on server type
            if type_var.get() == "Steam":
                appid_entry.config(state=tk.NORMAL)
                appid_browse_btn.config(state=tk.NORMAL)
                appid_help.config(text="(Required for Steam servers)")
            else:
                appid_entry.config(state=tk.DISABLED)
                appid_browse_btn.config(state=tk.DISABLED)
                appid_help.config(text="(Steam servers only)")
        
        # Bind type change event
        type_var.trace('w', lambda *args: toggle_appid_field())
        toggle_appid_field()  # Initial state
        
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
        
        # Initialise server-type-specific variables
        java_path_var = ram_var = jvm_args_var = mc_version_var = None
        auto_update_var = validate_files_var = None
        notes_var = None
        
        # Minecraft-specific configuration section
        if server_type == "Minecraft":
            minecraft_section = ttk.LabelFrame(scrollable_frame, text="🎮 Minecraft Settings", padding=10)
            minecraft_section.pack(fill=tk.X, pady=(15, 0))
            
            # Java Configuration
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
            
            # Memory Settings in same row
            ttk.Label(java_info_frame, text="RAM (MB):", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            ram_var = tk.StringVar(value=str(server_config.get("RAM", 1024)))
            ttk.Entry(java_info_frame, textvariable=ram_var, width=15, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
            
            ttk.Label(java_info_frame, text="JVM Args:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky=tk.W, pady=5, padx=10)
            jvm_args_var = tk.StringVar(value=server_config.get("JVMArgs", ""))
            ttk.Entry(java_info_frame, textvariable=jvm_args_var, width=30, font=("Segoe UI", 10)).grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=10, pady=5)
            
            # Minecraft Version
            ttk.Label(java_info_frame, text="MC Version:", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky=tk.W, pady=5, padx=10)
            mc_version_var = tk.StringVar(value=server_config.get("Version", ""))
            ttk.Entry(java_info_frame, textvariable=mc_version_var, width=25, font=("Segoe UI", 10)).grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)
            
            # Configure grid weights
            java_info_frame.grid_columnconfigure(0, weight=0, minsize=100)
            java_info_frame.grid_columnconfigure(1, weight=1, minsize=150)
            java_info_frame.grid_columnconfigure(2, weight=0, minsize=80)
            java_info_frame.grid_columnconfigure(3, weight=0, minsize=100)
        
        # Steam-specific configuration section
        elif server_type == "Steam":
            steam_section = ttk.LabelFrame(scrollable_frame, text="🚂 Steam Settings", padding=10)
            steam_section.pack(fill=tk.X, pady=(15, 0))
            
            # Steam Information
            steam_info_frame = ttk.LabelFrame(steam_section, text="Steam Configuration", padding=10)
            steam_info_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Update Settings
            auto_update_var = tk.BooleanVar(value=server_config.get("AutoUpdate", False))
            ttk.Checkbutton(steam_info_frame, text="Enable automatic updates", variable=auto_update_var).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            
            validate_files_var = tk.BooleanVar(value=server_config.get("ValidateFiles", False))
            ttk.Checkbutton(steam_info_frame, text="Validate files on update", variable=validate_files_var).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            
            # Configure grid weights
            steam_info_frame.grid_columnconfigure(0, weight=1)
            steam_info_frame.grid_columnconfigure(1, weight=0)
        
        # Other server type configuration section
        elif server_type == "Other":
            other_section = ttk.LabelFrame(scrollable_frame, text="🔧 Custom Server Settings", padding=10)
            other_section.pack(fill=tk.X, pady=(15, 0))
            
            # Custom Settings
            custom_frame = ttk.LabelFrame(other_section, text="Custom Configuration", padding=10)
            custom_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(custom_frame, text="Server Type:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=tk.W, pady=5, padx=10)
            ttk.Label(custom_frame, text="Other/Custom", font=("Segoe UI", 10)).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
            
            ttk.Label(custom_frame, text="Configuration Notes:", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky=tk.W, pady=5, padx=10)
            notes_var = tk.StringVar(value=server_config.get("Notes", ""))
            ttk.Entry(custom_frame, textvariable=notes_var, width=35, font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)
            
            # Configure grid weights
            custom_frame.grid_columnconfigure(0, weight=0, minsize=140)
            custom_frame.grid_columnconfigure(1, weight=1, minsize=200)
        if name_var.get() != server_name or type_var.get() != current_server_type:
            warning_frame = ttk.Frame(scrollable_frame)
            warning_frame.pack(fill=tk.X, pady=(0, 15))
            
            warning_label = ttk.Label(warning_frame, 
                                    text="⚠ Warning: Changing server name or type will update configuration files. Ensure server is stopped.",
                                    foreground="orange", font=("Segoe UI", 9, "bold"), wraplength=650)
            warning_label.pack()

        # Button frame at bottom of dialog (outside scrollable area)
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=10)
        
        def validate_inputs():
            # Validate all input fields
            errors = []
            
            new_name = name_var.get().strip()
            new_type = type_var.get()
            new_appid = appid_var.get().strip()
            exe_path = exe_var.get().strip()
            
            # Validate server name
            if not new_name:
                errors.append("Server name cannot be empty")
            elif new_name != server_name and self.server_manager:
                # Check if new name already exists
                try:
                    existing_config = self.server_manager.get_server_config(new_name)
                    if existing_config:
                        errors.append(f"Server name '{new_name}' already exists")
                except Exception:
                    pass  # Server doesn't exist, which is good
            
            # Validate AppID for Steam servers
            if new_type == 'Steam':
                if not new_appid:
                    errors.append("AppID is required for Steam servers")
                elif not new_appid.isdigit():
                    errors.append("AppID must contain only numbers")
            
            # Validate executable
            # REMOVED: Executable path is no longer required
            # if not exe_path:
            #     errors.append("Executable path is required")
            
            return errors
        
        def save_configuration():
            # Save the server configuration
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
                # Validate executable path
                exe_abs = exe_path if os.path.isabs(exe_path) else os.path.join(install_dir_var.get(), exe_path)
                if not os.path.exists(exe_abs):
                    if not messagebox.askyesno("Warning", f"Executable not found: {exe_abs}\nSave anyway?"):
                        return
                
                # Prepare configuration based on mode
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
                    
                    # Validate config file if enabled
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
                
                # Handle name/type/AppID changes first
                name_changed = new_name != server_name
                type_changed = new_type != current_server_type
                current_appid_str = str(server_config.get('appid', server_config.get('AppID', ''))) if server_config else ''
                appid_changed = new_type == 'Steam' and new_appid != current_appid_str
                
                if name_changed or type_changed or appid_changed:
                    # Create updated server config
                    if server_config:
                        updated_config = server_config.copy()
                        updated_config['type'] = new_type
                        if new_type == 'Steam' and new_appid:
                            updated_config['appid'] = int(new_appid)
                            updated_config['AppID'] = int(new_appid)  # Legacy support
                    
                    # Use the rename function if name changed
                    if name_changed:
                        success, message = rename_server_configuration(server_name, new_name, 
                                                                      self.server_manager)
                        if not success:
                            messagebox.showerror("Error", f"Failed to rename server: {message}")
                            return
                        
                        # Update server_name for subsequent operations
                        current_server_name = new_name
                    else:
                        # Just update the type/AppID without renaming
                        try:
                            # Get current config from server manager
                            if not self.server_manager:
                                messagebox.showerror("Error", "Server manager not available")
                                return
                                
                            current_config = self.server_manager.get_server_config(server_name)
                            if not current_config:
                                messagebox.showerror("Error", "Could not load server configuration")
                                return
                            
                            # Update the config
                            current_config['type'] = new_type
                            if new_type == 'Steam' and new_appid:
                                current_config['appid'] = int(new_appid)
                                current_config['AppID'] = int(new_appid)  # Legacy support
                            
                            # Save updated config to database
                            self.server_manager.update_server(server_name, current_config)
                            
                            logger.info(f"Updated server type/AppID for '{server_name}'")
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to update server configuration: {str(e)}")
                            return
                        
                        current_server_name = server_name
                else:
                    current_server_name = server_name
                
                # Update startup configuration
                if self.server_manager:
                    success, message = self.server_manager.update_server_config(
                        current_server_name, exe_path, startup_args, stop_cmd, use_config_file=use_config, 
                        config_file_path=config_file_path, config_argument=config_arg, additional_args=additional_args
                    )
                else:
                    success = False
                    message = "Server manager not available"
                
                # Update InstallDir in server configuration if it changed
                if success and install_dir_var.get() != server_config.get('InstallDir'):
                    try:
                        # Get current config from server manager
                        if self.server_manager:
                            current_config = self.server_manager.get_server_config(current_server_name)
                            if current_config:
                                # Update InstallDir
                                current_config['InstallDir'] = install_dir_var.get()
                                
                                # Save updated config to database
                                self.server_manager.update_server(current_server_name, current_config)
                                
                                logger.info(f"Updated InstallDir for server '{current_server_name}' to: {install_dir_var.get()}")
                    except Exception as e:
                        logger.warning(f"Failed to update InstallDir: {str(e)}")
                        # Don't fail the entire operation for this
                
                # Handle scheduled command configurations (applies to ALL server types)
                if success:
                    try:
                        # Get the updated configuration from server manager
                        if self.server_manager:
                            updated_config = self.server_manager.get_server_config(current_server_name)
                            if updated_config:
                                # Update scheduled command settings
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
                                
                                # Save the updated configuration with scheduled command settings to database
                                self.server_manager.update_server(current_server_name, updated_config)
                                
                                logger.info(f"Updated scheduled command configuration for server '{current_server_name}'")
                    
                    except Exception as e:
                        logger.warning(f"Failed to update scheduled command settings: {str(e)}")
                        # Don't fail the entire operation for this
                
                # Handle server-type-specific configurations
                if success and new_type:
                    try:
                        # Get the updated configuration from server manager
                        if self.server_manager:
                            updated_config = self.server_manager.get_server_config(current_server_name)
                            if updated_config:
                                # Update server-type-specific settings
                                if new_type == "Minecraft":
                                    # Update Minecraft-specific settings if they exist
                                    if java_path_var is not None:
                                        updated_config['JavaPath'] = java_path_var.get()
                                    if ram_var is not None:
                                        try:
                                            updated_config['RAM'] = int(ram_var.get())
                                        except ValueError:
                                            pass  # Keep existing value if invalid
                                    if jvm_args_var is not None:
                                        updated_config['JVMArgs'] = jvm_args_var.get()
                                    if mc_version_var is not None:
                                        updated_config['Version'] = mc_version_var.get()
                            
                                elif new_type == "Steam":
                                    # Update Steam-specific settings if they exist
                                    # Note: AppID is handled in the main identity section above
                                    if auto_update_var is not None:
                                        updated_config['AutoUpdate'] = auto_update_var.get()
                                    if validate_files_var is not None:
                                        updated_config['ValidateFiles'] = validate_files_var.get()
                            
                                elif new_type == "Other":
                                    # Update Other server-specific settings if they exist
                                    if notes_var is not None:
                                        updated_config['Notes'] = notes_var.get()
                            
                                # Save the updated configuration with server-specific settings to database
                                self.server_manager.update_server(current_server_name, updated_config)
                            
                                logger.info(f"Updated {new_type}-specific configuration for server '{current_server_name}'")
                    
                    except Exception as e:
                        logger.warning(f"Failed to update {new_type}-specific settings: {str(e)}")
                        # Don't fail the entire operation for this
                    # Log the actions
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
                    
                    # Refresh server list to show changes
                    self.update_server_list(force_refresh=True)
                else:
                    messagebox.showerror("Error", f"Failed to save startup configuration: {message}")
                    
            except Exception as e:
                logger.error(f"Error saving server configuration: {str(e)}")
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        # Buttons - Save and Cancel at bottom of dialog
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save Configuration", command=save_configuration).pack(side=tk.RIGHT)

        # Centre dialog relative to parent
        centre_window(dialog, None, None, self.root)

    def configure_java(self):
        # Open Java configuration dialog for selected server
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showwarning("No Selection", "No server list available.")
            return
            
        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a server to configure Java for.")
            return
        
        # Get selected server name
        item = selected_items[0]
        server_name = current_list.item(item)["values"][0]
        
        # Check if it's a Minecraft server
        server_config = None
        if hasattr(self, 'server_manager') and self.server_manager:
            server_config = self.server_manager.get_server_config(server_name)
        
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for '{server_name}'")
            return
        
        if server_config.get("Type") != "Minecraft":
            messagebox.showinfo("Info", f"Java configuration is only available for Minecraft servers.\n'{server_name}' is a {server_config.get('Type', 'Unknown')} server.")
            return
        
        # Open Java configuration dialog
        result = show_java_configuration_dialog(self.root, server_name, server_config, 
                                               self.server_manager)
        
        # Refresh server list if Java was updated
        if result['success']:
            self.update_server_list(force_refresh=True)
    
    def show_server_type_configuration(self):
        # Redirect to unified configure_server method
        self.configure_server()
    
    def show_minecraft_server_config(self, server_name, server_config):
        # Show Minecraft-specific configuration dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Minecraft Server Configuration - {server_name}")
        dialog.geometry("800x700")
        # Removed transient() and grab_set() to allow multiple windows
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Minecraft Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Basic Configuration Tab
        basic_frame = ttk.Frame(notebook, padding=10)
        notebook.add(basic_frame, text="Basic Settings")
        
        # Server Information
        info_frame = ttk.LabelFrame(basic_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Version
        ttk.Label(info_frame, text="Minecraft Version:").grid(row=1, column=0, sticky=tk.W, pady=5)
        version_var = tk.StringVar(value=server_config.get("Version", ""))
        ttk.Entry(info_frame, textvariable=version_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server JAR file
        ttk.Label(info_frame, text="Server JAR:").grid(row=3, column=0, sticky=tk.W, pady=5)
        jar_var = tk.StringVar(value=os.path.basename(server_config.get("ExecutablePath", "")))
        ttk.Entry(info_frame, textvariable=jar_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Java Configuration Tab
        java_frame = ttk.Frame(notebook, padding=10)
        notebook.add(java_frame, text="Java Settings")
        
        # Java Path
        java_info_frame = ttk.LabelFrame(java_frame, text="Java Configuration", padding=10)
        java_info_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(java_info_frame, text="Java Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        java_path_var = tk.StringVar(value=server_config.get("JavaPath", "java"))
        java_entry = ttk.Entry(java_info_frame, textvariable=java_path_var, width=50)
        java_entry.grid(row=0, column=1, sticky=tk.W, padx=(10, 5), pady=5)
        
        def browse_java():
            file_types = [("Java Executable", "java.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            java_path = filedialog.askopenfilename(title="Select Java Executable", filetypes=file_types)
            if java_path:
                java_path_var.set(java_path)
        
        ttk.Button(java_info_frame, text="Browse", command=browse_java).grid(row=0, column=2, padx=(5, 0), pady=5)
        
        def auto_detect_java():
            try:
                from Modules.minecraft import get_recommended_java_for_minecraft
                version = version_var.get()
                if version:
                    recommended = get_recommended_java_for_minecraft(version)
                    if recommended:
                        java_path_var.set(recommended["path"])
                        messagebox.showinfo("Auto-Detect", f"Found: {recommended['display_name']}")
                    else:
                        messagebox.showwarning("No Java Found", "No compatible Java installation found.")
                else:
                    messagebox.showwarning("No Version", "Please enter Minecraft version first.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to detect Java: {str(e)}")
        
        ttk.Button(java_info_frame, text="Auto-Detect", command=auto_detect_java).grid(row=0, column=3, padx=(5, 0), pady=5)
        
        # Memory Settings
        memory_frame = ttk.LabelFrame(java_frame, text="Memory Settings", padding=10)
        memory_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(memory_frame, text="RAM Allocation (MB):").grid(row=0, column=0, sticky=tk.W, pady=5)
        ram_var = tk.StringVar(value=str(server_config.get("RAM", 1024)))
        ttk.Entry(memory_frame, textvariable=ram_var, width=20).grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # JVM Arguments
        ttk.Label(memory_frame, text="JVM Arguments:").grid(row=1, column=0, sticky=tk.W, pady=5)
        jvm_args_var = tk.StringVar(value=server_config.get("JVMArgs", ""))
        ttk.Entry(memory_frame, textvariable=jvm_args_var, width=50).grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Advanced Tab
        advanced_frame = ttk.Frame(notebook, padding=10)
        notebook.add(advanced_frame, text="Advanced")
        
        # Server Properties
        props_frame = ttk.LabelFrame(advanced_frame, text="Server Properties", padding=10)
        props_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Add a text widget for server.properties editing
        props_text = tk.Text(props_frame, height=20, width=70)
        props_scroll = ttk.Scrollbar(props_frame, orient=tk.VERTICAL, command=props_text.yview)
        props_text.configure(yscrollcommand=props_scroll.set)
        
        props_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        props_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Load server.properties if it exists
        install_dir = server_config.get("InstallDir", "")
        props_file = os.path.join(install_dir, "server.properties")
        if os.path.exists(props_file):
            try:
                with open(props_file, 'r', encoding='utf-8') as f:
                    props_text.insert(tk.END, f.read())
            except Exception as e:
                props_text.insert(tk.END, f"# Error reading server.properties: {str(e)}\n")
        else:
            props_text.insert(tk.END, "# server.properties file not found\n# Create server first or manually add properties here\n")
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["Version"] = version_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = os.path.join(install_dir_var.get(), jar_var.get())
                server_config["JavaPath"] = java_path_var.get()
                server_config["RAM"] = int(ram_var.get()) if ram_var.get().isdigit() else 1024
                server_config["JVMArgs"] = jvm_args_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.update_server(server_name, server_config)
                
                # Save server.properties
                install_dir = install_dir_var.get()
                if install_dir and os.path.exists(install_dir):
                    props_file = os.path.join(install_dir, "server.properties")
                    try:
                        with open(props_file, 'w', encoding='utf-8') as f:
                            f.write(props_text.get(1.0, tk.END))
                    except Exception as e:
                        messagebox.showwarning("Properties Save Failed", f"Failed to save server.properties: {str(e)}")
                
                # Update launch script
                try:
                    manager = MinecraftServerManager(self.server_manager_dir, self.config)
                    script_path = manager.create_launch_script(
                        install_dir_var.get(),
                        jar_var.get(),
                        int(ram_var.get()) if ram_var.get().isdigit() else 1024,
                        jvm_args_var.get(),
                        java_path_var.get()
                    )
                except Exception as e:
                    messagebox.showwarning("Script Update Failed", f"Failed to update launch script: {str(e)}")
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 950, 750, self.root)
    
    def show_steam_server_config(self, server_name, server_config):
        # Show Steam-specific configuration dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Steam Server Configuration - {server_name}")
        dialog.geometry("700x600")
        # Removed transient() and grab_set() to allow multiple windows
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Steam Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Basic Configuration Tab
        basic_frame = ttk.Frame(notebook, padding=10)
        notebook.add(basic_frame, text="Basic Settings")
        
        # Server Information
        info_frame = ttk.LabelFrame(basic_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # App ID
        ttk.Label(info_frame, text="Steam App ID:").grid(row=1, column=0, sticky=tk.W, pady=5)
        app_id_var = tk.StringVar(value=server_config.get("AppID", ""))
        ttk.Entry(info_frame, textvariable=app_id_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Executable
        ttk.Label(info_frame, text="Server Executable:").grid(row=3, column=0, sticky=tk.W, pady=5)
        exe_var = tk.StringVar(value=os.path.basename(server_config.get("ExecutablePath", "")))
        ttk.Entry(info_frame, textvariable=exe_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Launch Parameters Tab
        launch_frame = ttk.Frame(notebook, padding=10)
        notebook.add(launch_frame, text="Launch Parameters")
        
        # Launch Arguments
        args_frame = ttk.LabelFrame(launch_frame, text="Launch Arguments", padding=10)
        args_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(args_frame, text="Command Line Arguments:").pack(anchor=tk.W, pady=(0, 5))
        args_var = tk.StringVar(value=server_config.get("LaunchArgs", ""))
        args_text = tk.Text(args_frame, height=5, width=70)
        args_text.insert(1.0, args_var.get())
        args_text.pack(fill=tk.X, pady=(0, 10))
        
        # Common Steam Server Settings
        steam_frame = ttk.LabelFrame(launch_frame, text="Common Steam Settings", padding=10)
        steam_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Port
        ttk.Label(steam_frame, text="Server Port:").grid(row=0, column=0, sticky=tk.W, pady=5)
        port_var = tk.StringVar(value=str(server_config.get("Port", 27015)))
        ttk.Entry(steam_frame, textvariable=port_var, width=20).grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Max Players
        ttk.Label(steam_frame, text="Max Players:").grid(row=1, column=0, sticky=tk.W, pady=5)
        maxplayers_var = tk.StringVar(value=str(server_config.get("MaxPlayers", 16)))
        ttk.Entry(steam_frame, textvariable=maxplayers_var, width=20).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server Name (in-game)
        ttk.Label(steam_frame, text="Server Name (in-game):").grid(row=2, column=0, sticky=tk.W, pady=5)
        servername_var = tk.StringVar(value=server_config.get("ServerName", ""))
        ttk.Entry(steam_frame, textvariable=servername_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Map
        ttk.Label(steam_frame, text="Map:").grid(row=3, column=0, sticky=tk.W, pady=5)
        map_var = tk.StringVar(value=server_config.get("Map", ""))
        ttk.Entry(steam_frame, textvariable=map_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Advanced Tab
        advanced_frame = ttk.Frame(notebook, padding=10)
        notebook.add(advanced_frame, text="Advanced")
        
        # SteamCMD Settings
        steamcmd_frame = ttk.LabelFrame(advanced_frame, text="SteamCMD Configuration", padding=10)
        steamcmd_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(steamcmd_frame, text="SteamCMD Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        steamcmd_var = tk.StringVar(value=server_config.get("SteamCMDPath", ""))
        ttk.Entry(steamcmd_frame, textvariable=steamcmd_var, width=50).grid(row=0, column=1, sticky=tk.W, padx=(10, 5), pady=5)
        
        def browse_steamcmd():
            file_types = [("SteamCMD", "steamcmd.exe"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            steamcmd_path = filedialog.askopenfilename(title="Select SteamCMD Executable", filetypes=file_types)
            if steamcmd_path:
                steamcmd_var.set(steamcmd_path)
        
        ttk.Button(steamcmd_frame, text="Browse", command=browse_steamcmd).grid(row=0, column=2, padx=(5, 0), pady=5)
        
        # Auto-update settings
        auto_update_var = tk.BooleanVar(value=server_config.get("AutoUpdate", False))
        ttk.Checkbutton(steamcmd_frame, text="Enable automatic updates", variable=auto_update_var).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["AppID"] = app_id_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = os.path.join(install_dir_var.get(), exe_var.get())
                server_config["LaunchArgs"] = args_text.get(1.0, tk.END).strip()
                server_config["Port"] = int(port_var.get()) if port_var.get().isdigit() else 27015
                server_config["MaxPlayers"] = int(maxplayers_var.get()) if maxplayers_var.get().isdigit() else 16
                server_config["ServerName"] = servername_var.get()
                server_config["Map"] = map_var.get()
                server_config["SteamCMDPath"] = steamcmd_var.get()
                server_config["AutoUpdate"] = auto_update_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.update_server(server_name, server_config)
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 700, 600, self.root)
    
    def show_other_server_config(self, server_name, server_config):
        # Show generic server configuration dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Server Configuration - {server_name}")
        dialog.geometry("600x500")
        # Removed transient() and grab_set() to allow multiple windows
        
        # Main frame
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text=f"Server Configuration - {server_name}", 
                               font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Server Information
        info_frame = ttk.LabelFrame(main_frame, text="Server Information", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Server Name
        ttk.Label(info_frame, text="Server Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        name_var = tk.StringVar(value=server_name)
        ttk.Entry(info_frame, textvariable=name_var, width=40, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Server Type
        ttk.Label(info_frame, text="Server Type:").grid(row=1, column=0, sticky=tk.W, pady=5)
        type_var = tk.StringVar(value=server_config.get("Type", "Other"))
        ttk.Entry(info_frame, textvariable=type_var, width=40).grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Install Directory
        ttk.Label(info_frame, text="Install Directory:").grid(row=2, column=0, sticky=tk.W, pady=5)
        install_dir_var = tk.StringVar(value=server_config.get("InstallDir", ""))
        ttk.Entry(info_frame, textvariable=install_dir_var, width=40).grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        # Executable
        ttk.Label(info_frame, text="Server Executable:").grid(row=3, column=0, sticky=tk.W, pady=5)
        exe_var = tk.StringVar(value=server_config.get("ExecutablePath", ""))
        ttk.Entry(info_frame, textvariable=exe_var, width=40).grid(row=3, column=1, sticky=tk.W, padx=(10, 0), pady=5)
        
        def browse_executable():
            file_types = [("Executable Files", "*.exe;*.bat;*.cmd;*.ps1;*.sh;*.jar"), ("All Files", "*.*")] if os.name == 'nt' else [("All Files", "*")]
            exe_path = filedialog.askopenfilename(title="Select Server Executable", filetypes=file_types)
            if exe_path:
                exe_var.set(exe_path)
        
        ttk.Button(info_frame, text="Browse", command=browse_executable).grid(row=3, column=2, padx=(5, 0), pady=5)
        
        # Launch Configuration
        launch_frame = ttk.LabelFrame(main_frame, text="Launch Configuration", padding=10)
        launch_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Launch Arguments
        ttk.Label(launch_frame, text="Command Line Arguments:").pack(anchor=tk.W, pady=(0, 5))
        args_var = tk.StringVar(value=server_config.get("LaunchArgs", ""))
        args_text = tk.Text(launch_frame, height=8, width=70)
        args_text.insert(1.0, args_var.get())
        args_scroll = ttk.Scrollbar(launch_frame, orient=tk.VERTICAL, command=args_text.yview)
        args_text.configure(yscrollcommand=args_scroll.set)
        
        args_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        args_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Working Directory
        work_dir_frame = ttk.Frame(main_frame)
        work_dir_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(work_dir_frame, text="Working Directory:").pack(side=tk.LEFT)
        work_dir_var = tk.StringVar(value=server_config.get("WorkingDir", ""))
        ttk.Entry(work_dir_frame, textvariable=work_dir_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 5))
        
        def browse_work_dir():
            work_dir = filedialog.askdirectory(title="Select Working Directory")
            if work_dir:
                work_dir_var.set(work_dir)
        
        ttk.Button(work_dir_frame, text="Browse", command=browse_work_dir).pack(side=tk.RIGHT)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def on_save():
            try:
                # Update server configuration
                server_config["Type"] = type_var.get()
                server_config["InstallDir"] = install_dir_var.get()
                server_config["ExecutablePath"] = exe_var.get()
                server_config["LaunchArgs"] = args_text.get(1.0, tk.END).strip()
                server_config["WorkingDir"] = work_dir_var.get()
                server_config["LastUpdate"] = datetime.datetime.now().isoformat()
                
                # Save server configuration
                if self.server_manager:
                    self.server_manager.update_server(server_name, server_config)
                
                messagebox.showinfo("Success", f"Configuration saved for '{server_name}'!")
                dialog.destroy()
                
                # Refresh server list
                self.update_server_list(force_refresh=True)
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")
        
        def on_cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Save", command=on_save, width=12).pack(side=tk.RIGHT)
        
        # Centre dialog
        centre_window(dialog, 600, 500, self.root)

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
            # Get server config from server manager
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
                
            # Use the imported function to open directory
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
        current_subhost = self.get_current_subhost()
        
        if self.server_manager is None:
            messagebox.showerror("Error", "Server manager not initialised.")
            return
        
        # Remove server directly without confirmation dialog
        try:
            # Use server manager to remove/uninstall the server (keep files by default)
            if self.server_manager:
                success, message = self.server_manager.uninstall_server(
                    server_name, remove_files=False
                )
            else:
                success = False
                message = "Server manager not initialised"

            if success:
                # Update server list
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
            # Choose import type
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
            
            # Button frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(pady=20)
            
            def proceed_import():
                import_dialog.destroy()
                if import_type.get() == "directory":
                    self.import_server_from_directory()
                else:
                    self.import_server_from_export()
            
            def cancel_import():
                import_dialog.destroy()
            
            ttk.Button(button_frame, text="Continue", command=proceed_import, width=15).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(button_frame, text="Cancel", command=cancel_import, width=15).pack(side=tk.LEFT, padx=(0, 10))
            
            # Centre dialog
            centre_window(import_dialog, 400, 300, self.root)
            
        except Exception as e:
            logger.error(f"Error in import server: {str(e)}")
            messagebox.showerror("Error", f"Failed to open import dialog: {str(e)}")

    def import_server_from_directory(self):
        # Import an existing server from a directory (legacy method)
        result = import_server_from_directory_dialog(
            self.root, self.paths, self.server_manager_dir, 
            update_callback=lambda: self.update_server_list(force_refresh=True),
            dashboard_server_manager=self.server_manager
        )

    def import_server_from_export(self):
        # Import server from exported configuration file
        result = import_server_from_export_dialog(
            self.root, self.paths, self.server_manager_dir,
            update_callback=lambda: self.update_server_list(force_refresh=True)
        )

    def export_server(self):
        # Export server configuration for use on other hosts or clusters
        current_list = self.get_current_server_list()
        if current_list:
            result = export_server_dialog(self.root, current_list, self.paths)

    def refresh_all(self):
        # Refresh all dashboard data
        try:
            logger.info("Refreshing all dashboard data")

            # Update system information
            self.update_system_info()

            # Update server list
            self.update_server_list(force_refresh=True)

            # Update web server status
            self.update_webserver_status()

            # Silently complete the refresh without showing a dialog

        except Exception as e:
            logger.error(f"Error refreshing dashboard: {str(e)}")
            messagebox.showerror("Error", f"Failed to refresh dashboard: {str(e)}")

    def sync_all(self):
        # Synchronise all server data with the database
        try:
            if self.variables["offlineMode"]:
                messagebox.showinfo("Offline Mode", "Cannot sync while in offline mode.")
                return
                
            if not self.current_user:
                messagebox.showinfo("Authentication Required", "Please log in to synchronise data.")
                return
                
            # Create progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Synchronising Data")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            
            progress_frame = ttk.Frame(progress_dialog, padding=20)
            progress_frame.pack(fill=tk.BOTH, expand=True)
            
            status_label = ttk.Label(progress_frame, text="Starting synchronization...")
            status_label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=10)
            progress_bar.start()
            
            def sync_data():
                try:
                    status_label.config(text="Syncing server configurations...")
                    
                    # Get all server configurations from database
                    from Modules.Database.server_configs_database import ServerConfigManager
                    manager = ServerConfigManager()
                    synced_count = 0
                    
                    all_servers = manager.get_all_servers()
                    for server_config in all_servers:
                        server_name = server_config.get('Name', 'Unknown')
                        try:
                            # Update local configuration timestamp
                            server_config['LastSync'] = datetime.datetime.now().isoformat()
                            if self.current_user and hasattr(self.current_user, 'username'):
                                server_config['SyncedBy'] = getattr(self.current_user, 'username', 'Unknown') if self.current_user else 'Unknown'
                            else:
                                server_config['SyncedBy'] = "Unknown"
                            
                            # Save updated configuration to database
                            manager.update_server(server_name, server_config)
                            
                            synced_count += 1
                                
                        except Exception as e:
                            logger.error(f"Error syncing server {server_name}: {str(e)}")
                    
                    status_label.config(text=f"Synchronization complete. Synced {synced_count} servers.")
                    progress_bar.stop()
                    
                    # Auto-close after 2 seconds
                    progress_dialog.after(2000, progress_dialog.destroy)
                    
                    logger.info(f"Sync completed. {synced_count} servers synchronised.")
                    
                except Exception as e:
                    logger.error(f"Error during sync: {str(e)}")
                    status_label.config(text=f"Sync failed: {str(e)}")
                    progress_bar.stop()
                    
                    # Show error and close after 3 seconds
                    progress_dialog.after(3000, progress_dialog.destroy)
            
            # Start sync in a separate thread
            sync_thread = threading.Thread(target=sync_data, daemon=True)
            sync_thread.start()
            
            # Centre progress dialog relative to parent
            centre_window(progress_dialog, 400, 150, self.root)
            
        except Exception as e:
            logger.error(f"Error in sync all: {str(e)}")
            messagebox.showerror("Error", f"Failed to synchronise data: {str(e)}")

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
        
        # Get server configuration
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
        
        # Check if it's a Steam server
        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Update checking is only available for Steam servers.")
            return
        
        # Show progress dialog
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
                    
                    # Show result in main thread
                    def show_result():
                        if has_updates:
                            result = messagebox.askyesno("Updates Available", 
                                f"Updates are available for {server_name}.\n\nWould you like to update now?")
                            # Close progress dialog automatically after user responds
                            progress_dialog.complete("Check completed", auto_close=True)
                            if result:
                                self.update_server_now(server_name, server_config)
                        else:
                            messagebox.showinfo("No Updates", f"{server_name} is up to date.")
                            # Close progress dialog automatically after user clicks OK
                            progress_dialog.complete("Check completed", auto_close=True)
                    
                    self.root.after(0, show_result)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Check Failed", message)
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Check failed", auto_close=True)
                    self.root.after(0, show_error)
                
            except Exception as e:
                error_msg = f"Update check failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Check failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start check in background thread
        import threading
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
        current_subhost = self.get_current_subhost()
        
        if not self.server_manager:
            messagebox.showerror("Error", "Server manager not available.")
            return
        
        # Get server configuration
        server_config = self.server_manager.get_server_config(server_name)
        if not server_config:
            messagebox.showerror("Error", f"Server configuration not found for: {server_name}")
            return
        
        # Check if it's a Steam server
        if server_config.get('Type') != 'Steam' or not server_config.get('AppID'):
            messagebox.showinfo("Not Supported", f"{server_name} is not a Steam server. Updates are only available for Steam servers.")
            return
        
        # Confirm update
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
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, f"Updating Server - {server_name}")
        
        def update_worker():
            try:
                def progress_callback(message):
                    try:
                        # Use the update_console method which is more robust
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        else:
                            print(message)
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")
                
                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual updates
                    success, message = self.update_manager.update_server(
                        server_name, server_config, progress_callback=progress_callback, scheduled=False
                    )
                else:
                    success, message = False, "Update manager not available"
                
                if success:
                    progress_callback(f"[SUCCESS] {message}")
                    def show_success():
                        messagebox.showinfo("Update Complete", f"{server_name} has been updated successfully!")
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Update completed", auto_close=True)
                        # Refresh server list
                        self.update_server_list()
                    self.root.after(0, show_success)
                else:
                    progress_callback(f"[ERROR] {message}")
                    def show_error():
                        messagebox.showerror("Update Failed", message)
                        # Close progress dialog automatically after user clicks OK
                        progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_error)
                
            except Exception as e:
                error_msg = f"Server update failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Update failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start update in background thread
        import threading
        update_thread = threading.Thread(target=update_worker, daemon=True)
        update_thread.start()
    
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
    
    def show_database_sync_manager(self):
        # Show database sync configuration dialog
        if not self.timer_manager:
            messagebox.showerror("Error", "Scheduler not available.")
            return
        
        if not self.agent_manager:
            messagebox.showerror("Error", "Cluster manager not available. Database syncing requires cluster configuration.")
            return
        
        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Database Sync Manager")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="Database Synchronization", font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Status section
        status_frame = ttk.LabelFrame(main_frame, text="Current Status", padding=10)
        status_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Status variables
        sync_status = self.timer_manager.get_database_sync_status()
        
        status_text = "Enabled" if sync_status['enabled'] else "Disabled"
        status_color = "green" if sync_status['enabled'] else "red"
        
        status_label = ttk.Label(status_frame, text=f"Status: {status_text}", foreground=status_color)
        status_label.pack(anchor=tk.W)
        
        interval_label = ttk.Label(status_frame, text=f"Sync Interval: {sync_status['interval_seconds']} seconds")
        interval_label.pack(anchor=tk.W, pady=(5, 0))
        
        if sync_status['last_sync']:
            last_sync_label = ttk.Label(status_frame, text=f"Last Sync: {sync_status['last_sync']}")
            last_sync_label.pack(anchor=tk.W, pady=(5, 0))
        
        if sync_status['next_sync']:
            next_sync_label = ttk.Label(status_frame, text=f"Next Sync: {sync_status['next_sync']}")
            next_sync_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Configuration section
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=10)
        config_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Enable/Disable checkbox
        enabled_var = tk.BooleanVar(value=sync_status['enabled'])
        enabled_cb = ttk.Checkbutton(config_frame, text="Enable database synchronization", 
                                   variable=enabled_var)
        enabled_cb.pack(anchor=tk.W, pady=(0, 10))
        
        # Interval setting
        interval_frame = ttk.Frame(config_frame)
        interval_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(interval_frame, text="Sync interval (seconds):").pack(side=tk.LEFT)
        interval_var = tk.StringVar(value=str(sync_status['interval_seconds']))
        interval_entry = ttk.Entry(interval_frame, textvariable=interval_var, width=10)
        interval_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        # Info text
        info_text = ("Database synchronization will periodically sync server configurations, "
                    "user data, and cluster settings across all online cluster nodes.\n\n"
                    "This ensures consistency across your cluster and prevents configuration drift.")
        
        info_label = ttk.Label(config_frame, text=info_text, wraplength=400, justify=tk.LEFT)
        info_label.pack(anchor=tk.W, pady=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        def apply_settings():
            try:
                interval = int(interval_var.get())
                if interval < 60:
                    messagebox.showerror("Error", "Sync interval must be at least 60 seconds.")
                    return
                
                if enabled_var.get():
                    self.timer_manager.enable_database_sync(interval)
                    messagebox.showinfo("Success", "Database synchronization enabled.")
                else:
                    self.timer_manager.disable_database_sync()
                    messagebox.showinfo("Success", "Database synchronization disabled.")
                
                dialog.destroy()
                
            except ValueError:
                messagebox.showerror("Error", "Invalid interval value. Please enter a number.")
        
        def sync_now():
            if not sync_status['enabled']:
                messagebox.showerror("Error", "Database synchronization is disabled.")
                return
            
            # Run sync immediately
            import threading
            sync_thread = threading.Thread(target=self.timer_manager.sync_cluster_databases, daemon=True)
            sync_thread.start()
            
            messagebox.showinfo("Sync Started", "Database synchronization started in background.")
        
        apply_btn = ttk.Button(button_frame, text="Apply Settings", command=apply_settings)
        apply_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        sync_btn = ttk.Button(button_frame, text="Sync Now", command=sync_now)
        sync_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        cancel_btn = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_btn.pack(side=tk.RIGHT)
        
        # Centre dialog with multi-screen support
        dialog.update_idletasks()
        dialog_width = dialog.winfo_width()
        dialog_height = dialog.winfo_height()

        # Calculate center position relative to main window
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog_width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog_height) // 2

        # Get screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Ensure dialog stays within screen bounds
        x = max(0, min(x, screen_width - dialog_width))
        y = max(0, min(y, screen_height - dialog_height))

        dialog.geometry(f"+{x}+{y}")
    
    def update_all_servers(self, scheduled=False):
        # Update all Steam servers
        # scheduled: bool - If True, skip confirmation dialogs and close progress dialog automatically
        if not self.update_manager:
            if not scheduled:
                messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Confirm update only for manual updates
        if not scheduled:
            result = messagebox.askyesno("Confirm Update All", 
                "Are you sure you want to update all Steam servers?\n\n"
                "This will stop all running Steam servers during the update process.")
            
            if not result:
                return
        
        # Show progress dialog only for manual updates
        progress_dialog = None
        if not scheduled:
            progress_dialog = create_progress_dialog_with_console(self.root, "Updating All Steam Servers")
        
        def update_all_worker():
            try:
                def progress_callback(message):
                    try:
                        if progress_dialog and hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        elif not scheduled:
                            # For manual updates without progress dialog, print to console
                            print(message)
                        # For scheduled updates, log messages but don't show dialogs
                        if scheduled:
                            logger.info(message)
                    except Exception as e:
                        if not scheduled:
                            print(f"Console callback error: {e}, message: {message}")
                        logger.error(f"Console callback error: {e}, message: {message}")

                if self.update_manager:
                    # Use scheduled parameter to control dialog behaviour in update manager
                    results = self.update_manager.update_all_steam_servers(progress_callback=progress_callback, scheduled=scheduled)
                else:
                    results = {"error": (False, "Update manager not available")}
                
                # Count successes and failures
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                
                if progress_callback:
                    progress_callback(f"\n[SUMMARY] Updates complete: {successes} successful, {failures} failed")
                
                # Show detailed results only for manual updates
                def show_results():
                    if not scheduled:
                        # For manual updates, show results dialog
                        if failures > 0:
                            failed_servers = [name for name, (success, _) in results.items() if not success]
                            messagebox.showwarning("Some Updates Failed", 
                                f"Update completed with some failures.\n\n"
                                f"Successful: {successes}\nFailed: {failures}\n\n"
                                f"Failed servers: {', '.join(failed_servers)}")
                        else:
                            messagebox.showinfo("Updates Complete", 
                                f"All Steam servers updated successfully!\n\n"
                                f"Updated {successes} servers.")
                        
                        # Close progress dialog automatically after user clicks OK on results dialog
                        if progress_dialog:
                            progress_dialog.complete("Updates completed", auto_close=True)
                    else:
                        # For scheduled updates, just log the results
                        if failures > 0:
                            failed_servers = [name for name, (success, _) in results.items() if not success]
                            logger.warning(f"Scheduled update completed with failures. Successful: {successes}, Failed: {failures}. Failed servers: {', '.join(failed_servers)}")
                        else:
                            logger.info(f"Scheduled update completed successfully. Updated {successes} servers.")
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch update failed: {str(e)}"
                logger.error(error_msg)
                if not scheduled:
                    def show_exception_error():
                        messagebox.showerror("Error", error_msg)
                        # Close progress dialog automatically after user clicks OK
                        if progress_dialog:
                            progress_dialog.complete("Update failed", auto_close=True)
                    self.root.after(0, show_exception_error)
        
        # Start update in background thread
        import threading
        update_thread = threading.Thread(target=update_all_worker, daemon=True)
        update_thread.start()

    def restart_all_servers(self):
        # Restart all servers
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available.")
            return
        
        # Get list of all servers
        all_servers = []
        if self.server_manager:
            servers = self.server_manager.get_all_servers()
            all_servers = list(servers.keys())
        
        if not all_servers:
            messagebox.showinfo("No Servers", "No servers found to restart.")
            return
        
        # Confirm action
        result = messagebox.askyesno("Confirm Batch Restart", 
            f"Restart all {len(all_servers)} servers?\n\n"
            f"Servers to restart: {', '.join(all_servers)}")
        
        if not result:
            return
        
        # Show progress dialog
        progress_dialog = create_progress_dialog_with_console(self.root, "Restarting All Servers")
        
        def restart_all_worker():
            try:
                def progress_callback(message):
                    try:
                        # Use the update_console method which is more robust
                        if hasattr(progress_dialog, 'update_console'):
                            progress_dialog.update_console(message)
                        else:
                            print(message)
                    except Exception as e:
                        print(f"Console callback error: {e}, message: {message}")

                if self.update_manager:
                    # Use scheduled=False to ensure full console output for manual batch restarts
                    results = self.update_manager.restart_all_servers(progress_callback=progress_callback, scheduled=False)
                else:
                    results = {"error": (False, "Update manager not available")}
                
                # Count successes and failures
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                
                progress_callback(f"\n[SUMMARY] Restarts complete: {successes} successful, {failures} failed")
                
                # Show detailed results
                def show_results():
                    if failures > 0:
                        failed_servers = [name for name, (success, _) in results.items() if not success]
                        messagebox.showwarning("Some Restarts Failed", 
                            f"Restart completed with some failures.\n\n"
                            f"Successful: {successes}\nFailed: {failures}\n\n"
                            f"Failed servers: {', '.join(failed_servers)}")
                    else:
                        messagebox.showinfo("Restarts Complete", 
                            f"All servers restarted successfully!\n\n"
                            f"Restarted {successes} servers.")
                    
                    # Close progress dialog automatically after user clicks OK on results dialog
                    progress_dialog.complete("Restarts completed", auto_close=True)
                    
                    # Refresh server list
                    self.update_server_list()
                
                self.root.after(0, show_results)
                
            except Exception as e:
                error_msg = f"Batch restart failed: {str(e)}"
                logger.error(error_msg)
                def show_exception_error():
                    messagebox.showerror("Error", error_msg)
                    # Close progress dialog automatically after user clicks OK
                    progress_dialog.complete("Restart failed", auto_close=True)
                self.root.after(0, show_exception_error)
        
        # Start restart in background thread
        import threading
        restart_thread = threading.Thread(target=restart_all_worker, daemon=True)
        restart_thread.start()

    def show_console_manager(self):
        # Show console manager dialog with list of active consoles
        try:
            if not self.console_manager:
                messagebox.showinfo("Console Manager", "Console manager not available.")
                return

            # Use the built-in console management window
            self.console_manager.show_console_manager_window(self.root)

        except Exception as e:
            log_exception(e, "Error showing console manager")
            messagebox.showerror("Console Manager Error", f"Failed to show console manager:\n{str(e)}")

    def open_automation_settings(self):
        # Open the automation settings window
        try:
            from Modules.automation_ui import open_automation_settings
            open_automation_settings(self.root, self.server_manager)
        except Exception as e:
            log_exception(e, "Error opening automation settings")
            messagebox.showerror("Automation Settings Error", f"Failed to open automation settings:\n{str(e)}")

    def batch_update_server_types(self):
        # Batch update all server types using database-based detection
        try:
            # Show confirmation dialog first
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
            
            # Show progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Updating Server Types")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            centre_window(progress_dialog, 400, 150, self.root)
            
            # Progress frame
            progress_frame = ttk.Frame(progress_dialog, padding=20)
            progress_frame.pack(fill=tk.BOTH, expand=True)
            
            status_var = tk.StringVar(value="Analysing server configurations...")
            status_label = ttk.Label(progress_frame, textvariable=status_var)
            status_label.pack(pady=(0, 10))
            
            progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
            progress_bar.pack(fill=tk.X, pady=(0, 20))
            progress_bar.start(10)
            
            # Run the update in a separate thread to avoid freezing UI
            def run_update():
                try:
                    # Perform batch update
                    updated_count, updated_servers = batch_update_server_types(self.paths)
                    
                    # Update UI in main thread
                    self.root.after(0, update_complete, updated_count, updated_servers)
                    
                except Exception as e:
                    # Handle error in main thread
                    self.root.after(0, update_error, str(e))
            
            def update_complete(count, servers):
                progress_bar.stop()
                progress_dialog.destroy()
                
                if count == 0:
                    messagebox.showinfo(
                        "Update Complete",
                        "No server type updates were needed. All servers are already correctly classified."
                    )
                else:
                    # Show results dialog
                    result_msg = f"Successfully updated {count} server(s):\n\n"
                    for server in servers[:10]:
                        result_msg += f"• {server['name']}: {server['old_type']} → {server['new_type']}\n"
                    
                    if len(servers) > 10:
                        result_msg += f"... and {len(servers) - 10} more\n"
                    
                    result_msg += f"\nPlease refresh the server list to see the changes."
                    
                    messagebox.showinfo("Update Complete", result_msg)
                
                # Refresh the server list
                self.update_server_list(force_refresh=True)
            
            def update_error(error_msg):
                progress_bar.stop()
                progress_dialog.destroy()
                messagebox.showerror("Update Error", f"Failed to update server types:\n{error_msg}")
            
            # Start the update thread
            import threading
            update_thread = threading.Thread(target=run_update, daemon=True)
            update_thread.start()
            
        except Exception as e:
            log_exception(e, "Error in batch update server types")
            messagebox.showerror("Update Error", f"Failed to update server types:\n{str(e)}")

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
        current_subhost = self.get_current_subhost()
        
        # Confirm action
        if not messagebox.askyesno("Kill Process", 
                                 f"Are you sure you want to forcefully kill the process for '{server_name}'?\n\nThis action cannot be undone and may cause data loss.",
                                 parent=self.root):
            return
        
        # Try to kill via console manager first
        if self.console_manager and hasattr(self.console_manager, 'kill_process'):
            if self.console_manager.kill_process(server_name):
                # Also clean up the server config to remove stale PID
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
            # Get server configuration
            if self.server_manager:
                server_config = self.server_manager.get_server_config(server_name)
                if server_config:
                    # Try to find process by executable path
                    exe_path = server_config.get('ExecutablePath', '')
                    if exe_path and os.path.exists(exe_path):
                        import psutil
                        exe_name = os.path.basename(exe_path)
                        
                        # Look for processes with matching executable name
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
                            # Clear PID from config and console state
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            self.server_manager.update_server(server_name, server_config)
                            
                            # Clean up console state
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

    def create_category(self):
        # Create a new server category
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        # Prompt for category name
        category_name = simpledialog.askstring("Create Category", "Enter category name:", parent=self.root)
        if not category_name or not category_name.strip():
            return

        category_name = category_name.strip()

        # Check if category already exists
        categories = load_categories(self.server_manager_dir)
        if category_name in categories:
            messagebox.showerror("Error", f"Category '{category_name}' already exists.")
            return

        # Add category to database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.add_category(category_name):
            # Refresh categories in the UI
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

        item = selected_items[0]
        item_values = current_list.item(item)['values']

        # Check if this is a category (no server name in second column)
        if item_values[1]:  # Has server name, so it's a server
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        current_name = item_values[0]

        # Prompt for new category name
        new_name = simpledialog.askstring("Rename Category", "Enter new category name:", initialvalue=current_name, parent=self.root)
        if not new_name or not new_name.strip() or new_name.strip() == current_name:
            return

        new_name = new_name.strip()

        # Check if new name already exists
        categories = load_categories(self.server_manager_dir)
        if new_name in categories:
            messagebox.showerror("Error", f"Category '{new_name}' already exists.")
            return

        # Rename category in database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.rename_category(current_name, new_name):
            # Update server configurations
            self._update_servers_category(current_name, new_name)

            # Refresh categories in the UI
            self.refresh_categories()

            logger.info(f"Renamed category from '{current_name}' to '{new_name}'")
        else:
            messagebox.showerror("Error", f"Failed to rename category '{current_name}'.")

    def delete_category(self):
        # Delete a category and move all servers to "Uncategorized"
        current_list = self.get_current_server_list()
        if not current_list:
            messagebox.showinfo("No Selection", "No server list available.")
            return

        selected_items = current_list.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a category first.")
            return

        item = selected_items[0]
        item_values = current_list.item(item)['values']

        # Check if this is a category (no server name in second column)
        if item_values[1]:  # Has server name, so it's a server
            messagebox.showerror("Error", "Please select a category, not a server.")
            return

        category_name = item_values[0]

        # Don't allow deleting "Uncategorized"
        if category_name == "Uncategorized":
            messagebox.showerror("Error", "Cannot delete the 'Uncategorized' category.")
            return

        # Confirm deletion
        if not messagebox.askyesno("Delete Category", 
                                 f"Are you sure you want to delete the category '{category_name}'?\n\nAll servers in this category will be moved to 'Uncategorized'.",
                                 parent=self.root):
            return

        # Delete category from database
        from Modules.Database.cluster_database import ClusterDatabase
        db = ClusterDatabase()
        if db.delete_category(category_name):
            # Update server configurations
            self._update_servers_category(category_name, "Uncategorized")

            # Refresh categories in the UI
            self.refresh_categories()

            logger.info(f"Deleted category '{category_name}', moved servers to 'Uncategorized'")
        else:
            messagebox.showerror("Error", f"Failed to delete category '{category_name}'.")

    def _update_servers_category(self, old_category, new_category):
        # Update the category for all servers in the old category to the new category
        try:
            # Get all servers from database
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            all_servers = manager.get_all_servers()

            updated_count = 0
            for server_config in all_servers:
                server_name = server_config.get('Name', 'Unknown')
                try:
                    # Update category if it matches the old category
                    if server_config.get('Category') == old_category:
                        server_config['Category'] = new_category

                        # Save updated configuration to database
                        manager.update_server(server_name, server_config)

                        updated_count += 1

                except Exception as e:
                    logger.error(f"Error updating category for server {server_name}: {str(e)}")

            if updated_count > 0:
                logger.info(f"Updated category from '{old_category}' to '{new_category}' for {updated_count} servers")

        except Exception as e:
            logger.error(f"Error updating server categories: {str(e)}")

    def refresh_categories(self):
        # Refresh only the category structure in the current server list without full server refresh
        current_list = self.get_current_server_list()
        if not current_list:
            logger.warning("refresh_categories: No current server list available")
            return

        logger.debug("refresh_categories: Starting category refresh")

        # Get current servers data (preserve existing data)
        # We need to iterate through category items and their children
        current_servers = {}
        for category_item in current_list.get_children():
            try:
                # Get children (servers) of this category
                for server_item in current_list.get_children(category_item):
                    try:
                        item = current_list.item(server_item)
                        if item and 'values' in item and len(item['values']) >= 1:
                            values = item['values']
                            server_name = values[0]
                            if server_name and len(values) > 1 and values[1]:  # Has server name and status
                                current_servers[server_name] = {
                                    'status': values[1] if len(values) > 1 else 'Unknown',
                                    'pid': values[2] if len(values) > 2 else '',
                                    'cpu': values[3] if len(values) > 3 else '0%',
                                    'memory': values[4] if len(values) > 4 else '0 MB',
                                    'uptime': values[5] if len(values) > 5 else '00:00:00',
                                    'category': 'Uncategorized'  # Will be updated from server config
                                }
                    except Exception as e:
                        logger.debug(f"Error processing server item {server_item}: {e}")
            except Exception as e:
                logger.debug(f"Error processing category item {category_item}: {e}")

        logger.debug(f"refresh_categories: Found {len(current_servers)} servers to reorganise")

        # Get updated categories from database
        from Host.dashboard_functions import load_categories
        all_categories = load_categories(self.server_manager_dir)
        logger.debug(f"refresh_categories: Loaded {len(all_categories)} categories from database")

        # Clear existing items
        for item in current_list.get_children():
            current_list.delete(item)

        # Group servers by category
        categories = {}
        for category in all_categories:
            categories[category] = []

        # Get server categories from their configurations (get from server manager for fresh data)
        for server_name in current_servers.keys():
            try:
                # Get category from server manager
                if self.server_manager:
                    server_config = self.server_manager.get_server_config(server_name)
                    if server_config:
                        category = server_config.get('Category', 'Uncategorized')
                    else:
                        category = 'Uncategorized'
                else:
                    category = 'Uncategorized'
                current_servers[server_name]['category'] = category
                logger.debug(f"refresh_categories: Server '{server_name}' -> category '{category}'")
            except Exception as e:
                logger.debug(f"Error getting category for {server_name}: {e}")
                current_servers[server_name]['category'] = 'Uncategorized'

        for server_name, server_info in current_servers.items():
            category = server_info.get('category', 'Uncategorized')
            if category not in categories:
                categories[category] = []
            categories[category].append((server_name, server_info))

        # Add categories and servers to Treeview
        for category_name in all_categories:
            servers = categories.get(category_name, [])

            # Insert category as parent (even if empty)
            category_item = current_list.insert("", tk.END, text=category_name,
                                             values=(category_name, "", "", "", "", ""),
                                             open=True, tags=('category',))

            # Add servers under category
            for server_name, server_info in servers:
                try:
                    status = server_info.get('status', 'Unknown')
                    pid = server_info.get('pid', '')
                    cpu = server_info.get('cpu', '0%')
                    memory = server_info.get('memory', '0 MB')
                    uptime = server_info.get('uptime', '00:00:00')

                    current_list.insert(category_item, tk.END, values=(
                        server_name, status, pid, cpu, memory, uptime
                    ), tags=('server',))
                except Exception as e:
                    logger.error(f"Error adding server {server_name} to category refresh: {e}")

        logger.info(f"Categories refreshed successfully - {len(current_servers)} servers in {len(all_categories)} categories")

    def find_broken_servers(self):
        # Find and display servers that are broken or have issues
        try:
            if self.server_manager is None:
                messagebox.showerror("Error", "Server manager not available")
                return
                
            logger.info("Searching for broken servers...")
            
            broken_servers = []
            all_servers = self.server_manager.get_all_servers()
            
            for server_name, server_config in all_servers.items():
                issues = []
                
                # Check if server directory exists
                install_dir = server_config.get('InstallDir', '')
                if install_dir and not os.path.exists(install_dir):
                    issues.append(f"Directory missing: {install_dir}")
                
                # Check if executable exists
                executable = server_config.get('ExecutablePath', '')
                if executable:
                    if not os.path.isabs(executable):
                        # Relative path - check relative to install dir
                        full_exe_path = os.path.join(install_dir, executable) if install_dir else executable
                    else:
                        full_exe_path = executable
                    
                    if not os.path.exists(full_exe_path):
                        issues.append(f"Executable missing: {full_exe_path}")
                
                # Check for required configuration fields
                required_fields = ['Name', 'Type', 'InstallDir']
                for field in required_fields:
                    if not server_config.get(field):
                        issues.append(f"Missing required field: {field}")
                
                # Check if server type is valid
                server_type = server_config.get('Type', '')
                if server_type not in ['Steam', 'Minecraft', 'Other']:
                    issues.append(f"Invalid server type: {server_type}")
                
                # Check for Steam servers without AppID
                if server_type == 'Steam' and not server_config.get('AppID'):
                    issues.append("Steam server missing AppID")
                
                # Check for processes that should be running but aren't
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
            
            # Display results
            if broken_servers:
                # Create dialog to show broken servers
                import tkinter as tk
                from tkinter import ttk, scrolledtext
                
                dialog = tk.Toplevel(self.root)
                dialog.title("Broken Servers Found")
                dialog.geometry("800x600")
                dialog.resizable(True, True)
                dialog.transient(self.root)
                
                # Centre dialog
                dialog.update_idletasks()
                x = (dialog.winfo_screenwidth() // 2) - (400)
                y = (dialog.winfo_screenheight() // 2) - (300)
                dialog.geometry(f"+{x}+{y}")
                
                # Main frame
                main_frame = ttk.Frame(dialog, padding=10)
                main_frame.pack(fill=tk.BOTH, expand=True)
                
                # Title
                title_label = ttk.Label(main_frame, text=f"Found {len(broken_servers)} broken server(s)", 
                                      font=("Segoe UI", 14, "bold"))
                title_label.pack(pady=(0, 10))
                
                # Scrolled text for results
                text_frame = ttk.Frame(main_frame)
                text_frame.pack(fill=tk.BOTH, expand=True)
                
                text_widget = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=("Consolas", 10))
                text_widget.pack(fill=tk.BOTH, expand=True)
                
                # Add broken server information
                for server in broken_servers:
                    text_widget.insert(tk.END, f"Server: {server['name']}\n", "server_name")
                    text_widget.insert(tk.END, f"Type: {server['config'].get('Type', 'Unknown')}\n")
                    text_widget.insert(tk.END, f"Directory: {server['config'].get('InstallDir', 'Not set')}\n")
                    text_widget.insert(tk.END, "Issues:\n")
                    
                    for issue in server['issues']:
                        text_widget.insert(tk.END, f"  • {issue}\n", "issue")
                    
                    text_widget.insert(tk.END, "\n" + "="*50 + "\n\n")
                
                # Configure tags
                text_widget.tag_config("server_name", foreground="blue", font=("Consolas", 10, "bold"))
                text_widget.tag_config("issue", foreground="red")
                
                text_widget.config(state=tk.DISABLED)  # Make read-only
                
                # Buttons
                button_frame = ttk.Frame(main_frame)
                button_frame.pack(fill=tk.X, pady=(10, 0))
                
                ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
                
                logger.info(f"Found {len(broken_servers)} broken servers")
            else:
                messagebox.showinfo("No Broken Servers", "All servers appear to be configured correctly!")
                logger.info("No broken servers found")
                
        except Exception as e:
            logger.error(f"Error finding broken servers: {str(e)}")
            messagebox.showerror("Error", f"Failed to search for broken servers: {str(e)}")

    def verify_servers(self):
        # Verify server information completeness - check for missing required fields
        try:
            if self.server_manager is None:
                messagebox.showerror("Error", "Server manager not available")
                return
                
            logger.info("Verifying server information completeness...")
            
            incomplete_servers = []
            all_servers = self.server_manager.get_all_servers()
            
            for server_name, server_config in all_servers.items():
                missing_info = []
                
                # Check for required fields that are empty or None
                required_fields = {
                    'Name': 'Server name',
                    'Type': 'Server type (Steam/Minecraft/Other)',
                    'InstallDir': 'Installation directory'
                }
                
                for field, description in required_fields.items():
                    value = server_config.get(field)
                    if value is None or (isinstance(value, str) and value.strip() == ''):
                        missing_info.append(f"Missing {description}")
                
                # Check Steam-specific required fields
                server_type = server_config.get('Type', '')
                if server_type == 'Steam':
                    if not server_config.get('AppID'):
                        missing_info.append("Missing Steam AppID")
                    if not server_config.get('ExecutablePath'):
                        missing_info.append("Missing executable path")
                
                # Check for optional but recommended fields
                recommended_fields = {
                    'Category': 'Server category',
                    'Description': 'Server description',
                    'MaxPlayers': 'Maximum players setting'
                }
                
                for field, description in recommended_fields.items():
                    if not server_config.get(field):
                        missing_info.append(f"Recommended: {description}")
                
                # Check for configuration file paths if they should exist
                install_dir = server_config.get('InstallDir', '')
                if install_dir and os.path.exists(install_dir):
                    # Check for common config files based on server type
                    if server_type == 'Minecraft':
                        config_files = ['server.properties', 'eula.txt']
                        for config_file in config_files:
                            config_path = os.path.join(install_dir, config_file)
                            if not os.path.exists(config_path):
                                missing_info.append(f"Missing Minecraft config: {config_file}")
                    
                    elif server_type == 'Steam':
                        # Check for common Steam server config files
                        steam_config_files = ['server.cfg', 'serverconfig.xml', 'config.cfg']
                        found_config = False
                        for config_file in steam_config_files:
                            if os.path.exists(os.path.join(install_dir, config_file)):
                                found_config = True
                                break
                        if not found_config:
                            missing_info.append("No server configuration file found")
                
                if missing_info:
                    incomplete_servers.append({
                        'name': server_name,
                        'missing_info': missing_info,
                        'config': server_config
                    })
            
            # Display results
            if incomplete_servers:
                # Create dialog to show incomplete server information
                import tkinter as tk
                from tkinter import ttk, scrolledtext
                
                dialog = tk.Toplevel(self.root)
                dialog.title("Server Information Verification")
                dialog.geometry("800x600")
                dialog.resizable(True, True)
                dialog.transient(self.root)
                
                # Centre dialog
                dialog.update_idletasks()
                x = (dialog.winfo_screenwidth() // 2) - (400)
                y = (dialog.winfo_screenheight() // 2) - (300)
                dialog.geometry(f"+{x}+{y}")
                
                # Main frame
                main_frame = ttk.Frame(dialog, padding=10)
                main_frame.pack(fill=tk.BOTH, expand=True)
                
                # Title
                title_label = ttk.Label(main_frame, text=f"Found {len(incomplete_servers)} server(s) with incomplete information", 
                                      font=("Segoe UI", 14, "bold"))
                title_label.pack(pady=(0, 10))
                
                # Scrolled text for results
                text_frame = ttk.Frame(main_frame)
                text_frame.pack(fill=tk.BOTH, expand=True)
                
                text_widget = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=("Consolas", 10))
                text_widget.pack(fill=tk.BOTH, expand=True)
                
                # Add incomplete server information
                for server in incomplete_servers:
                    text_widget.insert(tk.END, f"Server: {server['name']}\n", "server_name")
                    text_widget.insert(tk.END, f"Type: {server['config'].get('Type', 'Unknown')}\n")
                    text_widget.insert(tk.END, f"Directory: {server['config'].get('InstallDir', 'Not set')}\n")
                    text_widget.insert(tk.END, "Missing/Recommended Information:\n")
                    
                    for info in server['missing_info']:
                        if info.startswith("Missing"):
                            text_widget.insert(tk.END, f"  • {info}\n", "missing")
                        else:
                            text_widget.insert(tk.END, f"  • {info}\n", "recommended")
                    
                    text_widget.insert(tk.END, "\n" + "="*50 + "\n\n")
                
                # Configure tags
                text_widget.tag_config("server_name", foreground="blue", font=("Consolas", 10, "bold"))
                text_widget.tag_config("missing", foreground="red")
                text_widget.tag_config("recommended", foreground="orange")
                
                text_widget.config(state=tk.DISABLED)  # Make read-only
                
                # Buttons
                button_frame = ttk.Frame(main_frame)
                button_frame.pack(fill=tk.X, pady=(10, 0))
                
                ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
                
                logger.info(f"Found {len(incomplete_servers)} servers with incomplete information")
            else:
                messagebox.showinfo("Server Verification Complete", "All servers have complete information!")
                logger.info("All servers have complete information")
                
        except Exception as e:
            logger.error(f"Error verifying server information: {str(e)}")
            messagebox.showerror("Error", f"Failed to verify server information: {str(e)}")

    def show_help(self):
        # Show help dialog using the documentation module
        show_help_dialog(self.root, logger)

    def show_settings_dialog(self):
        # Show settings dialog for editing configuration
        import tkinter as tk
        from tkinter import ttk, messagebox
        
        # Create settings dialog
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("800x600")
        settings_window.resizable(True, True)
        # Removed transient() and grab_set() to allow multiple windows
        
        # Centre the dialog
        settings_window.update_idletasks()
        x = (settings_window.winfo_screenwidth() // 2) - (settings_window.winfo_width() // 2)
        y = (settings_window.winfo_screenheight() // 2) - (settings_window.winfo_height() // 2)
        settings_window.geometry(f"+{x}+{y}")
        
        # Create notebook for different settings categories
        notebook = ttk.Notebook(settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Dashboard Settings Tab
        dashboard_frame = ttk.Frame(notebook)
        notebook.add(dashboard_frame, text="Dashboard")
        
        # Cluster Settings Tab
        cluster_frame = ttk.Frame(notebook)
        notebook.add(cluster_frame, text="Cluster")
        
        # Update Settings Tab
        update_frame = ttk.Frame(notebook)
        notebook.add(update_frame, text="Updates")
        
        # Steam Settings Tab
        steam_frame = ttk.Frame(notebook)
        notebook.add(steam_frame, text="Steam")
        
        # System Settings Tab
        system_frame = ttk.Frame(notebook)
        notebook.add(system_frame, text="System")
        
        # Load current configurations
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
        
        # Dashboard Settings
        self._create_dashboard_settings_tab(dashboard_frame, dashboard_config, db)
        
        # Cluster Settings
        self._create_cluster_settings_tab(cluster_frame, db)
        
        # Update Settings
        self._create_update_settings_tab(update_frame, update_config, db)
        
        # Steam Settings
        self._create_steam_settings_tab(steam_frame, db)
        
        # System Settings
        self._create_system_settings_tab(system_frame, main_config, db)
        
        # Buttons
        button_frame = ttk.Frame(settings_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="Save", command=lambda: self._save_settings(settings_window, db)).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Cancel", command=settings_window.destroy).pack(side=tk.RIGHT)
        
        # Store reference to prevent garbage collection
        self.settings_window = settings_window
    
    def _create_dashboard_settings_tab(self, parent, config, db):
        # Create dashboard settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Dashboard settings
        settings = [
            ("Debug Mode", "configuration.debugMode", config.get("configuration.debugMode", False), "boolean"),
            ("Offline Mode", "configuration.offlineMode", config.get("configuration.offlineMode", False), "boolean"),
            ("Hide Server Consoles", "configuration.hideServerConsoles", config.get("configuration.hideServerConsoles", True), "boolean"),
            ("System Refresh Interval", "configuration.systemRefreshInterval", config.get("configuration.systemRefreshInterval", 4), "integer"),
            ("Process Monitoring Interval", "configuration.processMonitoringInterval", config.get("configuration.processMonitoringInterval", 5), "integer"),
            ("Network Update Interval", "configuration.networkUpdateInterval", config.get("configuration.networkUpdateInterval", 5), "integer"),
            ("Server List Update Interval", "configuration.serverListUpdateInterval", config.get("configuration.serverListUpdateInterval", 30), "integer"),
            ("Window Width", "ui.windowWidth", config.get("ui.windowWidth", 1200), "integer"),
            ("Window Height", "ui.windowHeight", config.get("ui.windowHeight", 700), "integer"),
        ]
        
        self._create_settings_controls(scrollable_frame, settings, "dashboard")
    
    def _create_cluster_settings_tab(self, parent, db):
        # Create cluster settings controls
        from Modules.common import REGISTRY_PATH, get_registry_value, set_registry_value
        
        main_frame = ttk.Frame(parent, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="Cluster Configuration", font=("Segoe UI", 12, "bold"))
        title_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Description
        desc_label = ttk.Label(main_frame, text="Configure this installation's role in a Server Manager cluster.\nChanges require a restart to take effect.", wraplength=700)
        desc_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Get current role from registry
        current_role = get_registry_value(REGISTRY_PATH, "HostType", "Host")
        current_host_address = get_registry_value(REGISTRY_PATH, "HostAddress", "")
        
        # Role selection frame
        role_frame = ttk.LabelFrame(main_frame, text="Cluster Role", padding=10)
        role_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.cluster_role_var = tk.StringVar(value=current_role)
        
        # Host radio button
        host_radio = ttk.Radiobutton(role_frame, text="Host (Master)", variable=self.cluster_role_var, value="Host")
        host_radio.pack(anchor=tk.W, pady=2)
        
        host_desc = ttk.Label(role_frame, text="This installation manages subhosts and accepts cluster join requests.", foreground="gray")
        host_desc.pack(anchor=tk.W, padx=(20, 0), pady=(0, 10))
        
        # Subhost radio button
        subhost_radio = ttk.Radiobutton(role_frame, text="Subhost (Slave)", variable=self.cluster_role_var, value="Subhost")
        subhost_radio.pack(anchor=tk.W, pady=2)
        
        subhost_desc = ttk.Label(role_frame, text="This installation connects to a master host for centralized management.", foreground="gray")
        subhost_desc.pack(anchor=tk.W, padx=(20, 0), pady=(0, 5))
        
        # Master host address frame (shown when Subhost is selected)
        master_frame = ttk.Frame(role_frame)
        master_frame.pack(fill=tk.X, padx=(20, 0), pady=(5, 0))
        
        ttk.Label(master_frame, text="Master Host IP:").pack(side=tk.LEFT)
        self.master_ip_var = tk.StringVar(value=current_host_address)
        self.master_ip_entry = ttk.Entry(master_frame, textvariable=self.master_ip_var, width=20)
        self.master_ip_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        # Update master IP entry state based on role
        def update_master_ip_state(*args):
            if self.cluster_role_var.get() == "Subhost":
                self.master_ip_entry.configure(state="normal")
            else:
                self.master_ip_entry.configure(state="disabled")
        
        self.cluster_role_var.trace_add("write", update_master_ip_state)
        update_master_ip_state()  # Set initial state
        
        # Pending requests section (only shown for hosts)
        if current_role == "Host":
            requests_frame = ttk.LabelFrame(main_frame, text="Pending Join Requests", padding=10)
            requests_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
            
            # Treeview for pending requests
            columns = ("id", "machine", "ip", "requested")
            requests_tree = ttk.Treeview(requests_frame, columns=columns, show="headings", height=5)
            requests_tree.heading("id", text="ID")
            requests_tree.heading("machine", text="Machine Name")
            requests_tree.heading("ip", text="IP Address")
            requests_tree.heading("requested", text="Requested At")
            
            requests_tree.column("id", width=150)
            requests_tree.column("machine", width=150)
            requests_tree.column("ip", width=120)
            requests_tree.column("requested", width=150)
            
            requests_scrollbar = ttk.Scrollbar(requests_frame, orient=tk.VERTICAL, command=requests_tree.yview)
            requests_tree.configure(yscrollcommand=requests_scrollbar.set)
            
            requests_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            requests_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            # Load pending requests
            try:
                pending = db.get_pending_requests()
                for req in pending:
                    if req['status'] == 'pending':
                        requests_tree.insert("", tk.END, values=(
                            req['node_name'],
                            req.get('machine_name', 'Unknown'),
                            req.get('ip_address', 'Unknown'),
                            req.get('requested_at', 'Unknown')
                        ))
            except Exception as e:
                logger.error(f"Failed to load pending requests: {e}")
            
            # Approve/Reject buttons
            button_frame = ttk.Frame(requests_frame)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            def approve_selected():
                selection = requests_tree.selection()
                if not selection:
                    messagebox.showwarning("No Selection", "Please select a request to approve.")
                    return
                    
                for item in selection:
                    values = requests_tree.item(item, 'values')
                    node_name = values[0]
                    try:
                        # Find the request_id for this node_name
                        pending = db.get_pending_requests()
                        request_id = None
                        for req in pending:
                            if req['node_name'] == node_name and req['status'] == 'pending':
                                request_id = req['id']
                                break
                        
                        if request_id is None:
                            messagebox.showerror("Error", f"Could not find pending request for {node_name}")
                            continue
                        
                        # Generate approval token
                        import secrets
                        approval_token = secrets.token_urlsafe(32)
                        
                        # Approve the request using the correct method
                        if db.approve_request(request_id, "admin", approval_token):
                            # Also add to cluster nodes
                            req_data = next((r for r in pending if r['id'] == request_id), None)
                            if req_data:
                                db.add_cluster_node(
                                    name=node_name,
                                    ip_address=req_data.get('ip_address', ''),
                                    port=req_data.get('port', 8080),
                                    node_type='subhost',
                                    cluster_token=approval_token,
                                    hostname=req_data.get('machine_name', '')
                                )
                            requests_tree.delete(item)
                            messagebox.showinfo("Approved", f"Request from {node_name} has been approved.")
                        else:
                            messagebox.showerror("Error", f"Failed to approve request from {node_name}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to approve: {e}")
            
            def reject_selected():
                selection = requests_tree.selection()
                if not selection:
                    messagebox.showwarning("No Selection", "Please select a request to reject.")
                    return
                    
                for item in selection:
                    values = requests_tree.item(item, 'values')
                    node_name = values[0]
                    try:
                        # Find the request_id for this node_name
                        pending = db.get_pending_requests()
                        request_id = None
                        for req in pending:
                            if req['node_name'] == node_name and req['status'] == 'pending':
                                request_id = req['id']
                                break
                        
                        if request_id is None:
                            messagebox.showerror("Error", f"Could not find pending request for {node_name}")
                            continue
                        
                        # Reject the request using the correct method
                        if db.reject_request(request_id, "admin"):
                            requests_tree.delete(item)
                            messagebox.showinfo("Rejected", f"Request from {node_name} has been rejected.")
                        else:
                            messagebox.showerror("Error", f"Failed to reject request from {node_name}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to reject: {e}")
            
            def refresh_requests():
                # Clear existing
                for item in requests_tree.get_children():
                    requests_tree.delete(item)
                # Reload
                try:
                    pending = db.get_pending_requests()
                    for req in pending:
                        if req['status'] == 'pending':
                            requests_tree.insert("", tk.END, values=(
                                req['node_name'],
                                req.get('machine_name', 'Unknown'),
                                req.get('ip_address', 'Unknown'),
                                req.get('requested_at', 'Unknown')
                            ))
                except Exception as e:
                    logger.error(f"Failed to refresh pending requests: {e}")
            
            ttk.Button(button_frame, text="Approve", command=approve_selected).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Reject", command=reject_selected).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Refresh", command=refresh_requests).pack(side=tk.LEFT)
            
            # Auto-refresh indicator
            auto_refresh_label = ttk.Label(button_frame, text="Auto-refresh: 10s", foreground="gray")
            auto_refresh_label.pack(side=tk.RIGHT, padx=(10, 0))
            
            # Auto-refresh timer for pending requests
            def auto_refresh():
                try:
                    # Only refresh if the parent widget still exists
                    if requests_frame.winfo_exists():
                        refresh_requests()
                        # Schedule next refresh after 10 seconds
                        requests_frame.after(10000, auto_refresh)
                except Exception:
                    pass  # Widget may have been destroyed
            
            # Start auto-refresh after initial load (delay by 10 seconds)
            requests_frame.after(10000, auto_refresh)
        
        # Save cluster settings function
        def save_cluster_settings():
            new_role = self.cluster_role_var.get()
            new_host_address = self.master_ip_var.get().strip() if new_role == "Subhost" else ""
            
            # Validate subhost settings
            if new_role == "Subhost" and not new_host_address:
                messagebox.showerror("Validation Error", "Master Host IP is required for Subhost mode.")
                return False
            
            try:
                from Modules.common import REGISTRY_PATH, set_registry_value
                set_registry_value(REGISTRY_PATH, "HostType", new_role)
                set_registry_value(REGISTRY_PATH, "HostAddress", new_host_address)
                
                logger.info(f"Cluster settings updated - Role: {new_role}, Master: {new_host_address}")
                messagebox.showinfo("Settings Saved", "Cluster settings saved successfully.\nPlease restart the application for changes to take effect.")
                return True
            except Exception as e:
                logger.error(f"Failed to save cluster settings: {e}")
                messagebox.showerror("Error", f"Failed to save cluster settings: {e}")
                return False
        
        # Save button for cluster settings
        save_btn = ttk.Button(main_frame, text="Save Cluster Settings", command=save_cluster_settings)
        save_btn.pack(anchor=tk.E, pady=(10, 0))
    
    def _create_update_settings_tab(self, parent, config, db):
        # Create update settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Update settings - for now just show the raw JSON
        ttk.Label(scrollable_frame, text="Update Configuration (JSON):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))
        
        text_frame = ttk.Frame(scrollable_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        text_widget = tk.Text(text_frame, height=20, wrap=tk.WORD)
        text_scrollbar = ttk.Scrollbar(text_frame, command=text_widget.yview)
        text_widget.configure(yscrollcommand=text_scrollbar.set)
        
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Load current update config
        full_config = config.get("full_config", {})
        if isinstance(full_config, str):
            import json
            try:
                full_config = json.loads(full_config)
            except (json.JSONDecodeError, ValueError):
                full_config = {}
        
        import json
        text_widget.insert(tk.END, json.dumps(full_config, indent=2))
        
        # Store reference for saving
        self.update_config_text = text_widget
    
    def _create_steam_settings_tab(self, parent, db):
        # Create Steam credentials settings tab
        main_frame = ttk.Frame(parent, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="🎮 Steam Credentials", font=("Segoe UI", 14, "bold"))
        title_label.pack(anchor=tk.W, pady=(0, 5))
        
        desc_label = ttk.Label(main_frame, 
                              text="Configure your Steam credentials for automatic login during server installations and updates. "
                                   "Credentials are stored locally with encryption.", 
                              wraplength=700, foreground="gray")
        desc_label.pack(anchor=tk.W, pady=(0, 20))
        
        # Load current credentials
        stored_creds = db.get_steam_credentials() or {}
        
        # Status indicator
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 15))
        
        if stored_creds.get('use_anonymous'):
            status_text = "✓ Using Anonymous Login"
            status_color = "blue"
        elif stored_creds.get('username'):
            status_text = f"✓ Credentials saved for: {stored_creds['username']}"
            status_color = "green"
        else:
            status_text = "○ No credentials configured"
            status_color = "gray"
        
        self.steam_status_label = ttk.Label(status_frame, text=status_text, foreground=status_color, font=("Segoe UI", 11))
        self.steam_status_label.pack(anchor=tk.W)
        
        if stored_creds.get('steam_guard_secret'):
            guard_status = ttk.Label(status_frame, text="✓ Steam Guard (2FA) configured", foreground="green")
            guard_status.pack(anchor=tk.W)
        
        # Credentials configuration frame
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=15)
        config_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Anonymous mode toggle
        self.steam_anon_var = tk.BooleanVar(value=stored_creds.get('use_anonymous', False))
        anon_check = ttk.Checkbutton(config_frame, text="Use Anonymous Login (limited to free games)", 
                                     variable=self.steam_anon_var)
        anon_check.pack(anchor=tk.W, pady=(0, 15))
        
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
        self.steam_password_entry = ttk.Entry(pass_frame, textvariable=self.steam_password_var, width=30, show="*")
        self.steam_password_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        # Show password toggle
        self.show_steam_pass_var = tk.BooleanVar(value=False)
        def toggle_pass_visibility():
            self.steam_password_entry.config(show="" if self.show_steam_pass_var.get() else "*")
        show_pass_btn = ttk.Checkbutton(pass_frame, text="Show", variable=self.show_steam_pass_var, command=toggle_pass_visibility)
        show_pass_btn.pack(side=tk.LEFT, padx=(10, 0))
        
        # Steam Guard section
        guard_frame = ttk.LabelFrame(main_frame, text="Steam Guard (2FA)", padding=15)
        guard_frame.pack(fill=tk.X, pady=(0, 15))
        
        guard_desc = ttk.Label(guard_frame, 
                              text="Enter your Steam Guard shared secret to automatically generate 2FA codes during login. "
                                   "This is the same secret used by mobile authenticators like WinAuth or SteamDesktopAuthenticator.",
                              wraplength=650, foreground="gray")
        guard_desc.pack(anchor=tk.W, pady=(0, 10))
        
        secret_frame = ttk.Frame(guard_frame)
        secret_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(secret_frame, text="Shared Secret:", width=15, anchor=tk.W).pack(side=tk.LEFT)
        self.steam_guard_var = tk.StringVar(value=stored_creds.get('steam_guard_secret', ''))
        self.steam_guard_entry = ttk.Entry(secret_frame, textvariable=self.steam_guard_var, width=35)
        self.steam_guard_entry.pack(side=tk.LEFT, padx=(10, 0))
        
        def test_steam_guard():
            # Test Steam Guard code generation
            secret = self.steam_guard_var.get().strip()
            if not secret:
                messagebox.showwarning("No Secret", "Please enter a Steam Guard shared secret first.")
                return
            try:
                import pyotp
                totp = pyotp.TOTP(secret)
                code = totp.now()
                messagebox.showinfo("Steam Guard Test", f"Current 2FA Code: {code}\n\nThis code changes every 30 seconds.")
            except ImportError:
                messagebox.showerror("Missing Package", "pyotp package is required for Steam Guard.\nInstall with: pip install pyotp")
            except Exception as e:
                messagebox.showerror("Error", f"Invalid secret: {e}")
        
        ttk.Button(secret_frame, text="Test Code", command=test_steam_guard).pack(side=tk.LEFT, padx=(10, 0))
        
        # Toggle field states based on anonymous mode
        def update_field_states(*args):
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
                use_anonymous=self.steam_anon_var.get()
            )
            if success:
                self.steam_status_label.config(text="✓ Credentials saved successfully!", foreground="green")
                messagebox.showinfo("Success", "Steam credentials saved successfully!")
            else:
                messagebox.showerror("Error", "Failed to save Steam credentials.")
        
        def clear_steam_credentials():
            if messagebox.askyesno("Confirm", "Are you sure you want to delete saved Steam credentials?"):
                db.delete_steam_credentials()
                self.steam_username_var.set("")
                self.steam_password_var.set("")
                self.steam_guard_var.set("")
                self.steam_anon_var.set(False)
                self.steam_status_label.config(text="○ No credentials configured", foreground="gray")
        
        ttk.Button(button_frame, text="Save Steam Credentials", command=save_steam_credentials).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Clear Credentials", command=clear_steam_credentials).pack(side=tk.RIGHT)
    
    def _create_system_settings_tab(self, parent, config, db):
        # Create system settings controls
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # System settings
        settings = [
            ("Version", "version", config.get("version", "0.1"), "string"),
            ("Web Port", "web_port", config.get("web_port", 8080), "integer"),
            ("Enable Auto Updates", "enable_auto_updates", config.get("enable_auto_updates", True), "boolean"),
            ("Enable Tray Icon", "enable_tray_icon", config.get("enable_tray_icon", True), "boolean"),
            ("Check Updates Interval", "check_updates_interval", config.get("check_updates_interval", 3600), "integer"),
            ("Log Level", "log_level", config.get("log_level", "INFO"), "string"),
            ("Max Log Size", "max_log_size", config.get("max_log_size", 10485760), "integer"),
            ("Max Log Files", "max_log_files", config.get("max_log_files", 10), "integer"),
        ]
        
        self._create_settings_controls(scrollable_frame, settings, "main")
    
    def _create_settings_controls(self, parent, settings, config_type):
        # Create form controls for settings
        self.settings_vars = getattr(self, 'settings_vars', {})
        self.settings_vars[config_type] = {}
        
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
            else:  # string
                var = tk.StringVar(value=str(default_value))
                control = ttk.Entry(frame, textvariable=var, width=30)
                control.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            self.settings_vars[config_type][key] = (var, value_type)
    
    def _save_settings(self, window, db):
        # Save all settings to database
        try:
            # Save dashboard settings
            if "dashboard" in self.settings_vars:
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
            
            # Save update settings
            if hasattr(self, 'update_config_text'):
                import json
                try:
                    config_data = json.loads(self.update_config_text.get(1.0, tk.END))
                    db.set_update_config("full_config", config_data, "json", "settings")
                except json.JSONDecodeError as e:
                    messagebox.showerror("JSON Error", f"Invalid JSON in update config: {e}")
                    return
            
            # Save system settings
            if "main" in self.settings_vars:
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
            
            messagebox.showinfo("Settings Saved", "Settings have been saved successfully!")
            window.destroy()
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save settings: {e}")

    def show_about(self):
        # Show about dialog using the documentation module
        show_about_dialog(self.root, logger)


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
                with open(lock_file, 'r') as f:
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
        with open(lock_file, 'w') as f:
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
            with open(lock_file, 'r') as f:
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
                return False  # Stop enumeration
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
    from Modules.server_logging import early_crash_log
    
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
