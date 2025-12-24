# Timer management
# - Dashboard update timers
# - CPU monitoring thread
import os
import json
import datetime
import psutil
import threading
import tkinter as tk
from Modules.server_logging import log_process_monitoring


class TimerManager:
    # - Schedules periodic UI updates
    # - Background CPU monitoring
    
    def __init__(self, dashboard):
        self.dashboard = dashboard
    
    def start_timers(self):
        # Fire up all update timers
        self._start_cpu_monitoring()
        
        system_interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
        self.dashboard.root.after(system_interval, self.system_info_timer)
        
        server_interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
        self.dashboard.root.after(server_interval, self.server_list_timer)
        
        webserver_interval = self.dashboard.variables["webserverStatusUpdateInterval"] * 1000
        self.dashboard.root.after(webserver_interval, self.webserver_status_timer)
        
        process_interval = self.dashboard.variables["processMonitorUpdateInterval"] * 1000
        self.dashboard.root.after(process_interval, self.process_monitor_timer)

    def _start_cpu_monitoring(self):
        # Background thread for CPU stats
        def cpu_monitor():
            try:
                while hasattr(self.dashboard, 'root'):
                    try:
                        if not self.dashboard.root.winfo_exists():
                            break
                    except tk.TclError:
                        break
                        
                    psutil.cpu_percent(interval=1)
                    threading.Event().wait(2)
            except Exception as e:
                log_process_monitoring(f"CPU monitor error: {str(e)}", "ERROR")
        
        cpu_thread = threading.Thread(target=cpu_monitor, daemon=True)
        cpu_thread.start()

    def system_info_timer(self):
        # System info update callback
        try:
            self.dashboard.update_system_info()
        except Exception as e:
            log_process_monitoring(f"System info error: {str(e)}", "ERROR")
        
        interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.system_info_timer)
    
    def server_list_timer(self):
        # Timer callback for server list updates
        try:
            self.dashboard.update_server_list()
        except Exception as e:
            log_process_monitoring(f"Server list update error: {str(e)}", "ERROR")
        
        interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.server_list_timer)
    
    def webserver_status_timer(self):
        # Timer callback for web server status updates
        try:
            self.dashboard.update_webserver_status()
        except Exception as e:
            log_process_monitoring(f"Webserver status update error: {str(e)}", "ERROR")
        
        interval = self.dashboard.variables["webserverStatusUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.webserver_status_timer)
    
    def process_monitor_timer(self):
        # Timer callback for process monitoring
        try:
            self.monitor_processes()
        except Exception as e:
            log_process_monitoring(f"Process monitoring error: {str(e)}", "ERROR")
        
        interval = self.dashboard.variables["processMonitorUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.process_monitor_timer)
    
    def monitor_processes(self):
        # Monitor running server processes
        try:
            # Skip if it's been less than processMonitoringInterval seconds since the last update
            if (self.dashboard.variables["lastProcessUpdate"] != datetime.datetime.min) and \
               (datetime.datetime.now() - self.dashboard.variables["lastProcessUpdate"]).total_seconds() < self.dashboard.variables["processMonitoringInterval"]:
                return
                
            # Check each server's process
            servers_path = self.dashboard.paths["servers"]
            if os.path.exists(servers_path):
                for file in os.listdir(servers_path):
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(servers_path, file), 'r') as f:
                                server_config = json.load(f)
                                
                            server_name = server_config.get("Name", "Unknown")
                            
                            # Check if server has a process ID registered
                            if "ProcessId" in server_config:
                                process_id = server_config["ProcessId"]
                                
                                # Check if process is still running
                                if not self.dashboard.is_process_running(process_id):
                                    log_process_monitoring(f"Server '{server_name}' process (PID {process_id}) is no longer running", "WARNING")
                                    
                                    # Clean up the process ID in the config
                                    server_config.pop('ProcessId', None)
                                    server_config.pop('PID', None)
                                    server_config.pop('StartTime', None)
                                    server_config.pop('ProcessCreateTime', None)
                                    server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                    
                                    # Clean up process history
                                    if process_id in self.dashboard.variables["processStatHistory"]:
                                        del self.dashboard.variables["processStatHistory"][process_id]
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                                    
                                    # Update the server list using thread-safe UI update
                                    def update_ui():
                                        try:
                                            self.dashboard.update_server_list(force_refresh=True)
                                        except Exception as e:
                                            log_process_monitoring(f"Error updating UI from process monitor: {str(e)}", "ERROR")
                                    
                                    # Schedule UI update on main thread
                                    self.dashboard.root.after(0, update_ui)
                                else:
                                    # Process is running, update statistics
                                    try:
                                        process = psutil.Process(process_id)
                                        # Update process statistics here if needed
                                    except Exception as e:
                                        log_process_monitoring(f"Error updating process statistics for {server_name}: {str(e)}", "ERROR")
                        except Exception as e:
                            log_process_monitoring(f"Error monitoring server process in {file}: {str(e)}", "ERROR")
                            
            # Update the last process update time
            self.dashboard.variables["lastProcessUpdate"] = datetime.datetime.now()
            
        except Exception as e:
            log_process_monitoring(f"Error in process monitoring: {str(e)}", "ERROR")