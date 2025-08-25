import os
import sys
import json
import time
import hmac
import hashlib
import secrets
import winreg
from datetime import datetime, timedelta

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("ClusterSecurity")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("ClusterSecurity")

class ClusterSecurityManager:
    """Manages secure communication between cluster nodes"""
    
    def __init__(self):
        self.cluster_keys = {}
        self.token_cache = {}
        self.load_cluster_keys()
        
    def load_cluster_keys(self):
        """Load cluster security keys from registry"""
        try:
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
            try:
                cluster_secret = winreg.QueryValueEx(key, "ClusterSecret")[0]
                self.cluster_keys["master"] = cluster_secret
                logger.debug("Loaded cluster secret from registry")
            except Exception:
                # Generate new cluster secret if not exists
                cluster_secret = self.generate_cluster_secret()
                self.save_cluster_secret(cluster_secret)
                self.cluster_keys["master"] = cluster_secret
                logger.info("Generated new cluster secret")
            winreg.CloseKey(key)
        except Exception as e:
            # Fallback to temporary key for development
            logger.warning(f"Failed to load cluster keys from registry: {str(e)}")
            self.cluster_keys["master"] = "dev-fallback-key-" + secrets.token_hex(16)
            logger.warning("Using temporary fallback cluster key - not secure for production!")
            
    def generate_cluster_secret(self):
        """Generate a new cluster secret"""
        return secrets.token_hex(32)
        
    def save_cluster_secret(self, secret):
        """Save cluster secret to registry"""
        try:
            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "ClusterSecret", 0, winreg.REG_SZ, secret)
            winreg.CloseKey(key)
            logger.info("Cluster secret saved to registry")
        except Exception as e:
            logger.error(f"Failed to save cluster secret to registry: {str(e)}")
            
    def generate_api_key(self, subhost_id):
        """Generate an API key for a subhost"""
        try:
            key_data = {
                "subhost_id": subhost_id,
                "created_at": datetime.now().isoformat(),
                "key_hash": secrets.token_hex(16)
            }
            
            # Use HMAC with cluster secret
            key_string = json.dumps(key_data, sort_keys=True)
            api_key = hmac.new(
                self.cluster_keys.get("master", "").encode(),
                key_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            logger.info(f"Generated API key for subhost {subhost_id}")
            return api_key
            
        except Exception as e:
            logger.error(f"Failed to generate API key: {str(e)}")
            return None
            
    def generate_subhost_token(self, subhost_id, expires_minutes=60):
        """Generate a secure token for subhost authentication"""
        try:
            # Ensure we have a master key
            if "master" not in self.cluster_keys or not self.cluster_keys["master"]:
                logger.error("No cluster secret available for token generation")
                return None
                
            # Create token payload
            expires_at = datetime.now() + timedelta(minutes=expires_minutes)
            payload = {
                "subhost_id": subhost_id,
                "created_at": datetime.now().isoformat(),
                "expires_at": expires_at.isoformat(),
                "nonce": secrets.token_hex(8)
            }
            
            # Create HMAC signature
            payload_str = json.dumps(payload, sort_keys=True)
            signature = hmac.new(
                self.cluster_keys["master"].encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Combine payload and signature
            token_data = {
                "payload": payload,
                "signature": signature
            }
            
            # Store in cache
            token_str = json.dumps(token_data)
            self.token_cache[subhost_id] = {
                "token": token_str,
                "expires": payload["expires_at"]
            }
            
            logger.info(f"Generated secure token for subhost {subhost_id}")
            return token_str
            
        except Exception as e:
            logger.error(f"Failed to generate subhost token: {str(e)}")
            return None
            
    def verify_subhost_token(self, token_str, subhost_id):
        """Verify a subhost token"""
        try:
            # Ensure we have a master key
            if "master" not in self.cluster_keys or not self.cluster_keys["master"]:
                logger.warning("No cluster secret available for token verification")
                return False
                
            token_data = json.loads(token_str)
            payload = token_data["payload"]
            signature = token_data["signature"]
            
            # Verify subhost ID matches
            if payload["subhost_id"] != subhost_id:
                logger.warning(f"Token subhost ID mismatch: expected {subhost_id}, got {payload['subhost_id']}")
                return False
                
            # Check expiration
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now() > expires_at:
                logger.warning(f"Token expired for subhost {subhost_id}")
                return False
                
            # Verify signature
            payload_str = json.dumps(payload, sort_keys=True)
            expected_signature = hmac.new(
                self.cluster_keys["master"].encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                logger.warning(f"Invalid token signature for subhost {subhost_id}")
                return False
                
            logger.info(f"Token verified successfully for subhost {subhost_id}")
            return True
            
        except Exception as e:
            logger.error(f"Token verification failed for subhost {subhost_id}: {str(e)}")
            return False
            
    def verify_cluster_token(self, token_str):
        """Verify any cluster token without specifying subhost ID"""
        try:
            # Ensure we have a master key
            if "master" not in self.cluster_keys or not self.cluster_keys["master"]:
                logger.warning("No cluster secret available for token verification")
                return None
                
            token_data = json.loads(token_str)
            payload = token_data["payload"]
            signature = token_data["signature"]
            
            # Check expiration
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now() > expires_at:
                logger.warning("Token expired")
                return None
                
            # Verify signature
            payload_str = json.dumps(payload, sort_keys=True)
            expected_signature = hmac.new(
                self.cluster_keys["master"].encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_signature):
                logger.warning("Invalid token signature")
                return None
                
            logger.debug(f"Token verified successfully for subhost {payload.get('subhost_id', 'unknown')}")
            return payload
            
        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            return None
            
    def get_cluster_secret(self):
        """Get the cluster secret"""
        return self.cluster_keys.get("master")

# Global instance
cluster_security = ClusterSecurityManager()
