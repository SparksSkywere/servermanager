import os
import sys
import winreg
import json
import datetime
from functools import wraps
from flask import Blueprint, jsonify, request

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import security managers
from Modules.cluster_security import ClusterSecurityManager
from Modules.network_security import NetworkSecurityManager, require_allowed_network

# Import standardized logging
from Modules.server_logging import get_component_logger
logger = get_component_logger("ClusterAPI")

cluster_api = Blueprint("cluster_api", __name__)

# Initialize security managers
security_manager = ClusterSecurityManager()
network_security_manager = NetworkSecurityManager()

# In-memory storage for subhost registration (in production, use database)
registered_subhosts = {}

def require_cluster_auth(f):
    """Decorator to require cluster authentication for API endpoints"""
    @wraps(f)
    @require_allowed_network(network_security_manager)
    def decorated_function(*args, **kwargs):
        # Allow unauthenticated access to role endpoint for initial setup
        if request.endpoint == 'cluster_api.api_cluster_role':
            return f(*args, **kwargs)
            
        # Check for authentication token in headers
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.warning(f"Unauthorized cluster API request from {request.remote_addr} - missing token")
            return jsonify({"error": "Authentication required"}), 401
            
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        
        # Verify the token
        token_data = security_manager.verify_cluster_token(token)
        if not token_data:
            logger.warning(f"Unauthorized cluster API request from {request.remote_addr} - invalid token")
            return jsonify({"error": "Invalid authentication token"}), 401
            
        return f(*args, **kwargs)
    return decorated_function

def get_cluster_role():
    """Get the cluster role and host address from registry"""
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
    """Get the cluster role of this instance"""
    role, host_address = get_cluster_role()
    return jsonify({
        "role": role,
        "hostAddress": host_address
    })

@cluster_api.route("/api/cluster/register", methods=["POST"])
@require_cluster_auth
def api_register_subhost():
    """Register a subhost with the host"""
    global registered_subhosts
    
    try:
        data = request.get_json()
        if not data:
            logger.warning("Register subhost request received with no data")
            return jsonify({"error": "No data provided"}), 400
            
        subhost_id = data.get("subhost_id")
        if not subhost_id:
            logger.warning("Register subhost request missing subhost_id")
            return jsonify({"error": "subhost_id is required"}), 400
            
        # Store subhost information
        registered_subhosts[subhost_id] = {
            "id": subhost_id,
            "info": data.get("info", {}),
            "last_seen": datetime.datetime.now().isoformat(),
            "registered_at": datetime.datetime.now().isoformat()
        }
        
        logger.info(f"Subhost {subhost_id} registered successfully")
        logger.info(f"SUBHOST_REGISTRATION: Subhost {subhost_id} registered (user: system)")
        
        return jsonify({
            "status": "registered",
            "subhost_id": subhost_id,
            "message": f"Subhost {subhost_id} registered successfully"
        })
        
    except Exception as e:
        logger.error(f"Error registering subhost: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/heartbeat", methods=["POST"])
@require_cluster_auth
def api_subhost_heartbeat():
    """Receive heartbeat from subhost"""
    global registered_subhosts
    
    try:
        data = request.get_json()
        if not data:
            logger.warning("Heartbeat request received with no data")
            return jsonify({"error": "No data provided"}), 400
            
        subhost_id = data.get("subhost_id")
        if not subhost_id:
            logger.warning("Heartbeat request missing subhost_id")
            return jsonify({"error": "subhost_id is required"}), 400
            
        # Update last seen timestamp
        if subhost_id in registered_subhosts:
            registered_subhosts[subhost_id]["last_seen"] = datetime.datetime.now().isoformat()
            registered_subhosts[subhost_id]["info"] = data.get("info", {})
            logger.debug(f"Heartbeat received from registered subhost: {subhost_id}")
        else:
            # Auto-register if not already registered
            registered_subhosts[subhost_id] = {
                "id": subhost_id,
                "info": data.get("info", {}),
                "last_seen": datetime.datetime.now().isoformat(),
                "registered_at": datetime.datetime.now().isoformat()
            }
            logger.info(f"Auto-registered new subhost from heartbeat: {subhost_id}")
            logger.info(f"SUBHOST_AUTO_REGISTRATION: Subhost {subhost_id} auto-registered via heartbeat (user: system)")
        
        return jsonify({
            "status": "acknowledged",
            "timestamp": datetime.datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error processing heartbeat: {str(e)}")
        return jsonify({"error": str(e)}), 500

@cluster_api.route("/api/cluster/subhosts", methods=["GET"])
@require_cluster_auth
def api_list_subhosts():
    """List all registered subhosts"""
    global registered_subhosts
    
    try:
        # Clean up old subhosts (haven't been seen in 5 minutes)
        current_time = datetime.datetime.now()
        active_subhosts = {}
        inactive_count = 0
        
        for subhost_id, subhost_data in registered_subhosts.items():
            last_seen = datetime.datetime.fromisoformat(subhost_data["last_seen"])
            time_diff = current_time - last_seen
            
            # Keep subhosts that have been seen in the last 5 minutes
            if time_diff.total_seconds() < 300:  # 5 minutes
                subhost_data["status"] = "active"
                subhost_data["last_seen_ago"] = f"{int(time_diff.total_seconds())} seconds ago"
                active_subhosts[subhost_id] = subhost_data
            else:
                subhost_data["status"] = "inactive"
                subhost_data["last_seen_ago"] = f"{int(time_diff.total_seconds())} seconds ago"
                active_subhosts[subhost_id] = subhost_data
                inactive_count += 1
                
        # Update the global registry
        # Clean up old entries (older than 1 hour)
        old_count = len(registered_subhosts)
        registered_subhosts = {k: v for k, v in registered_subhosts.items() 
                              if current_time - datetime.datetime.fromisoformat(v["last_seen"]) < datetime.timedelta(hours=1)}
        
        if old_count != len(registered_subhosts):
            logger.info(f"Cleaned up {old_count - len(registered_subhosts)} old subhost entries")
        
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
    """Get overall cluster status"""
    try:
        role, host_address = get_cluster_role()
        
        cluster_status = {
            "role": role,
            "host_address": host_address,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        if role == "Host":
            # Include subhost information for hosts
            cluster_status["subhosts"] = registered_subhosts
            cluster_status["subhost_count"] = len(registered_subhosts)
            
        logger.debug(f"Cluster status requested - Role: {role}, Subhosts: {len(registered_subhosts) if role == 'Host' else 'N/A'}")
        
        return jsonify(cluster_status)
        
    except Exception as e:
        logger.error(f"Error getting cluster status: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Remote Server Operations API (Host-only endpoints)
@cluster_api.route("/api/cluster/subhost/<subhost_id>/servers", methods=["GET"])
def api_get_subhost_servers(subhost_id):
    """Get servers from a specific subhost"""
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if subhost_id not in registered_subhosts:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_info = registered_subhosts[subhost_id]["info"]
        subhost_api_url = subhost_info.get("api_url", "http://localhost:8080")
        
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
    """Start a server on a specific subhost"""
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
    """Stop a server on a specific subhost"""
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
    """Restart a server on a specific subhost"""
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
    """Install a new server on a specific subhost"""
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if subhost_id not in registered_subhosts:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "No installation data provided"}), 400
            
        subhost_info = registered_subhosts[subhost_id]["info"]
        subhost_api_url = subhost_info.get("api_url", "http://localhost:8080")
        
        # Forward the installation request to the subhost
        import requests
        try:
            headers = {"Content-Type": "application/json"}
            if "Authorization" in request.headers:
                headers["Authorization"] = request.headers["Authorization"]
                
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
    """Remove a server from a specific subhost"""
    try:
        role, _ = get_cluster_role()
        if role != "Host":
            return jsonify({"error": "This operation is only available on host instances"}), 403
            
        if subhost_id not in registered_subhosts:
            return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
            
        subhost_info = registered_subhosts[subhost_id]["info"]
        subhost_api_url = subhost_info.get("api_url", "http://localhost:8080")
        
        # Forward the deletion request to the subhost
        import requests
        try:
            headers = {}
            if "Authorization" in request.headers:
                headers["Authorization"] = request.headers["Authorization"]
                
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
    """Helper function to execute server commands on subhost"""
    if subhost_id not in registered_subhosts:
        return jsonify({"error": f"Subhost {subhost_id} not found"}), 404
        
    subhost_info = registered_subhosts[subhost_id]["info"]
    subhost_api_url = subhost_info.get("api_url", "http://localhost:8080")
    
    # Make request to subhost API
    import requests
    try:
        headers = {}
        if "Authorization" in request.headers:
            headers["Authorization"] = request.headers["Authorization"]
            
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
