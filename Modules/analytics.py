# Analytics and Metrics Collection Module
# Provides system monitoring, server statistics, and health metrics
# Supports Prometheus, SNMP, Grafana integration with background collection

import os
import sys
import json
import logging
import psutil
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
import socket

# Import server manager common functionality
try:
    from Modules.common import ServerManagerModule
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("Analytics")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Analytics")

class AnalyticsCollector(ServerManagerModule):
    # Analytics module for collecting system and server statistics
    # Provides metrics for SNMP, Grafana, and other monitoring tools
    # Supports background collection with 24-hour history retention
    
    def __init__(self):
        try:
            super().__init__("Analytics")
            logger.info("Analytics module initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize base ServerManagerModule: {e}")
            # Initialize minimal attributes to prevent AttributeError
            self.module_name = "Analytics"
            self.logger = logging.getLogger("Analytics")
        
        # Metrics storage
        self.metrics_history = defaultdict(lambda: deque(maxlen=1440))  # 24 hours at 1min intervals
        self.last_collection = datetime.now()
        self.collection_interval = 60  # seconds
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        
        # Server manager integration
        self.server_manager = None
        self.dashboard_tracker = None
        
        # Performance counters
        self.server_uptime_start = {}
        self.server_restart_counts = defaultdict(int)
        self.server_error_counts = defaultdict(int)
        
        # System baseline
        self.boot_time = datetime.fromtimestamp(psutil.boot_time())
        
        self.initialize_integrations()

    def initialize_integrations(self):
        # Initialize integrations with server manager and dashboard tracker
        # Enables collection of server-specific and application metrics
        try:
            # Import server manager
            from Modules.server_manager import ServerManager
            self.server_manager = ServerManager()
            logger.info("Server manager integration initialized")
        except Exception as e:
            logger.warning(f"Server manager integration failed: {e}")
            
        try:
            # Import dashboard tracker
            from services.dashboard_tracker import tracker
            self.dashboard_tracker = tracker
            logger.info("Dashboard tracker integration initialized")
        except Exception as e:
            logger.warning(f"Dashboard tracker integration failed: {e}")

    def start_collection(self):
        # Start background metrics collection with 60-second intervals
        if self._thread and self._thread.is_alive():
            logger.warning("Metrics collection already running")
            return
            
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._collection_loop, daemon=True)
        self._thread.start()
        logger.info("Metrics collection started")

    def stop_collection(self):
        # Stop background metrics collection
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Metrics collection stopped")

    def _collection_loop(self):
        # Background collection loop with error recovery
        while not self._stop_event.is_set():
            try:
                self.collect_all_metrics()
                self._stop_event.wait(self.collection_interval)
            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                self._stop_event.wait(30)  # Wait longer on error

    def collect_all_metrics(self):
        # Collect all system and server metrics with thread-safe storage
        timestamp = datetime.now()
        
        with self.lock:
            # System metrics
            self._collect_system_metrics(timestamp)
            
            # Server metrics
            self._collect_server_metrics(timestamp)
            
            # Application metrics
            self._collect_application_metrics(timestamp)
            
            self.last_collection = timestamp

    def _collect_system_metrics(self, timestamp):
        # Collect system-level metrics (CPU, memory, disk, network)
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            self.metrics_history['system.cpu.percent'].append({
                'timestamp': timestamp.isoformat(),
                'value': cpu_percent
            })
            
            self.metrics_history['system.cpu.count'].append({
                'timestamp': timestamp.isoformat(),
                'value': cpu_count
            })
            
            if cpu_freq:
                self.metrics_history['system.cpu.frequency'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': cpu_freq.current
                })

            # Memory metrics
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            self.metrics_history['system.memory.total'].append({
                'timestamp': timestamp.isoformat(),
                'value': memory.total
            })
            
            self.metrics_history['system.memory.used'].append({
                'timestamp': timestamp.isoformat(),
                'value': memory.used
            })
            
            self.metrics_history['system.memory.percent'].append({
                'timestamp': timestamp.isoformat(),
                'value': memory.percent
            })
            
            self.metrics_history['system.swap.total'].append({
                'timestamp': timestamp.isoformat(),
                'value': swap.total
            })
            
            self.metrics_history['system.swap.used'].append({
                'timestamp': timestamp.isoformat(),
                'value': swap.used
            })

            # Disk metrics
            disk_usage = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()
            
            self.metrics_history['system.disk.total'].append({
                'timestamp': timestamp.isoformat(),
                'value': disk_usage.total
            })
            
            self.metrics_history['system.disk.used'].append({
                'timestamp': timestamp.isoformat(),
                'value': disk_usage.used
            })
            
            self.metrics_history['system.disk.percent'].append({
                'timestamp': timestamp.isoformat(),
                'value': (disk_usage.used / disk_usage.total) * 100
            })
            
            if disk_io:
                self.metrics_history['system.disk.read_bytes'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': disk_io.read_bytes
                })
                
                self.metrics_history['system.disk.write_bytes'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': disk_io.write_bytes
                })

            # Network metrics
            network_io = psutil.net_io_counters()
            if network_io:
                self.metrics_history['system.network.bytes_sent'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': network_io.bytes_sent
                })
                
                self.metrics_history['system.network.bytes_recv'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': network_io.bytes_recv
                })
                
                self.metrics_history['system.network.packets_sent'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': network_io.packets_sent
                })
                
                self.metrics_history['system.network.packets_recv'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': network_io.packets_recv
                })

            # System uptime
            uptime_seconds = (timestamp - self.boot_time).total_seconds()
            self.metrics_history['system.uptime'].append({
                'timestamp': timestamp.isoformat(),
                'value': uptime_seconds
            })
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")

    def _collect_server_metrics(self, timestamp):
        # Collect server-specific metrics (process stats, uptime, status)
        try:
            if not self.server_manager:
                return
                
            servers = self.server_manager.get_all_servers()
            server_count_by_status = defaultdict(int)
            total_servers = len(servers)
            
            for server_name, server_config in servers.items():
                pid = server_config.get('ProcessId')
                status = 'offline'
                
                if pid and psutil.pid_exists(pid):
                    status = 'running'
                    try:
                        process = psutil.Process(pid)
                        
                        # Server process metrics
                        cpu_percent = process.cpu_percent()
                        memory_info = process.memory_info()
                        create_time = datetime.fromtimestamp(process.create_time())
                        
                        self.metrics_history[f'server.{server_name}.cpu_percent'].append({
                            'timestamp': timestamp.isoformat(),
                            'value': cpu_percent
                        })
                        
                        self.metrics_history[f'server.{server_name}.memory_rss'].append({
                            'timestamp': timestamp.isoformat(),
                            'value': memory_info.rss
                        })
                        
                        self.metrics_history[f'server.{server_name}.memory_vms'].append({
                            'timestamp': timestamp.isoformat(),
                            'value': memory_info.vms
                        })
                        
                        # Server uptime
                        uptime_seconds = (timestamp - create_time).total_seconds()
                        self.metrics_history[f'server.{server_name}.uptime'].append({
                            'timestamp': timestamp.isoformat(),
                            'value': uptime_seconds
                        })
                        
                        # Track uptime start time
                        if server_name not in self.server_uptime_start:
                            self.server_uptime_start[server_name] = create_time
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        status = 'error'
                        self.server_error_counts[server_name] += 1
                        logger.debug(f"Error accessing process for server {server_name}: {e}")
                
                server_count_by_status[status] += 1
                
                # Server status metric
                status_value = {'offline': 0, 'running': 1, 'error': -1}.get(status, 0)
                self.metrics_history[f'server.{server_name}.status'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': status_value
                })
            
            # Overall server metrics
            self.metrics_history['servers.total'].append({
                'timestamp': timestamp.isoformat(),
                'value': total_servers
            })
            
            for status, count in server_count_by_status.items():
                self.metrics_history[f'servers.count.{status}'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': count
                })
                
        except Exception as e:
            logger.error(f"Error collecting server metrics: {e}")

    def _collect_application_metrics(self, timestamp):
        # Collect application-specific metrics (dashboard count, webserver stats)
        try:
            # Dashboard metrics
            if self.dashboard_tracker:
                try:
                    dashboards = self.dashboard_tracker.get_dashboards()
                    dashboard_count = len([d for d in dashboards.values() if d.get('status') == 'running'])
                    
                    self.metrics_history['application.dashboards.count'].append({
                        'timestamp': timestamp.isoformat(),
                        'value': dashboard_count
                    })
                except Exception as e:
                    logger.debug(f"Error getting dashboard metrics: {e}")
            
            # Process count for server manager components
            current_pid = os.getpid()
            try:
                current_process = psutil.Process(current_pid)
                
                self.metrics_history['application.webserver.cpu_percent'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': current_process.cpu_percent()
                })
                
                memory_info = current_process.memory_info()
                self.metrics_history['application.webserver.memory_rss'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': memory_info.rss
                })
                
                # Connection count (if we can get it)
                connections = current_process.connections()
                self.metrics_history['application.webserver.connections'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': len(connections)
                })
                
            except Exception as e:
                logger.debug(f"Error collecting application process metrics: {e}")
            
        except Exception as e:
            logger.error(f"Error collecting application metrics: {e}")

    def get_current_metrics(self):
        # Get current snapshot of all metrics with thread safety
        with self.lock:
            current_metrics = {}
            
            for metric_name, history in self.metrics_history.items():
                if history:
                    current_metrics[metric_name] = history[-1]['value']
                    
        return current_metrics

    def get_metric_history(self, metric_name, hours=24):
        # Get historical data for a specific metric within time window
        with self.lock:
            if metric_name not in self.metrics_history:
                return []
                
            cutoff_time = datetime.now() - timedelta(hours=hours)
            history = []
            
            for entry in self.metrics_history[metric_name]:
                entry_time = datetime.fromisoformat(entry['timestamp'])
                if entry_time >= cutoff_time:
                    history.append(entry)
                    
            return history

    def get_prometheus_metrics(self):
        # Get metrics in Prometheus format for Grafana integration
        # Converts dot notation to underscores for compatibility
        current_metrics = self.get_current_metrics()
        prometheus_output = []
        
        for metric_name, value in current_metrics.items():
            # Convert metric name to Prometheus format
            prom_name = metric_name.replace('.', '_')
            prometheus_output.append(f"{prom_name} {value}")
            
        return '\n'.join(prometheus_output)

    def get_json_metrics(self):
        # Get all metrics in JSON format with metadata
        return {
            'timestamp': datetime.now().isoformat(),
            'metrics': self.get_current_metrics(),
            'metadata': {
                'collection_interval': self.collection_interval,
                'last_collection': self.last_collection.isoformat() if self.last_collection else None,
                'uptime': (datetime.now() - self.boot_time).total_seconds()
            }
        }

    def get_server_summary(self):
        # Get summary of all server statuses with performance metrics
        if not self.server_manager:
            return {}
            
        servers = self.server_manager.get_all_servers()
        summary = {
            'total_servers': len(servers),
            'running_servers': 0,
            'offline_servers': 0,
            'error_servers': 0,
            'servers': {}
        }
        
        for server_name, server_config in servers.items():
            pid = server_config.get('ProcessId')
            status = 'offline'
            cpu_percent = 0
            memory_mb = 0
            uptime_seconds = 0
            
            if pid and psutil.pid_exists(pid):
                try:
                    process = psutil.Process(pid)
                    status = 'running'
                    cpu_percent = process.cpu_percent()
                    memory_mb = process.memory_info().rss / 1024 / 1024  # Convert to MB
                    uptime_seconds = (datetime.now() - datetime.fromtimestamp(process.create_time())).total_seconds()
                    summary['running_servers'] += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    status = 'error'
                    summary['error_servers'] += 1
            else:
                summary['offline_servers'] += 1
                
            summary['servers'][server_name] = {
                'status': status,
                'cpu_percent': cpu_percent,
                'memory_mb': memory_mb,
                'uptime_seconds': uptime_seconds,
                'restart_count': self.server_restart_counts.get(server_name, 0),
                'error_count': self.server_error_counts.get(server_name, 0)
            }
            
        return summary

    def get_system_health(self):
        # Get overall system health metrics with scoring algorithm
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk_usage = psutil.disk_usage('/')
            
            health_score = 100
            issues = []
            
            # CPU health check
            if cpu_percent > 90:
                health_score -= 30
                issues.append(f"High CPU usage: {cpu_percent:.1f}%")
            elif cpu_percent > 75:
                health_score -= 15
                issues.append(f"Moderate CPU usage: {cpu_percent:.1f}%")
                
            # Memory health check
            if memory.percent > 90:
                health_score -= 30
                issues.append(f"High memory usage: {memory.percent:.1f}%")
            elif memory.percent > 75:
                health_score -= 15
                issues.append(f"Moderate memory usage: {memory.percent:.1f}%")
                
            # Disk health check
            disk_percent = (disk_usage.used / disk_usage.total) * 100
            if disk_percent > 95:
                health_score -= 30
                issues.append(f"High disk usage: {disk_percent:.1f}%")
            elif disk_percent > 85:
                health_score -= 15
                issues.append(f"Moderate disk usage: {disk_percent:.1f}%")
                
            # Server health check
            server_summary = self.get_server_summary()
            if server_summary['error_servers'] > 0:
                health_score -= 20
                issues.append(f"{server_summary['error_servers']} servers in error state")
                
            return {
                'health_score': max(0, health_score),
                'status': 'healthy' if health_score >= 80 else 'warning' if health_score >= 60 else 'critical',
                'issues': issues,
                'uptime_seconds': (datetime.now() - self.boot_time).total_seconds(),
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk_percent
                }
            }
        except Exception as e:
            logger.error(f"Error calculating system health: {e}")
            return {
                'health_score': 0,
                'status': 'error',
                'issues': [f"Health check failed: {str(e)}"],
                'uptime_seconds': 0,
                'system': {}
            }

    def get_snmp_metrics(self):
        # Get metrics formatted for SNMP monitoring with OID structure
        current_metrics = self.get_current_metrics()
        health = self.get_system_health()
        server_summary = self.get_server_summary()
        
        # Format for SNMP (OID-like structure)
        snmp_metrics = {
            # System metrics (1.3.6.1.4.1.enterprise.1.x)
            '1.3.6.1.4.1.12345.1.1': health['health_score'],  # Overall health score
            '1.3.6.1.4.1.12345.1.2': current_metrics.get('system.cpu.percent', 0),
            '1.3.6.1.4.1.12345.1.3': current_metrics.get('system.memory.percent', 0),
            '1.3.6.1.4.1.12345.1.4': current_metrics.get('system.disk.percent', 0),
            '1.3.6.1.4.1.12345.1.5': current_metrics.get('system.uptime', 0),
            
            # Server metrics (1.3.6.1.4.1.enterprise.2.x)
            '1.3.6.1.4.1.12345.2.1': server_summary['total_servers'],
            '1.3.6.1.4.1.12345.2.2': server_summary['running_servers'],
            '1.3.6.1.4.1.12345.2.3': server_summary['offline_servers'],
            '1.3.6.1.4.1.12345.2.4': server_summary['error_servers'],
            
            # Application metrics (1.3.6.1.4.1.enterprise.3.x)
            '1.3.6.1.4.1.12345.3.1': current_metrics.get('application.webserver.cpu_percent', 0),
            '1.3.6.1.4.1.12345.3.2': current_metrics.get('application.webserver.memory_rss', 0),
            '1.3.6.1.4.1.12345.3.3': current_metrics.get('application.webserver.connections', 0),
            '1.3.6.1.4.1.12345.3.4': current_metrics.get('application.dashboards.count', 0),
        }
        
        return snmp_metrics

# Create global analytics instance
analytics = AnalyticsCollector()

def get_analytics_instance():
    # Get the global analytics instance
    return analytics

def start_analytics():
    # Start analytics collection
    analytics.start_collection()
    return analytics

def stop_analytics():
    # Stop analytics collection
    analytics.stop_collection()