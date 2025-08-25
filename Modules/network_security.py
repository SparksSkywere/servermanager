import ipaddress
import logging
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger("NetworkSecurity")

# Default allowed networks for cluster communication
DEFAULT_ALLOWED_NETWORKS = [
    "127.0.0.0/8",      # Localhost
    "10.0.0.0/8",       # Private Class A
    "172.16.0.0/12",    # Private Class B  
    "192.168.0.0/16",   # Private Class C
]

class NetworkSecurityManager:
    """Manages network-level security for the Server Manager"""
    
    def __init__(self, allowed_networks=None):
        self.allowed_networks = []
        if allowed_networks:
            for network in allowed_networks:
                try:
                    self.allowed_networks.append(ipaddress.ip_network(network, strict=False))
                except Exception as e:
                    logger.error(f"Invalid network configuration: {network} - {e}")
        else:
            # Use defaults
            for network in DEFAULT_ALLOWED_NETWORKS:
                self.allowed_networks.append(ipaddress.ip_network(network, strict=False))
                
        logger.info(f"Network security initialized with {len(self.allowed_networks)} allowed networks")
        
    def is_ip_allowed(self, ip_address):
        """Check if an IP address is allowed"""
        try:
            client_ip = ipaddress.ip_address(ip_address)
            for network in self.allowed_networks:
                if client_ip in network:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking IP address {ip_address}: {e}")
            return False
            
    def add_allowed_network(self, network):
        """Add an allowed network"""
        try:
            net = ipaddress.ip_network(network, strict=False)
            if net not in self.allowed_networks:
                self.allowed_networks.append(net)
                logger.info(f"Added allowed network: {network}")
                return True
        except Exception as e:
            logger.error(f"Failed to add network {network}: {e}")
        return False
        
    def remove_allowed_network(self, network):
        """Remove an allowed network"""
        try:
            net = ipaddress.ip_network(network, strict=False)
            if net in self.allowed_networks:
                self.allowed_networks.remove(net)
                logger.info(f"Removed allowed network: {network}")
                return True
        except Exception as e:
            logger.error(f"Failed to remove network {network}: {e}")
        return False

def require_allowed_network(security_manager):
    """Decorator to check if client IP is from an allowed network"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = request.environ.get('REMOTE_ADDR', request.remote_addr)
            
            # Handle proxied requests
            forwarded_for = request.headers.get('X-Forwarded-For')
            real_ip = request.headers.get('X-Real-IP')
            
            if forwarded_for:
                client_ip = forwarded_for.split(',')[0].strip()
            elif real_ip:
                client_ip = real_ip
                
            if not security_manager.is_ip_allowed(client_ip):
                logger.warning(f"Access denied for IP address: {client_ip}")
                return jsonify({
                    "error": "Access denied", 
                    "message": "Your IP address is not allowed to access this resource"
                }), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Global instance
network_security = NetworkSecurityManager()
