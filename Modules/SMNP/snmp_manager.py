# SNMP Management Module
import logging
from datetime import datetime

# Import server manager common functionality
try:
    from Modules.common import ServerManagerModule
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SNMP")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SNMP")

class SNMPManager(ServerManagerModule):
    # SNMP monitoring integration for Server Manager
    # Formats metrics with OID structure for SNMP monitoring systems
    # Integrates with analytics module for metric collection
    
    def __init__(self, analytics_instance=None):
        try:
            super().__init__("SNMP")
            logger.info("SNMP module initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize base ServerManagerModule: {e}")
            # Initialize minimal attributes to prevent AttributeError
            self.module_name = "SNMP"
            self.logger = logging.getLogger("SNMP")
        
        self.analytics = analytics_instance
        
        # SNMP OID base for Server Manager enterprise
        self.enterprise_base = "1.3.6.1.4.1.12345"
        
        # OID mappings for different metric categories
        self.oid_mappings = {
            # System metrics (1.3.6.1.4.1.enterprise.1.x)
            'system.health_score': f'{self.enterprise_base}.1.1',
            'system.cpu.percent': f'{self.enterprise_base}.1.2',
            'system.memory.percent': f'{self.enterprise_base}.1.3',
            'system.disk.percent': f'{self.enterprise_base}.1.4',
            'system.uptime': f'{self.enterprise_base}.1.5',
            
            # Server metrics (1.3.6.1.4.1.enterprise.2.x)
            'servers.total': f'{self.enterprise_base}.2.1',
            'servers.running': f'{self.enterprise_base}.2.2',
            'servers.offline': f'{self.enterprise_base}.2.3',
            'servers.error': f'{self.enterprise_base}.2.4',
            
            # Application metrics (1.3.6.1.4.1.enterprise.3.x)
            'application.webserver.cpu_percent': f'{self.enterprise_base}.3.1',
            'application.webserver.memory_rss': f'{self.enterprise_base}.3.2',
            'application.webserver.connections': f'{self.enterprise_base}.3.3',
            'application.dashboards.count': f'{self.enterprise_base}.3.4',
        }

    def set_analytics_instance(self, analytics_instance):
        # Set the analytics instance for metric collection
        self.analytics = analytics_instance
        logger.info("Analytics instance configured for SNMP manager")

    def get_snmp_metrics(self):
        # Get metrics formatted for SNMP monitoring with OID structure
        # Returns metrics with enterprise OID mappings
        if not self.analytics:
            logger.warning("Analytics instance not configured")
            return {}
            
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

    def get_oid_mapping(self, metric_name):
        # Get OID for a specific metric name
        return self.oid_mappings.get(metric_name)

    def get_all_oid_mappings(self):
        # Get all OID mappings
        return self.oid_mappings.copy()

    def format_snmp_response(self, oid, value):
        # Format a single SNMP response
        return {
            'oid': oid,
            'value': value,
            'timestamp': datetime.now().isoformat()
        }

    def get_snmp_walk_data(self):
        # Get all metrics formatted for SNMP walk operation
        snmp_metrics = self.get_snmp_metrics()
        walk_data = []
        
        for oid, value in sorted(snmp_metrics.items()):
            walk_data.append(self.format_snmp_response(oid, value))
            
        return walk_data

    def get_metric_by_oid(self, requested_oid):
        # Get a specific metric by its OID
        snmp_metrics = self.get_snmp_metrics()
        
        if requested_oid in snmp_metrics:
            return self.format_snmp_response(requested_oid, snmp_metrics[requested_oid])
        
        logger.warning(f"Requested OID not found: {requested_oid}")
        return None

# Create global SNMP manager instance
snmp_manager = None

def get_snmp_manager(analytics_instance=None):
    # Get the global SNMP manager instance
    global snmp_manager
    if snmp_manager is None:
        snmp_manager = SNMPManager(analytics_instance)
    elif analytics_instance and not snmp_manager.analytics:
        snmp_manager.set_analytics_instance(analytics_instance)
    return snmp_manager

def initialize_snmp(analytics_instance):
    # Initialize SNMP manager with analytics integration
    global snmp_manager
    snmp_manager = SNMPManager(analytics_instance)
    logger.info("SNMP manager initialized with analytics integration")
    return snmp_manager
