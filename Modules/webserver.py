# Flask web server for Server Manager with API endpoints, authentication, analytics, and cluster support
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
import bcrypt
import win32security
import win32api
import traceback
import ctypes
from pathlib import Path
from waitress import serve

# Try to import psutil with fallback
try:
    import psutil
except ImportError:
    psutil = None
    
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("WebServer")
except Exception:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger("WebServer")

# Import dashboard tracker with fallback
def get_server_manager_dir():
    try:
        # Add project root to sys.path for imports
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
        winreg.CloseKey(key)
        return server_manager_dir
    except Exception as e:
        logger.error(f"Failed to get server manager directory from registry: {e}")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_manager_dir = os.path.dirname(script_dir)
        logger.warning(f"Using fallback server manager directory: {server_manager_dir}")
        return server_manager_dir

# Create a dummy dashboard tracker class for fallback
class DummyDashboardTracker:
    def start_auto_refresh(self):
        pass
    def stop_auto_refresh(self):
        pass
    def get_dashboards(self):
        return []
    def get_servers(self):
        return []
    def refresh(self):
        pass

tracker = None
try:
    # Try to import from services directory
    server_manager_dir = get_server_manager_dir()
    services_path = os.path.join(server_manager_dir, "services")
    if os.path.exists(services_path):
        sys.path.insert(0, server_manager_dir)
    from services.dashboard_tracker import tracker
    logger.info("Dashboard tracker imported successfully")
except ImportError as e:
    logger.warning(f"Dashboard tracker not available: {e}")
    tracker = DummyDashboardTracker()
except NameError:
    # Handle case where get_server_manager_dir is not yet defined
    tracker = DummyDashboardTracker()
    logger.warning("Dashboard tracker not available - using dummy implementation")

# Import Flask dependencies - removed duplicate imports and handled CORS fallback
try:
    logger.info("Flask imported successfully")
    # CORS is already imported at the top
    logger.info("Flask-CORS imported successfully")
except ImportError:
    logger.warning("Flask-CORS not installed. Running without CORS support.")
    # Create a dummy CORS class if import fails
    class DummyCORS:
        def __init__(self, app):
            logger.warning("Using dummy CORS implementation")
            pass
    CORS = DummyCORS

# Import SQL modules
try:
    # Add server manager directory to Python path for module imports
    server_manager_dir = get_server_manager_dir()
    if server_manager_dir not in sys.path:
        sys.path.insert(0, server_manager_dir)
    
    from Modules.Database.user_database import get_user_engine, ensure_root_admin, build_user_db_url, get_user_sql_config_from_registry
    from Modules.user_management import User, UserManager
    # Import server manager
    from Modules.server_manager import ServerManager as CoreServerManager
    logger.info("SQL modules imported successfully")
except ImportError as e:
    logger.error(f"Failed to import SQL modules: {e}")
    logger.error(f"SQL import traceback:\n{traceback.format_exc()}")
    get_user_engine = None
    ensure_root_admin = None
    build_user_db_url = None
    get_user_sql_config_from_registry = None
    User = None
    UserManager = None
    CoreServerManager = None

# Legacy Authentication system (kept for fallback compatibility)
class Authentication:
    def __init__(self, config_path):
        self.config_path = config_path
        self.users = self._load_users()
        self.tokens = {}

    def _hash_password(self, password):
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def _check_password(self, password, hashed):
        return bcrypt.checkpw(password.encode(), hashed.encode())

    def _load_users(self):
        try:
            users_file = os.path.join(self.config_path, "users.json")
            if not os.path.exists(users_file):
                logger.warning("Users file not found. Creating empty users file.")
                # Create empty users file with proper permissions
                try:
                    os.makedirs(self.config_path, exist_ok=True)
                    with open(users_file, 'w') as f:
                        json.dump({}, f)
                    logger.info(f"Created empty users file: {users_file}")
                except Exception as e:
                    logger.error(f"Failed to create users file: {e}")
                return {}
            
            # Try to read the users file with error handling for permissions
            try:
                with open(users_file, 'r') as f:
                    return json.load(f)
            except PermissionError:
                logger.error(f"Permission denied accessing users file: {users_file}")
                logger.warning("Using in-memory user storage due to file permission issues")
                return {}
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in users file: {users_file}")
                return {}
        except Exception as e:
            logger.error(f"Failed to load users: {e}")
            return {}

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

    def authenticate(self, username, password):
        if username in self.users:
            stored_hash = self.users[username]["password"]
            if self._check_password(password, stored_hash):
                token = str(uuid.uuid4())
                self.tokens[token] = {
                    "username": username,
                    "created": datetime.datetime.now().isoformat(),
                    "expires": (datetime.datetime.now() + datetime.timedelta(hours=8)).isoformat()
                }
                return {"token": token, "username": username}
        return None

    def verify_token(self, token):
        if token in self.tokens:
            token_data = self.tokens[token]
            expires = datetime.datetime.fromisoformat(token_data["expires"])
            if datetime.datetime.now() < expires:
                return token_data
            del self.tokens[token]
        return None

    def is_admin(self, username):
        return self.users.get(username, {}).get("isAdmin", False)

    def get_all_users(self):
        return [{"username": u, "isAdmin": d.get("isAdmin", False)} for u, d in self.users.items()]

    def add_user(self, username, password, is_admin=False):
        if username in self.users:
            return False
        if not self._validate_password(password):
            logger.error(f"Invalid password for user {username}: Must be at least 8 characters")
            return False
        self.users[username] = {
            "password": self._hash_password(password),
            "isAdmin": is_admin
        }
        return self._save_users()

    def delete_user(self, username):
        if username in self.users and username != "admin":
            del self.users[username]
            return self._save_users()
        return False

    def change_password(self, username, new_password):
        if username in self.users:
            if not self._validate_password(new_password):
                logger.error(f"Invalid new password for user {username}: Must be at least 8 characters")
                return False
            self.users[username]["password"] = self._hash_password(new_password)
            return self._save_users()
        return False

    def _validate_password(self, password):
        return len(password) >= 8

# SQL Authentication system
class SQLAuthentication:
    def __init__(self, engine):
        self.engine = engine
        if UserManager is not None:
            self.user_manager = UserManager(engine)
        else:
            self.user_manager = None
        self.tokens = {}

    def _hash_password(self, password):
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def _check_password(self, password, hashed):
        return bcrypt.checkpw(password.encode(), hashed.encode())

    def authenticate(self, username, password):
        if self.user_manager is None:
            return None
        user = self.user_manager.get_user(username)
        if not user or not getattr(user, 'is_active', True):
            return None
        if self._check_password(password, user.password):
            token = str(uuid.uuid4())
            self.tokens[token] = {
                "username": username,
                "created": datetime.datetime.now().isoformat(),
                "expires": (datetime.datetime.now() + datetime.timedelta(hours=8)).isoformat()
            }
            return {"token": token, "username": username}
        return None

    def verify_token(self, token):
        if token in self.tokens:
            token_data = self.tokens[token]
            expires = datetime.datetime.fromisoformat(token_data["expires"])
            if datetime.datetime.now() < expires:
                return token_data
            del self.tokens[token]
        return None

    def is_admin(self, username):
        if self.user_manager is None:
            return False
        user = self.user_manager.get_user(username)
        return getattr(user, "is_admin", False) if user else False

    def get_all_users(self):
        if self.user_manager is None:
            return []
        users = self.user_manager.list_users()
        return [{"username": u.username, "isAdmin": getattr(u, "is_admin", False)} for u in users]

    def add_user(self, username, password, is_admin=False):
        if self.user_manager is None:
            return False
        try:
            if not self._validate_password(password):
                logger.error(f"Invalid password for user {username}: Must be at least 8 characters")
                return False
            self.user_manager.add_user(username, self._hash_password(password), "", is_admin)
            return True
        except Exception as e:
            logger.error(f"Failed to add SQL user: {e}")
            return False

    def delete_user(self, username):
        if self.user_manager is None:
            return False
        try:
            self.user_manager.delete_user(username)
            return True
        except Exception as e:
            logger.error(f"Failed to delete SQL user: {e}")
            return False

    def change_password(self, username, new_password):
        if self.user_manager is None:
            return False
        try:
            if not self._validate_password(new_password):
                logger.error(f"Invalid new password for user {username}: Must be at least 8 characters")
                return False
            self.user_manager.update_user(username, password=self._hash_password(new_password))
            return True
        except Exception as e:
            logger.error(f"Failed to change SQL user password: {e}")
            return False

    def _validate_password(self, password):
        return len(password) >= 8

# Legacy ServerManager class (kept for web API compatibility)
# Note: This could be replaced with imports from Modules.server_manager in the future
class ServerManager:
    def __init__(self, servers_path):
        self.servers_path = servers_path

    def get_all_servers(self):
        try:
            servers = []
            if os.path.exists(self.servers_path):
                for file in os.listdir(self.servers_path):
                    if file.endswith(".json"):
                        try:
                            with open(os.path.join(self.servers_path, file), 'r') as f:
                                server_config = json.load(f)
                            server = {
                                "id": server_config.get("Name", "unknown"),
                                "name": server_config.get("Name", "Unknown Server"),
                                "status": "running" if "ProcessId" in server_config else "stopped",
                                "type": server_config.get("Type", "other").lower(),
                                "cpu": 0,
                                "memory": 0,
                                "disk": 0
                            }
                            if "ProcessId" in server_config and psutil:
                                try:
                                    process = psutil.Process(server_config["ProcessId"])
                                    server["cpu"] = round(process.cpu_percent(interval=0.1), 1)
                                    server["memory"] = round(process.memory_percent(), 1)
                                except Exception:
                                    pass
                            servers.append(server)
                        except Exception as e:
                            logger.error(f"Error reading server config {file}: {e}")
            return servers
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
            server["status"] = "running"
            logger.info(f"Started server: {server_id}")
            return True
        return False

    def stop_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            server["status"] = "stopped"
            logger.info(f"Stopped server: {server_id}")
            return True
        return False

    def restart_server(self, server_id):
        server = self.get_server(server_id)
        if server:
            logger.info(f"Restarted server: {server_id}")
            return True
        return False

# Import common module
from Modules.common import ServerManagerModule

class ServerManagerWebServer(ServerManagerModule):
    def __init__(self):
        logger.info("Initializing ServerManagerWebServer...")
        try:
            super().__init__("ServerManagerWebServer")
            logger.info("Base ServerManagerModule initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize base ServerManagerModule: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Initialize minimal attributes to prevent AttributeError
            self.module_name = "ServerManagerWebServer"
            try:
                from Modules.server_logging import get_component_logger
                self.logger = get_component_logger("ServerManagerWebServer")
            except Exception:
                self.logger = logging.getLogger("ServerManagerWebServer")
        
        # Initialize all attributes to ensure they exist
        self.auth = None
        self.sql_auth = None  
        self.engine = None
        self.server_manager = None
        self.app = None
        self.limiter = None
        self.tracker = None
        self.subhost_thread = None
        self.auth_tokens = {}  # Initialize auth_tokens attribute
        
        # Read from environment first, fall back to inherited web_port property or default
        try:
            base_port = self.web_port if hasattr(self, 'web_port') else 8080
            logger.info(f"Base port from property: {base_port}")
        except Exception as e:
            logger.warning(f"Could not get web_port property, using default: {e}")
            base_port = 8080
            
        self._web_port = int(os.getenv("WEB_PORT", str(base_port)))
        logger.info(f"Web port set to: {self._web_port}")
        
        # Cluster API port (separate from web port for security)
        self._cluster_port = int(os.getenv("CLUSTER_PORT", "5001"))
        logger.info(f"Cluster API port set to: {self._cluster_port}")
        # Read host type and address from environment
        self.host_type = os.getenv("HOST_TYPE", "Unknown")
        self.host_address = os.getenv("HOST_ADDRESS", None)
        self.sql_available = False

        parser = argparse.ArgumentParser(description='Server Manager Web Server')
        parser.add_argument('--port', type=int, help='Web server port')
        args = parser.parse_args()

        if args.port:
            self._web_port = args.port

        # Override host type and address from environment if available
        if os.getenv("SERVERMANAGER_DIR"):
            logger.info("Using configuration from environment variables")
        else:
            # Try to read host type from registry for additional info
            try:
                from Modules.common import REGISTRY_ROOT
                key = winreg.OpenKey(REGISTRY_ROOT, self.registry_path)
                try:
                    self.host_type = winreg.QueryValueEx(key, "HostType")[0]
                except:
                    pass
                try:
                    self.host_address = winreg.QueryValueEx(key, "HostAddress")[0]
                except:
                    pass
                winreg.CloseKey(key)
                logger.info("Using configuration from registry")
            except:
                logger.info("Using default configuration")

        logger.info(f"Initialized webserver. Server Manager directory: {self.server_manager_dir}")
        logger.info(f"Web server port: {self.web_port}")
        logger.info(f"Cluster role: {self.host_type}" + (f", HostAddress: {self.host_address}" if self.host_address else ""))

        # Initialize Flask app first
        self.app = Flask(
            __name__,
            static_folder=os.path.join(self.server_manager_dir or "", "www")
        )
        CORS(self.app)
        self.app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
        
        # Initialize rate limiter
        try:
            self.limiter = Limiter(
                app=self.app, 
                key_func=get_remote_address, 
                default_limits=["200 per day", "50 per hour"]
            )
        except Exception as e:
            logger.error(f"Failed to initialize rate limiter: {e}")
            self.limiter = None

        self.check_sql_availability()

        # Initialize authentication
        try:
            if self.sql_available and get_user_engine and UserManager:
                self.engine = get_user_engine()
                self.sql_auth = SQLAuthentication(self.engine)
                self.auth = self.sql_auth  # Set auth to point to sql_auth for consistent interface
                logger.info("SQL authentication system initialized successfully")
            else:
                self.auth = Authentication(self.paths["config"])
                self.sql_auth = None
                logger.warning("SQL not available, using file-based authentication")
        except Exception as e:
            logger.error(f"Failed to initialize authentication: {e}")
            self.auth = self.create_fallback_auth()
            self.sql_auth = None

        # Initialize cluster database and host status
        try:
            from Modules.Database.cluster_database import ClusterDatabase
            self.cluster_db = ClusterDatabase()
            
            # Initialize host status as online with dashboard active
            self.cluster_db.update_host_status(
                status="online",
                dashboard_active=True,
                maintenance_mode=False,
                status_message="Web server initialized"
            )
            
            # Start host heartbeat thread
            self.start_host_heartbeat()
            
            logger.info("Cluster database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize cluster database: {e}")
            self.cluster_db = None

        # Initialize server manager
        try:
            self.server_manager = ServerManager(self.paths["servers"])
            logger.info("Server manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize server manager: {e}")
            self.server_manager = None

        # Initialize analytics
        try:
            from Modules.analytics import AnalyticsCollector
            self.analytics = AnalyticsCollector()
            self.analytics.start_collection()
            logger.info("Analytics module initialized and started successfully")
        except Exception as e:
            logger.error(f"Failed to initialize analytics module: {e}")
            self.analytics = None

        # Setup routes after all components are initialized
        self.setup_routes()
        self.write_pid_file("webserver", os.getpid())

        # Initialize tracker
        self.tracker = tracker
        if self.tracker:
            try:
                self.tracker.start_auto_refresh()
                logger.info("Dashboard tracker started in background thread")
            except Exception as e:
                logger.warning(f"Failed to start dashboard tracker: {e}")
                self.tracker = DummyDashboardTracker()

        # Start subhost communication thread
        self.subhost_thread = threading.Thread(target=self.subhost_communication_loop, daemon=True)
        self.subhost_thread.start()
        logger.info("Subhost communication thread started")

    @property
    def web_port(self):
        # Get the web server port
        return self._web_port
    
    @property
    def cluster_port(self):
        # Get the cluster API port
        return getattr(self, '_cluster_port', 5001)

    def check_sql_availability(self):
        try:
            if get_user_engine and get_user_sql_config_from_registry and build_user_db_url:
                sql_conf = get_user_sql_config_from_registry()
                logger.info(f"SQL config from registry: {sql_conf}")
                db_url = build_user_db_url(sql_conf)
                logger.info(f"SQLAlchemy DB URL: {db_url}")
                if sql_conf["type"].lower() == "sqlite":
                    db_path = sql_conf["db_path"]
                    if not os.path.isabs(db_path):
                        db_path = os.path.abspath(db_path)
                        logger.info(f"Resolved absolute SQLite DB path: {db_path}")
                    if not os.path.exists(db_path):
                        logger.error(f"SQLite DB file does not exist: {db_path}")
                        raise FileNotFoundError(f"Database file missing: {db_path}")
                    try:
                        with open(db_path, "rb"):
                            logger.info(f"SQLite DB file exists and is readable: {db_path}")
                    except Exception as e:
                        logger.error(f"SQLite DB file exists but is not readable: {e}")
                        raise
                self.engine = get_user_engine()
                from sqlalchemy import text
                with self.engine.connect() as conn:
                    result = conn.execute(text("SELECT 1")).fetchone()
                    logger.info(f"SQL connection test result: {result}")
                self.sql_available = True
                logger.info("SQL connection available")
            else:
                self.sql_available = False
                logger.warning("SQL modules not available")
        except Exception as e:
            logger.warning(f"SQL connection not available: {e}")
            import traceback
            logger.error(f"SQL connection traceback:\n{traceback.format_exc()}")
            self.sql_available = False

    def create_fallback_auth(self):
        class FallbackAuth:
            def __init__(self, config_path):
                self.config_path = config_path
                self.users = {}
                self.tokens = {}
                logger.info("Using fallback authentication system")

            def authenticate(self, username, password):
                return None

            def verify_token(self, token):
                return None

            def is_admin(self, username):
                return False

            def get_all_users(self):
                return []

            def add_user(self, username, password, is_admin=False):
                return False

            def delete_user(self, username):
                return False

            def change_password(self, username, new_password):
                return False

        return FallbackAuth(self.paths["config"])

    def subhost_communication_loop(self):
        while True:
            try:
                time.sleep(10)
            except Exception as e:
                logger.error(f"Error in subhost communication loop: {e}")
                time.sleep(30)





    def setup_routes(self):
        if not self.app:
            logger.error("Flask app not initialized")
            return
            
        app = self.app
        
        # Add root route to serve index.html which handles login redirect
        @app.route('/')
        def index():
            try:
                www_path = os.path.join(self.server_manager_dir or "", "www")
                if not os.path.exists(www_path):
                    logger.error(f"WWW directory not found: {www_path}")
                    from flask import redirect
                    return redirect('/login.html')
                
                index_file = os.path.join(www_path, "index.html")
                if os.path.exists(index_file):
                    return send_from_directory(www_path, "index.html")
                else:
                    logger.debug("index.html not found, redirecting to login.html")
                    from flask import redirect
                    return redirect('/login.html')
            except Exception as e:
                logger.error(f"Error serving index page: {e}")
                from flask import redirect
                return redirect('/login.html')
        
        # Register cluster API blueprint on main server
        try:
            # Import the cluster API
            import sys
            api_path = os.path.join(self.server_manager_dir or "", "api")
            if api_path not in sys.path:
                sys.path.insert(0, api_path)
                
            # Import using absolute path to avoid issues
            cluster_module_path = os.path.join(api_path, "cluster.py")
            if os.path.exists(cluster_module_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("cluster", cluster_module_path)
                if spec and spec.loader:
                    cluster_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(cluster_module)
                    app.register_blueprint(cluster_module.cluster_api)
                    logger.info("Cluster API registered successfully on main server")
                else:
                    logger.warning("Failed to create module spec for cluster API")
            else:
                logger.warning(f"Cluster API module not found at: {cluster_module_path}")
        except Exception as e:
            logger.warning(f"Failed to register cluster API: {e}")
            import traceback
            logger.debug(f"Cluster API registration error: {traceback.format_exc()}")

        # Helper function to handle rate limiting
        def limit_decorator(rate_limit):
            if self.limiter:
                return self.limiter.limit(rate_limit)
            else:
                # Return a no-op decorator if limiter is not available
                def no_op_decorator(func):
                    return func
                return no_op_decorator

        # Helper function to safely call auth methods
        def safe_auth_call(method_name, *args, **kwargs):
            if self.auth and hasattr(self.auth, method_name):
                method = getattr(self.auth, method_name)
                return method(*args, **kwargs)
            return None

        @limit_decorator("5 per minute")
        @app.route('/api/auth/login', methods=['POST'])
        def api_login():
            try:
                data = request.json
                if not data or not isinstance(data, dict):
                    return jsonify({"error": "Invalid request body"}), 400
                username = data.get('username')
                password = data.get('password')
                auth_type = data.get('authType', 'Database')

                if not username or not password or not isinstance(username, str) or not isinstance(password, str):
                    return jsonify({"error": "Username and password must be non-empty strings"}), 400

                logger.info(f"Login attempt for user: {username} with auth type: {auth_type}")

                if auth_type == "Database" and self.sql_available and self.sql_auth:
                    auth_result = self.sql_auth.authenticate(username, password)
                    if auth_result:
                        logger.info(f"Successful SQL login for user: {username}")
                        return jsonify({
                            "token": auth_result["token"],
                            "username": auth_result["username"],
                            "isAdmin": auth_result["isAdmin"]
                        })
                    logger.warning(f"SQL authentication failed for user: {username}")

                # Try SQL authentication if available
                if self.sql_auth:
                    sql_result = safe_auth_call('authenticate', username, password, auth_instance=self.sql_auth)
                    if sql_result:
                        logger.info(f"Successful SQL authentication for user: {username}")
                        return jsonify({
                            "token": sql_result["token"],
                            "username": sql_result["username"],
                            "isAdmin": sql_result["isAdmin"]
                        })

                # Try file-based authentication
                auth_result = safe_auth_call('authenticate', username, password)
                if auth_result:
                    logger.info(f"Successful file-based authentication for user: {username}")
                    return jsonify({
                        "token": auth_result["token"],
                        "username": auth_result["username"],
                        "isAdmin": auth_result["isAdmin"]
                    })

                try:
                    import getpass
                    current_user = getpass.getuser()
                    if username.lower() == current_user.lower():
                        try:
                            handle = win32security.LogonUser(
                                username, None, password,
                                win32security.LOGON32_LOGON_NETWORK,
                                win32security.LOGON32_PROVIDER_DEFAULT
                            )
                            handle.Close()  # Use the PyHANDLE Close method
                            token = str(uuid.uuid4())
                            if not hasattr(self, 'auth_tokens'):
                                self.auth_tokens = {}
                            self.auth_tokens[token] = {
                                "username": username,
                                "created": datetime.datetime.now().isoformat(),
                                "expires": (datetime.datetime.now() + datetime.timedelta(hours=8)).isoformat(),
                                "isAdmin": True
                            }
                            logger.info(f"Successful Windows authentication for user: {username}")
                            return jsonify({
                                "token": token,
                                "username": username,
                                "isAdmin": True
                            })
                        except Exception as e:
                            logger.debug(f"Windows authentication failed: {e}")
                except Exception as e:
                    logger.debug(f"Windows authentication attempt failed: {e}")

                logger.warning(f"All authentication methods failed for user: {username}")
                return jsonify({"error": "Invalid username or password"}), 401
            except Exception as e:
                logger.error(f"Login error: {e}")
                import traceback
                logger.error(f"Login traceback: {traceback.format_exc()}")
                return jsonify({"error": "Authentication error"}), 500

        @app.route('/api/auth/verify', methods=['GET'])
        def api_verify_auth():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"authenticated": False}), 401

                token = auth_header.split(' ')[1]

                if self.sql_auth:
                    token_data = self.sql_auth.verify_token(token)
                    if token_data:
                        return jsonify({
                            "authenticated": True,
                            "username": token_data["username"],
                            "isAdmin": self.sql_auth.is_admin(token_data["username"])
                        })

                if hasattr(self, 'auth_tokens') and token in self.auth_tokens:
                    token_data = self.auth_tokens[token]
                    expires = datetime.datetime.fromisoformat(token_data["expires"])
                    if datetime.datetime.now() < expires:
                        return jsonify({
                            "authenticated": True,
                            "username": token_data["username"],
                            "isAdmin": token_data.get("isAdmin", False)
                        })
                    del self.auth_tokens[token]

                return jsonify({"authenticated": False}), 401
            except Exception as e:
                logger.error(f"Auth verification error: {e}")
                return jsonify({"error": "Authentication verification error"}), 500

        @app.route('/api/servers', methods=['GET'])
        def api_get_servers():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                servers = self.server_manager.get_all_servers()
                return jsonify(servers)
            except Exception as e:
                logger.error(f"Get servers error: {e}")
                return jsonify({"error": "Failed to get servers"}), 500

        @app.route('/api/servers/<server_id>/start', methods=['POST'])
        def api_start_server(server_id):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                result = self.server_manager.start_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} started successfully"})
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
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                result = self.server_manager.stop_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} stopped successfully"})
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
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                result = self.server_manager.restart_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} restarted successfully"})
                return jsonify({"error": f"Failed to restart server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Restart server error: {e}")
                return jsonify({"error": "Failed to restart server"}), 500

        @app.route('/api/users', methods=['GET'])
        def api_get_users():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                users = safe_auth_call('get_all_users')
                return jsonify(users)
            except Exception as e:
                logger.error(f"Get users error: {e}")
                return jsonify({"error": "Failed to get users"}), 500

        @app.route('/api/users', methods=['POST'])
        def api_create_user():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                username = data.get('username', '').strip()
                email = data.get('email', '').strip()
                password = data.get('password', '')
                is_admin = data.get('is_admin', False)

                if not username or not password:
                    return jsonify({"error": "Username and password are required"}), 400

                if len(password) < 6:
                    return jsonify({"error": "Password must be at least 6 characters"}), 400

                # Use SQL user management if available
                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.add_user(username, password, email, is_admin)
                        if success:
                            return jsonify({"message": "User created successfully"})
                        else:
                            return jsonify({"error": "Failed to create user - user may already exist"}), 409
                    except Exception as e:
                        logger.error(f"SQL user creation error: {e}")
                        return jsonify({"error": f"Failed to create user: {str(e)}"}), 500
                else:
                    # Fallback to legacy authentication
                    try:
                        result = safe_auth_call('add_user', username, password, is_admin)
                        if result:
                            return jsonify({"message": "User created successfully"})
                        else:
                            return jsonify({"error": "Failed to create user"}), 500
                    except Exception as e:
                        logger.error(f"Legacy user creation error: {e}")
                        return jsonify({"error": f"Failed to create user: {str(e)}"}), 500

            except Exception as e:
                logger.error(f"Create user error: {e}")
                return jsonify({"error": "Failed to create user"}), 500

        @app.route('/api/users/<username>', methods=['DELETE'])
        def api_delete_user(username):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                # Prevent deletion of current user
                if token_data["username"] == username:
                    return jsonify({"error": "Cannot delete your own account"}), 400

                # Use SQL user management if available
                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.delete_user(username)
                        if success:
                            return jsonify({"message": "User deleted successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"SQL user deletion error: {e}")
                        return jsonify({"error": f"Failed to delete user: {str(e)}"}), 500
                else:
                    # Fallback to legacy authentication
                    try:
                        result = safe_auth_call('delete_user', username)
                        if result:
                            return jsonify({"message": "User deleted successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"Legacy user deletion error: {e}")
                        return jsonify({"error": f"Failed to delete user: {str(e)}"}), 500

            except Exception as e:
                logger.error(f"Delete user error: {e}")
                return jsonify({"error": "Failed to delete user"}), 500

        @app.route('/api/users/<username>/password', methods=['PUT'])
        def api_reset_password(username):
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                new_password = data.get('password', '')
                if not new_password:
                    return jsonify({"error": "New password is required"}), 400

                if len(new_password) < 6:
                    return jsonify({"error": "Password must be at least 6 characters"}), 400

                # Use SQL user management if available
                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.update_user(username, password=new_password)
                        if success:
                            return jsonify({"message": "Password updated successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"SQL password reset error: {e}")
                        return jsonify({"error": f"Failed to reset password: {str(e)}"}), 500
                else:
                    # Fallback to legacy authentication
                    try:
                        result = safe_auth_call('change_password', username, new_password)
                        if result:
                            return jsonify({"message": "Password updated successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"Legacy password reset error: {e}")
                        return jsonify({"error": f"Failed to reset password: {str(e)}"}), 500

            except Exception as e:
                logger.error(f"Reset password error: {e}")
                return jsonify({"error": "Failed to reset password"}), 500

        @app.route('/api/system-settings', methods=['GET'])
        def api_get_system_settings():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                # Return default settings for now
                return jsonify({
                    "autoUpdate": False,
                    "backupSchedule": 24,
                    "debugLogging": False
                })
            except Exception as e:
                logger.error(f"Get system settings error: {e}")
                return jsonify({"error": "Failed to get system settings"}), 500

        @app.route('/api/system-settings', methods=['POST'])
        def api_save_system_settings():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                # For now, just return success - settings would be saved to database/config in a real implementation
                logger.info(f"System settings update requested by {token_data['username']}: {data}")
                return jsonify({"message": "Settings saved successfully"})

            except Exception as e:
                logger.error(f"Save system settings error: {e}")
                return jsonify({"error": "Failed to save system settings"}), 500

        @app.route('/api/settings', methods=['GET'])
        def api_get_settings():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                return jsonify({
                    "autoUpdate": True,
                    "backupSchedule": 24,
                    "notificationsEnabled": True
                })
            except Exception as e:
                logger.error(f"Get settings error: {e}")
                return jsonify({"error": "Failed to get settings"}), 500

        @app.route('/api/cluster/role', methods=['GET'])
        def api_cluster_role():
            return jsonify({
                "role": self.host_type,
                "hostAddress": self.host_address
            })

        @app.route('/api/tracker/dashboards', methods=['GET'])
        def api_tracker_dashboards():
            try:
                if self.tracker is None or not hasattr(self.tracker, 'get_dashboards'):
                    return jsonify({"error": "Dashboard tracker not available"}), 500
                return jsonify(self.tracker.get_dashboards())
            except Exception as e:
                logger.error(f"Tracker dashboards error: {e}")
                return jsonify({"error": "Dashboard tracker not available"}), 500

        @app.route('/api/tracker/servers', methods=['GET', 'POST', 'DELETE', 'PATCH'])
        def api_tracker_servers():
            try:
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401
                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)
                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if request.method == 'GET':
                    if self.tracker is None or not hasattr(self.tracker, 'get_servers'):
                        return jsonify({"error": "Tracker not available"}), 500
                    return jsonify(self.tracker.get_servers())

                if request.method == 'POST':
                    data = request.json
                    if not data or not isinstance(data, dict):
                        return jsonify({"error": "Invalid request body"}), 400
                    name = data.get("Name")
                    config = data
                    if not name or not isinstance(name, str):
                        return jsonify({"error": "Missing or invalid server name"}), 400
                    servers_dir = self.paths["servers"]
                    os.makedirs(servers_dir, exist_ok=True)
                    config_file = os.path.join(servers_dir, f"{name}.json")
                    if os.path.exists(config_file):
                        return jsonify({"error": "Server already exists"}), 409
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=4)
                    if self.tracker and hasattr(self.tracker, 'refresh'):
                        self.tracker.refresh()
                    return jsonify({"success": True})

                if request.method == 'DELETE':
                    data = request.json
                    if not data or not isinstance(data, dict):
                        return jsonify({"error": "Invalid request body"}), 400
                    name = data.get("Name")
                    if not name or not isinstance(name, str):
                        return jsonify({"error": "Missing or invalid server name"}), 400
                    servers_dir = self.paths["servers"]
                    config_file = os.path.join(servers_dir, f"{name}.json")
                    if not os.path.exists(config_file):
                        return jsonify({"error": "Server not found"}), 404
                    os.remove(config_file)
                    if self.tracker and hasattr(self.tracker, 'refresh'):
                        self.tracker.refresh()
                    return jsonify({"success": True})

                if request.method == 'PATCH':
                    data = request.json
                    if not data or not isinstance(data, dict):
                        return jsonify({"error": "Invalid request body"}), 400
                    name = data.get("Name")
                    action = data.get("Action")
                    if not name or not action or not isinstance(name, str) or not isinstance(action, str):
                        return jsonify({"error": "Missing or invalid server name or action"}), 400
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
                    if self.tracker and hasattr(self.tracker, 'refresh'):
                        self.tracker.refresh()
                    return jsonify({"success": True, "status": config["Status"]})

                return jsonify({"error": "Unsupported method"}), 405
            except Exception as e:
                logger.error(f"Tracker servers error: {e}")
                return jsonify({"error": "Failed to process tracker request"}), 500

        # Analytics API routes
        @app.route('/api/analytics/metrics', methods=['GET'])
        def api_analytics_metrics():
            # Get current system and server metrics
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                    
                format_type = request.args.get('format', 'json')
                
                if format_type == 'prometheus':
                    return self.analytics.get_prometheus_metrics(), 200, {'Content-Type': 'text/plain'}
                elif format_type == 'snmp':
                    return jsonify(self.analytics.get_snmp_metrics())
                else:
                    return jsonify(self.analytics.get_json_metrics())
                    
            except Exception as e:
                logger.error(f"Analytics metrics error: {e}")
                return jsonify({"error": "Failed to get metrics"}), 500

        @app.route('/api/analytics/metrics/<metric_name>', methods=['GET'])
        def api_analytics_metric_history(metric_name):
            # Get historical data for a specific metric
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                    
                hours = request.args.get('hours', 24, type=int)
                history = self.analytics.get_metric_history(metric_name, hours)
                
                return jsonify({
                    'metric_name': metric_name,
                    'hours': hours,
                    'data': history
                })
                
            except Exception as e:
                logger.error(f"Analytics metric history error: {e}")
                return jsonify({"error": "Failed to get metric history"}), 500

        @app.route('/api/analytics/servers', methods=['GET'])
        def api_analytics_servers():
            # Get server summary with performance metrics
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                    
                return jsonify(self.analytics.get_server_summary())
                
            except Exception as e:
                logger.error(f"Analytics servers error: {e}")
                return jsonify({"error": "Failed to get server analytics"}), 500

        @app.route('/api/analytics/health', methods=['GET'])
        def api_analytics_health():
            # Get overall system health metrics
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                    
                return jsonify(self.analytics.get_system_health())
                
            except Exception as e:
                logger.error(f"Analytics health error: {e}")
                return jsonify({"error": "Failed to get system health"}), 500

        @limit_decorator("10 per minute")
        @app.route('/api/analytics/snmp', methods=['GET'])
        def api_analytics_snmp():
            # SNMP-compatible metrics endpoint
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                    
                # Return SNMP-formatted metrics
                snmp_metrics = self.analytics.get_snmp_metrics()
                
                # Format as SNMP walk output if requested
                if request.args.get('format') == 'walk':
                    output_lines = []
                    for oid, value in snmp_metrics.items():
                        output_lines.append(f"{oid} = {value}")
                    return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain'}
                
                return jsonify(snmp_metrics)
                
            except Exception as e:
                logger.error(f"Analytics SNMP error: {e}")
                return jsonify({"error": "Failed to get SNMP metrics"}), 500

        # Prometheus metrics endpoint (commonly used path)
        @app.route('/metrics', methods=['GET'])
        def prometheus_metrics():
            # Standard Prometheus metrics endpoint
            try:
                if not self.analytics:
                    return "# Analytics not available\n", 503, {'Content-Type': 'text/plain'}
                    
                return self.analytics.get_prometheus_metrics(), 200, {'Content-Type': 'text/plain'}
                
            except Exception as e:
                logger.error(f"Prometheus metrics error: {e}")
                return f"# Error: {str(e)}\n", 500, {'Content-Type': 'text/plain'}

        @app.errorhandler(404)
        def page_not_found(e):
            return jsonify({"error": "Not found"}), 404

        @app.errorhandler(500)
        def internal_server_error(e):
            logger.error(f"Internal server error: {e}")
            return jsonify({"error": "Internal server error"}), 500

        @app.errorhandler(429)
        def ratelimit_handler(e):
            logger.warning(f"Rate limit exceeded: {e}")
            return jsonify({"error": "Too many requests"}), 429

        # Static file serving routes
        @app.route('/<path:filename>')
        def serve_static_files(filename):
            # Serve static files from the www directory
            try:
                # Try multiple possible www directory locations
                www_paths = [
                    os.path.join(self.server_manager_dir or "", "www"),
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), "www"),  # Development location
                    os.path.join(os.path.dirname(__file__), "..", "www"),  # Relative to Scripts
                ]
                
                www_path = None
                for path in www_paths:
                    if os.path.exists(path):
                        www_path = path
                        logger.debug(f"Using www directory: {www_path}")
                        break
                
                if not www_path:
                    logger.error(f"WWW directory not found. Tried paths: {www_paths}")
                    return jsonify({"error": "Static files directory not found"}), 404
                
                file_path = os.path.join(www_path, filename)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    logger.debug(f"Serving static file: {filename} from {www_path}")
                    return send_from_directory(www_path, filename)
                else:
                    logger.debug(f"Static file not found: {filename} in {www_path}")
                    return jsonify({"error": "File not found"}), 404
                    
            except Exception as e:
                logger.error(f"Error serving static file {filename}: {e}")
                return jsonify({"error": "Error serving file"}), 500

    def run(self):
        try:
            logger.info(f"Starting web server on port {self.web_port}")
            
            # Start cluster API server in a separate thread if cluster is enabled
            cluster_thread = None
            try:
                from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
                key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
                host_type = winreg.QueryValueEx(key, "HostType")[0]
                winreg.CloseKey(key)
                
                if host_type == "Host":
                    logger.info("Starting cluster API server on port 5001")
                    cluster_thread = threading.Thread(target=self._run_cluster_server, daemon=True)
                    cluster_thread.start()
                    # Give the cluster server a moment to start
                    import time
                    time.sleep(2)
                    logger.info("Cluster API server thread started")
            except Exception as e:
                logger.error(f"Cluster API startup failed: {e}")
                import traceback
                logger.error(f"Cluster API startup traceback: {traceback.format_exc()}")
            
            # Security-first host binding
            # Default to localhost only for security
            default_host = "127.0.0.1"  # Secure default - localhost only
            
            # Load security configuration
            security_config = None
            try:
                config_path = os.path.join(self.server_manager_dir or "", "config", "security_config.json")
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        security_config = json.load(f)
                        logger.info("Loaded security configuration from file")
            except Exception as e:
                logger.debug(f"Could not load security config file: {e}")
            
            # Check if this is a cluster host that needs external access
            try:
                # Import registry constants
                from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
                key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
                host_type = winreg.QueryValueEx(key, "HostType")[0]
                try:
                    cluster_enabled = winreg.QueryValueEx(key, "ClusterEnabled")[0] == "true"
                except Exception:
                    cluster_enabled = False
                winreg.CloseKey(key)
                
                # Override with security config if available
                if security_config:
                    cluster_enabled = security_config.get("security", {}).get("cluster_enabled", cluster_enabled)
                    bind_localhost_only = security_config.get("security", {}).get("bind_localhost_only", True)
                    
                    if bind_localhost_only:
                        logger.info("SECURITY: Security config enforcing localhost-only binding")
                    elif host_type == "Host" and cluster_enabled:
                        # For cluster hosts, allow external binding but log security warning
                        default_host = "0.0.0.0"
                        logger.warning("SECURITY: Binding to all interfaces (0.0.0.0) for cluster host - ensure firewall is configured!")
                    else:
                        logger.info("SECURITY: Using secure default localhost binding (127.0.0.1)")
                else:
                    # Legacy behavior - only bind to all interfaces if explicitly configured as cluster host
                    if host_type == "Host" and cluster_enabled:
                        # For cluster hosts, allow external binding but log security warning
                        default_host = "0.0.0.0"
                        logger.warning("SECURITY: Binding to all interfaces (0.0.0.0) for cluster host - ensure firewall is configured!")
                    else:
                        logger.info("SECURITY: Using secure default localhost binding (127.0.0.1)")
            except Exception as e:
                logger.debug(f"Could not read cluster config from registry: {e}")
                if security_config and security_config.get("security", {}).get("bind_localhost_only", True):
                    logger.info("SECURITY: Security config enforcing localhost-only binding")
                else:
                    logger.info("SECURITY: Using secure default localhost binding (127.0.0.1)")
            
            # Allow override via environment variable (with security warning)
            host = os.getenv("WEB_HOST", default_host)
            if host == "0.0.0.0" and default_host != "0.0.0.0":
                logger.warning("SECURITY: WEB_HOST environment variable overriding secure default - ensure this is intentional!")
            
            # Prepare server arguments
            server_args = {
                'host': host,
                'port': self.web_port,
                'threads': 8
            }
            
            # Add SSL configuration if enabled
            if os.getenv("SSL_ENABLED", "false").lower() == "true":
                cert_path = os.getenv("SSL_CERT_PATH")
                key_path = os.getenv("SSL_KEY_PATH")
                if cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path):
                    server_args.update({
                        'ssl_cert': cert_path,
                        'ssl_key': key_path
                    })
                    logger.info(f"SSL enabled with certificate and key files on {host}:{self.web_port}")
                else:
                    logger.warning("SSL enabled but certificate or key file missing/invalid - falling back to HTTP")
                    logger.info(f"SSL disabled - running HTTP only on {host}:{self.web_port}")
            else:
                logger.info(f"SSL disabled - running HTTP only on {host}:{self.web_port}")
            
            if not self.app:
                logger.error("Flask app not initialized - cannot start server")
                return False
                
            serve(self.app, **server_args)
            return True
        except KeyboardInterrupt:
            logger.info("Web server stopping due to keyboard interrupt")
            self.cleanup()
            return True
        except Exception as e:
            logger.error(f"Web server error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.cleanup()
            return False

    def _run_cluster_server(self):
        # Run a simple HTTP proxy server on port 5001 that forwards cluster API requests to port 8080
        try:
            import http.server
            import socketserver
            import urllib.request
            import urllib.parse
            import json
            
            class ClusterAPIProxy(http.server.BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    # Use the webserver logger instead of default logging
                    logger.debug(f"Cluster API Proxy: {format % args}")
                
                def do_GET(self):
                    self.proxy_request()
                
                def do_POST(self):
                    self.proxy_request()
                
                def proxy_request(self):
                    try:
                        # Forward the request to the main webserver on port 8080
                        target_url = f"http://127.0.0.1:8080{self.path}"
                        
                        # Prepare headers
                        headers = {}
                        for header_name, header_value in self.headers.items():
                            if header_name.lower() not in ['host', 'content-length']:
                                headers[header_name] = header_value
                        
                        # Handle request body for POST requests
                        data = None
                        if self.command == 'POST':
                            content_length = int(self.headers.get('Content-Length', 0))
                            if content_length > 0:
                                data = self.rfile.read(content_length)
                                headers['Content-Type'] = self.headers.get('Content-Type', 'application/json')
                        
                        # Create request
                        req = urllib.request.Request(target_url, data=data, headers=headers, method=self.command)
                        
                        # Make the request
                        with urllib.request.urlopen(req, timeout=30) as response:
                            # Forward the response
                            self.send_response(response.getcode())
                            
                            # Forward response headers
                            for header_name, header_value in response.headers.items():
                                if header_name.lower() not in ['server', 'date']:
                                    self.send_header(header_name, header_value)
                            self.end_headers()
                            
                            # Forward response body
                            response_data = response.read()
                            self.wfile.write(response_data)
                            
                    except Exception as e:
                        logger.error(f"Cluster proxy error: {e}")
                        self.send_error(502, f"Bad Gateway: {str(e)}")
            
            # Start the proxy server on port 5001
            with socketserver.TCPServer(("0.0.0.0", 5001), ClusterAPIProxy) as httpd:
                logger.info("Cluster API proxy server started on 0.0.0.0:5001 (forwarding to 127.0.0.1:8080)")
                httpd.serve_forever()
                
        except Exception as e:
            logger.error(f"Cluster proxy server error: {e}")
            import traceback
            logger.error(f"Cluster proxy server traceback: {traceback.format_exc()}")

    def cleanup(self):
        # Cleanup resources when shutting down
        try:
            # Update cluster status for shutdown
            self.shutdown_cluster_status()
            
            # Stop analytics collection
            if hasattr(self, 'analytics') and self.analytics:
                logger.info("Stopping analytics collection...")
                self.analytics.stop_collection()
                
            # Stop tracker
            if hasattr(self, 'tracker') and self.tracker:
                try:
                    if hasattr(self.tracker, 'stop_auto_refresh'):
                        self.tracker.stop_auto_refresh()
                except Exception as e:
                    logger.warning(f"Error stopping tracker: {e}")
                    
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def test_auth_modules(self):
        # Test available authentication modules
        try:
            logger.info("Testing authentication modules...")
            
            # Test SQL authentication
            if self.sql_auth:
                try:
                    users = self.sql_auth.get_all_users()
                    logger.info(f"SQL authentication available with {len(users)} users")
                except Exception as e:
                    logger.warning(f"SQL authentication test failed: {e}")
            
            # Test file-based authentication
            try:
                if hasattr(self, 'auth') and self.auth:
                    users = self.auth.get_all_users()
                    logger.info(f"File-based authentication available with {len(users)} users")
            except Exception as e:
                logger.warning(f"File-based authentication test failed: {e}")
                
            logger.info("Authentication module testing completed")
        except Exception as e:
            logger.error(f"Error testing authentication modules: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def start_host_heartbeat(self):
        # Start the host heartbeat thread to maintain cluster status
        def heartbeat_worker():
            while True:
                try:
                    if hasattr(self, 'cluster_db') and self.cluster_db:
                        self.cluster_db.heartbeat()
                    time.sleep(30)  # Heartbeat every 30 seconds
                except Exception as e:
                    logger.error(f"Host heartbeat error: {e}")
                    time.sleep(60)  # Wait longer on error
        
        heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
        heartbeat_thread.start()
        logger.info("Host heartbeat thread started")
    
    def shutdown_cluster_status(self):
        # Update cluster status on shutdown
        try:
            if hasattr(self, 'cluster_db') and self.cluster_db:
                self.cluster_db.update_host_status(
                    status="offline",
                    dashboard_active=False,
                    maintenance_mode=False,
                    status_message="Web server shutting down"
                )
                logger.info("Cluster status updated for shutdown")
        except Exception as e:
            logger.error(f"Failed to update cluster status on shutdown: {e}")

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def main():
    try:
        # Ensure proper path setup for subprocess execution
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_manager_dir = os.path.dirname(script_dir)
        if server_manager_dir not in sys.path:
            sys.path.insert(0, server_manager_dir)
            logger.info(f"Added to Python path: {server_manager_dir}")
        
        if not is_admin():
            logger.warning("Not running with administrator privileges. Some features may be limited.")
        if get_user_engine and ensure_root_admin:
            try:
                engine = get_user_engine()
                ensure_root_admin(engine)
                logger.info("Root admin ensured in SQL database")
            except Exception as e:
                logger.error(f"Could not ensure root admin in SQL: {e}")
        web_server = ServerManagerWebServer()
        return web_server.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    try:
        # Use logger instead of print for debug info to avoid console windows
        logger.info("Starting ServerManager webserver...")
        logger.debug(f"Working directory: {os.getcwd()}")
        logger.debug(f"Script path: {__file__}")
        logger.debug(f"Python path: {sys.path[:3]}")  # First 3 entries
        main()
    except Exception as e:
        import traceback
        logger.error("Webserver failed to start!")
        logger.error(traceback.format_exc())
        sys.exit(1)
