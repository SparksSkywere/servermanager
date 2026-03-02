# Server automation module - Handles automated server operations like MOTD broadcasting, restart warnings, and start commands. Can run independently of the dashboard for scheduled operations.
import os
import sys
import datetime
import threading
import psutil
from typing import Dict, Optional, Callable
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging, send_command_to_server
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

    def _send_command_to_server(self, server_name: str, command: str) -> bool:
        # Delegate to shared implementation in common.py
        return send_command_to_server(server_name, command)

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
