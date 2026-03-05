# -*- coding: utf-8 -*-
# Dashboard tracker
import os
import sys
import json
import time
import threading
import psutil
import logging
from pathlib import Path

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path, setup_module_logging
setup_module_path()
logger: logging.Logger = setup_module_logging("DashboardTracker")

class DashboardTracker:
    # Scans for running dashboard/server processes
    def __init__(self, server_manager_dir=None):
        if server_manager_dir is None:
            server_manager_dir = os.environ.get("SERVERMANAGERDIR")
            if not server_manager_dir:
                server_manager_dir = str(Path(__file__).resolve().parent.parent)
        self.server_manager_dir = server_manager_dir
        self.temp_dir = os.path.join(self.server_manager_dir, "temp")
        self.servers_dir = os.path.join(self.server_manager_dir, "servers")
        self.dashboards = {}
        self.servers = {}
        self.lock = threading.Lock()
        self.refresh_interval = 10
        self._stop_event = threading.Event()
        self._thread = None

    def scan_dashboards(self):
        # Check temp dir for dashboard PID files
        dashboards = {}
        temp_path = Path(self.temp_dir)
        if temp_path.exists():
            for fname in temp_path.iterdir():
                if fname.name.startswith("dashboard") and fname.name.endswith(".pid"):
                    pid_file = str(fname)
                    try:
                        with open(pid_file, 'r', encoding='utf-8') as f:
                            pid_info = json.load(f)
                        pid = pid_info.get("ProcessId")
                        if pid and psutil.pid_exists(pid):
                            dashboards[pid] = {
                                "pid": pid,
                                "start_time": pid_info.get("StartTime"),
                                "type": pid_info.get("ProcessType", "dashboard"),
                                "status": "running"
                            }
                        else:
                            dashboards[pid] = {
                                "pid": pid,
                                "start_time": pid_info.get("StartTime"),
                                "type": pid_info.get("ProcessType", "dashboard"),
                                "status": "not running"
                            }
                    except Exception as e:
                        logger.debug(f"PID file read error {fname.name}: {e}")
        self.dashboards = dashboards

    def scan_servers(self):
        # Check servers from database for running server processes
        servers = {}
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            all_servers = manager.get_all_servers()

            for config in all_servers:
                name = config.get("Name", "Unknown")
                try:
                    pid = config.get("ProcessId")
                    status = "offline"
                    if pid and psutil.pid_exists(pid):
                        status = "running"
                    servers[name] = {
                        "pid": pid,
                        "status": status,
                        "config": config
                    }
                except Exception as e:
                    logger.debug(f"Error processing server config {name}: {e}")
        except Exception as e:
            logger.error(f"Error loading servers from database: {e}")
        self.servers = servers

    def refresh(self):
        # Refresh dashboards and servers info (thread-safe)
        with self.lock:
            self.scan_dashboards()
            self.scan_servers()

    def get_dashboards(self):
        # Get current dashboards info
        with self.lock:
            return dict(self.dashboards)

    def get_servers(self):
        # Get current servers info
        with self.lock:
            return dict(self.servers)

    def start_auto_refresh(self):
        # Start background thread to refresh info periodically
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
        self._thread.start()

    def stop_auto_refresh(self):
        # Stop background refresh thread
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None  # Clear thread reference to prevent memory leak
        self._stop_event = threading.Event()

    def _auto_refresh_loop(self):
        while not self._stop_event.is_set():
            self.refresh()
            time.sleep(self.refresh_interval)

# Create a global instance for import
tracker = DashboardTracker()