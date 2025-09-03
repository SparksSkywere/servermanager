# Simple Cluster Management Module
# Provides Hyper-V style clustering for server manager instances
# Handles master/subhost configuration with database and registry persistence

import os
import sys
import winreg
from datetime import datetime

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
from Modules.Database.cluster_database import ClusterDatabase

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SimpleCluster")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SimpleCluster")

class SimpleClusterManager:
    # Simple cluster management like Windows Hyper-V clustering
    # Provides master/subhost architecture with database and registry persistence
    
    def __init__(self):
        # Initialize cluster database
        try:
            self.cluster_db = ClusterDatabase()
        except Exception as e:
            logger.error(f"Failed to initialize cluster database: {e}")
            self.cluster_db = None
        
        # Determine role and configuration from registry
        self.is_master = self.get_host_type() == "Host"
        self.master_ip = self.get_master_ip()
        self.load_or_create_cluster()
        
    def get_host_type(self):
        # Get the host type from registry (Host = master, Subhost = node)
        try:
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
            host_type = winreg.QueryValueEx(key, "HostType")[0]
            winreg.CloseKey(key)
            return host_type
        except:
            return "Host"  # Default to master host
    
    def get_master_ip(self):
        # Get master IP from registry or return None if this is master
        if self.is_master:
            return None
        try:
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
            master_ip = winreg.QueryValueEx(key, "MasterHostIP")[0]
            winreg.CloseKey(key)
            return master_ip
        except:
            return None
    
    def load_or_create_cluster(self):
        # Load existing cluster or create new one
        # Checks database first, then registry fallback for configuration
        try:
            # Check database first
            if self.cluster_db:
                config = self.cluster_db.get_cluster_config()
                if config:
                    logger.info(f"Cluster already configured from database ({'Master' if self.is_master else 'Node'})")
                    return
                    
            # Fallback to registry check
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
            try:
                winreg.QueryValueEx(key, "ClusterCreated")[0]
                logger.info(f"Cluster already configured ({'Master' if self.is_master else 'Node'})")
            except:
                pass
            winreg.CloseKey(key)
        except:
            if self.is_master:
                self.create_cluster()
            else:
                logger.info("Node waiting for cluster configuration from master")
    
    def create_cluster(self):
        # Create new cluster (Master Host only)
        # Stores configuration in database with registry backup
        if not self.is_master:
            return False
        
        try:
            # Store in database if available
            if self.cluster_db:
                success = self.cluster_db.set_cluster_config(
                    host_type="Host",
                    cluster_name="ServerManager-Cluster",
                    master_ip=None  # This is the master
                )
                if success:
                    logger.info("New cluster created successfully in database")
                else:
                    logger.warning("Failed to create cluster in database, using registry fallback")
            
            # Also store in registry for backward compatibility
            key = winreg.CreateKeyEx(REGISTRY_ROOT, REGISTRY_PATH)
            winreg.SetValueEx(key, "ClusterCreated", 0, winreg.REG_SZ, datetime.now().isoformat())
            winreg.CloseKey(key)
            
            logger.info("New cluster created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create cluster: {e}")
            return False
    
    def join_cluster(self, master_ip):
        # Join existing cluster (Cluster Node only)
        if self.is_master:
            return False
        
        try:
            # Store in database if available
            if self.cluster_db:
                success = self.cluster_db.set_cluster_config(
                    host_type="Subhost",
                    cluster_name="ServerManager-Cluster",
                    master_ip=master_ip
                )
                if success:
                    self.master_ip = master_ip
                    logger.info(f"Successfully joined cluster managed by {master_ip} (database)")
                else:
                    logger.warning("Failed to store cluster config in database, using registry fallback")
            
            # Also store in registry for backward compatibility
            key = winreg.CreateKeyEx(REGISTRY_ROOT, REGISTRY_PATH)
            winreg.SetValueEx(key, "HostAddress", 0, winreg.REG_SZ, master_ip)
            winreg.SetValueEx(key, "JoinedCluster", 0, winreg.REG_SZ, datetime.now().isoformat())
            winreg.CloseKey(key)
            
            self.master_ip = master_ip
            logger.info(f"Successfully joined cluster managed by {master_ip}")
            return True
        except Exception as e:
            logger.error(f"Failed to join cluster: {e}")
        return False
    
    def get_cluster_status(self):
        # Get current cluster status
        return {
            "is_master": self.is_master,
            "has_cluster": self.is_master or bool(self.master_ip),
            "master_ip": self.master_ip,
            "cluster_ready": self.is_master or bool(self.master_ip)
        }
