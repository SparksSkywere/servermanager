# Security operations including authentication, encryption, and privilege management

import os
import sys
import json
import logging
import ctypes
import winreg
import hashlib
import secrets
import base64
from datetime import datetime

try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("Security")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Security")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("Security module debug mode enabled via environment")

class SecurityManager:
    # Manages security operations including authentication and encryption
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        
        # Initialize from registry
        self.initialize_from_registry()
    
    def initialize_from_registry(self):
        # Initialize paths from registry settings
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "security": os.path.join(self.server_manager_dir, "config", "security")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            logger.info(f"Security manager initialized from registry")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize security manager from registry: {str(e)}")
            return False
            
    def is_admin(self):
        # Check if the current process has administrator privileges
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
            
    def generate_token(self, length=32):
        # Generate a secure random token
        return secrets.token_hex(length)
        
    def hash_password(self, password, salt=None):
        # Hash a password with optional salt
        if salt is None:
            salt = secrets.token_hex(16)
            
        password_bytes = password.encode('utf-8')
        salt_bytes = salt.encode('utf-8')
        
        hash_obj = hashlib.sha256(password_bytes + salt_bytes)
        password_hash = base64.b64encode(hash_obj.digest()).decode('utf-8')
        
        return {
            "hash": password_hash,
            "salt": salt
        }
        
    def verify_password(self, password, stored_hash, salt):
        # Verify a password against a stored hash and salt
        password_bytes = password.encode('utf-8')
        salt_bytes = salt.encode('utf-8')
        
        hash_obj = hashlib.sha256(password_bytes + salt_bytes)
        calculated_hash = base64.b64encode(hash_obj.digest()).decode('utf-8')
        
        return calculated_hash == stored_hash
        
    def encrypt_data(self, data, key=None):
        # Encrypt data with an optional key
        try:
            from cryptography.fernet import Fernet
            
            if key is None:
                key = Fernet.generate_key()
            elif isinstance(key, str):
                # Ensure the key is proper Fernet key format
                try:
                    Fernet(key.encode('utf-8'))
                except:
                    key = Fernet.generate_key()
            
            if isinstance(data, str):
                data = data.encode('utf-8')
                
            f = Fernet(key)
            encrypted_data = f.encrypt(data)
            
            return {
                "data": encrypted_data,
                "key": key
            }
        except ImportError:
            logger.error("Cryptography module not installed. Using base64 encoding instead.")
            # Fallback to simple encoding if cryptography not available
            if isinstance(data, str):
                data = data.encode('utf-8')
            return {
                "data": base64.b64encode(data),
                "key": None
            }
        except Exception as e:
            logger.error(f"Encryption error: {str(e)}")
            return None
            
    def decrypt_data(self, encrypted_data, key):
        # Decrypt data with the provided key
        try:
            from cryptography.fernet import Fernet
            
            if isinstance(key, str):
                key = key.encode('utf-8')
                
            f = Fernet(key)
            decrypted_data = f.decrypt(encrypted_data)
            
            return decrypted_data
        except ImportError:
            logger.error("Cryptography module not installed. Using base64 decoding instead.")
            # Fallback to simple decoding if cryptography not available
            return base64.b64decode(encrypted_data)
        except Exception as e:
            logger.error(f"Decryption error: {str(e)}")
            return None

# Create instance for easy access
security_manager = SecurityManager()

# Export functions for easy module access
def is_admin():
    # Check if current process has admin privileges
    return security_manager.is_admin()

def generate_token(length=32):
    # Generate a secure random token
    return security_manager.generate_token(length)

def hash_password(password, salt=None):
    # Hash a password with optional salt
    return security_manager.hash_password(password, salt)

def verify_password(password, stored_hash, salt):
    # Verify a password against stored hash and salt
    return security_manager.verify_password(password, stored_hash, salt)

def encrypt_data(data, key=None):
    # Encrypt data with optional key
    return security_manager.encrypt_data(data, key)

def decrypt_data(encrypted_data, key):
    # Decrypt data with the provided key
    return security_manager.decrypt_data(encrypted_data, key)
