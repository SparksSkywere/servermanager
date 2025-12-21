# Server update and system task scheduling with unified interface management

# -*- coding: utf-8 -*-
import os
import json
import datetime
import psutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Callable
import requests

# Add project root to sys.path for module resolution
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.server_logging import log_process_monitoring, get_dashboard_logger

logger = get_dashboard_logger()

class SchedulerManager:
    # Enhanced scheduler for server updates and system tasks with unified interface
    
    def __init__(self, dashboard):
        # Initialize the SchedulerManager with dashboard reference
        self.dashboard = dashboard
        self.update_manager = None
        self.scheduled_tasks = {}
        self.update_check_interval = 300  # 5 minutes in seconds
        self.last_update_check = datetime.datetime.min
        
        # Database syncing configuration
        self.database_sync_enabled = False
        self.database_sync_interval = 600  # 10 minutes default
        self.last_database_sync = datetime.datetime.min
        self.agent_manager = None
    
    def set_update_manager(self, update_manager):
        # Set the server update manager instance
        self.update_manager = update_manager
    
    def set_agent_manager(self, agent_manager):
        # Set the cluster agent manager instance for database syncing
        self.agent_manager = agent_manager
    
    def start_timers(self):
        # Start all update timers using configuration values
        # Start background CPU monitoring
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
        # Timer function for system info updates
        try:
            if self.dashboard and hasattr(self.dashboard, 'update_system_info'):
                self.dashboard.update_system_info()
            system_interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
            self.dashboard.root.after(system_interval, self.system_info_timer)
        except Exception as e:
            logger.error(f"System info timer error: {str(e)}")
    
    def server_list_timer(self):
        # Timer function for server list updates
        try:
            if self.dashboard and hasattr(self.dashboard, 'periodic_server_list_refresh'):
                self.dashboard.periodic_server_list_refresh()
            elif self.dashboard and hasattr(self.dashboard, 'refresh_server_list'):
                self.dashboard.refresh_server_list()
            server_interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
            self.dashboard.root.after(server_interval, self.server_list_timer)
        except Exception as e:
            logger.error(f"Server list timer error: {str(e)}")
    
    def update_check_timer(self):
        # Timer function for scheduled update checks
        try:
            current_time = datetime.datetime.now()
            
            # Check if enough time has passed since last check
            time_diff = (current_time - self.last_update_check).total_seconds()
            if time_diff >= self.update_check_interval:
                # Run scheduled updates
                if self.update_manager:
                    threading.Thread(target=self.update_manager.run_scheduled_updates, daemon=True).start()
                self.last_update_check = current_time
            
            # Schedule next check
            update_interval = self.dashboard.variables["updateCheckInterval"] * 1000
            self.dashboard.root.after(update_interval, self.update_check_timer)
        except Exception as e:
            logger.error(f"Update check timer error: {str(e)}")
    
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
            
            # Schedule next sync
            self.dashboard.root.after(self.database_sync_interval * 1000, self.database_sync_timer)
        except Exception as e:
            logger.error(f"Database sync timer error: {str(e)}")
    
    def enable_database_sync(self, interval_seconds: int = 600):
        # Enable database syncing across cluster nodes
        self.database_sync_enabled = True
        self.database_sync_interval = max(60, interval_seconds)  # Minimum 1 minute
        logger.info(f"Database syncing enabled with {self.database_sync_interval} second interval")
    
    def disable_database_sync(self):
        # Disable database syncing
        self.database_sync_enabled = False
        logger.info("Database syncing disabled")
    
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
            
            for node in nodes:
                try:
                    # Get server's configurations via API
                    response = requests.get(f"http://{node.ip}:8080/api/servers", timeout=10)
                    if response.status_code == 200:
                        remote_servers = response.json().get('servers', [])
                        
                        # Compare and sync missing configurations
                        for server_name, server_config in local_servers.items():
                            # Check if remote node has this server
                            remote_server = next((s for s in remote_servers if s.get('name') == server_name), None)
                            
                            if not remote_server:
                                # Remote node doesn't have this server, send configuration
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
            
            for node in nodes:
                try:
                    # Send cluster config to remote node
                    config_data = {
                        'action': 'sync_cluster_config',
                        'config': local_config,
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    
                    response = requests.post(f"http://{node.ip}:8080/api/cluster/sync",
                                           json=config_data, timeout=10)
                    
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
            
            response = requests.post(f"http://{node.ip}:8080/api/servers/sync",
                                   json=config_data, timeout=15)
            
            if response.status_code == 200:
                logger.info(f"Server config '{server_name}' synced to {node.name}")
            else:
                logger.warning(f"Failed to sync server config '{server_name}' to {node.name}: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to send server config to {node.name}: {str(e)}")
    
    def get_database_sync_status(self):
        # Get the current status of database syncing
        return {
            'enabled': self.database_sync_enabled,
            'interval_seconds': self.database_sync_interval,
            'last_sync': self.last_database_sync.isoformat() if self.last_database_sync != datetime.datetime.min else None,
            'next_sync': (self.last_database_sync + datetime.timedelta(seconds=self.database_sync_interval)).isoformat() if self.database_sync_enabled and self.last_database_sync != datetime.datetime.min else None
        }
    
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
        
        # Create main window
        manager = tk.Toplevel(self.dashboard.root)
        manager.title("Schedule Manager")
        manager.geometry("1200x800")
        manager.transient(self.dashboard.root)
        manager.grab_set()
        
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
        
        close_btn = ttk.Button(bottom_frame, text="Close", command=manager.destroy, width=12)
        close_btn.pack(side=tk.RIGHT)
        
        # Populate targets list
        self.populate_targets_list()
        
        # Center window
        manager.update_idletasks()
        x = self.dashboard.root.winfo_rootx() + (self.dashboard.root.winfo_width() - manager.winfo_width()) // 2
        y = self.dashboard.root.winfo_rooty() + (self.dashboard.root.winfo_height() - manager.winfo_height()) // 2
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
    
    # Legacy method redirects for backward compatibility
    def show_update_schedule_dialog(self, server_name: Optional[str] = None, schedule_type: str = "update"):
        # Legacy method - redirect to unified manager
        self.show_schedules_manager()

    def show_restart_schedule_dialog(self, server_name: Optional[str] = None):
        # Legacy method - redirect to unified manager
        self.show_schedules_manager()
        
    def show_update_schedules_overview(self):
        # Legacy method - redirect to unified manager
        self.show_schedules_manager()


# For backwards compatibility - alias the old class name
TimerManager = SchedulerManager