# Task scheduling
# -*- coding: utf-8 -*-
import os
import sys
import datetime
import psutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging, save_automation_settings, get_node_url
setup_module_path()
from Modules.server_logging import log_process_monitoring

logger: logging.Logger = setup_module_logging("Scheduler")

class SchedulerManager:
    # - Runs update checks, timers, cluster sync
    # - Relies on dashboard for UI updates
    
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.update_manager = None
        self.scheduled_tasks = {}
        self.update_check_interval = 300
        self.last_update_check = datetime.datetime.min
        self.database_sync_enabled = False
        self.database_sync_interval = 600
        self.last_database_sync = datetime.datetime.min
        self.agent_manager = None
    
    def set_update_manager(self, update_manager):
        self.update_manager = update_manager
    
    def set_agent_manager(self, agent_manager):
        # Hook up cluster agent for db sync
        self.agent_manager = agent_manager
    
    def start_timers(self):
        # Fire up all scheduled timers
        self._start_cpu_monitoring()
        
        # System info update timer
        system_interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
        self.dashboard.root.after(system_interval, self.system_info_timer)
        
        # Server list update timer
        server_interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
        self.dashboard.root.after(server_interval, self.server_list_timer)
        
        # Update check timer
        update_interval = self.dashboard.variables["updateCheckInterval"] * 1000
        self.dashboard.root.after(update_interval, self.update_check_timer)
        
        # Database sync timer (if cluster is enabled)
        if self.agent_manager and self.database_sync_enabled:
            self.dashboard.root.after(30000, self.database_sync_timer)  # Start after 30 seconds
    
    def system_info_timer(self):
        try:
            if self.dashboard and hasattr(self.dashboard, 'update_system_info'):
                self.dashboard.update_system_info()
        except Exception as e:
            logger.error(f"System info timer error: {str(e)}")
        finally:
            # Always reschedule, even on error
            try:
                system_interval = self.dashboard.variables.get("systemInfoUpdateInterval", 10) * 1000
                self.dashboard.root.after(system_interval, self.system_info_timer)
            except Exception:
                pass  # Dashboard may be closing
    
    def server_list_timer(self):
        try:
            if self.dashboard and hasattr(self.dashboard, 'periodic_server_list_refresh'):
                self.dashboard.periodic_server_list_refresh()
            elif self.dashboard and hasattr(self.dashboard, 'refresh_server_list'):
                self.dashboard.refresh_server_list()
        except Exception as e:
            logger.error(f"Server list timer error: {str(e)}")
        finally:
            # Always reschedule, even on error
            try:
                server_interval = self.dashboard.variables.get("serverListUpdateInterval", 30) * 1000
                self.dashboard.root.after(server_interval, self.server_list_timer)
            except Exception:
                pass  # Dashboard may be closing
    
    def update_check_timer(self):
        # Timer function for scheduled update checks
        try:
            current_time = datetime.datetime.now()
            
            # Check if enough time has passed since last check
            time_diff = (current_time - self.last_update_check).total_seconds()
            if time_diff >= self.update_check_interval:
                # Run scheduled updates in background thread
                if self.update_manager:
                    threading.Thread(target=self.update_manager.run_scheduled_updates, daemon=True).start()
                self.last_update_check = current_time
        except Exception as e:
            logger.error(f"Update check timer error: {str(e)}")
        finally:
            # Always reschedule, even on error
            try:
                update_interval = self.dashboard.variables.get("updateCheckInterval", 300) * 1000
                self.dashboard.root.after(update_interval, self.update_check_timer)
            except Exception:
                pass  # Dashboard may be closing
    
    def database_sync_timer(self):
        # Timer function for scheduled database syncing across cluster nodes
        try:
            if not self.agent_manager or not self.database_sync_enabled:
                return
                
            current_time = datetime.datetime.now()
            
            # Check if enough time has passed since last sync
            time_diff = (current_time - self.last_database_sync).total_seconds()
            if time_diff >= self.database_sync_interval:
                # Run database sync in background thread
                threading.Thread(target=self.sync_cluster_databases, daemon=True).start()
                self.last_database_sync = current_time
        except Exception as e:
            logger.error(f"Database sync timer error: {str(e)}")
        finally:
            # Always reschedule if sync is enabled
            try:
                if self.database_sync_enabled:
                    self.dashboard.root.after(self.database_sync_interval * 1000, self.database_sync_timer)
            except Exception:
                pass  # Dashboard may be closing
    
    def sync_cluster_databases(self):
        # Sync database changes across cluster nodes
        try:
            if not self.agent_manager:
                logger.warning("No agent manager available for database syncing")
                return
            
            # Only sync if this is a master host or if we're configured to sync
            cluster_status = self.agent_manager.get_cluster_status()
            if cluster_status.get('error'):
                logger.debug("Cluster not configured, skipping database sync")
                return
            
            # Get all online cluster nodes
            online_nodes = []
            for node in self.agent_manager.get_all_nodes():
                if node.is_online and node.status == "online":
                    online_nodes.append(node)
            
            if not online_nodes:
                logger.debug("No online cluster nodes found for syncing")
                return
            
            logger.info(f"Starting database sync with {len(online_nodes)} cluster nodes")
            
            # Sync different types of data
            self._sync_server_configurations(online_nodes)
            self._sync_user_data(online_nodes)
            self._sync_cluster_settings(online_nodes)
            
            logger.info("Database sync completed successfully")
            
        except Exception as e:
            logger.error(f"Database sync failed: {str(e)}")
    
    def _sync_server_configurations(self, nodes):
        # Sync server configurations across cluster nodes
        try:
            if not hasattr(self.dashboard, 'server_manager') or not self.dashboard.server_manager:
                return
            
            # Get local server configurations
            local_servers = self.dashboard.server_manager.get_all_servers()
            
            def _fetch_remote_servers(node):
                node_url = get_node_url(node.ip, node.port)
                response = requests.get(f"{node_url}/api/servers", timeout=10)
                return node, response

            with ThreadPoolExecutor(max_workers=min(len(nodes), 10)) as executor:
                futures = {executor.submit(_fetch_remote_servers, n): n for n in nodes}
                for future in as_completed(futures):
                    node = futures[future]
                    try:
                        node, response = future.result()
                        if response.status_code == 200:
                            remote_servers = response.json().get('servers', [])
                            for server_name, server_config in local_servers.items():
                                remote_server = next((s for s in remote_servers if s.get('name') == server_name), None)
                                if not remote_server:
                                    self._send_server_config_to_node(node, server_name, server_config)
                    except Exception as e:
                        logger.error(f"Failed to sync server configs with {node.name}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Server configuration sync error: {str(e)}")
    
    def _sync_user_data(self, nodes):
        # Sync user management data across cluster nodes
        try:
            # This would sync user accounts, permissions, etc.
            # Implementation depends on user management system structure
            # For now, just log that this feature is available
            logger.debug("User data sync placeholder - implement based on user management system")
            
        except Exception as e:
            logger.error(f"User data sync error: {str(e)}")
    
    def _sync_cluster_settings(self, nodes):
        # Sync cluster-wide settings and configurations
        try:
            if not self.agent_manager or not hasattr(self.agent_manager, 'cluster_db'):
                return
            
            # Get local cluster configuration
            local_config = self.agent_manager.cluster_db.get_cluster_config()
            
            config_data = {
                'action': 'sync_cluster_config',
                'config': local_config,
                'timestamp': datetime.datetime.now().isoformat()
            }

            def _post_cluster_config(node):
                response = requests.post(f"{get_node_url(node.ip, node.port)}/api/cluster/sync",
                                       json=config_data, timeout=10)
                return node, response

            with ThreadPoolExecutor(max_workers=min(len(nodes), 10)) as executor:
                futures = {executor.submit(_post_cluster_config, n): n for n in nodes}
                for future in as_completed(futures):
                    node = futures[future]
                    try:
                        node, response = future.result()
                        if response.status_code == 200:
                            logger.debug(f"Cluster config synced to {node.name}")
                        else:
                            logger.warning(f"Failed to sync cluster config to {node.name}: {response.status_code}")
                    except Exception as e:
                        logger.error(f"Failed to sync cluster settings with {node.name}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Cluster settings sync error: {str(e)}")
    
    def _send_server_config_to_node(self, node, server_name, server_config):
        # Send a server configuration to a remote cluster node
        try:
            config_data = {
                'action': 'sync_server_config',
                'server_name': server_name,
                'server_config': server_config,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            response = requests.post(f"{get_node_url(node.ip, node.port)}/api/servers/sync",
                                   json=config_data, timeout=15)
            
            if response.status_code == 200:
                logger.info(f"Server config '{server_name}' synced to {node.name}")
            else:
                logger.warning(f"Failed to sync server config '{server_name}' to {node.name}: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to send server config to {node.name}: {str(e)}")
    
    def _start_cpu_monitoring(self):
        # Start background CPU monitoring for servers
        def monitor_cpu():
            try:
                if not (self.dashboard and hasattr(self.dashboard, 'server_manager') and self.dashboard.server_manager):
                    return
                
                servers = self.dashboard.server_manager.get_all_servers()
                for server_name, server_config in servers.items():
                    try:
                        server_status = self.dashboard.server_manager.get_server_status(server_name)
                        if server_status and server_status[0] == 'Running':
                            pid = server_status[1]
                            if pid:
                                try:
                                    process = psutil.Process(pid)
                                    cpu_usage = process.cpu_percent()
                                    
                                    # Log high CPU usage
                                    if cpu_usage > 80:
                                        log_process_monitoring(f"High CPU usage detected for {server_name}: {cpu_usage:.1f}%", "WARNING")
                                    
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                    except Exception as e:
                        log_process_monitoring(f"Error monitoring {server_name}: {str(e)}", "ERROR")
                        
            except Exception as e:
                log_process_monitoring(f"Process monitoring error: {str(e)}", "ERROR")
        
        # Start monitoring in background thread
        threading.Thread(target=monitor_cpu, daemon=True).start()

    def show_schedules_manager(self):
        # Show unified schedules manager window for configuring all schedules
        if not self.update_manager:
            messagebox.showerror("Error", "Update manager not available")
            return
        
        # Create main window (non-modal for multi-window support)
        manager = tk.Toplevel(self.dashboard.root)
        manager.title("Schedule Manager")
        manager.geometry("1200x800")
        # Removed transient() and grab_set() to allow multiple windows
        
        # Create main frame with consistent padding
        main_frame = ttk.Frame(manager, padding=(15, 15, 15, 10))
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title with consistent spacing
        title_label = ttk.Label(main_frame, text="Schedule Manager", font=("Segoe UI", 16, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Create paned window for left panel (schedules list) and right panel (configuration)
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # Left panel - Target selection
        left_frame = ttk.Frame(paned, padding=(5, 0, 5, 0))
        paned.add(left_frame, weight=1)
        
        # Target list header
        list_header_frame = ttk.Frame(left_frame)
        list_header_frame.pack(fill=tk.X, pady=(0, 8))
        
        list_label = ttk.Label(list_header_frame, text="Schedule Targets", font=("Segoe UI", 12, "bold"))
        list_label.pack(side=tk.LEFT)
        
        # Create treeview for targets with simpler columns
        columns = ("type", "update_status", "restart_status")
        self.targets_tree = ttk.Treeview(left_frame, columns=columns, show="tree headings", height=18)
        
        # Define headings for target selection
        self.targets_tree.heading("#0", text="Target")
        self.targets_tree.heading("type", text="Type")
        self.targets_tree.heading("update_status", text="Update")
        self.targets_tree.heading("restart_status", text="Restart")
        
        # Configure columns for target view
        self.targets_tree.column("#0", width=200, minwidth=150)
        self.targets_tree.column("type", width=80, minwidth=60)
        self.targets_tree.column("update_status", width=80, minwidth=60)
        self.targets_tree.column("restart_status", width=80, minwidth=60)
        
        # Add scrollbar for tree
        tree_scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.targets_tree.yview)
        self.targets_tree.configure(yscrollcommand=tree_scrollbar.set)
        
        # Pack tree and scrollbar with proper frame
        tree_container = ttk.Frame(left_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        
        # Move tree to container
        self.targets_tree.pack_forget()
        self.targets_tree = ttk.Treeview(tree_container, columns=columns, show="tree headings", height=18)
        
        # Redefine headings and columns for the moved tree
        self.targets_tree.heading("#0", text="Target")
        self.targets_tree.heading("type", text="Type")
        self.targets_tree.heading("update_status", text="Update")
        self.targets_tree.heading("restart_status", text="Restart")
        
        self.targets_tree.column("#0", width=200, minwidth=150)
        self.targets_tree.column("type", width=80, minwidth=60)
        self.targets_tree.column("update_status", width=80, minwidth=60)
        self.targets_tree.column("restart_status", width=80, minwidth=60)
        
        # Reconfigure scrollbar for moved tree
        tree_scrollbar.pack_forget()
        tree_scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.targets_tree.yview)
        self.targets_tree.configure(yscrollcommand=tree_scrollbar.set)
        
        self.targets_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Remove the old buttons - we'll move all controls to the right side
        
        # Right panel - Schedule Management
        right_frame = ttk.Frame(paned, padding=(5, 0, 5, 0))
        paned.add(right_frame, weight=2)  # Give more space to the right panel
        
        # Management header
        management_header_frame = ttk.Frame(right_frame)
        management_header_frame.pack(fill=tk.X, pady=(0, 8))
        
        management_label = ttk.Label(management_header_frame, text="Schedule Management", font=("Segoe UI", 12, "bold"))
        management_label.pack(side=tk.LEFT)
        
        # Management area (will be populated when target is selected)
        self.management_frame = ttk.Frame(right_frame)
        self.management_frame.pack(fill=tk.BOTH, expand=True)
        
        # Initial message with better styling
        initial_msg = ttk.Label(self.management_frame, text="Select a target to manage schedules", 
                               font=("Segoe UI", 11), foreground="gray")
        initial_msg.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Bind selection event
        self.targets_tree.bind("<<TreeviewSelect>>", self.on_target_select)
        
        # Bottom buttons with consistent styling
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(15, 0))

        # Separator line for visual clarity
        separator = ttk.Separator(bottom_frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=(0, 10))

        # Save All button
        def save_all_schedules():
            try:
                # All schedules are saved immediately when configured,
                # but this provides a confirmation that everything is saved
                messagebox.showinfo("Success", "All schedules are already saved. No pending changes.")
            except Exception as e:
                messagebox.showerror("Error", f"Error: {str(e)}")

        save_all_btn = ttk.Button(bottom_frame, text="Save All", command=save_all_schedules, width=12)
        save_all_btn.pack(side=tk.RIGHT, padx=(0, 10))

        close_btn = ttk.Button(bottom_frame, text="Close", command=manager.destroy, width=12)
        close_btn.pack(side=tk.RIGHT)
        
        # Populate targets list
        self.populate_targets_list()
        
        # Centre window with multi-screen support
        manager.update_idletasks()
        window_width = manager.winfo_width()
        window_height = manager.winfo_height()

        # Calculate center position relative to dashboard
        dashboard_x = self.dashboard.root.winfo_rootx()
        dashboard_y = self.dashboard.root.winfo_rooty()
        dashboard_width = self.dashboard.root.winfo_width()
        dashboard_height = self.dashboard.root.winfo_height()

        x = dashboard_x + (dashboard_width // 2) - (window_width // 2)
        y = dashboard_y + (dashboard_height // 2) - (window_height // 2)

        # Get screen dimensions
        screen_width = self.dashboard.root.winfo_screenwidth()
        screen_height = self.dashboard.root.winfo_screenheight()

        # Ensure window stays within screen bounds
        x = max(0, min(x, screen_width - window_width))
        y = max(0, min(y, screen_height - window_height))

        manager.geometry(f"+{x}+{y}")
    
    def populate_targets_list(self):
        # Populate the targets tree with current targets and their schedule status
        if not self.update_manager:
            return
            
        # Clear existing items
        for item in self.targets_tree.get_children():
            self.targets_tree.delete(item)
        
        # Add global target
        global_update = self.update_manager.get_global_update_schedule()
        global_restart = self.update_manager.get_global_restart_schedule()
        
        update_status = "Enabled" if global_update and global_update.get("enabled", False) else "Disabled"
        restart_status = "Enabled" if global_restart and global_restart.get("enabled", False) else "Disabled"
        
        self.targets_tree.insert("", tk.END, text="Global (All Servers)", 
                                values=("Global", update_status, restart_status),
                                tags=("global",))
        
        # Add server targets
        if hasattr(self.dashboard, 'server_manager') and self.dashboard.server_manager:
            servers = self.dashboard.server_manager.get_all_servers()
            
            for server_name in sorted(servers.keys()):
                server_update = self.update_manager.get_server_update_schedule(server_name)
                server_restart = self.update_manager.get_server_restart_schedule(server_name)
                
                update_status = "Enabled" if server_update and server_update.get("enabled", False) else "Disabled"
                restart_status = "Enabled" if server_restart and server_restart.get("enabled", False) else "Disabled"
                
                self.targets_tree.insert("", tk.END, text=server_name,
                                        values=("Server", update_status, restart_status),
                                        tags=("server", server_name))
    
    def on_target_select(self, event):
        # Handle target selection in the tree view
        selection = self.targets_tree.selection()
        if not selection:
            return
        
        tags = self.targets_tree.item(selection[0], "tags")
        
        if not tags:
            # Clear management area if no valid target selected
            self.clear_management_area()
            return
        
        target_type = tags[0]  # "global" or "server"
        server_name = tags[1] if len(tags) > 1 else None
        
        self.show_target_management(target_type, server_name)
    
    def clear_management_area(self):
        # Clear the management area interface
        for widget in self.management_frame.winfo_children():
            widget.destroy()
        initial_msg = ttk.Label(self.management_frame, text="Select a target to manage schedules", 
                               font=("Segoe UI", 11), foreground="gray")
        initial_msg.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
    
    def show_target_management(self, target_type, server_name=None):
        # Show management interface for the selected target
        if not self.update_manager:
            self.clear_management_area()
            return
            
        # Clear management area
        for widget in self.management_frame.winfo_children():
            widget.destroy()
        
        # Determine target name and get schedules
        if target_type == "global":
            target_name = "Global (All Servers)"
            update_schedule = self.update_manager.get_global_update_schedule()
            restart_schedule = self.update_manager.get_global_restart_schedule()
        else:
            target_name = server_name
            update_schedule = self.update_manager.get_server_update_schedule(server_name)
            restart_schedule = self.update_manager.get_server_restart_schedule(server_name)
        
        # Create management container
        management_container = ttk.Frame(self.management_frame)
        management_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        # Title
        title_label = ttk.Label(management_container, text=f"Schedule Management - {target_name}", 
                               font=("Segoe UI", 13, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Create notebook for update and restart schedules
        notebook = ttk.Notebook(management_container)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Update Schedule Tab
        update_frame = ttk.Frame(notebook, padding=(15, 15))
        notebook.add(update_frame, text="Update Schedule")
        
        self.create_schedule_form(update_frame, "update", target_type, server_name, update_schedule)
        
        # Restart Schedule Tab
        restart_frame = ttk.Frame(notebook, padding=(15, 15))
        notebook.add(restart_frame, text="Restart Schedule")
        
        self.create_schedule_form(restart_frame, "restart", target_type, server_name, restart_schedule)
        
        # Commands Tab (only for individual servers, not global)
        if target_type == "server" and server_name:
            commands_frame = ttk.Frame(notebook, padding=(15, 15))
            notebook.add(commands_frame, text="Server Commands")
            
            self.create_commands_form(commands_frame, server_name)
            
    def create_commands_form(self, parent_frame, server_name):
        # Create form for configuring server commands (MOTD, warnings, save, etc.)
        # Get current server config
        server_config = {}
        if hasattr(self.dashboard, 'server_manager') and self.dashboard.server_manager:
            server_config = self.dashboard.server_manager.get_server_config(server_name) or {}
        
        # Create scrollable frame for content
        canvas = tk.Canvas(parent_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Instructions
        info_label = ttk.Label(scrollable_frame, text="Configure commands for this server. Use {message} as a placeholder for dynamic text.",
                              font=("Segoe UI", 9), foreground="gray", wraplength=600)
        info_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Stop Command
        stop_frame = ttk.LabelFrame(scrollable_frame, text="Stop Command", padding=(10, 8))
        stop_frame.pack(fill=tk.X, pady=(0, 12))
        
        stop_help = ttk.Label(stop_frame, text="Command to gracefully stop the server (e.g., 'stop', 'quit', '/stop')", 
                             font=("Segoe UI", 9), foreground="gray")
        stop_help.pack(anchor=tk.W, pady=(0, 5))
        
        stop_var = tk.StringVar(value=server_config.get('StopCommand', ''))
        stop_entry = ttk.Entry(stop_frame, textvariable=stop_var, width=60)
        stop_entry.pack(fill=tk.X)
        
        # Save Command
        save_frame = ttk.LabelFrame(scrollable_frame, text="Save Command", padding=(10, 8))
        save_frame.pack(fill=tk.X, pady=(0, 12))
        
        save_help = ttk.Label(save_frame, text="Command to save world/data before shutdown (e.g., 'save-all', '/save-all')", 
                             font=("Segoe UI", 9), foreground="gray")
        save_help.pack(anchor=tk.W, pady=(0, 5))
        
        save_var = tk.StringVar(value=server_config.get('SaveCommand', ''))
        save_entry = ttk.Entry(save_frame, textvariable=save_var, width=60)
        save_entry.pack(fill=tk.X)
        
        # MOTD Settings
        motd_frame = ttk.LabelFrame(scrollable_frame, text="MOTD (Message of the Day)", padding=(10, 8))
        motd_frame.pack(fill=tk.X, pady=(0, 12))

        # MOTD Command
        ttk.Label(motd_frame, text="MOTD Command:", font=("Segoe UI", 9)).grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        motd_var = tk.StringVar(value=server_config.get('MotdCommand', ''))
        motd_entry = ttk.Entry(motd_frame, textvariable=motd_var, width=50)
        motd_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        # MOTD Message
        ttk.Label(motd_frame, text="MOTD Message:", font=("Segoe UI", 9)).grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        motd_msg_var = tk.StringVar(value=server_config.get('MotdMessage', ''))
        motd_msg_entry = ttk.Entry(motd_frame, textvariable=motd_msg_var, width=50)
        motd_msg_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        # Broadcast Interval
        ttk.Label(motd_frame, text="Broadcast Interval (minutes):", font=("Segoe UI", 9)).grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        motd_interval_var = tk.StringVar(value=str(server_config.get('MotdInterval', 0)))
        motd_interval_entry = ttk.Entry(motd_frame, textvariable=motd_interval_var, width=10)
        motd_interval_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(motd_frame, text="0 = disabled", font=("Segoe UI", 8), foreground="gray").grid(row=2, column=2, padx=5, pady=5, sticky=tk.W)

        # Configure grid weights
        motd_frame.columnconfigure(1, weight=1)

        # Warning Command (for shutdown/restart warnings)
        warning_frame = ttk.LabelFrame(scrollable_frame, text="Warning Command", padding=(10, 8))
        warning_frame.pack(fill=tk.X, pady=(0, 12))

        warning_help = ttk.Label(warning_frame, text="Command for shutdown/restart warnings (e.g., 'say Server restarting in {message}')",
                                font=("Segoe UI", 9), foreground="gray")
        warning_help.pack(anchor=tk.W, pady=(0, 5))

        warning_var = tk.StringVar(value=server_config.get('WarningCommand', ''))
        warning_entry = ttk.Entry(warning_frame, textvariable=warning_var, width=60)
        warning_entry.pack(fill=tk.X)

        # Warning Intervals
        intervals_frame = ttk.LabelFrame(scrollable_frame, text="Warning Intervals (minutes)", padding=(10, 8))
        intervals_frame.pack(fill=tk.X, pady=(0, 12))

        intervals_help = ttk.Label(intervals_frame, text="Comma-separated minutes before shutdown to send warnings (e.g., '30,15,10,5,1')",
                                  font=("Segoe UI", 9), foreground="gray")
        intervals_help.pack(anchor=tk.W, pady=(0, 5))

        intervals_var = tk.StringVar(value=server_config.get('WarningIntervals', '30,15,10,5,1'))
        intervals_entry = ttk.Entry(intervals_frame, textvariable=intervals_var, width=60)
        intervals_entry.pack(fill=tk.X)
        start_frame = ttk.LabelFrame(scrollable_frame, text="Start Command", padding=(10, 8))
        start_frame.pack(fill=tk.X, pady=(0, 12))
        
        start_help = ttk.Label(start_frame, text="Command to run after server starts (e.g., welcome message)", 
                              font=("Segoe UI", 9), foreground="gray")
        start_help.pack(anchor=tk.W, pady=(0, 5))
        
        start_var = tk.StringVar(value=server_config.get('StartCommand', ''))
        start_entry = ttk.Entry(start_frame, textvariable=start_var, width=60)
        start_entry.pack(fill=tk.X)
        
        # Scheduled Restart
        restart_frame = ttk.LabelFrame(scrollable_frame, text="Scheduled Restart", padding=(10, 8))
        restart_frame.pack(fill=tk.X, pady=(0, 12))
        
        scheduled_restart_var = tk.BooleanVar(value=server_config.get('ScheduledRestartEnabled', False))
        restart_check = ttk.Checkbutton(restart_frame, text="Enable scheduled restart with warnings", 
                                       variable=scheduled_restart_var)
        restart_check.pack(anchor=tk.W)
        
        # Warning Message Template
        template_frame = ttk.LabelFrame(scrollable_frame, text="Warning Message Template", padding=(10, 8))
        template_frame.pack(fill=tk.X, pady=(0, 12))
        
        template_help = ttk.Label(template_frame, text="Template for warning messages (use {message} for time)", 
                                 font=("Segoe UI", 9), foreground="gray")
        template_help.pack(anchor=tk.W, pady=(0, 5))
        
        template_var = tk.StringVar(value=server_config.get('WarningMessageTemplate', 'Server restarting in {message}'))
        template_entry = ttk.Entry(template_frame, textvariable=template_var, width=60)
        template_entry.pack(fill=tk.X)
        
        # Example commands section
        examples_frame = ttk.LabelFrame(scrollable_frame, text="Common Command Examples", padding=(10, 8))
        examples_frame.pack(fill=tk.X, pady=(0, 12))
        
        examples_text = """Minecraft: stop, save-all, say {message}
Vintage Story: /stop, /announce {message}
ARK: saveworld, broadcast {message}
Rust: quit, say {message}
Valheim: No console commands available (use CTRL+C)"""
        
        examples_label = ttk.Label(examples_frame, text=examples_text, font=("Consolas", 9), justify=tk.LEFT)
        examples_label.pack(anchor=tk.W)
        
        # Save Button
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        separator = ttk.Separator(button_frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=(0, 12))
        
        def save_commands():
            try:
                if not hasattr(self.dashboard, 'server_manager') or not self.dashboard.server_manager:
                    messagebox.showerror("Error", "Server manager not available")
                    return
                
                # Get current config
                current_config = self.dashboard.server_manager.get_server_config(server_name) or {}
                
                # Prepare automation data
                automation_data = {
                    'motd_command': motd_var.get().strip(),
                    'motd_message': motd_msg_var.get().strip(),
                    'motd_interval': motd_interval_var.get().strip(),
                    'start_command': start_var.get().strip(),
                    'scheduled_restart_enabled': scheduled_restart_var.get(),
                    'warning_command': warning_var.get().strip(),
                    'warning_intervals': intervals_var.get().strip(),
                    'warning_message_template': template_var.get().strip(),
                    'stop_command': stop_var.get().strip(),
                    'save_command': save_var.get().strip()
                }
                
                # Save using common function
                current_config = save_automation_settings(current_config, automation_data)
                
                # Save to database
                if self.dashboard.server_manager.update_server(server_name, current_config):
                    messagebox.showinfo("Success", "Server commands saved successfully")
                else:
                    messagebox.showerror("Error", "Failed to save server commands")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save commands: {str(e)}")
        
        save_btn = ttk.Button(button_frame, text="Save Commands", command=save_commands, width=16)
        save_btn.pack(side=tk.LEFT)
        
    def create_schedule_form(self, parent_frame, schedule_type, target_type, server_name, existing_schedule):
        # Create a form for configuring a schedule
        # Default values if no existing schedule
        if not existing_schedule:
            default_time = "02:00" if schedule_type == "update" else "04:00"
            existing_schedule = {
                "enabled": False,
                "time": default_time,
                "days": list(range(7)),  # All days
                "scattered": False,
                "scatter_window": 60
            }
            if schedule_type == "update":
                existing_schedule["check_only"] = False
        
        # Enable/Disable checkbox
        enabled_var = tk.BooleanVar(value=existing_schedule.get("enabled", False))
        enabled_frame = ttk.Frame(parent_frame)
        enabled_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Checkbutton(enabled_frame, text=f"Enable {schedule_type} schedule", 
                       variable=enabled_var, 
                       command=lambda: self.on_schedule_enable_change(enabled_var.get(), schedule_type, target_type, server_name)).pack(anchor=tk.W)
        
        # Time selection
        time_frame = ttk.LabelFrame(parent_frame, text="Time", padding=(10, 8))
        time_frame.pack(fill=tk.X, pady=(0, 12))
        
        time_label = ttk.Label(time_frame, text="Time (24-hour format):")
        time_label.pack(anchor=tk.W, pady=(0, 5))
        
        time_var = tk.StringVar(value=existing_schedule.get("time", "02:00"))
        time_entry = ttk.Entry(time_frame, textvariable=time_var, width=8)
        time_entry.pack(anchor=tk.W)
        
        # Day selection
        days_frame = ttk.LabelFrame(parent_frame, text="Days", padding=(10, 8))
        days_frame.pack(fill=tk.X, pady=(0, 12))
        
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_vars = []
        
        # Create two columns for better space usage
        days_grid_frame = ttk.Frame(days_frame)
        days_grid_frame.pack(fill=tk.X)
        
        for i, day_name in enumerate(day_names):
            var = tk.BooleanVar(value=i in existing_schedule.get("days", []))
            day_vars.append(var)
            
            column = i % 2
            row = i // 2
            
            cb = ttk.Checkbutton(days_grid_frame, text=day_name, variable=var)
            cb.grid(row=row, column=column, sticky=tk.W, padx=(0, 20), pady=2)
        
        # Scattered option
        scattered_var = tk.BooleanVar(value=existing_schedule.get("scattered", False))
        scatter_window_var = tk.IntVar(value=existing_schedule.get("scatter_window", 60))
        
        scattered_frame = ttk.LabelFrame(parent_frame, text="Scattered Execution", padding=(10, 8))
        scattered_frame.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Checkbutton(scattered_frame, text="Scatter execution across time window", 
                       variable=scattered_var).pack(anchor=tk.W, pady=(0, 5))
        
        scatter_time_frame = ttk.Frame(scattered_frame)
        scatter_time_frame.pack(fill=tk.X)
        ttk.Label(scatter_time_frame, text="Scatter window (minutes):").pack(side=tk.LEFT)
        scatter_entry = ttk.Entry(scatter_time_frame, textvariable=scatter_window_var, width=8)
        scatter_entry.pack(side=tk.LEFT, padx=(8, 0))
        
        # Update-specific options
        check_only_var = None
        if schedule_type == "update":
            update_options_frame = ttk.LabelFrame(parent_frame, text="Update Options", padding=(10, 8))
            update_options_frame.pack(fill=tk.X, pady=(0, 12))
            
            check_only_var = tk.BooleanVar(value=existing_schedule.get("check_only", False))
            ttk.Checkbutton(update_options_frame, text="Check only (don't install updates automatically)", 
                           variable=check_only_var).pack(anchor=tk.W)
        
        # Save and Delete buttons
        button_frame = ttk.Frame(parent_frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        # Add separator for visual clarity
        separator = ttk.Separator(button_frame, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=(0, 12))
        
        # Button functions
        def save_schedule():
            # Validate time format
            try:
                time_str = time_var.get()
                hour, minute = map(int, time_str.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time")
            except ValueError:
                messagebox.showerror("Error", "Invalid time format. Use HH:MM (24-hour format)")
                return
            
            # Build schedule config
            schedule_config = {
                "enabled": enabled_var.get(),
                "time": time_var.get(),
                "days": [i for i, var in enumerate(day_vars) if var.get()],
                "scattered": scattered_var.get(),
                "scatter_window": scatter_window_var.get()
            }
            
            if schedule_type == "update" and check_only_var:
                schedule_config["check_only"] = check_only_var.get()
            
            # Save schedule
            try:
                if not self.update_manager:
                    messagebox.showerror("Error", "Update manager not available")
                    return
                    
                if target_type == "global":
                    if schedule_type == "update":
                        self.update_manager.set_global_update_schedule(schedule_config)
                    else:
                        self.update_manager.set_global_restart_schedule(schedule_config)
                else:  # server
                    if schedule_type == "update":
                        self.update_manager.set_server_update_schedule(server_name, schedule_config)
                    else:
                        self.update_manager.set_server_restart_schedule(server_name, schedule_config)
                
                messagebox.showinfo("Success", f"{schedule_type.capitalize()} schedule saved successfully")
                self.populate_targets_list()  # Refresh the list
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save schedule: {str(e)}")
        
        def delete_schedule():
            if not self.update_manager:
                messagebox.showerror("Error", "Update manager not available")
                return
                
            if messagebox.askyesno("Confirm", f"Remove this {schedule_type} schedule?"):
                try:
                    if target_type == "global":
                        if schedule_type == "update":
                            self.update_manager.remove_global_update_schedule()
                        else:
                            self.update_manager.remove_global_restart_schedule()
                    else:  # server
                        if schedule_type == "update":
                            self.update_manager.remove_server_update_schedule(server_name)
                        else:
                            self.update_manager.remove_server_restart_schedule(server_name)
                    
                    messagebox.showinfo("Success", f"{schedule_type.capitalize()} schedule removed successfully")
                    self.populate_targets_list()  # Refresh the list
                    # Refresh the current view
                    self.show_target_management(target_type, server_name)
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to remove schedule: {str(e)}")
        
        # Buttons with consistent spacing and sizing
        button_container = ttk.Frame(button_frame)
        button_container.pack(side=tk.LEFT)
        
        save_btn = ttk.Button(button_container, text=f"Save {schedule_type.capitalize()}", 
                             command=save_schedule, width=16)
        save_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        delete_btn = ttk.Button(button_container, text=f"Delete {schedule_type.capitalize()}", 
                               command=delete_schedule, width=16)
        delete_btn.pack(side=tk.LEFT)
    
    def on_schedule_enable_change(self, enabled, schedule_type, target_type, server_name):
        # Handle immediate enable/disable of schedules
        try:
            if not self.update_manager:
                return
            
            # Get current schedule
            if target_type == "global":
                if schedule_type == "update":
                    schedule = self.update_manager.get_global_update_schedule()
                else:
                    schedule = self.update_manager.get_global_restart_schedule()
            else:
                if schedule_type == "update":
                    schedule = self.update_manager.get_server_update_schedule(server_name)
                else:
                    schedule = self.update_manager.get_server_restart_schedule(server_name)
            
            if schedule:
                schedule["enabled"] = enabled
                
                # Save updated schedule
                if target_type == "global":
                    if schedule_type == "update":
                        self.update_manager.set_global_update_schedule(schedule)
                    else:
                        self.update_manager.set_global_restart_schedule(schedule)
                else:
                    if schedule_type == "update":
                        self.update_manager.set_server_update_schedule(server_name, schedule)
                    else:
                        self.update_manager.set_server_restart_schedule(server_name, schedule)
                
                # Refresh the target list to show updated status
                self.populate_targets_list()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update schedule: {str(e)}")
