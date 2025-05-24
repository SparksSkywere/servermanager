import os
import sys
import json
import logging
import subprocess
import winreg
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ServerManager")

class ServerManager:
    """Main class for server management"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.config = {}
        self.servers = {}
        
        # Initialize from registry
        self.initialize_from_registry()
        
    def initialize_from_registry(self):
        """Initialize paths from registry settings"""
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
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "modules": os.path.join(self.server_manager_dir, "modules")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Load configuration
            self.load_config()
            
            # Load server list
            self.load_servers()
                
            logger.info(f"Server manager initialized from registry")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize server manager from registry: {str(e)}")
            return False
            
    def load_config(self):
        """Load configuration from file"""
        try:
            config_file = os.path.join(self.paths["config"], "config.json")
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    self.config = json.load(f)
                logger.info(f"Configuration loaded from {config_file}")
            else:
                # Create default configuration
                self.config = {
                    "version": "1.0.0",
                    "web_port": 8080,
                    "log_level": "INFO",
                    "steam_cmd_path": os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD"),
                    "auto_update_check_interval": 3600,  # seconds
                    "max_log_files": 10,
                    "max_log_size": 10 * 1024 * 1024  # 10 MB
                }
                
                # Save default configuration
                with open(config_file, 'w') as f:
                    json.dump(self.config, f, indent=4)
                    
                logger.info(f"Default configuration created at {config_file}")
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
            
    def load_servers(self):
        """Load list of servers from config directory"""
        try:
            servers_dir = self.paths["servers"]
            
            if not os.path.exists(servers_dir):
                os.makedirs(servers_dir, exist_ok=True)
                logger.info(f"Created servers directory: {servers_dir}")
                return
                
            for file in os.listdir(servers_dir):
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(servers_dir, file), 'r') as f:
                            server_config = json.load(f)
                            
                        server_name = server_config.get("Name")
                        if server_name:
                            self.servers[server_name] = server_config
                    except Exception as e:
                        logger.error(f"Error loading server config {file}: {str(e)}")
                        
            logger.info(f"Loaded {len(self.servers)} server configurations")
        except Exception as e:
            logger.error(f"Error loading servers: {str(e)}")
            
    def save_config(self):
        """Save configuration to file"""
        try:
            config_file = os.path.join(self.paths["config"], "config.json")
            
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
                
            logger.info(f"Configuration saved to {config_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving configuration: {str(e)}")
            return False
            
    def get_server_config(self, server_name):
        """Get configuration for a specific server"""
        if server_name in self.servers:
            return self.servers[server_name]
            
        # Try to load from file if not in memory
        config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    server_config = json.load(f)
                    
                # Cache the config
                self.servers[server_name] = server_config
                return server_config
            except Exception as e:
                logger.error(f"Error loading server config {server_name}: {str(e)}")
                
        return None
        
    def save_server_config(self, server_name, config):
        """Save configuration for a specific server"""
        try:
            config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
                
            # Update cache
            self.servers[server_name] = config
            
            logger.info(f"Server configuration saved for {server_name}")
            return True
        except Exception as e:
            logger.error(f"Error saving server config {server_name}: {str(e)}")
            return False
            
    def get_server_list(self):
        """Get list of all configured servers"""
        return list(self.servers.values())
            
    def start_server(self, server_name):
        """Start a server using the appropriate script"""
        try:
            script_path = os.path.join(self.paths["scripts"], "start_server.py")
            
            if not os.path.exists(script_path):
                logger.error(f"Start server script not found: {script_path}")
                return False
                
            result = subprocess.run([sys.executable, script_path, server_name], 
                                   capture_output=True, text=True)
                                   
            if result.returncode != 0:
                logger.error(f"Error starting server {server_name}: {result.stderr}")
                return False
                
            logger.info(f"Server {server_name} started successfully")
            return True
        except Exception as e:
            logger.error(f"Error starting server {server_name}: {str(e)}")
            return False
            
    def stop_server(self, server_name, force=False):
        """Stop a server using the appropriate script"""
        try:
            script_path = os.path.join(self.paths["scripts"], "stop_server.py")
            
            if not os.path.exists(script_path):
                logger.error(f"Stop server script not found: {script_path}")
                return False
                
            cmd = [sys.executable, script_path, server_name]
            if force:
                cmd.append("--force")
                
            result = subprocess.run(cmd, capture_output=True, text=True)
                                   
            if result.returncode != 0:
                logger.error(f"Error stopping server {server_name}: {result.stderr}")
                return False
                
            logger.info(f"Server {server_name} stopped successfully")
            return True
        except Exception as e:
            logger.error(f"Error stopping server {server_name}: {str(e)}")
            return False

# Create singleton instance
server_manager = ServerManager()
