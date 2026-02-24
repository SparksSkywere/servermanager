# -*- coding: utf-8 -*-
# Server update management
import os
import sys
import json
import time
import subprocess
import datetime
from typing import Dict, Tuple, Optional, Callable
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, ServerManagerModule, setup_module_logging, get_subprocess_creation_flags
setup_module_path()

from Modules.Database.cluster_database import get_cluster_database

logger: logging.Logger = setup_module_logging("ServerUpdateManager")


class ServerUpdateManager(ServerManagerModule):
    # - Automatic updates and restarts
    # - Per-server and global schedules
    
    def __init__(self, server_manager_dir: Optional[str] = None, config: Optional[Dict] = None):
        super().__init__("ServerUpdateManager")
        self.server_manager = None
        self.steam_cmd_path: Optional[str] = None
        self.update_in_progress: Dict[str, bool] = {}
        self.update_schedules: Dict[str, Dict] = {}
        self.restart_schedules: Dict[str, Dict] = {}
        self.global_schedule: Optional[Dict] = None
        self.global_restart_schedule: Optional[Dict] = None
        self.last_update_check: Dict[str, str] = {}
        self.last_restart: Dict[str, str] = {}
        self.load_update_config()
    
    def set_server_manager(self, server_manager):
        self.server_manager = server_manager
    
    def set_steam_cmd_path(self, steam_cmd_path):
        self.steam_cmd_path = steam_cmd_path
    
    def load_update_config(self):
        # Load from DB-migrates JSON if needed
        try:
            db = get_cluster_database()
            
            config_data = db.get_update_config()
            full_config = config_data.get("full_config", {})
            
            if isinstance(full_config, str):
                full_config = json.loads(full_config)
            
            if not full_config:
                server_dir = self.server_manager_dir or os.getcwd()
                config_file = os.path.join(server_dir, "data", "update_config.json")
                if os.path.exists(config_file):
                    logger.info("Migrating update config from JSON")
                    db.migrate_update_config_from_json(config_file)
                    config_data = db.get_update_config()
                    full_config = config_data.get("full_config", {})
                    if isinstance(full_config, str):
                        full_config = json.loads(full_config)
            
            # Load config values
            self.update_schedules = full_config.get("server_schedules", {})
            self.restart_schedules = full_config.get("restart_schedules", {})
            self.global_schedule = full_config.get("global_schedule", None)
            self.global_restart_schedule = full_config.get("global_restart_schedule", None)
            self.last_update_check = full_config.get("last_update_check", {})
            self.last_restart = full_config.get("last_restart", {})
            
        except Exception as e:
            logger.error(f"Error loading update config from database: {str(e)}")
            # Initialise with defaults
            self.update_schedules = {}
            self.restart_schedules = {}
            self.global_schedule = None
            self.global_restart_schedule = None
            self.last_update_check = {}
            self.last_restart = {}
    
    def save_update_config(self):
        try:
            db = get_cluster_database()
            
            data = {
                "server_schedules": self.update_schedules,
                "restart_schedules": self.restart_schedules,
                "global_schedule": self.global_schedule,
                "global_restart_schedule": self.global_restart_schedule,
                "last_update_check": self.last_update_check,
                "last_restart": self.last_restart,
                "last_saved": datetime.datetime.now().isoformat()
            }
            
            db.set_update_config("full_config", data, "json", "schedules")
            logger.debug("Update config saved to database")
            
        except Exception as e:
            logger.error(f"Error saving update config to database: {str(e)}")
    
    def check_for_updates(self, server_name: str, app_id: str, credentials: Optional[Dict] = None,
                         progress_callback: Optional[Callable] = None) -> Tuple[bool, str, bool]:
        # Check if a Steam server has updates available
        process = None
        try:
            if not self.steam_cmd_path:
                return False, "SteamCMD path not configured", False
            
            if progress_callback:
                progress_callback(f"[INFO] Checking for updates for {server_name} (App ID: {app_id})")
            
            steam_cmd_exe = os.path.join(self.steam_cmd_path, "steamcmd.exe")
            if not os.path.exists(steam_cmd_exe):
                return False, f"SteamCMD executable not found at: {steam_cmd_exe}", False
            
            # Use anonymous login by default
            if not credentials:
                credentials = {"anonymous": True}
            
            # Build SteamCMD command for update check (as a proper arg list to avoid shell injection)
            if credentials.get("anonymous", True):
                login_args = ["+login", "anonymous"]
            else:
                login_args = ["+login", credentials['username'], credentials['password']]
            
            steam_cmd_args = [
                steam_cmd_exe,
                *login_args,
                "+app_info_update", "1",
                "+app_info_print", str(app_id),
                "+quit"
            ]
            
            if progress_callback:
                progress_callback(f"[INFO] Running update check: {steam_cmd_exe} +login ... +app_info_update +app_info_print {app_id} +quit")
            
            # Execute SteamCMD (shell=False to prevent shell injection)
            process = subprocess.Popen(
                steam_cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=get_subprocess_creation_flags(hide_window=True)
            )
            
            stdout, stderr = process.communicate(timeout=120)  # 2 minute timeout
            
            if process.returncode == 0:
                # Parse output to check for updates
                # This is a simplified check - in practice, you'd compare build IDs
                has_updates = self._parse_update_info(stdout, app_id)
                
                # Update last check time
                self.last_update_check[server_name] = datetime.datetime.now().isoformat()
                self.save_update_config()
                
                if progress_callback:
                    status = "Updates available" if has_updates else "Up to date"
                    progress_callback(f"[INFO] Update check complete: {status}")
                
                return True, "Update check completed successfully", has_updates
            else:
                exit_code = process.returncode
                error_description = "Unknown error"
                
                # Get detailed error description if server_manager is available
                if self.server_manager and hasattr(self.server_manager, 'get_steamcmd_error_description'):
                    error_description = self.server_manager.get_steamcmd_error_description(exit_code)
                
                error_msg = f"SteamCMD failed with exit code {exit_code}: {error_description}"
                if stderr:
                    error_msg += f" (Details: {stderr.strip()})"
                return False, error_msg, False
                
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
            return False, "Update check timed out", False
        except Exception as e:
            logger.error(f"Error checking for updates: {str(e)}")
            return False, f"Update check failed: {str(e)}", False
    
    def _parse_update_info(self, steamcmd_output: str, app_id: str) -> bool:
        # Parse SteamCMD output to determine if updates are available
        try:
            # Look for the app info section
            lines = steamcmd_output.split('\n')
            in_app_section = False
            
            for line in lines:
                line = line.strip()
                if f'"{app_id}"' in line and 'AppID' in line:
                    in_app_section = True
                elif in_app_section and 'buildid' in line.lower():
                    # Extract build ID and compare with cached version
                    # For now, return True to indicate updates might be available
                    # In practice, you'd store and compare build IDs
                    return True
            
            return False  # No clear indication of updates
        except Exception as e:
            logger.error(f"Error parsing update info: {str(e)}")
            return False
    
    def update_server(self, server_name: str, server_config: Dict, credentials: Optional[Dict] = None,
                     progress_callback: Optional[Callable] = None, stop_server: bool = True, 
                     scheduled: bool = False) -> Tuple[bool, str]:
        # Update a Steam server
        try:
            if server_name in self.update_in_progress:
                return False, f"Update already in progress for {server_name}"
            
            # Mark update as in progress
            self.update_in_progress[server_name] = True
            
            app_id = server_config.get('AppID', '')
            install_dir = server_config.get('InstallDir', '')
            
            if not app_id:
                return False, "Server does not have an App ID (not a Steam server)"
            
            if not install_dir or not os.path.exists(install_dir):
                return False, f"Installation directory not found: {install_dir}"
            
            if progress_callback:
                progress_callback(f"[INFO] Starting update for {server_name}")
            elif scheduled:
                logger.info(f"Starting scheduled update for {server_name}")
            
            # Stop server if requested and if server manager is available
            server_was_running = False
            if stop_server and self.server_manager:
                # Check if server is running
                server_status = self.server_manager.get_server_status(server_name)
                # server_status returns a tuple (status, pid)
                if server_status and server_status[0] == 'Running':
                    server_was_running = True
                    if progress_callback:
                        progress_callback(f"[INFO] Stopping {server_name} for update...")
                    elif scheduled:
                        logger.info(f"Stopping {server_name} for scheduled update...")
                    
                    success, msg = self.server_manager.stop_server(server_name)
                    if not success:
                        error_msg = f"Failed to stop server for update: {msg}"
                        if scheduled:
                            logger.error(error_msg)
                        return False, error_msg
                    
                    # Wait a moment for the server to fully stop
                    time.sleep(3)
            
            try:
                # Use the existing install_steam_server method for updates
                if not credentials:
                    credentials = {"anonymous": True}
                
                # Create a wrapped progress callback for scheduled updates
                wrapped_progress_callback = None
                if progress_callback:
                    wrapped_progress_callback = progress_callback
                elif scheduled:
                    # For scheduled updates, log to file instead of showing console
                    def scheduled_progress_callback(message):
                        logger.info(f"[{server_name}] {message}")
                    wrapped_progress_callback = scheduled_progress_callback
                
                # This will validate and update the server
                if self.server_manager:
                    success, message = self.server_manager.install_steam_server(
                        server_name, app_id, install_dir, self.steam_cmd_path, 
                        credentials, wrapped_progress_callback
                    )
                else:
                    return False, "Server manager not available"
                
                if success:
                    # Update last update time
                    server_config['LastUpdate'] = datetime.datetime.now().isoformat()
                    if self.server_manager:
                        self.server_manager.update_server(server_name, server_config)
                    
                    if progress_callback:
                        progress_callback(f"[INFO] Update completed for {server_name}")
                    elif scheduled:
                        logger.info(f"Scheduled update completed for {server_name}")
                    
                    # Restart server if it was running before
                    if server_was_running and self.server_manager:
                        if progress_callback:
                            progress_callback(f"[INFO] Restarting {server_name}...")
                        elif scheduled:
                            logger.info(f"Restarting {server_name} after scheduled update...")
                        
                        restart_result = self.server_manager.start_server(server_name)
                        # Handle both boolean and tuple return types
                        if isinstance(restart_result, tuple):
                            restart_success, restart_msg = restart_result
                        else:
                            restart_success = restart_result
                            restart_msg = "Failed to start" if not restart_success else "Started successfully"
                            
                        if not restart_success:
                            warning_msg = f"Failed to restart server after update: {restart_msg}"
                            logger.warning(warning_msg)
                            message += f" (Warning: Failed to restart server: {restart_msg})"
                    
                    return True, message
                else:
                    if scheduled:
                        logger.error(f"Scheduled update failed for {server_name}: {message}")
                    return False, message
                    
            finally:
                # Always restart server if it was running, even if update failed
                if server_was_running and self.server_manager:
                    try:
                        restart_result = self.server_manager.start_server(server_name)
                        # Handle both boolean and tuple return types
                        if isinstance(restart_result, tuple):
                            restart_success, restart_msg = restart_result
                        else:
                            restart_success = restart_result
                        if not restart_success:
                            error_msg = f"Failed to restart server after failed update"
                            logger.error(error_msg)
                            if scheduled:
                                logger.error(f"[{server_name}] {error_msg}")
                    except Exception as e:
                        error_msg = f"Error restarting server after failed update: {str(e)}"
                        logger.error(error_msg)
                        if scheduled:
                            logger.error(f"[{server_name}] {error_msg}")
                        
        except Exception as e:
            error_msg = f"Error updating server {server_name}: {str(e)}"
            logger.error(error_msg)
            if scheduled:
                logger.error(f"Scheduled update error for {server_name}: {str(e)}")
            return False, f"Update failed: {str(e)}"
        finally:
            # Mark update as complete
            if server_name in self.update_in_progress:
                del self.update_in_progress[server_name]
    
    def update_all_steam_servers(self, credentials: Optional[Dict] = None, progress_callback: Optional[Callable] = None,
                                stop_servers: bool = True, scheduled: bool = False) -> Dict[str, Tuple[bool, str]]:
        # Update all Steam servers
        results = {}
        
        if not self.server_manager:
            return {"error": (False, "Server manager not available")}
        
        try:
            # Get all servers
            servers = self.server_manager.get_all_servers()
            steam_servers = []
            
            # Filter Steam servers
            for server_name, server_config in servers.items():
                if server_config.get('Type') == 'Steam' and server_config.get('AppID'):
                    steam_servers.append((server_name, server_config))
            
            if not steam_servers:
                return {"info": (True, "No Steam servers found to update")}
            
            if progress_callback:
                progress_callback(f"[INFO] Found {len(steam_servers)} Steam servers to update")
            elif scheduled:
                logger.info(f"Found {len(steam_servers)} Steam servers for scheduled update")
            
            # Update each server
            for server_name, server_config in steam_servers:
                if progress_callback:
                    progress_callback(f"[INFO] Updating {server_name}...")
                elif scheduled:
                    logger.info(f"Starting scheduled update for {server_name}...")
                
                success, message = self.update_server(
                    server_name, server_config, credentials, progress_callback, stop_servers, scheduled
                )
                results[server_name] = (success, message)
                
                # Small delay between updates
                time.sleep(2)
            
            return results
            
        except Exception as e:
            error_msg = f"Batch update failed: {str(e)}"
            logger.error(error_msg)
            if scheduled:
                logger.error(f"Scheduled batch update failed: {str(e)}")
            return {"error": (False, error_msg)}
    
    def set_server_update_schedule(self, server_name: str, schedule_config: Dict):
        # Set update schedule for a specific server
        self.update_schedules[server_name] = schedule_config
        self.save_update_config()
        logger.info(f"Set update schedule for {server_name}: {schedule_config}")
    
    def set_global_update_schedule(self, schedule_config: Dict):
        # Set global update schedule for all Steam servers
        self.global_schedule = schedule_config
        self.save_update_config()
        logger.info(f"Set global update schedule: {schedule_config}")
    
    def get_server_update_schedule(self, server_name: str) -> Optional[Dict]:
        # Get update schedule for a server
        return self.update_schedules.get(server_name)
    
    def get_global_update_schedule(self) -> Optional[Dict]:
        # Get global update schedule
        return self.global_schedule
    
    def remove_server_update_schedule(self, server_name: str):
        # Remove update schedule for a server
        if server_name in self.update_schedules:
            del self.update_schedules[server_name]
            self.save_update_config()
            logger.info(f"Removed update schedule for {server_name}")
    
    def remove_global_update_schedule(self):
        # Remove global update schedule
        self.global_schedule = None
        self.save_update_config()
        logger.info("Removed global update schedule")
    
    # Restart schedule methods
    def set_server_restart_schedule(self, server_name: str, schedule_config: Dict):
        # Set restart schedule for a specific server
        self.restart_schedules[server_name] = schedule_config
        self.save_update_config()
        logger.info(f"Set restart schedule for {server_name}: {schedule_config}")
    
    def set_global_restart_schedule(self, schedule_config: Dict):
        # Set global restart schedule for all servers
        self.global_restart_schedule = schedule_config
        self.save_update_config()
        logger.info(f"Set global restart schedule: {schedule_config}")
    
    def get_server_restart_schedule(self, server_name: str) -> Optional[Dict]:
        # Get restart schedule for a server
        return self.restart_schedules.get(server_name)
    
    def get_global_restart_schedule(self) -> Optional[Dict]:
        # Get global restart schedule
        return self.global_restart_schedule
    
    def remove_server_restart_schedule(self, server_name: str):
        # Remove restart schedule for a server
        if server_name in self.restart_schedules:
            del self.restart_schedules[server_name]
            self.save_update_config()
            logger.info(f"Removed restart schedule for {server_name}")
    
    def remove_global_restart_schedule(self):
        # Remove global restart schedule
        self.global_restart_schedule = None
        self.save_update_config()
        logger.info("Removed global restart schedule")
    
    def should_check_for_updates(self, server_name: str, schedule_config: Dict) -> bool:
        # Check if it's time to check for updates based on schedule
        try:
            if not schedule_config.get('enabled', False):
                return False
            
            now = datetime.datetime.now()
            schedule_time = schedule_config.get('time', '02:00')  # Default 2 AM
            schedule_days = schedule_config.get('days', list(range(7)))  # Default all days
            
            # Check if today is a scheduled day
            if now.weekday() not in schedule_days:
                return False
            
            # Parse schedule time
            try:
                schedule_hour, schedule_minute = map(int, schedule_time.split(':'))
            except ValueError:
                logger.error(f"Invalid schedule time format: {schedule_time}")
                return False
            
            # Check if we're within the update window (30 minutes)
            schedule_datetime = now.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
            time_diff = abs((now - schedule_datetime).total_seconds())
            
            # Check if we're within 30 minutes of the scheduled time
            if time_diff <= 1800:  # 30 minutes in seconds
                # Check if we haven't already checked today
                last_check = self.last_update_check.get(server_name)
                if last_check:
                    last_check_date = datetime.datetime.fromisoformat(last_check).date()
                    if last_check_date >= now.date():
                        return False  # Already checked today
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking update schedule: {str(e)}")
            return False
    
    def should_restart_server(self, server_name: str, schedule_config: Dict) -> bool:
        # Check if it's time to restart a server based on schedule
        try:
            if not schedule_config.get('enabled', False):
                return False
            
            now = datetime.datetime.now()
            schedule_time = schedule_config.get('time', '04:00')  # Default 4 AM for restarts
            schedule_days = schedule_config.get('days', list(range(7)))  # Default all days
            scattered = schedule_config.get('scattered', False)
            scatter_window = schedule_config.get('scatter_window', 60)  # Default 60 minutes
            
            # Check if today is a scheduled day
            if now.weekday() not in schedule_days:
                return False
            
            # Parse schedule time
            try:
                schedule_hour, schedule_minute = map(int, schedule_time.split(':'))
            except ValueError:
                logger.error(f"Invalid restart schedule time format: {schedule_time}")
                return False
            
            # Create scheduled restart time
            schedule_datetime = now.replace(hour=schedule_hour, minute=schedule_minute, second=0, microsecond=0)
            
            # If scattered restarts are enabled, add a server-specific offset
            if scattered:
                # Use server name hash to get consistent offset for this server
                import hashlib
                server_hash = int(hashlib.sha256(server_name.encode()).hexdigest()[:8], 16)
                offset_minutes = server_hash % scatter_window
                schedule_datetime += datetime.timedelta(minutes=offset_minutes)
            
            # Check if we're within the restart window (10 minutes for restarts)
            time_diff = abs((now - schedule_datetime).total_seconds())
            
            # Check if we're within 10 minutes of the scheduled time
            if time_diff <= 600:  # 10 minutes in seconds
                # Check if we haven't already restarted today
                last_restart = self.last_restart.get(server_name)
                if last_restart:
                    last_restart_date = datetime.datetime.fromisoformat(last_restart).date()
                    if last_restart_date >= now.date():
                        return False  # Already restarted today
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking restart schedule: {str(e)}")
            return False
    
    def _send_restart_warnings(self, server_name: str, server_config: Dict, 
                               progress_callback: Optional[Callable] = None):
        # Send pre-restart warning messages to players
        try:
            warning_command = server_config.get('WarningCommand', '')
            warning_message_template = server_config.get('WarningMessageTemplate', 'Server restarting in {message}')
            if not warning_command:
                logger.debug(f"No warning command configured for {server_name}, skipping warnings")
                return
            
            warning_intervals_str = server_config.get('WarningIntervals', '30,15,10,5,1')
            try:
                warning_intervals = [int(x.strip()) for x in warning_intervals_str.split(',') if x.strip()]
            except ValueError:
                warning_intervals = [30, 15, 10, 5, 1]
            
            if not warning_intervals:
                warning_intervals = [1]  # At least 1 minute warning
            
            # Sort intervals in descending order
            warning_intervals.sort(reverse=True)
            
            if progress_callback:
                progress_callback(f"[INFO] Sending restart warnings to {server_name} at intervals: {warning_intervals} minutes")
            
            # Send warnings at each interval
            for minutes in warning_intervals:
                try:
                    # Format the warning message
                    if minutes == 1:
                        time_message = "1 minute"
                    else:
                        time_message = f"{minutes} minutes"
                    
                    # Replace {message} in template with time
                    full_message = warning_message_template.replace('{message}', time_message)
                    
                    # Replace {message} placeholder in command with the full message
                    command = warning_command.replace('{message}', full_message)
                    
                    # Send the command to the server
                    if self._send_command_to_server(server_name, command):
                        if progress_callback:
                            progress_callback(f"[INFO] Sent warning: {full_message}")
                        logger.info(f"Sent restart warning to {server_name}: {full_message}")
                    else:
                        if progress_callback:
                            progress_callback(f"[WARN] Failed to send warning to {server_name}")
                    
                    # Wait until the next warning interval
                    if warning_intervals.index(minutes) < len(warning_intervals) - 1:
                        next_interval = warning_intervals[warning_intervals.index(minutes) + 1]
                        wait_seconds = (minutes - next_interval) * 60
                        if wait_seconds > 0:
                            if progress_callback:
                                progress_callback(f"[INFO] Waiting {wait_seconds} seconds until next warning...")
                            time.sleep(wait_seconds)
                    else:
                        # Wait for the final interval before restart
                        if progress_callback:
                            progress_callback(f"[INFO] Final warning sent, waiting {minutes * 60} seconds before restart...")
                        time.sleep(minutes * 60)
                        
                except Exception as e:
                    logger.error(f"Error sending warning at {minutes} minutes: {str(e)}")
                    continue
            
            # Send save command before restart if configured
            save_command = server_config.get('SaveCommand', '')
            if save_command:
                if progress_callback:
                    progress_callback(f"[INFO] Sending save command before restart...")
                if self._send_command_to_server(server_name, save_command):
                    logger.info(f"Sent save command to {server_name} before restart")
                    time.sleep(5)  # Give the server time to save
                    
        except Exception as e:
            logger.error(f"Error sending restart warnings for {server_name}: {str(e)}")
    
    def _send_command_to_server(self, server_name: str, command: str) -> bool:
        # Send a command to a running server
        try:
            # Try using persistent stdin pipe
            try:
                from services.persistent_stdin import send_command_to_stdin_pipe, is_stdin_pipe_available
                if is_stdin_pipe_available(server_name):
                    result = send_command_to_stdin_pipe(server_name, command)
                    # Handle both bool and tuple return types
                    if isinstance(result, tuple):
                        return result[0]
                    return result
            except ImportError:
                pass
            
            # Try using command queue
            try:
                from services.command_queue import queue_command, is_relay_active
                if is_relay_active(server_name):
                    result = queue_command(server_name, command)
                    # Handle both bool and tuple return types
                    if isinstance(result, tuple):
                        return result[0]
                    return result
            except ImportError:
                pass
            
            logger.warning(f"No command input method available for {server_name}")
            return False
            
        except Exception as e:
            logger.error(f"Error sending command to {server_name}: {str(e)}")
            return False
    
    def send_motd(self, server_name: str, message: str, progress_callback: Optional[Callable] = None) -> bool:
        # Send a MOTD/broadcast message to a server
        try:
            if not self.server_manager:
                return False
            
            server_config = self.server_manager.get_server_config(server_name)
            if not server_config:
                logger.error(f"Server config not found for {server_name}")
                return False
            
            motd_command = server_config.get('MotdCommand', '')
            if not motd_command:
                logger.warning(f"No MOTD command configured for {server_name}")
                return False
            
            # Replace {message} placeholder
            command = motd_command.replace('{message}', message)
            
            if self._send_command_to_server(server_name, command):
                if progress_callback:
                    progress_callback(f"[INFO] MOTD sent to {server_name}: {message}")
                logger.info(f"MOTD sent to {server_name}: {message}")
                return True
            else:
                if progress_callback:
                    progress_callback(f"[ERROR] Failed to send MOTD to {server_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending MOTD to {server_name}: {str(e)}")
            return False
    
    def restart_server(self, server_name: str, server_config: Dict, 
                      progress_callback: Optional[Callable] = None, scheduled: bool = False) -> Tuple[bool, str]:
        # Restart a server with optional pre-restart warnings
        try:
            if not self.server_manager:
                return False, "Server manager not available"
            
            if progress_callback:
                action = "Scheduled restart" if scheduled else "Manual restart"
                progress_callback(f"[INFO] {action} starting for {server_name}")
            
            # Send pre-restart warnings if scheduled and warning command is configured
            if scheduled:
                self._send_restart_warnings(server_name, server_config, progress_callback)
            
            # Use the server manager to restart the server
            success, message = self.server_manager.restart_server_advanced(
                server_name,
                callback=lambda status: progress_callback(f"[INFO] {status}") if progress_callback else None
            )
            
            if success:
                # Update last restart time
                self.last_restart[server_name] = datetime.datetime.now().isoformat()
                self.save_update_config()
                
                if progress_callback:
                    progress_callback(f"[SUCCESS] {server_name} restarted successfully")
                
                logger.info(f"Server {server_name} restarted successfully")
                return True, f"Server '{server_name}' restarted successfully"
            else:
                if progress_callback:
                    progress_callback(f"[ERROR] Failed to restart {server_name}: {message}")
                
                logger.error(f"Failed to restart server {server_name}: {message}")
                return False, f"Failed to restart server: {message}"
                
        except Exception as e:
            error_msg = f"Error restarting server {server_name}: {str(e)}"
            logger.error(error_msg)
            if progress_callback:
                progress_callback(f"[ERROR] {error_msg}")
            return False, error_msg
    
    def restart_all_servers(self, progress_callback: Optional[Callable] = None, scheduled: bool = False) -> Dict[str, Tuple[bool, str]]:
        # Restart all servers
        try:
            if not self.server_manager:
                return {"error": (False, "Server manager not available")}
            
            servers = self.server_manager.get_all_servers()
            results = {}
            
            if progress_callback:
                action = "Scheduled restart" if scheduled else "Manual restart"
                progress_callback(f"[INFO] {action} starting for all servers...")
            
            for server_name, server_config in servers.items():
                if progress_callback:
                    progress_callback(f"[INFO] Restarting {server_name}...")
                
                success, message = self.restart_server(
                    server_name, server_config, progress_callback, scheduled
                )
                results[server_name] = (success, message)
                
                # Small delay between restarts to avoid overwhelming the system
                time.sleep(2)
            
            # Count successes and failures
            successes = len([r for r in results.values() if r[0]])
            failures = len([r for r in results.values() if not r[0]])
            
            if progress_callback:
                progress_callback(f"[SUMMARY] Restart batch complete: {successes} successful, {failures} failed")
            
            logger.info(f"Batch restart complete: {successes} successful, {failures} failed")
            return results
            
        except Exception as e:
            error_msg = f"Batch restart failed: {str(e)}"
            logger.error(error_msg)
            if progress_callback:
                progress_callback(f"[ERROR] {error_msg}")
            if scheduled:
                logger.error(f"Scheduled batch restart failed: {str(e)}")
            return {"error": (False, error_msg)}
    
    def run_scheduled_updates(self, progress_callback: Optional[Callable] = None):
        # Run scheduled update checks and restarts for all configured servers
        try:
            logger.debug("[SUBPROCESS_TRACE] run_scheduled_updates() called")
            if not self.server_manager:
                return
            
            servers = self.server_manager.get_all_servers()
            updates_performed = 0
            restarts_performed = 0
            
            # Check global update schedule first
            if self.global_schedule and self.should_check_for_updates("global", self.global_schedule):
                logger.info("Running global scheduled updates...")
                logger.debug("[SUBPROCESS_TRACE] Running global scheduled updates - may call subprocess")
                
                results = self.update_all_steam_servers(progress_callback=progress_callback, scheduled=True)
                updates_performed += len([r for r in results.values() if r[0]])
                
                # Log results for scheduled updates
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                logger.info(f"Global scheduled updates complete: {successes} successful, {failures} failed")
            
            # Check global restart schedule
            if self.global_restart_schedule and self.should_restart_server("global", self.global_restart_schedule):
                logger.info("Running global scheduled restarts...")
                
                results = self.restart_all_servers(progress_callback=progress_callback, scheduled=True)
                restarts_performed += len([r for r in results.values() if r[0]])
                
                # Log results for scheduled restarts
                successes = len([r for r in results.values() if r[0]])
                failures = len([r for r in results.values() if not r[0]])
                logger.info(f"Global scheduled restarts complete: {successes} successful, {failures} failed")
            
            # Check individual server schedules
            for server_name, server_config in servers.items():
                # Check for update schedule
                if server_config.get('Type') == 'Steam' and server_config.get('AppID'):
                    update_schedule = self.get_server_update_schedule(server_name)
                    if update_schedule and self.should_check_for_updates(server_name, update_schedule):
                        logger.info(f"Running scheduled update for {server_name}...")
                        
                        if update_schedule.get('check_only', False):
                            # Only check for updates, don't install
                            success, msg, has_updates = self.check_for_updates(
                                server_name, server_config['AppID'], progress_callback=progress_callback
                            )
                            if success and has_updates:
                                logger.info(f"Updates available for {server_name} (check-only mode)")
                            elif success:
                                logger.info(f"No updates available for {server_name} (check-only mode)")
                            else:
                                logger.error(f"Failed to check updates for {server_name}: {msg}")
                        else:
                            # Perform actual update
                            success, msg = self.update_server(
                                server_name, server_config, progress_callback=progress_callback, scheduled=True
                            )
                            if success:
                                updates_performed += 1
                                logger.info(f"Scheduled update completed successfully for {server_name}")
                            else:
                                logger.error(f"Scheduled update failed for {server_name}: {msg}")
                
                # Check for restart schedule (applies to all server types)
                restart_schedule = self.get_server_restart_schedule(server_name)
                if restart_schedule and self.should_restart_server(server_name, restart_schedule):
                    logger.info(f"Running scheduled restart for {server_name}...")
                    
                    success, msg = self.restart_server(
                        server_name, server_config, progress_callback=progress_callback, scheduled=True
                    )
                    if success:
                        restarts_performed += 1
                        logger.info(f"Scheduled restart completed successfully for {server_name}")
                    else:
                        logger.error(f"Scheduled restart failed for {server_name}: {msg}")
            
            if updates_performed > 0 or restarts_performed > 0:
                logger.info(f"Scheduled tasks complete. {updates_performed} servers updated, {restarts_performed} servers restarted.")
                
        except Exception as e:
            logger.error(f"Error running scheduled tasks: {str(e)}")
