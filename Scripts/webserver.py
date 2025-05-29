import os
import sys
import json
import logging
import winreg
import argparse
import datetime
import threading
import time
import uuid
import hashlib
from pathlib import Path

# Import dashboard tracker
try:
    from services.dashboard_tracker import tracker
except ImportError as e:
    logger.error(f"Failed to import dashboard tracker: {e}")
    tracker = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("WebServer")

# Import Flask for web server - with better error handling
try:
    from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
    logger.info("Flask imported successfully")
    try:
        from flask_cors import CORS
        logger.info("Flask-CORS imported successfully")
    except ImportError:
        logger.error("Flask-CORS not installed. Running without CORS support.")
        # Define a dummy CORS class that does nothing
        class CORS:
            def __init__(self, app):
                logger.warning("Using dummy CORS implementation")
                pass
except ImportError as e:
    logger.critical(f"Flask not installed: {e}. Please run setup.py or install manually.")
    logger.critical("You can install required packages with: pip install flask flask-cors")
    sys.exit(1)

# Get server manager directory from registry to find modules
def get_server_manager_dir():
    try:
        registry_path = r"Software\SkywereIndustries\Servermanager"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Failed to get server manager directory from registry: {e}")
        # Use fallback approach based on script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_manager_dir = os.path.dirname(script_dir)
        logger.warning(f"Using fallback server manager directory: {server_manager_dir}")
        return server_manager_dir

# Authentication system
class Authentication:
    def __init__(self, config_path):
        self.config_path = config_path
        self.users = self._load_users()
        self.tokens = {}  # Store active tokens
        
    def _load_users(self):
        try:
            users_file = os.path.join(self.config_path, "users.json")
            if not os.path.exists(users_file):
                # Create default admin user if file doesn't exist
                default_users = {
                    "admin": {
                        "password": self._hash_password("admin"),
                        "isAdmin": True
                    }
                }
                os.makedirs(os.path.dirname(users_file), exist_ok=True)
                with open(users_file, 'w') as f:
                    json.dump(default_users, f, indent=4)
                logger.info("Created default users file with admin user")
                return default_users
            
            with open(users_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            # Return a default admin user if there's an error
            return {"admin": {"password": self._hash_password("admin"), "isAdmin": True}}
    
    def _save_users(self):
        try:
            users_file = os.path.join(self.config_path, "users.json")
            os.makedirs(os.path.dirname(users_file), exist_ok=True)
            with open(users_file, 'w') as f:
                json.dump(self.users, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Failed to save users: {e}")
            return False
    
    def _hash_password(self, password):
        # Simple password hashing - in production, use more secure methods
        return hashlib.sha256(password.encode()).hexdigest()
    
    def authenticate(self, username, password):
        if username in self.users:
            stored_hash = self.users[username]["password"]
            if self._hash_password(password) == stored_hash:
                # Generate token
                token = str(uuid.uuid4())
                self.tokens[token] = {
                    "username": username,
                    "created": datetime.datetime.now().isoformat(),
                    "expires": (datetime.datetime.now() + datetime.timedelta(hours=8)).isoformat()
                }
                return {"token": token, "username": username, "isAdmin": self.users[username].get("isAdmin", False)}
        return None
    
    def verify_token(self, token):
        if token in self.tokens:
            token_data = self.tokens[token]
            expires = datetime.datetime.fromisoformat(token_data["expires"])
            if datetime.datetime.now() < expires:
                return token_data
        return None
    
    def is_admin(self, username):
        if username in self.users:
            return self.users[username].get("isAdmin", False)
        return False
    
    def get_all_users(self):
        user_list = []
        for username, data in self.users.items():
            user_list.append({
                "username": username,
                "isAdmin": data.get("isAdmin", False)
            })
        return user_list
    
    def add_user(self, username, password, is_admin=False):
        if username in self.users:
            return False
        
        self.users[username] = {
            "password": self._hash_password(password),
            "isAdmin": is_admin
        }
        self._save_users()
        return True
    
    def delete_user(self, username):
        if username in self.users:
            if username == "admin":
                return False  # Prevent deleting the main admin
            
            del self.users[username]
            self._save_users()
            return True
        return False
    
    def change_password(self, username, new_password):
        if username in self.users:
            self.users[username]["password"] = self._hash_password(new_password)
            self._save_users()
            return True
        return False

# Server Manager operations
class ServerManager:
    def __init__(self, servers_path):
        self.servers_path = servers_path
        
    def get_all_servers(self):
        try:
            # For demo purposes, return simulated servers
            return [
                {
                    "id": "server1",
                    "name": "Production Server",
                    "status": "running",
                    "type": "windows",
                    "cpu": 15,
                    "memory": 45,
                    "disk": 67
                },
                {
                    "id": "server2",
                    "name": "Development Server",
                    "status": "stopped",
                    "type": "linux",
                    "cpu": 0,
                    "memory": 0,
                    "disk": 23
                },
                {
                    "id": "server3",
                    "name": "Test Server",
                    "status": "running",
                    "type": "windows",
                    "cpu": 5,
                    "memory": 30,
                    "disk": 45
                }
            ]
        except Exception as e:
            logger.error(f"Error getting servers: {e}")
            return []
    
    def get_server(self, server_id):
        servers = self.get_all_servers()
        for server in servers:
            if server["id"] == server_id:
                return server
        return None
    
    def start_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            # Simulate starting server
            server["status"] = "running"
            return True
        return False
    
    def stop_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            # Simulate stopping server
            server["status"] = "stopped"
            return True
        return False
    
    def restart_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            # Simulate restarting server
            return True
        return False

class ServerManagerWebServer:
    """Web server for Server Manager"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = get_server_manager_dir()  # Use the already determined directory
        self.web_port = 8080
        self.debug_mode = False
        self.paths = {}
        self.host_type = "Unknown"  # New: HostType ("Host" or "Subhost")
        self.host_address = None    # New: HostAddress (for subhost, if present)
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Web Server')
        parser.add_argument('--port', type=int, help='Web server port')
        parser.add_argument('--debug', action='store_true', help='Enable debug mode')
        args = parser.parse_args()
        
        # Set debug mode if specified
        if args.debug:
            self.debug_mode = True
            logger.setLevel(logging.DEBUG)
        
        # Set port if specified
        if args.port:
            self.web_port = args.port
        
        # Initialize paths
        self.initialize_from_registry()
        
        # Initialize authentication and server manager
        self.auth = Authentication(self.paths["config"])
        self.server_manager = ServerManager(self.paths["servers"])
        
        # Create Flask app
        self.app = Flask(
            __name__,
            static_folder=os.path.join(self.server_manager_dir, "www")
        )
        
        # Enable CORS for API
        CORS(self.app)
        
        # Set up Flask secret key
        self.app.secret_key = os.urandom(24)
        
        # Set up routes
        self.setup_routes()
        
        # Write PID file
        self.write_pid_file()
        
        # Start dashboard tracker in a background thread
        self.tracker = tracker
        if self.tracker:
            self.tracker.start_auto_refresh()
            logger.info("Dashboard tracker started in background thread")
        else:
            logger.warning("Dashboard tracker not available")

        # Start subhost communication thread (placeholder)
        self.subhost_thread = threading.Thread(target=self.subhost_communication_loop, daemon=True)
        self.subhost_thread.start()
        logger.info("Subhost communication thread started")

    def subhost_communication_loop(self):
        """Placeholder: Communicate with subhosts for sending/receiving info"""
        while True:
            # TODO: Implement subhost communication logic here
            # Example: poll subhosts, send/receive data, etc.
            time.sleep(10)

    def initialize_from_registry(self):
        """Initialize paths and settings from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            
            # Get web port from registry if available
            try:
                self.web_port = int(winreg.QueryValueEx(key, "WebPort")[0])
            except:
                pass
            
            # Get HostType and HostAddress if present
            try:
                self.host_type = winreg.QueryValueEx(key, "HostType")[0]
            except Exception:
                self.host_type = "Unknown"
            try:
                self.host_address = winreg.QueryValueEx(key, "HostAddress")[0]
            except Exception:
                self.host_address = None
                
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "www": os.path.join(self.server_manager_dir, "www")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
            # Set up file logging
            log_file = os.path.join(self.paths["logs"], "webserver.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.info(f"Initialized from registry. Server Manager directory: {self.server_manager_dir}")
            logger.info(f"Web server port: {self.web_port}")
            logger.info(f"Cluster role: {self.host_type}" + (f", HostAddress: {self.host_address}" if self.host_address else ""))
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize from registry: {str(e)}")
            
            # Use fallback paths based on script location
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.server_manager_dir = os.path.dirname(script_dir)
            
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": script_dir,
                "www": os.path.join(self.server_manager_dir, "www")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Set up file logging in fallback location
            log_file = os.path.join(self.paths["logs"], "webserver.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.warning(f"Using fallback paths. Server Manager directory: {server_manager_dir}")
            return False
    
    def write_pid_file(self):
        """Write process ID to file"""
        try:
            pid_file = os.path.join(self.paths["temp"], "webserver.pid")
            
            # Create PID info dictionary
            pid_info = {
                "ProcessId": os.getpid(),
                "StartTime": datetime.datetime.now().isoformat(),
                "ProcessType": "webserver",
                "Port": self.web_port,
                "Status": "Running"
            }
            
            # Write PID info to file as JSON
            with open(pid_file, 'w') as f:
                json.dump(pid_info, f, indent=4)
                
            logger.debug(f"PID file created: {pid_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to write PID file: {str(e)}")
            return False
    
    def setup_routes(self):
        """Set up Flask routes"""
        app = self.app
        
        # Serve static files from www directory
        @app.route('/', defaults={'path': 'login.html'})
        @app.route('/<path:path>')
        def serve_static(path):
            if path == "" or path == "/":
                path = "login.html"
            
            # Check if file exists in www directory
            www_path = os.path.join(self.paths["www"], path)
            if os.path.exists(www_path) and os.path.isfile(www_path):
                # Determine directory and filename
                directory = os.path.dirname(path)
                filename = os.path.basename(path)
                
                # If directory is empty, serve from root of www
                if not directory:
                    return send_from_directory(self.paths["www"], filename)
                else:
                    # Serve from subdirectory of www
                    return send_from_directory(os.path.join(self.paths["www"], directory), filename)
            
            # Default to 404 if file not found
            return "File not found", 404
        
        # API routes
        
        # Authentication API
        @app.route('/api/auth/login', methods=['POST'])
        def api_login():
            try:
                data = request.json
                username = data.get('username')
                password = data.get('password')
                
                if not username or not password:
                    return jsonify({"error": "Username and password are required"}), 400
                
                auth_result = self.auth.authenticate(username, password)
                if auth_result:
                    return jsonify({
                        "token": auth_result["token"],
                        "username": auth_result["username"],
                        "isAdmin": auth_result["isAdmin"]
                    })
                else:
                    return jsonify({"error": "Invalid username or password"}), 401
            except Exception as e:
                logger.error(f"Login error: {e}")
                return jsonify({"error": "Authentication error"}), 500
        
        @app.route('/api/auth/verify', methods=['GET'])
        def api_verify_auth():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"authenticated": False}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if token_data:
                    return jsonify({
                        "authenticated": True,
                        "username": token_data["username"],
                        "isAdmin": self.auth.is_admin(token_data["username"])
                    })
                else:
                    return jsonify({"authenticated": False}), 401
            except Exception as e:
                logger.error(f"Auth verification error: {e}")
                return jsonify({"error": "Authentication verification error"}), 500
        
        @app.route('/api/verify-admin', methods=['GET'])
        def api_verify_admin():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"isAdmin": False}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if token_data:
                    is_admin = self.auth.is_admin(token_data["username"])
                    return jsonify({"isAdmin": is_admin})
                else:
                    return jsonify({"isAdmin": False}), 401
            except Exception as e:
                logger.error(f"Admin verification error: {e}")
                return jsonify({"error": "Admin verification error"}), 500
        
        # Server management API
        @app.route('/api/servers', methods=['GET'])
        def api_get_servers():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                servers = self.server_manager.get_all_servers()
                return jsonify(servers)
            except Exception as e:
                logger.error(f"Get servers error: {e}")
                return jsonify({"error": "Failed to get servers"}), 500
        
        # Server control API
        @app.route('/api/servers/<server_id>/start', methods=['POST'])
        def api_start_server(server_id):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                result = self.server_manager.start_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} started successfully"})
                else:
                    return jsonify({"error": f"Failed to start server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Start server error: {e}")
                return jsonify({"error": "Failed to start server"}), 500
        
        @app.route('/api/servers/<server_id>/stop', methods=['POST'])
        def api_stop_server(server_id):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                result = self.server_manager.stop_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} stopped successfully"})
                else:
                    return jsonify({"error": f"Failed to stop server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Stop server error: {e}")
                return jsonify({"error": "Failed to stop server"}), 500
        
        @app.route('/api/servers/<server_id>/restart', methods=['POST'])
        def api_restart_server(server_id):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                result = self.server_manager.restart_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} restarted successfully"})
                else:
                    return jsonify({"error": f"Failed to restart server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Restart server error: {e}")
                return jsonify({"error": "Failed to restart server"}), 500
        
        # User management API (admin only)
        @app.route('/api/users', methods=['GET'])
        def api_get_users():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                # Check if user is admin
                if not self.auth.is_admin(token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403
                
                users = self.auth.get_all_users()
                return jsonify(users)
            except Exception as e:
                logger.error(f"Get users error: {e}")
                return jsonify({"error": "Failed to get users"}), 500
        
        # System settings API
        @app.route('/api/settings', methods=['GET'])
        def api_get_settings():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                
                token = auth_header.split(' ')[1]
                token_data = self.auth.verify_token(token)
                
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401
                
                # Return some default settings
                return jsonify({
                    "autoUpdate": True,
                    "backupSchedule": 24,
                    "notificationsEnabled": True
                })
            except Exception as e:
                logger.error(f"Get settings error: {e}")
                return jsonify({"error": "Failed to get settings"}), 500
        
        # --- Cluster role API ---
        @app.route('/api/cluster/role', methods=['GET'])
        def api_cluster_role():
            return jsonify({
                "role": self.host_type,
                "hostAddress": self.host_address
            })

        # --- Tracker API ---
        @app.route('/api/tracker/dashboards', methods=['GET'])
        def api_tracker_dashboards():
            if self.tracker:
                return jsonify(self.tracker.get_dashboards())
            return jsonify({"error": "Dashboard tracker not available"}), 500

        @app.route('/api/tracker/servers', methods=['GET', 'POST', 'DELETE', 'PATCH'])
        def api_tracker_servers():
            # Require authentication
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return jsonify({"error": "Authentication required"}), 401
            token = auth_header.split(' ')[1]
            token_data = self.auth.verify_token(token)
            if not token_data:
                return jsonify({"error": "Invalid or expired token"}), 401

            # GET: List all servers
            if request.method == 'GET':
                if self.tracker:
                    return jsonify(self.tracker.get_servers())
                return jsonify({"error": "Dashboard tracker not available"}), 500

            # POST: Add a new server
            if request.method == 'POST':
                data = request.json
                name = data.get("Name")
                config = data
                if not name:
                    return jsonify({"error": "Missing server name"}), 400
                servers_dir = self.paths["servers"]
                os.makedirs(servers_dir, exist_ok=True)
                config_file = os.path.join(servers_dir, f"{name}.json")
                if os.path.exists(config_file):
                    return jsonify({"error": "Server already exists"}), 409
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
                if self.tracker:
                    self.tracker.refresh()
                return jsonify({"success": True})

            # DELETE: Remove a server
            if request.method == 'DELETE':
                data = request.json
                name = data.get("Name")
                if not name:
                    return jsonify({"error": "Missing server name"}), 400
                servers_dir = self.paths["servers"]
                config_file = os.path.join(servers_dir, f"{name}.json")
                if not os.path.exists(config_file):
                    return jsonify({"error": "Server not found"}), 404
                os.remove(config_file)
                if self.tracker:
                    self.tracker.refresh()
                return jsonify({"success": True})

            # PATCH: Update server status (start/stop/restart)
            if request.method == 'PATCH':
                data = request.json
                name = data.get("Name")
                action = data.get("Action")
                if not name or not action:
                    return jsonify({"error": "Missing server name or action"}), 400
                # For demo, just update status in config file
                servers_dir = self.paths["servers"]
                config_file = os.path.join(servers_dir, f"{name}.json")
                if not os.path.exists(config_file):
                    return jsonify({"error": "Server not found"}), 404
                with open(config_file, 'r') as f:
                    config = json.load(f)
                if action == "start":
                    config["Status"] = "Running"
                elif action == "stop":
                    config["Status"] = "Stopped"
                elif action == "restart":
                    config["Status"] = "Restarting"
                else:
                    return jsonify({"error": "Unknown action"}), 400
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
                if self.tracker:
                    self.tracker.refresh()
                return jsonify({"success": True, "status": config["Status"]})

            return jsonify({"error": "Unsupported method"}), 405

        # Error handlers
        @app.errorhandler(404)
        def page_not_found(e):
            return jsonify({"error": "Not found"}), 404
        
        @app.errorhandler(500)
        def internal_server_error(e):
            logger.error(f"Internal server error: {e}")
            return jsonify({"error": "Internal server error"}), 500
    
    def run(self):
        """Run the web server"""
        try:
            logger.info(f"Starting web server on port {self.web_port}")
            
            # Instead of running in a thread, run directly in the main thread
            # This provides better error reporting and stability
            self.app.run(
                host='0.0.0.0',  # Bind to all interfaces
                port=self.web_port,
                debug=self.debug_mode,
                threaded=True,
                use_reloader=False  # Disable reloader to prevent duplicate processes
            )
                
        except KeyboardInterrupt:
            logger.info("Web server stopping due to keyboard interrupt")
        except Exception as e:
            logger.error(f"Web server error: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        
        return True

def is_admin():
    """Check if running with admin privileges"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def main():
    """Main function"""
    try:
        # Check if admin (informational only)
        if not is_admin():
            logger.warning("Not running with administrator privileges. Some features may be limited.")
        
        # Create and run web server
        web_server = ServerManagerWebServer()
        return web_server.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return False

if __name__ == "__main__":
    main()
