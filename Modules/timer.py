import os
import json
import datetime
import psutil
from Modules.logging import log_process_monitoring


class TimerManager:
    """Manages all timer functionality for the dashboard"""
    
    def __init__(self, dashboard):
        """
        Initialize the TimerManager with a reference to the dashboard
        
        Args:
            dashboard: Reference to the ServerManagerDashboard instance
        """
        self.dashboard = dashboard
    
    def start_timers(self):
        """Start update timers using configuration values"""
        # System info update timer
        system_interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
        self.dashboard.root.after(system_interval, self.system_info_timer)
        
        # Server list update timer
        server_interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
        self.dashboard.root.after(server_interval, self.server_list_timer)
        
        # Web server status update timer
        webserver_interval = self.dashboard.variables["webserverStatusUpdateInterval"] * 1000
        self.dashboard.root.after(webserver_interval, self.webserver_status_timer)
        
        # Process monitoring timer
        process_interval = self.dashboard.variables["processMonitorUpdateInterval"] * 1000
        self.dashboard.root.after(process_interval, self.process_monitor_timer)

    def system_info_timer(self):
        """Timer callback for system info updates"""
        self.dashboard.update_system_info()
        interval = self.dashboard.variables["systemInfoUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.system_info_timer)
    
    def server_list_timer(self):
        """Timer callback for server list updates"""
        self.dashboard.update_server_list()
        interval = self.dashboard.variables["serverListUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.server_list_timer)
    
    def webserver_status_timer(self):
        """Timer callback for web server status updates"""
        self.dashboard.update_webserver_status()
        interval = self.dashboard.variables["webserverStatusUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.webserver_status_timer)
    
    def process_monitor_timer(self):
        """Timer callback for process monitoring"""
        self.monitor_processes()
        interval = self.dashboard.variables["processMonitorUpdateInterval"] * 1000
        self.dashboard.root.after(interval, self.process_monitor_timer)
    
    def monitor_processes(self):
        """Monitor running server processes"""
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
                                    server_config.pop('StartTime', None)
                                    server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                                    
                                    # Clean up process history
                                    if process_id in self.dashboard.variables["processStatHistory"]:
                                        del self.dashboard.variables["processStatHistory"][process_id]
                                    
                                    # Save updated configuration
                                    with open(os.path.join(servers_path, file), 'w') as f:
                                        json.dump(server_config, f, indent=4)
                                    
                                    # Update the server list
                                    self.dashboard.update_server_list(force_refresh=True)
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
