# Server automation module - Handles automated server operations like MOTD broadcasting, restart warnings, and start commands. Can run independently of the dashboard for scheduled operations.
import os
import sys
import time
import datetime
import threading
import psutil
from typing import Dict, Optional, Callable
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging
setup_module_path()

from Modules.Database.server_configs_database import ServerConfigManager

logger: logging.Logger = setup_module_logging("ServerAutomation")


class ServerAutomationManager:
    # Manages automated server operations like MOTD, restart warnings, and start commands

    def __init__(self, server_manager=None):
        self.server_manager = server_manager
        self.running = False
        self._stop_event = threading.Event()
        self.automation_thread = None
        self.last_motd_broadcast = {}  # Track last MOTD broadcast per server
        self.motd_timers = {}  # Track MOTD timers per server

    def start_automation(self):
        # Start the automation service
        if self.running:
            logger.warning("Automation service already running")
            return

        self.running = True
        self.automation_thread = threading.Thread(target=self._automation_loop, daemon=True)
        self.automation_thread.start()
        logger.info("Server automation service started")

    def stop_automation(self):
        # Stop the automation service
        self.running = False
        self._stop_event.set()
        if self.automation_thread and self.automation_thread.is_alive():
            self.automation_thread.join(timeout=5)
        logger.info("Server automation service stopped")

    def _automation_loop(self):
        # Main automation loop that runs periodically
        while self.running:
            try:
                self._check_and_send_motd()
                # Other automation checks can be added here
            except Exception as e:
                logger.error(f"Error in automation loop: {str(e)}")

            # Check every 60 seconds (interruptible)
            self._stop_event.wait(60)
            if self._stop_event.is_set():
                break

    def _check_and_send_motd(self):
        # Check all servers for MOTD broadcasting
        try:
            if not self.server_manager:
                return

            # Get all server configs
            server_configs = self._get_all_server_configs()
            current_time = datetime.datetime.now()

            for server_name, config in server_configs.items():
                try:
                    self._process_server_motd(server_name, config, current_time)
                except Exception as e:
                    logger.error(f"Error processing MOTD for {server_name}: {str(e)}")

        except Exception as e:
            logger.error(f"Error checking MOTD broadcasts: {str(e)}")

    def _process_server_motd(self, server_name: str, config: Dict, current_time: datetime.datetime):
        # Process MOTD for a specific server
        motd_interval = config.get('MotdInterval', 0)
        if motd_interval <= 0:
            return  # MOTD disabled for this server

        motd_message = config.get('MotdMessage', '').strip()
        if not motd_message:
            return  # No message configured

        # Check if it's time to send MOTD
        last_broadcast = self.last_motd_broadcast.get(server_name)
        if last_broadcast:
            last_broadcast_time = datetime.datetime.fromisoformat(last_broadcast)
            time_diff = (current_time - last_broadcast_time).total_seconds() / 60  # minutes
            if time_diff < motd_interval:
                return  # Not time yet

        # Check if server is running
        if not self._is_server_running(server_name):
            return  # Server not running

        # Send MOTD
        if self.send_motd(server_name, motd_message):
            self.last_motd_broadcast[server_name] = current_time.isoformat()
            logger.info(f"MOTD sent to {server_name}: {motd_message}")
        else:
            logger.warning(f"Failed to send MOTD to {server_name}")

    def _get_all_server_configs(self) -> Dict[str, Dict]:
        # Get all server configurations
        try:
            if self.server_manager and hasattr(self.server_manager, 'get_all_servers'):
                servers = self.server_manager.get_all_servers()
                return {server['Name']: server for server in servers}
            elif self.server_manager and hasattr(self.server_manager, 'server_configs'):
                return self.server_manager.server_configs
            else:
                # Fallback: get from database directly
                manager = ServerConfigManager()
                all_servers = manager.get_all_servers()
                configs = {}
                for server in all_servers:
                    server_name = server.get('Name', server.get('name', ''))
                    if server_name:
                        configs[server_name] = server
                return configs
        except Exception as e:
            logger.error(f"Error getting server configs: {str(e)}")
            return {}

    def _is_server_running(self, server_name: str) -> bool:
        # Check if a server is currently running
        try:
            if self.server_manager and hasattr(self.server_manager, 'is_server_running'):
                return self.server_manager.is_server_running(server_name)

            # Fallback: check process ID from config
            config = self._get_server_config(server_name)
            if config:
                pid = config.get('ProcessId') or config.get('PID')
                if pid:
                    return psutil.pid_exists(pid)

            return False
        except Exception as e:
            logger.debug(f"Error checking if {server_name} is running: {str(e)}")
            return False

    def _get_server_config(self, server_name: str) -> Optional[Dict]:
        # Get configuration for a specific server
        try:
            if self.server_manager and hasattr(self.server_manager, 'get_server_config'):
                return self.server_manager.get_server_config(server_name)
            else:
                # Fallback: get from database
                manager = ServerConfigManager()
                return manager.get_server(server_name)
        except Exception as e:
            logger.error(f"Error getting config for {server_name}: {str(e)}")
            return None

    def send_motd(self, server_name: str, message: str, progress_callback: Optional[Callable] = None) -> bool:
        # Send a MOTD/broadcast message to a server
        try:
            server_config = self._get_server_config(server_name)
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

    def execute_start_command(self, server_name: str, progress_callback: Optional[Callable] = None) -> bool:
        # Execute the start command for a server after it starts
        try:
            server_config = self._get_server_config(server_name)
            if not server_config:
                logger.error(f"Server config not found for {server_name}")
                return False

            start_command = server_config.get('StartCommand', '').strip()
            if not start_command:
                return True  # No start command configured, consider success

            # Wait a bit for server to fully start (interruptible)
            self._stop_event.wait(10)

            if self._send_command_to_server(server_name, start_command):
                if progress_callback:
                    progress_callback(f"[INFO] Start command executed for {server_name}")
                logger.info(f"Start command executed for {server_name}: {start_command}")
                return True
            else:
                if progress_callback:
                    progress_callback(f"[ERROR] Failed to execute start command for {server_name}")
                logger.warning(f"Failed to execute start command for {server_name}")
                return False

        except Exception as e:
            logger.error(f"Error executing start command for {server_name}: {str(e)}")
            return False

    def send_restart_warnings(self, server_name: str, progress_callback: Optional[Callable] = None) -> bool:
        # Send pre-restart warning messages to players
        try:
            server_config = self._get_server_config(server_name)
            if not server_config:
                logger.error(f"Server config not found for {server_name}")
                return False

            warning_command = server_config.get('WarningCommand', '')
            if not warning_command:
                logger.debug(f"No warning command configured for {server_name}, skipping warnings")
                return True  # Not an error, just no warnings configured

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
                        message = "1 minute"
                    else:
                        message = f"{minutes} minutes"

                    # Replace {message} placeholder with the time remaining
                    command = warning_command.replace('{message}', message)

                    # Send the command to the server
                    if self._send_command_to_server(server_name, command):
                        if progress_callback:
                            progress_callback(f"[INFO] Sent warning: {message} remaining")
                        logger.info(f"Sent restart warning to {server_name}: {message} remaining")
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
                            self._stop_event.wait(wait_seconds)
                            if self._stop_event.is_set():
                                return True
                    else:
                        # Wait for the final interval before restart
                        if progress_callback:
                            progress_callback(f"[INFO] Final warning sent, waiting {minutes * 60} seconds before restart...")
                        self._stop_event.wait(minutes * 60)
                        if self._stop_event.is_set():
                            return True

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

            return True

        except Exception as e:
            logger.error(f"Error sending restart warnings for {server_name}: {str(e)}")
            return False

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

    def run(self):
        # Main automation loop - runs indefinitely
        logger.info("Server automation manager starting...")
        
        try:
            while True:
                try:
                    self._automation_loop()
                except Exception as e:
                    logger.error(f"Error in automation loop: {str(e)}")
                
                # Sleep for 30 seconds between automation checks (interruptible)
                self._stop_event.wait(30)
                if self._stop_event.is_set():
                    break
                
        except KeyboardInterrupt:
            logger.info("Server automation manager stopped")
        except Exception as e:
            logger.error(f"Fatal error in server automation: {str(e)}")
            raise


def main():
    # Main entry point for running server automation as a standalone process
    try:
        logger.info("Starting Server Automation Manager...")
        
        # Create and start the automation manager
        automation_manager = ServerAutomationManager()
        
        # Run the automation loop indefinitely
        automation_manager.run()
        
    except KeyboardInterrupt:
        logger.info("Server automation stopped by user")
    except Exception as e:
        logger.error(f"Server automation failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
