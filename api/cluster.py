import os
import sys
import winreg
import json
from datetime import datetime
from functools import wraps
from flask import Blueprint, jsonify, request

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import security managers
from Modules.network_security import NetworkSecurityManager, require_cluster_network_security

# Import database for persistent cluster data
from Modules.Database.cluster_database import ClusterDatabase

# Import standardized logging
from Modules.server_logging import get_component_logger
logger = get_component_logger("ClusterAPI")

cluster_api = Blueprint("cluster_api", __name__)

# Initialize security managers and database
network_security_manager = NetworkSecurityManager()
cluster_db = ClusterDatabase()

def is_subhost_registered(subhost_id):
    # Check if a subhost is registered in the database
    node = cluster_db.get_cluster_node(subhost_id)
    return node is not None and node['node_type'] == 'subhost'

def get_subhost_info(subhost_id):
    # Get subhost information from database
    node = cluster_db.get_cluster_node(subhost_id)
    if node and node['node_type'] == 'subhost':
        return {
            "id": node['name'],
            "info": {},  # Legacy compatibility: info field no longer stored in new schema
            "last_seen": node['last_ping'] or node['added_at'],
            "registered_at": node['added_at'],
            "ip_address": node['ip_address'],
            "port": node['port'],
            "status": node['status']
        }
    return None

def require_cluster_auth(f):
    # Decorator to require cluster authentication for API endpoints
    @wraps(f)
    @require_cluster_network_security(network_security_manager)
    def decorated_function(*args, **kwargs):
        # Allow unauthenticated access to role endpoint for initial setup
        if request.endpoint == 'cluster_api.api_cluster_role':
            logger.debug("Allowing unauthenticated access to cluster role endpoint")
            return f(*args, **kwargs)
            
        # In simplified cluster system, authentication is handled automatically
        # Log the access and allow the request to proceed
        logger.debug(f"Cluster API access from {request.remote_addr}")
        return f(*args, **kwargs)
    return decorated_function

def get_cluster_role():
    # Get the cluster role and host address from registry
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        role = winreg.QueryValueEx(key, "HostType")[0]
        try:
            host_address = winreg.QueryValueEx(key, "HostAddress")[0]
        except Exception:
            host_address = None
        winreg.CloseKey(key)
        logger.debug(f"Retrieved cluster role: {role}, host_address: {host_address}")
        return role, host_address
    except Exception as e:
        logger.error(f"Failed to get cluster role from registry: {str(e)}")
        return "Unknown", None

@cluster_api.route("/api/cluster/role", methods=["GET"])
def api_cluster_role():
    # Get the cluster role of this instance
    role, host_address = get_cluster_role()
    return jsonify({
        "role": role,
        "hostAddress": host_address
    })

@cluster_api.route("/api/cluster/register", methods=["POST"])
@require_cluster_auth
def api_register_subhost():
    # Register a subhost with the host (DEPRECATED - use approval workflow instead)
    try:
        data = request.get_json()
        if not data:
            logger.warning("Register subhost request received with no data")
            return jsonify({"error": "No data provided"}), 400
            
        subhost_id = data.get("subhost_id")
        if not subhost_id:
            logger.warning("Register subhost request missing subhost_id")
            return jsonify({"error": "subhost_id is required"}), 400
        
        # Check if node is already registered
        existing_node = cluster_db.get_cluster_node(subhost_id)
        if existing_node:
            # Update existing node
            cluster_db.update_node_status(subhost_id, "active")
            logger.info(f"Subhost {subhost_id} updated registration")
            return jsonify({
                "status": "updated",
                "subhost_id": subhost_id,
                "message": f"Subhost {subhost_id} registration updated"
            })
        
        # Add new node using legacy registration path (should use approval workflow)
        info = data.get("info", {})
        success = cluster_db.add_cluster_node(
            name=subhost_id,
            ip_address=request.remote_addr or "unknown",
            node_type="subhost",
            cluster_token=""  # No token required for legacy registration
        )
        
        if success:
            logger.info(f"Subhost {subhost_id} registered successfully (legacy)")
            logger.info(f"SUBHOST_REGISTRATION: Subhost {subhost_id} registered (user: system)")
            
            return jsonify({
                "status": "registered",
                "subhost_id": subhost_id,
                "message": f"Subhost {subhost_id} registered successfully"
            })
        else:
            return jsonify({"error": "Failed to register subhost"}), 500
        
    except Exception as e:
        logger.error(f"Error registering subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/request-join", methods=["POST"])
def api_request_join():
    # Request to join cluster - requires approval
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        subhost_id = data.get("subhost_id")
        if not subhost_id:
            return jsonify({"error": "subhost_id is required"}), 400
        
        # Extract subhost information from the join request
        info = data.get("info", {})
        machine_name = info.get("machine_name", "")
        os_info = info.get("os", "")
        
        # Store pending request in database
        request_id = cluster_db.add_pending_request(
            node_name=subhost_id,
            ip_address=request.remote_addr or "unknown",
            port=8080,
            machine_name=machine_name,
            os_info=os_info,
            request_data=json.dumps(data)
        )
        
        if request_id is None:
            return jsonify({"error": "Failed to store join request"}), 500
        
        logger.info(f"Subhost {subhost_id} requested to join cluster from {request.remote_addr}")
        
        return jsonify({
            "status": "pending_approval",
            "subhost_id": subhost_id,
            "request_id": request_id,
            "message": "Join request submitted. Awaiting approval from cluster administrator."
        })
        
    except Exception as e:
        logger.error(f"Error processing join request: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/pending", methods=["GET"])
@require_cluster_auth
def api_get_pending():
    # Get pending cluster join requests
    try:
        role, _ = get_cluster_role()
        logger.info(f"api_get_pending called - role: {role}")
        
        if role != "Host":
            logger.warning(f"Pending requests requested from non-host: {role}")
            return jsonify({"error": "This operation is only available on host instances"}), 403
        
        # Get pending requests from database
        logger.info("Getting pending requests from database...")
        pending_requests = cluster_db.get_pending_requests()
        logger.info(f"Database returned {len(pending_requests)} pending requests")
        
        if pending_requests:
            logger.info(f"First request: {pending_requests[0]}")
        
        # Convert to legacy format for compatibility
        pending_dict = {}
        for req in pending_requests:
            logger.info(f"Converting request: {req['node_name']} from {req['ip_address']}")
            pending_dict[req['node_name']] = {
                "id": req['node_name'],
                "request_id": req['id'],
                "info": json.loads(req['request_data']) if req['request_data'] else {},
                "request_time": req['requested_at'],
                "ip_address": req['ip_address'],
                "status": req['status'],
                "machine_name": req['machine_name'],
                "os_info": req['os_info']
            }
        
        response_data = {
            "pending_requests": pending_dict,
            "count": len(pending_requests)
        }
        
        logger.info(f"Returning response with {response_data['count']} requests")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error getting pending requests: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/approve/<subhost_id>", methods=["POST"])
@require_cluster_auth
def api_approve_subhost(subhost_id):
    # Approve a pending subhost join request
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
        
        # Find the pending request in database
        pending_requests = cluster_db.get_pending_requests()
        matching_request = None
        for req in pending_requests:
            if req['node_name'] == subhost_id:
                matching_request = req
                break
        
        if not matching_request:
            return jsonify({"error": f"No pending request found for subhost {subhost_id}"}), 404
        
        # Generate approval token
        import uuid
        approval_token = str(uuid.uuid4())
        
        # Approve the request in database
        success = cluster_db.approve_request(
            request_id=matching_request['id'],
            approved_by="system",
            approval_token=approval_token
        )
        
        if not success:
            return jsonify({"error": "Failed to approve request"}), 500
        
        # Add to registered nodes
        cluster_db.add_cluster_node(
            name=subhost_id,
            ip_address=matching_request['ip_address'],
            port=matching_request['port'],
            node_type='subhost',
            cluster_token=approval_token
        )
        
        logger.info(f"Subhost {subhost_id} approved and registered")
        
        return jsonify({
            "status": "approved",
            "subhost_id": subhost_id,
            "approval_token": approval_token,
            "message": f"Subhost {subhost_id} approved successfully"
        })
        
    except Exception as e:
        logger.error(f"Error approving subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/reject/<subhost_id>", methods=["POST"])
@require_cluster_auth
def api_reject_subhost(subhost_id):
    # Reject a pending subhost join request
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
        
        # Find the pending request in database
        pending_requests = cluster_db.get_pending_requests()
        matching_request = None
        for req in pending_requests:
            if req['node_name'] == subhost_id:
                matching_request = req
                break
        
        if not matching_request:
            return jsonify({"error": f"No pending request found for subhost {subhost_id}"}), 404
        
        # Reject the request in database
        success = cluster_db.reject_request(
            request_id=matching_request['id'],
            rejected_by="system"
        )
        
        if not success:
            return jsonify({"error": "Failed to reject request"}), 500
        
        logger.info(f"Subhost {subhost_id} join request rejected")
        
        return jsonify({
            "status": "rejected",
            "subhost_id": subhost_id,
            "message": f"Subhost {subhost_id} join request rejected"
        })
        
    except Exception as e:
        logger.error(f"Error rejecting subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/check-approval/<subhost_id>", methods=["GET"])
def api_check_approval(subhost_id):
    # Check if a subhost join request has been approved
    try:
        # Check if already registered as a node
        registered_node = cluster_db.get_cluster_node(subhost_id)
        if registered_node:
            return jsonify({
                "status": "approved",
                "approved": True,
                "approval_token": registered_node.get('cluster_token'),
                "message": "Subhost approved and registered"
            })
        
        # Check pending requests
        pending_requests = cluster_db.get_pending_requests()
        for req in pending_requests:
            if req['node_name'] == subhost_id:
                if req['status'] == 'approved':
                    return jsonify({
                        "status": "approved",
                        "approved": True,
                        "approval_token": req['approval_token'],
                        "message": "Subhost approved, completing registration"
                    })
                elif req['status'] == 'pending':
                    return jsonify({
                        "status": "pending",
                        "approved": False,
                        "message": "Join request still pending approval"
                    })
                elif req['status'] == 'rejected':
                    return jsonify({
                        "status": "rejected",
                        "approved": False,
                        "message": "Join request was rejected"
                    })
        
        return jsonify({
            "status": "not_found",
                "approved": False,
                "message": "No join request found"
            })
            
    except Exception as e:
        logger.error(f"Error checking approval status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/heartbeat", methods=["POST"])
@require_cluster_auth
def api_subhost_heartbeat():
    # Receive heartbeat from subhost
    try:
        data = request.get_json()
        if not data:
            logger.warning("Heartbeat request received with no data")
            return jsonify({"error": "No data provided"}), 400
            
        subhost_id = data.get("subhost_id")
        if not subhost_id:
            logger.warning("Heartbeat request missing subhost_id")
            return jsonify({"error": "subhost_id is required"}), 400
        
        # Check if subhost is registered
        existing_node = cluster_db.get_cluster_node(subhost_id)
        
        if existing_node:
            # Update last ping timestamp and status
            cluster_db.update_node_status(subhost_id, "active", datetime.now())
            logger.debug(f"Heartbeat received from registered subhost: {subhost_id}")
        else:
            # Auto-register unregistered subhosts for backward compatibility
            info = data.get("info", {})
            machine_name = info.get("machine_name", "")
            
            success = cluster_db.add_cluster_node(
                name=subhost_id,
                ip_address=request.remote_addr or "unknown",
                node_type="subhost",
                cluster_token=""
            )
            
            if success:
                cluster_db.update_node_status(subhost_id, "active", datetime.now())
                logger.info(f"Auto-registered new subhost from heartbeat: {subhost_id}")
                logger.info(f"SUBHOST_AUTO_REGISTRATION: Subhost {subhost_id} auto-registered via heartbeat (user: system)")
            else:
                logger.error(f"Failed to auto-register subhost {subhost_id}")
                return jsonify({"error": "Failed to register subhost"}), 500
        
        # Update host heartbeat as well
        cluster_db.heartbeat()
        
        return jsonify({
            "status": "acknowledged",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error processing heartbeat: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhosts", methods=["GET"])
@require_cluster_auth
def api_list_subhosts():
    # List all registered subhosts
    try:
        # Get all cluster nodes
        all_nodes = cluster_db.get_all_cluster_nodes()
        
        # Filter for subhosts and convert to legacy format
        active_subhosts = {}
        inactive_count = 0
        current_time = datetime.now()
        
        for node in all_nodes:
            if node['node_type'] == 'subhost':
                subhost_id = node['name']
                last_ping = node['last_ping']
                
                # Calculate time since last ping
                if last_ping:
                    try:
                        last_ping_time = datetime.fromisoformat(last_ping)
                        time_diff = current_time - last_ping_time
                        seconds_ago = int(time_diff.total_seconds())
                        
                        # Mark as active if last seen within 5 minutes
                        if seconds_ago < 300:  # 5 minutes
                            status = "active"
                        else:
                            status = "inactive"
                            inactive_count += 1
                            
                        last_seen_ago = f"{seconds_ago} seconds ago"
                    except:
                        status = "unknown"
                        last_seen_ago = "unknown"
                        seconds_ago = 999999
                else:
                    status = "unknown"
                    last_seen_ago = "never"
                    seconds_ago = 999999
                
                # Convert to legacy format
                active_subhosts[subhost_id] = {
                    "id": subhost_id,
                    "info": {},  # Legacy compatibility: info field no longer stored
                    "last_seen": node['last_ping'] or node['added_at'],
                    "registered_at": node['added_at'],
                    "status": status,
                    "last_seen_ago": last_seen_ago,
                    "ip_address": node['ip_address'],
                    "port": node['port']
                }
        
        # Clean up inactive subhosts that haven't been seen for over 1 hour
        old_count = len(active_subhosts)
        nodes_to_remove = []
        for subhost_id, data in active_subhosts.items():
            if data['status'] == 'inactive':
                last_ping = data['last_seen']
                if last_ping and last_ping != 'never':
                    try:
                        last_ping_time = datetime.fromisoformat(last_ping)
                        time_diff = current_time - last_ping_time
                        if time_diff.total_seconds() > 3600:  # 1 hour
                            nodes_to_remove.append(subhost_id)
                    except:
                        pass
        
        # Remove old nodes
        for subhost_id in nodes_to_remove:
            cluster_db.remove_cluster_node(subhost_id)
            active_subhosts.pop(subhost_id, None)
        
        cleanup_count = old_count - len(active_subhosts)
        if cleanup_count > 0:
            logger.info(f"Cleaned up {cleanup_count} old subhost entries")
        
        logger.debug(f"Listed {len(active_subhosts)} subhosts ({inactive_count} inactive)")
        
        return jsonify({
            "subhosts": active_subhosts,
            "count": len(active_subhosts)
        })
        
    except Exception as e:
        logger.error(f"Error listing subhosts: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/status", methods=["GET"])
@require_cluster_auth
def api_cluster_status():
    # Get overall cluster status
    try:
        role, host_address = get_cluster_role()
        
        cluster_status = {
            "role": role,
            "host_address": host_address,
            "timestamp": datetime.now().isoformat()
        }
        
        if role == "Host":
            # Include subhost information for hosts
            all_nodes = cluster_db.get_all_cluster_nodes()
            subhosts = {}
            subhost_count = 0
            
            for node in all_nodes:
                if node['node_type'] == 'subhost':
                    subhosts[node['name']] = {
                        "id": node['name'],
                        "info": {},  # Legacy compatibility
                        "last_seen": node['last_ping'] or node['added_at'],
                        "registered_at": node['added_at'],
                        "ip_address": node['ip_address'],
                        "port": node['port'],
                        "status": node['status']
                    }
                    subhost_count += 1
            
            cluster_status["subhosts"] = subhosts
            cluster_status["subhost_count"] = subhost_count
            
            # Add host status information
            host_status = cluster_db.get_host_status()
            if host_status:
                cluster_status["host_status"] = host_status['status']
                cluster_status["dashboard_active"] = host_status['dashboard_active']
                cluster_status["maintenance_mode"] = host_status['maintenance_mode']
            else:
                cluster_status["host_status"] = "unknown"
                cluster_status["dashboard_active"] = True
                cluster_status["maintenance_mode"] = False
            
        logger.debug(f"Cluster status requested - Role: {role}, Subhosts: {subhost_count if role == 'Host' else 'N/A'}")
        
        return jsonify(cluster_status)
        
    except Exception as e:
        logger.error(f"Error getting cluster status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/host-status", methods=["GET"])
def api_get_host_status():
    # Get current host status - available without authentication for subhost health checks
    try:
        # This endpoint is available without authentication for subhosts to check host status
        host_status = cluster_db.get_host_status()
        
        if host_status:
            return jsonify({
                "host_status": host_status['status'],
                "dashboard_active": host_status['dashboard_active'],
                "maintenance_mode": host_status['maintenance_mode'],
                "status_message": host_status.get('status_message', ''),
                "last_heartbeat": host_status['last_heartbeat'],
                "timestamp": datetime.now().isoformat()
            })
        else:
            # No status record means host might be starting up or in unknown state
            return jsonify({
                "host_status": "unknown",
                "dashboard_active": False,
                "maintenance_mode": False,
                "status_message": "Host status not available",
                "last_heartbeat": None,
                "timestamp": datetime.now().isoformat()
            })
        
    except Exception as e:
        logger.error(f"Error getting host status: {str(e)}")
        return jsonify({
            "host_status": "error",
            "dashboard_active": False,
            "maintenance_mode": True,
            "status_message": f"Error retrieving status: {str(e)}",
            "last_heartbeat": None,
            "timestamp": datetime.now().isoformat()
        }), 500

# Remote Server Operations API (Host-only endpoints)
@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers", methods=["GET"])
def api_get_subhost_servers(subhost_id):
    # Get servers from a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if not is_subhost_registered(subhost_id):
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_info = get_subhost_info(subhost_id)
        if not subhost_info:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        # Use subhost IP address from database
        subhost_ip = subhost_info['ip_address']
        subhost_port = subhost_info['port']
        subhost_api_url = f"http://{subhost_ip}:{subhost_port}"
        
        # Make request to subhost API
        import requests
        try:
            response = requests.get(f"{subhost_api_url}/api/servers", timeout=10)
            if response.status_code == 200:
                return jsonify(response.json())
            else:
                return jsonify({"error": f"Subhost returned error: {response.status_code}"}), response.status_code
        except requests.RequestException as e:
            logger.error(f"Failed to connect to subhost {subhost_id}: {str(e)}")
            return jsonify({"error": f"Failed to connect to subhost: {str(e)}"}), 503
            
    except Exception as e:
        logger.error(f"Error getting subhost servers: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers/<server_name>/start", methods=["POST"])
def api_start_subhost_server(subhost_id, server_name):
    # Start a server on a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        return _execute_subhost_server_command(subhost_id, server_name, "start")
        
    except Exception as e:
        logger.error(f"Error starting subhost server: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers/<server_name>/stop", methods=["POST"])
def api_stop_subhost_server(subhost_id, server_name):
    # Stop a server on a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        return _execute_subhost_server_command(subhost_id, server_name, "stop")
        
    except Exception as e:
        logger.error(f"Error stopping subhost server: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers/<server_name>/restart", methods=["POST"])
def api_restart_subhost_server(subhost_id, server_name):
    # Restart a server on a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        return _execute_subhost_server_command(subhost_id, server_name, "restart")
        
    except Exception as e:
        logger.error(f"Error restarting subhost server: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers", methods=["POST"])
def api_install_subhost_server(subhost_id):
    # Install a new server on a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if not is_subhost_registered(subhost_id):
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "No installation data provided"}), 400
            
        subhost_info = get_subhost_info(subhost_id)
        if not subhost_info:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_ip = subhost_info['ip_address']
        subhost_port = subhost_info['port']
        subhost_api_url = f"http://{subhost_ip}:{subhost_port}"
        
        # Forward the installation request to the subhost
        import requests
        try:
            headers = {"Content-Type": "application/json"}
            # No authorization headers needed in simplified cluster system
                
            response = requests.post(f"{subhost_api_url}/api/servers", 
                                   json=data, headers=headers, timeout=30)
            if response.status_code == 200:
                logger.info(f"Successfully initiated server installation on subhost {subhost_id}")
                return jsonify(response.json())
            else:
                return jsonify({"error": f"Subhost returned error: {response.status_code}"}), response.status_code
        except requests.RequestException as e:
            logger.error(f"Failed to connect to subhost {subhost_id} for installation: {str(e)}")
            return jsonify({"error": f"Failed to connect to subhost: {str(e)}"}), 503
            
    except Exception as e:
        logger.error(f"Error installing server on subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers/<server_name>", methods=["DELETE"])
def api_remove_subhost_server(subhost_id, server_name):
    # Remove a server from a specific subhost
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if not is_subhost_registered(subhost_id):
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_info = get_subhost_info(subhost_id)
        if not subhost_info:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_ip = subhost_info['ip_address']
        subhost_port = subhost_info['port']
        subhost_api_url = f"http://{subhost_ip}:{subhost_port}"
        
        # Forward the deletion request to the subhost
        import requests
        try:
            headers = {}
            # No authorization headers needed in simplified cluster system
                
            response = requests.delete(f"{subhost_api_url}/api/servers/{server_name}", 
                                     headers=headers, timeout=15)
            if response.status_code == 200:
                logger.info(f"Successfully removed server {server_name} from subhost {subhost_id}")
                return jsonify(response.json())
            else:
                return jsonify({"error": f"Subhost returned error: {response.status_code}"}), response.status_code
        except requests.RequestException as e:
            logger.error(f"Failed to connect to subhost {subhost_id} for server removal: {str(e)}")
            return jsonify({"error": f"Failed to connect to subhost: {str(e)}"}), 503
            
    except Exception as e:
        logger.error(f"Error removing server from subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

def _execute_subhost_server_command(subhost_id, server_name, action):
    # Helper function to execute server commands on subhost
    if not is_subhost_registered(subhost_id):
        return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
        
    subhost_info = get_subhost_info(subhost_id)
    if not subhost_info:
        return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
        
    subhost_ip = subhost_info['ip_address']
    subhost_port = subhost_info['port']
    subhost_api_url = f"http://{subhost_ip}:{subhost_port}"
    
    # Make request to subhost API
    import requests
    try:
        headers = {}
        # No authorization headers needed in simplified cluster system
            
        response = requests.post(f"{subhost_api_url}/api/servers/{server_name}/{action}", 
                               headers=headers, timeout=15)
        if response.status_code == 200:
            logger.info(f"Successfully executed {action} on server {server_name} on subhost {subhost_id}")
            return jsonify(response.json())
        else:
            return jsonify({"error": f"Subhost returned error: {response.status_code}"}), response.status_code
    except requests.RequestException as e:
        logger.error(f"Failed to connect to subhost {subhost_id} for {action}: {str(e)}")
        return jsonify({"error": f"Failed to connect to subhost: {str(e)}"}), 503

@cluster_api.route("/api/cluster/nodes", methods=["GET"])
@require_cluster_auth
def api_cluster_nodes():
    # Get all approved cluster nodes
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        # Get all registered subhosts from database
        all_nodes = cluster_db.get_all_cluster_nodes()
        nodes = []
        
        for node in all_nodes:
            if node['node_type'] == 'subhost':
                nodes.append({
                    "id": node['name'],
                    "subhost_id": node['name'],
                    "hostname": node['name'],  # Use name as hostname for now
                    "ip_address": node['ip_address'],
                    "status": node['status'].title() if node['status'] else "Unknown",
                    "approved_timestamp": node['added_at'],
                    "last_seen": node['last_ping'] or node['added_at']
                })
            
        logger.debug(f"Returning {len(nodes)} approved cluster nodes")
        return jsonify(nodes)
        
    except Exception as e:
        logger.error(f"Error getting cluster nodes: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ====== REMOTE HOST API ENDPOINTS (Separate from Cluster) ======
# These endpoints handle one-time remote connections without cluster membership

@cluster_api.route("/api/status", methods=["GET"])
def api_server_status():
    # Get server status - used for remote host connectivity testing
    try:
        return jsonify({
            "success": True,
            "status": "online",
            "server": "Server Manager",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error getting server status: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/auth/login", methods=["POST"])
def api_remote_login():
    # Authenticate remote host connection (separate from cluster auth)
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password required"}), 400
        
        # Import user management for authentication
        try:
            from Modules.Database.user_database import initialize_user_manager
            engine, user_manager = initialize_user_manager()
            
            # Authenticate user
            user = user_manager.authenticate_user(username, password)
            if user:
                # For simplicity, return success without complex session management
                # In production environments, proper session tokens should be used
                logger.info(f"Remote host authentication successful for user: {username}")
                return jsonify({
                    "success": True,
                    "message": "Authentication successful",
                    "user": {"username": username, "role": getattr(user, 'role', 'user')}
                })
            else:
                return jsonify({"success": False, "error": "Invalid credentials"}), 401
                
        except Exception as auth_error:
            logger.error(f"Authentication error: {str(auth_error)}")
            return jsonify({"success": False, "error": "Authentication system error"}), 500
            
    except Exception as e:
        logger.error(f"Error in remote login: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/auth/logout", methods=["POST"])
def api_remote_logout():
    # Logout from remote host connection
    try:
        # For now, just return success status
        # In production environments, session tokens should be invalidated here
        return jsonify({"success": True, "message": "Logged out successfully"})
    except Exception as e:
        logger.error(f"Error in remote logout: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/servers", methods=["GET"])
def api_get_servers():
    # Get list of all servers for remote host access
    try:
        # Import server manager
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        server_manager.load_config()
        server_manager.load_servers()
        
        # Get all servers with their current status
        servers = server_manager.get_all_servers()
        result = []
        
        for server_name, server_config in servers.items():
            try:
                # Get server status
                status, pid = server_manager.get_server_status(server_name)
                
                server_info = {
                    "name": server_name,
                    "status": status,
                    "pid": pid,
                    "type": server_config.get('Type', 'Unknown'),
                    "install_dir": server_config.get('InstallDir', ''),
                    "app_id": server_config.get('AppID', ''),
                    "executable": server_config.get('ExecutablePath', ''),
                    "args": server_config.get('LaunchArgs', ''),
                    "last_started": server_config.get('StartTime', ''),
                    "auto_start": server_config.get('AutoStart', False)
                }
                result.append(server_info)
                
            except Exception as server_error:
                logger.debug(f"Error getting status for server {server_name}: {str(server_error)}")
                # Add server with error status if status check fails
                result.append({
                    "name": server_name,
                    "status": "Error",
                    "pid": None,
                    "type": server_config.get('Type', 'Unknown'),
                    "error": str(server_error)
                })
        
        return jsonify({
            "success": True,
            "servers": result,
            "count": len(result)
        })
        
    except Exception as e:
        logger.error(f"Error getting servers: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/servers/<server_name>/status", methods=["GET"])
def api_get_server_status(server_name):
    # Get status of a specific server
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        server_manager.load_config()
        server_manager.load_servers()
        
        # Check if server exists
        server_config = server_manager.get_server_config(server_name)
        if not server_config:
            return jsonify({"success": False, "error": "Server not found"}), 404
        
        # Get server status
        status, pid = server_manager.get_server_status(server_name)
        
        # Get additional process details if the server is currently running
        process_info = {}
        if status == "Running" and pid:
            try:
                import psutil
                process = psutil.Process(pid)
                process_info = {
                    "cpu_percent": process.cpu_percent(),
                    "memory_mb": process.memory_info().rss / 1024 / 1024,
                    "create_time": process.create_time()
                }
            except:
                pass
        
        result = {
            "name": server_name,
            "status": status,
            "pid": pid,
            "type": server_config.get('Type', 'Unknown'),
            "process_info": process_info
        }
        
        return jsonify({"success": True, "server": result})
        
    except Exception as e:
        logger.error(f"Error getting server status for {server_name}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/servers/<server_name>/start", methods=["POST"])
def api_start_server(server_name):
    # Start a specific server
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        server_manager.load_config()
        server_manager.load_servers()
        
        # Check if server exists
        server_config = server_manager.get_server_config(server_name)
        if not server_config:
            return jsonify({"success": False, "error": "Server not found"}), 404
        
        # Start the server
        success = server_manager.start_server_advanced(server_name)
        
        if success:
            logger.info(f"Remote request: Started server {server_name}")
            return jsonify({
                "success": True,
                "message": f"Server '{server_name}' started successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to start server '{server_name}'"
            }), 500
            
    except Exception as e:
        logger.error(f"Error starting server {server_name}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/servers/<server_name>/stop", methods=["POST"])
def api_stop_server(server_name):
    # Stop a specific server
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        server_manager.load_config()
        server_manager.load_servers()
        
        # Check if server exists
        server_config = server_manager.get_server_config(server_name)
        if not server_config:
            return jsonify({"success": False, "error": "Server not found"}), 404
        
        # Stop the server
        success = server_manager.stop_server(server_name)
        
        if success:
            logger.info(f"Remote request: Stopped server {server_name}")
            return jsonify({
                "success": True,
                "message": f"Server '{server_name}' stopped successfully"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to stop server '{server_name}'"
            }), 500
            
    except Exception as e:
        logger.error(f"Error stopping server {server_name}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@cluster_api.route("/api/servers/<server_name>/restart", methods=["POST"])
def api_restart_server(server_name):
    # Restart a specific server
    try:
        from Modules.server_manager import ServerManager
        server_manager = ServerManager()
        server_manager.load_config()
        server_manager.load_servers()
        
        # Check if server exists
        server_config = server_manager.get_server_config(server_name)
        if not server_config:
            return jsonify({"success": False, "error": "Server not found"}), 404
        
        # Restart the server (stop then start)
        stop_success = server_manager.stop_server(server_name)
        if stop_success:
            # Wait a moment before starting
            import time
            time.sleep(2)
            start_success = server_manager.start_server_advanced(server_name)
            
            if start_success:
                logger.info(f"Remote request: Restarted server {server_name}")
                return jsonify({
                    "success": True,
                    "message": f"Server '{server_name}' restarted successfully"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": f"Server stopped but failed to start again"
                }), 500
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to stop server for restart"
            }), 500
            
    except Exception as e:
        logger.error(f"Error restarting server {server_name}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500