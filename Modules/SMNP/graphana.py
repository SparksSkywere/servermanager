# Grafana integration
import os
import sys
import logging
from typing import Optional, TYPE_CHECKING

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

if TYPE_CHECKING:
    from Modules.analytics import AnalyticsCollector

from Modules.common import ServerManagerModule
from Modules.server_logging import get_component_logger
logger = get_component_logger("Grafana")
_HAS_SERVER_MANAGER_MODULE = True

class GrafanaManager(ServerManagerModule):  # type: ignore[valid-type, misc]
    # Prometheus format metrics

    def __init__(self, analytics_instance=None):
        try:
            super().__init__("Grafana")
            logger.info("Grafana module initialised")
        except Exception as e:
            logger.error(f"Base module init failed: {e}")
            self.module_name = "Grafana"
            self.logger = logging.getLogger("Grafana")

        self.analytics: Optional['AnalyticsCollector'] = analytics_instance

        # Prometheus prefixes
        self.metric_prefix = "servermanager"

        # Metric types
        self.metric_types = {
            'counter': 'counter',
            'gauge': 'gauge',
            'histogram': 'histogram',
            'summary': 'summary'
        }

    def get_prometheus_metrics(self):
        # Metrics in Prometheus format
        if not self.analytics:
            logger.warning("Analytics not configured")
            return ""

        assert self.analytics is not None  # For type checker

        try:
            current_metrics = self.analytics.get_current_metrics()
            prometheus_output = []

            prometheus_output.append(f"# HELP {self.metric_prefix}_info Server Manager metrics")
            prometheus_output.append(f"# TYPE {self.metric_prefix}_info gauge")
            prometheus_output.append("")

            for metric_name, value in current_metrics.items():
                # Convert metric name to Prometheus format
                prom_name = f"{self.metric_prefix}_{metric_name.replace('.', '_')}"

                # Add metric help and type
                prometheus_output.append(f"# HELP {prom_name} {self._get_metric_description(metric_name)}")
                prometheus_output.append(f"# TYPE {prom_name} {self._get_metric_type(metric_name)}")
                prometheus_output.append(f"{prom_name} {value}")
                prometheus_output.append("")

            logger.debug(f"Generated Prometheus metrics for {len(current_metrics)} metrics")
            return '\n'.join(prometheus_output)

        except Exception as e:
            logger.error(f"Error generating Prometheus metrics: {e}")
            return ""

    def _get_metric_description(self, metric_name):
        # Get human-readable description for a metric
        descriptions = {
            'system.cpu.percent': 'CPU usage percentage',
            'system.memory.percent': 'Memory usage percentage',
            'system.memory.total': 'Total system memory in bytes',
            'system.memory.used': 'Used system memory in bytes',
            'system.disk.percent': 'Disk usage percentage',
            'system.disk.total': 'Total disk space in bytes',
            'system.disk.used': 'Used disk space in bytes',
            'system.uptime': 'System uptime in seconds',
            'system.network.bytes_sent': 'Network bytes sent',
            'system.network.bytes_recv': 'Network bytes received',
            'servers.total': 'Total number of servers',
            'servers.count.running': 'Number of running servers',
            'servers.count.offline': 'Number of offline servers',
            'application.webserver.cpu_percent': 'Webserver CPU usage percentage',
            'application.webserver.memory_rss': 'Webserver memory usage in bytes',
            'application.webserver.connections': 'Number of webserver connections',
            'application.dashboards.count': 'Number of active dashboards'
        }

        return descriptions.get(metric_name, f"Server Manager metric: {metric_name}")

    def _get_metric_type(self, metric_name):
        # Get Prometheus metric type for a metric
        gauge_metrics = [
            'system.cpu.percent', 'system.memory.percent', 'system.disk.percent',
            'servers.total', 'servers.count', 'application.webserver.cpu_percent',
            'application.webserver.connections', 'application.dashboards.count'
        ]

        # Counter metrics (always increasing)
        counter_metrics = [
            'system.network.bytes_sent', 'system.network.bytes_recv',
            'system.disk.read_bytes', 'system.disk.write_bytes',
            'system.uptime'
        ]

        if any(gauge_metric in metric_name for gauge_metric in gauge_metrics):
            return 'gauge'
        elif any(counter_metric in metric_name for counter_metric in counter_metrics):
            return 'counter'
        else:
            return 'gauge'

    def get_dashboard_config(self):
        # Get basic Grafana dashboard configuration
        dashboard_config = {
            "dashboard": {
                "title": "Server Manager Monitoring",
                "tags": ["server-manager", "monitoring"],
                "timezone": "browser",
                "panels": [
                    {
                        "id": 1,
                        "title": "System Health Score",
                        "type": "stat",
                        "targets": [
                            {
                                "expr": f"{self.metric_prefix}_system_health_score",
                                "refId": "A"
                            }
                        ],
                        "fieldConfig": {
                            "defaults": {
                                "min": 0,
                                "max": 100,
                                "unit": "percent"
                            }
                        }
                    },
                    {
                        "id": 2,
                        "title": "Server Status",
                        "type": "piechart",
                        "targets": [
                            {
                                "expr": f"{self.metric_prefix}_servers_count_running",
                                "legendFormat": "Running",
                                "refId": "A"
                            },
                            {
                                "expr": f"{self.metric_prefix}_servers_count_offline",
                                "legendFormat": "Offline",
                                "refId": "B"
                            }
                        ]
                    },
                    {
                        "id": 3,
                        "title": "System Resources",
                        "type": "timeseries",
                        "targets": [
                            {
                                "expr": f"{self.metric_prefix}_system_cpu_percent",
                                "legendFormat": "CPU %",
                                "refId": "A"
                            },
                            {
                                "expr": f"{self.metric_prefix}_system_memory_percent",
                                "legendFormat": "Memory %",
                                "refId": "B"
                            },
                            {
                                "expr": f"{self.metric_prefix}_system_disk_percent",
                                "legendFormat": "Disk %",
                                "refId": "C"
                            }
                        ]
                    }
                ]
            }
        }

        return dashboard_config

# Create global Grafana manager instance
grafana_manager = None

def initialize_grafana(analytics_instance):
    # Initialise Grafana manager with analytics integration
    global grafana_manager
    grafana_manager = GrafanaManager(analytics_instance)
    logger.info("Grafana manager initialised with analytics integration")
    return grafana_manager