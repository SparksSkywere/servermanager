import os
import sys
import winreg
import json
import datetime
from flask import Blueprint, jsonify, request

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import standardized logging
from Modules.server_logging import get_component_logger
logger = get_component_logger("ClusterAPI")

cluster_api = Blueprint("cluster_api", __name__)

# In-memory storage for subhost registration (in production, use database)
registered_subhosts = {}

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
