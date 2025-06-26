import os
import sys
import json
import logging
import hashlib
import secrets
import base64
import xml.etree.ElementTree as ET
from datetime import datetime
import subprocess
import winreg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Authentication")

# Get the server manager directory from registry
def get_server_manager_dir():
    try:
        registry_path = r"Software\SkywereIndustries\Servermanager"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Failed to get server manager directory from registry: {e}")
        return None

# Get config directory
server_manager_dir = get_server_manager_dir()
config_dir = os.path.join(server_manager_dir, "config") if server_manager_dir else None
users_file = os.path.join(config_dir, "users.xml") if config_dir else None

# Create necessary directories
if config_dir and not os.path.exists(config_dir):
    os.makedirs(config_dir, exist_ok=True)

def generate_salt(length=16):
    """Generate a random salt for password hashing"""
    return secrets.token_hex(length)

def hash_password(password, salt):
    """Hash a password with the given salt using SHA256"""
    password_bytes = password.encode('utf-8')
    salt_bytes = salt.encode('utf-8')
    hash_obj = hashlib.sha256(password_bytes + salt_bytes)
    return base64.b64encode(hash_obj.digest()).decode('utf-8')

def create_user(username, password, is_admin=False):
    """Create a new user"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return False
    
    try:
        # Load existing users
        users = []
        if os.path.exists(users_file):
            try:
                # Parse the XML file
                tree = ET.parse(users_file)
                root = tree.getroot()
                for user_elem in root.findall('.//Obj'):
                    # Extract user data from XML
                    user_data = {}
                    for prop in user_elem.findall('.//MS/S'):
                        name = prop.get('N')
                        if name:
                            user_data[name] = prop.text
                    users.append(user_data)
            except Exception as e:
                logger.error(f"Error parsing users file: {e}")
                # If parsing fails, assume empty users list
        
        # Check if user already exists
        for user in users:
            if user.get('Username') == username:
                logger.error(f"User {username} already exists")
                return False
        
        # Generate salt and hash the password
        salt = generate_salt()
        hashed_password = hash_password(password, salt)
        
        # Create the new user object
        new_user = {
            'Username': username,
            'PasswordHash': hashed_password,
            'Salt': salt,
            'IsAdmin': str(is_admin).lower(),
            'Created': datetime.now().isoformat(),
            'LastModified': datetime.now().isoformat()
        }
        
        users.append(new_user)
        
        # Create XML structure
        root = ET.Element('Objs')
        root.set('Version', '1.1.0.1')
        root.set('xmlns', 'http://schemas.microsoft.com/powershell/2004/04')
        
        for user in users:
            obj = ET.SubElement(root, 'Obj')
            obj.set('RefId', str(users.index(user)))
            
            ms = ET.SubElement(obj, 'MS')
            
            for key, value in user.items():
                s = ET.SubElement(ms, 'S')
                s.set('N', key)
                s.text = str(value)
        
        # Write to file
        tree = ET.ElementTree(root)
        tree.write(users_file, encoding='utf-8', xml_declaration=True)
        
        logger.info(f"User {username} created successfully")
        return True
    
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return False

def authenticate_user(username, password):
    """Authenticate a user with the given credentials"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        logger.error(f"config_dir: {config_dir}, users_file: {users_file}")
        return False
    
    try:
        logger.debug(f"Attempting to authenticate user: {username}")
        logger.debug(f"Using users file: {users_file}")
        
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        
        logger.debug(f"XML file parsed successfully, root element: {root.tag}")
        
        user_found = False
        for user_elem in root.findall('.//Obj'):
            user_data = {}
            for prop in user_elem.findall('.//MS/S'):
                name = prop.get('N')
                if name:
                    user_data[name] = prop.text
            
            if user_data.get('Username') == username:
                user_found = True
                logger.debug(f"User {username} found in XML file")
                
                # Found the user, verify password
                stored_hash = user_data.get('PasswordHash')
                salt = user_data.get('Salt')
                
                if not stored_hash or not salt:
                    logger.error(f"Incomplete user data for {username}: hash={bool(stored_hash)}, salt={bool(salt)}")
                    return False
                
                # Hash the provided password with the stored salt
                calculated_hash = hash_password(password, salt)
                
                logger.debug(f"Password verification for {username}:")
                logger.debug(f"  Stored hash: {stored_hash[:20]}...")
                logger.debug(f"  Calculated hash: {calculated_hash[:20]}...")
                logger.debug(f"  Salt: {salt[:10]}...")
                
                # Compare the hashes
                if calculated_hash == stored_hash:
                    logger.info(f"User {username} authenticated successfully")
                    return True
                else:
                    logger.warning(f"Invalid password for user {username}")
                    return False
        
        if not user_found:
            logger.warning(f"User {username} not found in XML file")
            
            # List all users for debugging
            logger.debug("Available users in XML file:")
            for user_elem in root.findall('.//Obj'):
                user_data = {}
                for prop in user_elem.findall('.//MS/S'):
                    name = prop.get('N')
                    if name == 'Username':
                        logger.debug(f"  Found user: {prop.text}")
                        break
        
        return False
    
    except Exception as e:
        logger.error(f"Error authenticating user: {e}")
        import traceback
        logger.error(f"Authentication traceback: {traceback.format_exc()}")
        return False

def is_admin_user(username):
    """Check if a user has admin privileges"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return False
    
    if not os.path.exists(users_file):
        logger.error("Users file not found")
        return False
    
    try:
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        
        for user_elem in root.findall('.//Obj'):
            user_data = {}
            for prop in user_elem.findall('.//MS/S'):
                name = prop.get('N')
                if name:
                    user_data[name] = prop.text
            
            if user_data.get('Username') == username:
                # Check if user is admin
                is_admin = user_data.get('IsAdmin', 'false').lower()
                return is_admin == 'true'
        
        return False
    
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

def get_all_users():
    """Get a list of all users"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return []
    
    if not os.path.exists(users_file):
        logger.error("Users file not found")
        return []
    
    try:
        users = []
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        
        for user_elem in root.findall('.//Obj'):
            user_data = {}
            for prop in user_elem.findall('.//MS/S'):
                name = prop.get('N')
                if name:
                    user_data[name] = prop.text
            
            # Clean up the user data for display
            display_user = {
                'Username': user_data.get('Username'),
                'IsAdmin': user_data.get('IsAdmin', 'false').lower() == 'true',
                'Created': user_data.get('Created'),
                'LastModified': user_data.get('LastModified')
            }
            users.append(display_user)
        
        return users
    
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return []

def update_user_password(username, new_password):
    """Update a user's password"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return False
    
    if not os.path.exists(users_file):
        logger.error("Users file not found")
        return False
    
    try:
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        user_found = False
        
        for user_elem in root.findall('.//Obj'):
            user_data = {}
            props = user_elem.findall('.//MS/S')
            
            # Get the username from properties
            username_prop = None
            for prop in props:
                if prop.get('N') == 'Username':
                    username_prop = prop
                    user_data['Username'] = prop.text
            
            if user_data.get('Username') == username:
                user_found = True
                # Generate new salt and hash
                salt = generate_salt()
                hashed_password = hash_password(new_password, salt)
                
                # Update properties
                for prop in props:
                    if prop.get('N') == 'PasswordHash':
                        prop.text = hashed_password
                    elif prop.get('N') == 'Salt':
                        prop.text = salt
                    elif prop.get('N') == 'LastModified':
                        prop.text = datetime.now().isoformat()
        
        if not user_found:
            logger.warning(f"User {username} not found")
            return False
        
        # Write back to file
        tree.write(users_file, encoding='utf-8', xml_declaration=True)
        
        logger.info(f"Password updated for user {username}")
        return True
    
    except Exception as e:
        logger.error(f"Error updating password: {e}")
        return False

def delete_user(username):
    """Delete a user"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return False
    
    if not os.path.exists(users_file):
        logger.error("Users file not found")
        return False
    
    try:
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        user_found = False
        user_elem_to_remove = None
        
        for user_elem in root.findall('.//Obj'):
            for prop in user_elem.findall('.//MS/S'):
                if prop.get('N') == 'Username' and prop.text == username:
                    user_found = True
                    user_elem_to_remove = user_elem
                    break
            
            if user_found:
                break
        
        if not user_found:
            logger.warning(f"User {username} not found")
            return False
        
        # Remove the user element
        if user_elem_to_remove is not None:
            root.remove(user_elem_to_remove)
        
        # Write back to file
        tree.write(users_file, encoding='utf-8', xml_declaration=True)
        
        logger.info(f"User {username} deleted successfully")
        return True
    
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return False

def set_user_admin_status(username, is_admin):
    """Set or remove admin status for a user"""
    if not config_dir or not users_file:
        logger.error("Configuration directory not initialized")
        return False
    
    if not os.path.exists(users_file):
        logger.error("Users file not found")
        return False
    
    try:
        # Parse the XML file
        tree = ET.parse(users_file)
        root = tree.getroot()
        user_found = False
        
        for user_elem in root.findall('.//Obj'):
            user_data = {}
            props = user_elem.findall('.//MS/S')
            
            # Get the username from properties
            for prop in props:
                if prop.get('N') == 'Username':
                    user_data['Username'] = prop.text
            
            if user_data.get('Username') == username:
                user_found = True
                # Update IsAdmin property
                admin_prop_found = False
                for prop in props:
                    if prop.get('N') == 'IsAdmin':
                        prop.text = str(is_admin).lower()
                        admin_prop_found = True
                    elif prop.get('N') == 'LastModified':
                        prop.text = datetime.now().isoformat()
                
                # If IsAdmin property doesn't exist, create it
                if not admin_prop_found:
                    ms_elem = user_elem.find('.//MS')
                    if ms_elem is not None:
                        admin_prop = ET.SubElement(ms_elem, 'S')
                        admin_prop.set('N', 'IsAdmin')
                        admin_prop.text = str(is_admin).lower()
        
        if not user_found:
            logger.warning(f"User {username} not found")
            return False
        
        # Write back to file
        tree.write(users_file, encoding='utf-8', xml_declaration=True)
        
        logger.info(f"Admin status for user {username} set to {is_admin}")
        return True
    
    except Exception as e:
        logger.error(f"Error setting admin status: {e}")
        return False