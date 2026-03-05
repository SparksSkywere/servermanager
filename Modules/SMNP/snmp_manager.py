# SNMP management module
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
logger = get_component_logger("SNMP")
_HAS_SERVER_MANAGER_MODULE = True

class SNMPManager(ServerManagerModule):  # type: ignore[valid-type, misc]
    # SNMP monitoring integration

    def __init__(self, analytics_instance=None):
        try:
            super().__init__("SNMP")
            logger.info("SNMP module initialised")
        except Exception as e:
            logger.error(f"Base module init failed: {e}")
            self.module_name = "SNMP"
            self.logger = logging.getLogger("SNMP")

        self.analytics: Optional['AnalyticsCollector'] = analytics_instance

        # Enterprise OID base
        self.enterprise_base = "1.3.6.1.4.1.12345"

        # OID mappings
        self.oid_mappings = {
            # System metrics
            'system.health_score': f'{self.enterprise_base}.1.1',
            'system.cpu.percent': f'{self.enterprise_base}.1.2',
            'system.memory.percent': f'{self.enterprise_base}.1.3',
            'system.disk.percent': f'{self.enterprise_base}.1.4',
            'system.uptime': f'{self.enterprise_base}.1.5',

            # Server metrics
            'servers.total': f'{self.enterprise_base}.2.1',
            'servers.running': f'{self.enterprise_base}.2.2',
            'servers.offline': f'{self.enterprise_base}.2.3',
            'servers.error': f'{self.enterprise_base}.2.4',

            # App metrics
            'application.webserver.cpu_percent': f'{self.enterprise_base}.3.1',
            'application.webserver.memory_rss': f'{self.enterprise_base}.3.2',
            'application.webserver.connections': f'{self.enterprise_base}.3.3',
            'application.dashboards.count': f'{self.enterprise_base}.3.4',
        }

    def get_snmp_metrics(self):
        # Get metrics formatted for SNMP monitoring with OID structure
        if not self.analytics:
            logger.warning("Analytics instance not configured")
            return {}

        assert self.analytics is not None

        try:
            current_metrics = self.analytics.get_current_metrics()
            health = self.analytics.get_system_health()
            server_summary = self.analytics.get_server_summary()

            # Format for SNMP (OID-like structure)
            snmp_metrics = {
                # System metrics (1.3.6.1.4.1.enterprise.1.x)
                self.oid_mappings['system.health_score']: health['health_score'],
                self.oid_mappings['system.cpu.percent']: current_metrics.get('system.cpu.percent', 0),
                self.oid_mappings['system.memory.percent']: current_metrics.get('system.memory.percent', 0),
                self.oid_mappings['system.disk.percent']: current_metrics.get('system.disk.percent', 0),
                self.oid_mappings['system.uptime']: current_metrics.get('system.uptime', 0),

                # Server metrics (1.3.6.1.4.1.enterprise.2.x)
                self.oid_mappings['servers.total']: server_summary['total_servers'],
                self.oid_mappings['servers.running']: server_summary['running_servers'],
                self.oid_mappings['servers.offline']: server_summary['offline_servers'],
                self.oid_mappings['servers.error']: server_summary['error_servers'],

                # Application metrics (1.3.6.1.4.1.enterprise.3.x)
                self.oid_mappings['application.webserver.cpu_percent']: current_metrics.get('application.webserver.cpu_percent', 0),
                self.oid_mappings['application.webserver.memory_rss']: current_metrics.get('application.webserver.memory_rss', 0),
                self.oid_mappings['application.webserver.connections']: current_metrics.get('application.webserver.connections', 0),
                self.oid_mappings['application.dashboards.count']: current_metrics.get('application.dashboards.count', 0),
            }

            logger.debug(f"Generated SNMP metrics for {len(snmp_metrics)} OIDs")
            return snmp_metrics

        except Exception as e:
            logger.error(f"Error generating SNMP metrics: {e}")
            return {}

# Create global SNMP manager instance
snmp_manager = None

def initialize_snmp(analytics_instance):
    # Initialise SNMP manager with analytics integration
    global snmp_manager
    snmp_manager = SNMPManager(analytics_instance)
    logger.info("SNMP manager initialised with analytics integration")
    return snmp_manager