# Cluster management
import os
import sys
from datetime import datetime
import requests
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path, REGISTRY_PATH, setup_module_logging, get_registry_value, set_registry_value
setup_module_path()
from Modules.Database.cluster_database import get_cluster_database

logger: logging.Logger = setup_module_logging("SimpleCluster")

class SimpleClusterManager:
    # Clustering like Hyper-V (Cluster Host + Cluster Node)
    def __init__(self):
        try:
            self.cluster_db = get_cluster_database()
        except Exception as e:
            logger.error(f"Cluster DB init failed: {e}")
            self.cluster_db = None

        self.is_master = self.get_host_type() == "Host"
        self.master_ip = self.get_master_ip()
        self.load_or_create_cluster()

    def get_host_type(self):
        # Host = master, Subhost = node
        return get_registry_value(REGISTRY_PATH, "HostType", "Host")

    def get_master_ip(self):
        # Get master IP (None if we are master)
        if self.is_master:
            return None
        return get_registry_value(REGISTRY_PATH, "HostAddress", None)

    def load_or_create_cluster(self):
        # Load cluster config from DB or registry
        try:
            if self.cluster_db:
                config = self.cluster_db.get_cluster_config()
                if config:
                    logger.info(f"Cluster ready ({'Master' if self.is_master else 'Node'})")
                    return

            # Fallback to registry check
            cluster_created = get_registry_value(REGISTRY_PATH, "ClusterCreated", None)
            if cluster_created:
                logger.info(f"Cluster already configured ({'Master' if self.is_master else 'Node'})")
        except (FileNotFoundError, OSError):
            if self.is_master:
                self.create_cluster()
            else:
                logger.info("Node waiting for cluster configuration from master")

    def create_cluster(self):
        # Create new cluster (Master Host only)
        if not self.is_master:
            return False

        try:
            # Store in database if available
            if self.cluster_db:
                success = self.cluster_db.set_cluster_config(
                    host_type="Host",
                    cluster_name="ServerManager-Cluster",
                    master_ip=None
                )
                if success:
                    logger.info("New cluster created successfully in database")
                else:
                    logger.warning("Failed to create cluster in database, using registry fallback")

            # Store in registry
            set_registry_value(REGISTRY_PATH, "ClusterCreated", datetime.now().isoformat())

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
            import socket
            import platform

            # Get local machine information
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
            except socket.gaierror:
                local_ip = "127.0.0.1"

            machine_info = {
                "machine_name": hostname,
                "os": platform.system() + " " + platform.release(),
                "ip_address": local_ip
            }

            # Send join request to master host
            join_data = {
                "subhost_id": hostname,
                "info": machine_info
            }

            try:
                response = requests.post(f"http://{master_ip}:5000/api/cluster/request-join",
                                       json=join_data, timeout=30)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "pending_approval":
                        logger.info(f"Join request sent to master {master_ip}, awaiting approval")
                        # Store the master IP locally even though approval is pending
                        self.master_ip = master_ip

                        # Store the join token for later approval checking
                        join_token = result.get("join_token")
                        if join_token:
                            set_registry_value(REGISTRY_PATH, "JoinToken", join_token)

                        # Store in database if available
                        if self.cluster_db:
                            success = self.cluster_db.set_cluster_config(
                                host_type="Subhost",
                                cluster_name="ServerManager-Cluster",
                                master_ip=master_ip
                            )
                            if success:
                                logger.info(f"Cluster config stored in database")

                        # Store in registry
                        set_registry_value(REGISTRY_PATH, "HostAddress", master_ip)
                        set_registry_value(REGISTRY_PATH, "JoinedCluster", datetime.now().isoformat())

                        return True
                    else:
                        logger.error(f"Unexpected response from master: {result}")
                        return False
                else:
                    logger.error(f"Failed to send join request to master {master_ip}: HTTP {response.status_code}")
                    return False

            except requests.exceptions.RequestException as e:
                logger.error(f"Network error joining cluster: {e}")
                return False

        except Exception as e:
            logger.error(f"Failed to join cluster: {e}")
        return False

    def check_join_status(self):
        # Check if the join request has been approved by the master host
        try:
            # Get the master IP from registry
            master_ip = self.get_master_ip()
            if not master_ip:
                return None

            # Get our join token from registry
            join_token = self.get_join_token()
            if not join_token:
                return None

            # Check status with master
            response = requests.get(
                f"http://{master_ip}:5000/api/cluster/join-status",
                params={"token": join_token},
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to check join status: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error checking join status: {e}")
            return None

    def complete_cluster_join(self, approval_token):
        # Complete the cluster join process with the approval token
        try:
            # Get the master IP from registry
            master_ip = self.get_master_ip()
            if not master_ip:
                return False

            # Get our join token from registry
            join_token = self.get_join_token()
            if not join_token:
                return False

            # Complete the join with master
            response = requests.post(
                f"http://{master_ip}:5000/api/cluster/complete-join",
                json={
                    "join_token": join_token,
                    "approval_token": approval_token
                },
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    # Update our registry to mark as joined
                    self.set_cluster_status("joined")
                    self.set_master_ip(master_ip)
                    logger.info("Successfully joined cluster")
                    return True
                else:
                    logger.error(f"Join completion failed: {result.get('message')}")
                    return False
            else:
                logger.error(f"Failed to complete join: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error completing cluster join: {e}")
            return False

    def get_join_token(self):
        # Get the join token from registry
        return get_registry_value(REGISTRY_PATH, "JoinToken", None)

    def set_cluster_status(self, status):
        # Set cluster status in registry
        if not set_registry_value(REGISTRY_PATH, "ClusterStatus", status):
            logger.error(f"Error setting cluster status")

    def set_master_ip(self, ip):
        # Set master IP in registry
        if not set_registry_value(REGISTRY_PATH, "HostAddress", ip):
            logger.error(f"Error setting master IP")

    def get_cluster_status(self):
        # Get current cluster status
        return {
            "is_master": self.is_master,
            "has_cluster": self.is_master or bool(self.master_ip),
            "master_ip": self.master_ip,
            "cluster_ready": self.is_master or bool(self.master_ip)
        }

