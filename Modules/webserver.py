import os
import sys
import json
import logging
import argparse
import datetime
import threading
import time
import uuid
import bcrypt
import win32security
import traceback
import glob
from functools import wraps
from typing import Optional, TYPE_CHECKING
from waitress import serve

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import (
    setup_module_path, setup_module_logging, REGISTRY_PATH, is_admin, 
    get_host_type, get_host_address, 
    is_cluster_enabled, get_registry_value, set_registry_value,
    get_allowed_origins
)
setup_module_path()

try:
    import psutil
except ImportError:
    psutil = None
    
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from Modules.web_security import (
    init_security_manager, get_security_headers,
    get_client_ip, InputValidator, PathSecurity
)

if TYPE_CHECKING:
    from Modules.analytics import AnalyticsCollector

logger: logging.Logger = setup_module_logging("WebServer")


class DummyDashboardTracker:
    # Stub when real tracker unavailable
    def start_auto_refresh(self): pass
    def stop_auto_refresh(self): pass
    def get_dashboards(self): return []
    def get_servers(self): return []
    def refresh(self): pass


tracker = None
try:
    from services.dashboard_tracker import tracker
    logger.debug("Dashboard tracker imported successfully")
except ImportError as e:
    logger.warning(f"Dashboard tracker not available: {e}")
    tracker = DummyDashboardTracker()
except NameError:
    # Handle case where get_server_manager_dir is not yet defined
    tracker = DummyDashboardTracker()
    logger.warning("Dashboard tracker not available - using dummy implementation")

# Import Flask dependencies - removed duplicate imports and handled CORS fallback
try:
    logger.debug("Flask imported successfully")
    # CORS is already imported at the top
    logger.debug("Flask-CORS imported successfully")
except ImportError:
    logger.warning("Flask-CORS not installed. Running without CORS support.")
    # Create a dummy CORS class if import fails
    class DummyCORS:
        def __init__(self, app):
            logger.warning("Using dummy CORS implementation")
    CORS = DummyCORS

# Import SQL modules
try:
    from Modules.Database.user_database import get_user_engine, ensure_root_admin, build_user_db_url, get_user_sql_config_from_registry
    from Modules.user_management import UserManager
    # Import server manager
    from Modules.server_manager import ServerManager as CoreServerManager
    logger.debug("SQL modules imported successfully")
except ImportError as e:
    logger.error(f"Failed to import SQL modules: {e}")
    logger.error(f"SQL import traceback:\n{traceback.format_exc()}")
    get_user_engine = None
    ensure_root_admin = None
    build_user_db_url = None
    get_user_sql_config_from_registry = None
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
        # Legacy file-based user loading - no longer creating config folder
        # All authentication should use SQL database now
        try:
            users_file = os.path.join(self.config_path, "users.json")
            if not os.path.exists(users_file):
                logger.warning("Users file not found. File-based auth is deprecated - use SQL authentication.")
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
        # Legacy file-based user saving - deprecated, no longer creating folders
        # All authentication should use SQL database now
        logger.warning("File-based user save attempted - this is deprecated. Use SQL authentication.")
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
        # Try bcrypt first, fallback to SHA256 for backward compatibility
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            # Fallback to SHA256 for backward compatibility
            import hashlib
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            return hashed == hashed_password

    def authenticate(self, username, password):
        if self.user_manager is None:
            return None
        
        # Use the same authentication method as the Python dashboard
        user = self.user_manager.authenticate_user(username, password)
        if not user:
            return None
        
        # Check if password was SHA256 and upgrade to bcrypt (same logic as UserManager)
        try:
            bcrypt.checkpw(password.encode(), user.password.encode())
        except Exception:
            # Password was SHA256, upgrade to bcrypt
            try:
                self.user_manager.update_user(username, password=password)
                logger.debug(f"Upgraded password hash to bcrypt for user: {username}")
            except Exception as e:
                logger.warning(f"Failed to upgrade password hash: {e}")
        
        token = str(uuid.uuid4())
        self.tokens[token] = {
            "username": username,
            "created": datetime.datetime.now().isoformat(),
            "expires": (datetime.datetime.now() + datetime.timedelta(hours=8)).isoformat()
        }
        return {
            "token": token, 
            "username": username,
            "isAdmin": getattr(user, 'is_admin', False)
        }

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
# Now uses database instead of JSON files
class ServerManager:
    def __init__(self, servers_path=None):
        # servers_path is now ignored - we use database instead
        self.servers_path = servers_path

    def get_all_servers(self):
        # Get all servers as a dict keyed by server name from database
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            all_servers = manager.get_all_servers()
            servers = {}
            for server_config in all_servers:
                server_name = server_config.get("Name", "Unknown")
                servers[server_name] = server_config
            return servers
        except Exception as e:
            logger.error(f"Error getting servers from database: {e}")
            return {}

    def get_server_status(self, server_name):
        # Get the status and PID of a server
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            server_config = manager.get_server(server_name)
            if server_config:
                pid = server_config.get("ProcessId") or server_config.get("PID")
                if pid and psutil:
                    try:
                        if psutil.pid_exists(pid):
                            return "Running", pid
                    except Exception:
                        pass
                return "Stopped", None
        except Exception as e:
            logger.error(f"Error getting server status for {server_name}: {e}")
        return "Unknown", None

    def get_server(self, server_id):
        # Get a server config by its name/id
        servers = self.get_all_servers()
        return servers.get(server_id)

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

    def create_server_config(self, server_name, server_type, install_dir, executable_path="", startup_args="", app_id="", version="", modloader=""):
        try:
            from Modules.Database.server_configs_database import ServerConfigManager
            manager = ServerConfigManager()
            
            # Check if server already exists
            existing = manager.get_server(server_name)
            if existing:
                return False, "Server already exists"
            
            server_config = {
                "Name": server_name,
                "Type": server_type,
                "InstallDir": install_dir,
                "ExecutablePath": executable_path,
                "StartupArgs": startup_args,
                "AppId": app_id,
                "Version": version,
                "Modloader": modloader,
                "Created": datetime.datetime.now().isoformat(),
                "LastUpdate": datetime.datetime.now().isoformat()
            }
            
            # Save to database
            result = manager.update_server(server_name, server_config)
            if result:
                return True, "Server configuration created successfully"
            else:
                return False, "Failed to save server configuration to database"
        except Exception as e:
            logger.error(f"Error creating server config: {e}")
            return False, f"Failed to create server config"

from Modules.common import ServerManagerModule


class ServerManagerWebServer(ServerManagerModule):
    def __init__(self):
        logger.debug("Initialising ServerManagerWebServer...")
        try:
            super().__init__("ServerManagerWebServer")
            logger.debug("Base ServerManagerModule initialised successfully")
        except Exception as e:
            logger.error(f"Failed to Initialise base ServerManagerModule: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Initialise minimal attributes to prevent AttributeError
            self.module_name = "ServerManagerWebServer"
            try:
                from Modules.server_logging import get_component_logger
                self.logger = get_component_logger("ServerManagerWebServer")
            except Exception:
                self.logger = logging.getLogger("ServerManagerWebServer")
        
        # Initialise all attributes to ensure they exist
        self.auth = None
        self.sql_auth = None  
        self.engine = None
        self.server_manager = None
        self.app = None
        self.limiter = None
        self.tracker = None
        self.subhost_thread = None
        self.auth_tokens = {}
        self.cluster_db = None  # Cluster database for host/subhost management
        self.analytics: Optional['AnalyticsCollector'] = None  # Analytics collector for metrics
        self._shutdown_event = threading.Event()  # Event for clean shutdown of background threads
        # Note: server_manager_dir is inherited from ServerManagerModule base class
        
        # Console monitoring for HTTPS/secured consoles
        self.console_monitor_thread = None
        self.console_monitor_active = False
        self.console_log_positions = {}  # server_name -> log_file -> position
        
        # Read from environment first, fall back to inherited web_port property or default
        try:
            base_port = self.web_port if hasattr(self, 'web_port') else 8080
            logger.debug(f"Base port from property: {base_port}")
        except Exception as e:
            logger.warning(f"Could not get web_port property, using default: {e}")
            base_port = 8080
            
        self._web_port = int(os.getenv("WEB_PORT", str(base_port)))
        logger.debug(f"Web port set to: {self._web_port}")
        
        # Cluster API port (separate from web port for security)
        self._cluster_port = int(os.getenv("CLUSTER_PORT", "5001"))
        logger.debug(f"Cluster API port set to: {self._cluster_port}")
        self.host_type = os.getenv("HOST_TYPE", "Unknown")
        self.host_address = os.getenv("HOST_ADDRESS", None)
        self.sql_available = False

        parser = argparse.ArgumentParser(description='Server Manager Web Server')
        parser.add_argument('--port', type=int, help='Web server port')
        args = parser.parse_args()
        
        self._continue_init(args)

    def _get_or_create_secret_key(self):
        # Get or create a persistent Flask secret key from registry
        import secrets
        existing = get_registry_value(REGISTRY_PATH, "FlaskSecretKey")
        if existing:
            return existing.encode() if isinstance(existing, str) else existing
        
        # Generate new secret key
        secret_key = secrets.token_hex(32)
        if set_registry_value(REGISTRY_PATH, "FlaskSecretKey", secret_key):
            logger.debug("Created new persistent Flask secret key")
        else:
            logger.warning("Could not persist Flask secret key to registry")
        
        return secret_key.encode()

    def _continue_init(self, args):
        if args.port:
            self._web_port = args.port

        # Override host type and address from environment if available
        if os.getenv("SERVERMANAGER_DIR"):
            logger.debug("Using configuration from environment variables")
        else:
            # Read host type from registry using centralized helpers
            self.host_type = get_host_type()
            self.host_address = get_host_address() or None
            logger.debug("Using configuration from registry")

        logger.debug(f"initialised webserver. Server Manager directory: {self.server_manager_dir}")
        logger.debug(f"Web server port: {self.web_port}")
        logger.debug(f"Cluster role: {self.host_type}" + (f", HostAddress: {self.host_address}" if self.host_address else ""))

        self.app = Flask(
            __name__,
            static_folder=os.path.join(self.server_manager_dir or "", "www")
        )
        
        # Configure CORS with restricted origins (not wildcard)
        allowed_origins = get_allowed_origins(host='localhost', port=self._web_port)
        CORS(self.app, origins=allowed_origins, supports_credentials=True)  # type: ignore[call-arg]
        self.app.secret_key = self._get_or_create_secret_key()
        
        self.security = init_security_manager({
            'web_port': self._web_port,
            'max_login_attempts': 5,
            'lockout_duration': 900,
            'allowed_origins': allowed_origins
        })
        
        # Path security for static file serving
        www_path = os.path.join(self.server_manager_dir or "", "www")
        self.path_security = PathSecurity(allowed_roots=[www_path])
        
        # Configure secure session settings
        ssl_enabled = os.getenv("SSL_ENABLED", "false").lower() == "true"
        self.app.config.update(
            SESSION_COOKIE_SECURE=ssl_enabled,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax'
        )
        
        # Add comprehensive security headers to all responses
        @self.app.after_request
        def add_security_headers(response):
            headers = get_security_headers(
                ssl_enabled=os.getenv("SSL_ENABLED", "false").lower() == "true",
                allowed_origins=allowed_origins
            )
            for header_name, header_value in headers.items():
                response.headers[header_name] = header_value
            return response

        self.check_sql_availability()

        try:
            if self.sql_available and get_user_engine and UserManager:
                self.engine = get_user_engine()
                self.sql_auth = SQLAuthentication(self.engine)
                self.auth = self.sql_auth  # Set auth to point to sql_auth for consistent interface
                logger.debug("SQL authentication system initialised successfully")
            else:
                # File-based authentication no longer supported (config folder removed)
                self.auth = self.create_fallback_auth()
                self.sql_auth = None
                logger.warning("File-based authentication not available (config folder removed), using fallback auth")
        except Exception as e:
            logger.error(f"Failed to Initialise authentication: {e}")
            self.auth = self.create_fallback_auth()
            self.sql_auth = None

        try:
            from Modules.Database.cluster_database import ClusterDatabase
            self.cluster_db = ClusterDatabase()
            
            self.cluster_db.update_host_status(
                status="online",
                dashboard_active=True,
                maintenance_mode=False,
                status_message="Web server initialised"
            )
            
            self.start_host_heartbeat()
            
            logger.debug("Cluster database initialised successfully")
        except Exception as e:
            logger.error(f"Failed to Initialise cluster database: {e}")
            self.cluster_db = None

        try:
            self.server_manager = ServerManager()
            self.db_manager = self.server_manager  # Alias for backward compatibility
            logger.debug("Server manager initialised successfully")
        except Exception as e:
            logger.error(f"Failed to Initialise server manager: {e}")
            self.server_manager = None
            self.db_manager = None

        try:
            from Modules.analytics import AnalyticsCollector
            self.analytics = AnalyticsCollector()
            self.analytics.start_collection()
            logger.debug("Analytics module initialised and started successfully")
        except Exception as e:
            logger.error(f"Failed to Initialise analytics module: {e}")
            self.analytics = None

        self.setup_routes()
        self.write_pid_file("webserver", os.getpid())

        self.tracker = tracker
        if self.tracker:
            try:
                self.tracker.start_auto_refresh()
                logger.debug("Dashboard tracker started in background thread")
            except Exception as e:
                logger.warning(f"Failed to start dashboard tracker: {e}")
                self.tracker = DummyDashboardTracker()

        self.subhost_thread = threading.Thread(target=self.subhost_communication_loop, daemon=True)
        self.subhost_thread.start()
        logger.debug("Subhost communication thread started")

        # Auto-configure SSL if certificates are available
        self._configure_ssl()

    @property
    def web_port(self):
        return self._web_port
    
    @web_port.setter
    def web_port(self, value):
        try:
            self._web_port = int(value) if value else 8080
        except (ValueError, TypeError):
            self._web_port = 8080
    
    @property
    def cluster_port(self):
        return getattr(self, '_cluster_port', 5001)

    def check_sql_availability(self):
        try:
            if get_user_engine and get_user_sql_config_from_registry and build_user_db_url:
                sql_conf = get_user_sql_config_from_registry()
                logger.debug(f"SQL config from registry: {sql_conf}")
                db_url = build_user_db_url(sql_conf)
                logger.debug(f"SQLAlchemy DB URL: {db_url}")
                if sql_conf["type"].lower() == "sqlite":
                    db_path = sql_conf["db_path"]
                    if not os.path.isabs(db_path):
                        db_path = os.path.abspath(db_path)
                        logger.debug(f"Resolved absolute SQLite DB path: {db_path}")
                    if not os.path.exists(db_path):
                        logger.error(f"SQLite DB file does not exist: {db_path}")
                        raise FileNotFoundError(f"Database file missing: {db_path}")
                    try:
                        with open(db_path, "rb"):
                            logger.debug(f"SQLite DB file exists and is readable: {db_path}")
                    except Exception as e:
                        logger.error(f"SQLite DB file exists but is not readable: {e}")
                        raise
                self.engine = get_user_engine()
                from sqlalchemy import text
                with self.engine.connect() as conn:
                    result = conn.execute(text("SELECT 1")).fetchone()
                    logger.debug(f"SQL connection test result: {result}")
                self.sql_available = True
                logger.debug("SQL connection available")
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
            def __init__(self):
                self.users = {}
                self.tokens = {}
                logger.debug("Using fallback authentication system")

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

        return FallbackAuth()

    def subhost_communication_loop(self):
        while not getattr(self, '_shutdown_event', threading.Event()).is_set():
            try:
                self._shutdown_event.wait(10)
            except Exception as e:
                logger.error(f"Error in subhost communication loop: {e}")
                self._shutdown_event.wait(30)





    def _configure_ssl(self):
        # Auto-configure SSL if certificates are available
        try:
            from Modules.ssl_utils import ensure_ssl_certificate
            cert_path, key_path = ensure_ssl_certificate()
            if cert_path and key_path:
                os.environ["SSL_ENABLED"] = "true"
                os.environ["SSL_CERT_PATH"] = cert_path
                os.environ["SSL_KEY_PATH"] = key_path
                logger.info(f"SSL auto-configured with certificates: {cert_path}, {key_path}")
            else:
                logger.debug("SSL certificates not available, SSL will remain disabled")
        except Exception as e:
            logger.error(f"Failed to auto-configure SSL: {e}")

    def setup_routes(self):
        if not self.app:
            logger.error("Flask app not initialised")
            return
            
        app = self.app
        
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
            import sys
            api_path = os.path.join(self.server_manager_dir or "", "api")
            logger.info(f"Cluster API path: {api_path}")
            if api_path not in sys.path:
                sys.path.insert(0, api_path)
                
            # Import using absolute path to avoid issues
            cluster_module_path = os.path.join(api_path, "cluster.py")
            logger.info(f"Cluster module path: {cluster_module_path}, exists: {os.path.exists(cluster_module_path)}")
            if os.path.exists(cluster_module_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("cluster", cluster_module_path)
                if spec and spec.loader:
                    cluster_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(cluster_module)
                    # Register without url_prefix since routes already have /api/cluster/ prefix
                    app.register_blueprint(cluster_module.cluster_api)
                    cluster_routes = [rule.rule for rule in list(app.url_map.iter_rules()) if 'cluster' in rule.rule]
                    logger.info(f"Cluster API registered successfully. Routes: {cluster_routes}")
                else:
                    logger.warning("Failed to create module spec for cluster API")
            else:
                logger.warning(f"Cluster API module not found at: {cluster_module_path}")
        except Exception as e:
            logger.warning(f"Failed to register cluster API: {e}")
            import traceback
            logger.debug(f"Cluster API registration error: {traceback.format_exc()}")

        # Helper function to handle rate limiting via web_security
        def check_rate_limit(limit_type='api'):
            client_ip = get_client_ip(request)
            allowed, retry_after = self.security.check_rate_limit(client_ip, limit_type)
            if not allowed:
                return jsonify({"error": f"Too many requests. Try again in {retry_after} seconds"}), 429
            return None

        def safe_auth_call(method_name, *args, **kwargs):
            if method_name == 'verify_token':
                token = args[0] if args else None
                if not token:
                    return None
                
                # Unified token verification for verify_token
                if self.sql_auth:
                    token_data = self.sql_auth.verify_token(token)
                    if token_data:
                        return token_data
                if self.auth:
                    token_data = self.auth.verify_token(token)
                    if token_data:
                        return token_data
                if hasattr(self, 'auth_tokens') and token in self.auth_tokens:
                    token_info = self.auth_tokens[token]
                    expires = datetime.datetime.fromisoformat(token_info["expires"])
                    if datetime.datetime.now() < expires:
                        return token_info
                    else:
                        del self.auth_tokens[token]
                return None
            else:
                # For other methods, use the original logic
                auth_instance = kwargs.pop('auth_instance', self.auth)
                if auth_instance and hasattr(auth_instance, method_name):
                    method = getattr(auth_instance, method_name)
                    return method(*args, **kwargs)
                return None

        def require_auth(f):
            # Decorator that verifies Bearer token and injects token_data
            @wraps(f)
            def decorated(*args, **kwargs):
                # Rate limit API calls
                rate_resp = check_rate_limit('api')
                if rate_resp:
                    return rate_resp
                
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                request.token_data = token_data  # type: ignore
                return f(*args, **kwargs)
            return decorated

        def require_admin(f):
            # Decorator that verifies Bearer token AND admin privileges
            @wraps(f)
            def decorated(*args, **kwargs):
                # Rate limit API calls
                rate_resp = check_rate_limit('api')
                if rate_resp:
                    return rate_resp
                
                auth_header = request.headers.get('Authorization')
                if not auth_header or not auth_header.startswith('Bearer '):
                    return jsonify({"error": "Authentication required"}), 401

                token = auth_header.split(' ')[1]
                token_data = safe_auth_call('verify_token', token)

                if not token_data:
                    return jsonify({"error": "Invalid or expired token"}), 401

                if not safe_auth_call('is_admin', token_data["username"]):
                    return jsonify({"error": "Admin privileges required"}), 403

                request.token_data = token_data  # type: ignore
                return f(*args, **kwargs)
            return decorated

        def validate_input(value, field_name="input"):
            # Validate input against SQL injection, XSS, and path traversal
            is_safe, error_msg = InputValidator.validate_safe_input(value, field_name)
            if not is_safe:
                return error_msg
            return None

        @app.route('/api/auth/login', methods=['POST'])
        def api_login():
            try:
                # Rate limit login attempts
                rate_resp = check_rate_limit('login')
                if rate_resp:
                    return rate_resp

                data = request.json
                if not data or not isinstance(data, dict):
                    return jsonify({"error": "Invalid request body"}), 400
                username = data.get('username')
                password = data.get('password')
                auth_type = data.get('authType', 'Database')

                if not username or not password or not isinstance(username, str) or not isinstance(password, str):
                    return jsonify({"error": "Username and password must be non-empty strings"}), 400

                # Validate input against injection
                input_err = validate_input(username, "username")
                if input_err:
                    return jsonify({"error": input_err}), 400

                # Check account lockout
                client_ip = get_client_ip(request)
                allowed, error_msg = self.security.validate_login_attempt(username, client_ip)
                if not allowed:
                    return jsonify({"error": error_msg}), 429

                logger.debug(f"Login attempt for user: {username} with auth type: {auth_type}")

                # Try SQL authentication first (same as dashboard)
                if self.sql_auth:
                    sql_result = safe_auth_call('authenticate', username, password, auth_instance=self.sql_auth)
                    if sql_result:
                        self.security.record_login_success(username, client_ip)
                        logger.debug(f"Successful SQL authentication for user: {username}")
                        return jsonify({
                            "token": sql_result["token"],
                            "username": sql_result["username"],
                            "isAdmin": sql_result["isAdmin"]
                        })
                    logger.warning(f"SQL authentication failed for user: {username}")

                # Fallback to file-based authentication only if SQL is not available
                if not self.sql_auth:
                    auth_result = safe_auth_call('authenticate', username, password)
                    if auth_result:
                        self.security.record_login_success(username, client_ip)
                        logger.debug(f"Successful file-based authentication for user: {username}")
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
                            logger.debug(f"Successful Windows authentication for user: {username}")
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
                # Record failed login attempt for lockout
                is_locked, remaining = self.security.record_login_failure(username, client_ip)
                if is_locked:
                    return jsonify({"error": f"Account temporarily locked. Try again later"}), 429
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

                if self.auth:
                    token_data = self.auth.verify_token(token)
                    if token_data:
                        return jsonify({
                            "authenticated": True,
                            "username": token_data["username"],
                            "isAdmin": self.auth.is_admin(token_data["username"])
                        })

                # Try Windows auth tokens
                if hasattr(self, 'auth_tokens') and token in self.auth_tokens:
                    token_data = self.auth_tokens[token]
                    expires = datetime.datetime.fromisoformat(token_data["expires"])
                    if datetime.datetime.now() < expires:
                        return jsonify({
                            "authenticated": True,
                            "username": token_data["username"],
                            "isAdmin": token_data.get("isAdmin", False)
                        })
                    else:
                        del self.auth_tokens[token]

                return jsonify({"authenticated": False}), 401
            except Exception as e:
                logger.error(f"Auth verification error: {e}")
                return jsonify({"error": "Authentication verification error"}), 500

        @app.route('/api/servers', methods=['GET', 'POST'])
        @require_auth
        def api_servers():
            try:
                token_data = request.token_data  # type: ignore

                if request.method == 'GET':
                    if self.server_manager is None:
                        return jsonify({"error": "Server manager not available"}), 500
                        
                    # Get all servers with their current status (similar to cluster API)
                    servers = self.server_manager.get_all_servers()
                    result = []
                    
                    for server_name, server_config in servers.items():
                        try:
                            status, pid = self.server_manager.get_server_status(server_name)
                            server_info = {
                                "id": server_name,
                                "name": server_name,
                                "status": status,
                                "cpu": 0,  # Placeholder - would need system monitoring
                                "memory": 0,  # Placeholder - would need system monitoring
                                "disk": 0,  # Placeholder - would need system monitoring
                                "pid": pid,
                                "type": server_config.get("Type", "Unknown"),
                                "path": server_config.get("InstallDir", ""),
                                "executable": server_config.get("ExecutablePath", ""),
                                "app_id": server_config.get("AppID", ""),
                                "args": server_config.get("StartupArgs", ""),
                                "auto_start": server_config.get("AutoStart", False),
                                "last_started": server_config.get("StartTime", "")
                            }
                            result.append(server_info)
                            
                        except Exception as server_error:
                            logger.debug(f"Error getting status for server {server_name}: {str(server_error)}")
                            # Add server with error status if status check fails
                            server_info = {
                                "id": server_name,
                                "name": server_name,
                                "status": "Error",
                                "cpu": 0,
                                "memory": 0,
                                "disk": 0,
                                "pid": None,
                                "type": server_config.get("Type", "Unknown"),
                                "path": server_config.get("InstallDir", ""),
                                "executable": server_config.get("ExecutablePath", ""),
                                "app_id": server_config.get("AppID", ""),
                                "args": server_config.get("StartupArgs", ""),
                                "auto_start": server_config.get("AutoStart", False),
                                "last_started": server_config.get("StartTime", "")
                            }
                            result.append(server_info)
                    
                    return jsonify({
                        "success": True,
                        "servers": result,
                        "count": len(result)
                    })

                elif request.method == 'POST':
                    if self.server_manager is None:
                        return jsonify({"error": "Server manager not available"}), 500

                    data = request.get_json()
                    if not data:
                        return jsonify({"error": "No data provided"}), 400

                    server_name = InputValidator.sanitize_string(data.get('name', ''), max_length=100)
                    server_type = InputValidator.sanitize_string(data.get('type', ''), max_length=50)
                    server_path = InputValidator.sanitize_string(data.get('path', ''), max_length=500)

                    if not server_name:
                        return jsonify({"error": "Server name is required"}), 400

                    # Validate inputs against injection attacks
                    for field_name, field_val in [("name", server_name), ("type", server_type), ("path", server_path)]:
                        err = validate_input(field_val, field_name)
                        if err:
                            return jsonify({"error": err}), 400

                    if not server_type:
                        return jsonify({"error": "Server type is required"}), 400

                    if not server_path:
                        return jsonify({"error": "Server path is required"}), 400

                    try:
                        if self.server_manager and hasattr(self.server_manager, 'create_server_config'):
                            result = self.server_manager.create_server_config(
                                server_name=server_name,
                                server_type=server_type,
                                install_dir=server_path,
                                executable_path="",  # Empty executable path - will be set later
                                startup_args="",
                                app_id="",
                                version="",
                                modloader=""
                            )
                            success, message = result if isinstance(result, tuple) else (result, "Operation completed")
                        else:
                            # Fallback: use database directly
                            try:
                                from Modules.Database.server_configs_database import ServerConfigManager
                                manager = ServerConfigManager()
                                
                                # Check if server already exists
                                existing = manager.get_server(server_name)
                                if existing:
                                    return jsonify({"error": "Server already exists"}), 409
                                
                                server_config = {
                                    "Name": server_name,
                                    "Type": server_type,
                                    "InstallDir": server_path,
                                    "ExecutablePath": "",
                                    "StartupArgs": "",
                                    "Created": datetime.datetime.now().isoformat(),
                                    "LastUpdate": datetime.datetime.now().isoformat()
                                }
                                
                                result = manager.update_server(server_name, server_config)
                                success, message = result, "Server configuration created successfully" if result else "Failed to save"
                            except Exception as db_err:
                                logger.error(f"Database fallback failed: {db_err}")
                                success, message = False, "Database operation failed"

                        if success:
                            return jsonify({"success": True, "message": message}), 200
                        else:
                            return jsonify({"error": message}), 400
                    except AttributeError:
                        return jsonify({"error": "Server creation not available"}), 500

            except Exception as e:
                logger.error(f"Servers API error: {e}")
                return jsonify({"error": "Internal server error"}), 500

            # This should not be reached due to method restriction, but for type safety
            return jsonify({"error": "Method not allowed"}), 405

        @app.route('/api/servers/<server_id>', methods=['DELETE'])
        @require_auth
        def api_delete_server(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500

                if server_id not in self.server_manager.servers:  # type: ignore
                    return jsonify({"error": f"Server {server_id} not found"}), 404

                # Remove server (keep files by default)
                success, message = self.server_manager.uninstall_server(server_id, remove_files=False)  # type: ignore
                
                if success:
                    return jsonify({"success": True, "message": message}), 200
                else:
                    return jsonify({"error": message}), 400
                    
            except Exception as e:
                logger.error(f"Delete server error: {e}")
                return jsonify({"error": "Failed to delete server"}), 500

        @app.route('/api/servers/<server_id>/start', methods=['POST'])
        @require_auth
        def api_start_server(server_id):
            try:
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
        @require_auth
        def api_stop_server(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                result = self.server_manager.stop_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} stopped successfully"})
                return jsonify({"error": f"Failed to stop server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Stop server error: {e}")
                return jsonify({"error": "Failed to stop server"}), 500

        @app.route('/api/servers/<server_id>/console', methods=['GET'])
        @require_auth
        def api_get_console(server_id):
            try:
                lines = request.args.get('lines', 100, type=int)
                since = request.args.get('since', 0, type=int)  # Index of last seen entry for incremental updates
                
                try:
                    from Modules.Database.console_database import load_console_state_db
                    output_buffer, command_history = load_console_state_db(server_id)
                    if output_buffer is not None:
                        # Normalize output entries to consistent format for frontend
                        # Entries may be dicts {text, type, timestamp} or plain strings
                        normalized = []
                        for entry in output_buffer:
                            if isinstance(entry, dict):
                                normalized.append({
                                    'text': entry.get('text', ''),
                                    'type': entry.get('type', 'stdout'),
                                    'timestamp': entry.get('timestamp', '')
                                })
                            elif isinstance(entry, str):
                                normalized.append({
                                    'text': entry,
                                    'type': 'stdout',
                                    'timestamp': ''
                                })
                        
                        # Support incremental updates - only return entries after 'since' index
                        total_entries = len(normalized)
                        if since > 0 and since < total_entries:
                            result_entries = normalized[since:]
                        else:
                            result_entries = normalized[-lines:] if len(normalized) > lines else normalized
                        
                        return jsonify({
                            "success": True,
                            "output": result_entries,
                            "total_entries": total_entries,
                            "server_id": server_id
                        })
                    else:
                        return jsonify({"success": True, "output": [], "total_entries": 0, "server_id": server_id})
                except ImportError:
                    logger.warning("Console database not available")
                    return jsonify({"success": True, "output": [], "total_entries": 0, "server_id": server_id})
                except Exception as e:
                    logger.error(f"Error reading console state from database: {e}")
                    return jsonify({"success": True, "output": [], "total_entries": 0, "server_id": server_id})
                    
            except Exception as e:
                logger.error(f"Get console error: {e}")
                return jsonify({"error": "Failed to get console output"}), 500

        @app.route('/api/servers/<server_id>/console', methods=['POST'])
        @require_auth
        def api_send_command(server_id):
            try:
                data = request.get_json()
                command = data.get('command', '').strip() if data else ''
                
                if not command:
                    return jsonify({"error": "No command provided"}), 400

                if not self.server_manager_dir:
                    return jsonify({"error": "Server manager directory not configured"}), 500
                queue_dir = os.path.join(self.server_manager_dir, "temp", "command_queues")
                os.makedirs(queue_dir, exist_ok=True)
                queue_file = os.path.join(queue_dir, f"{server_id}.queue")
                
                try:
                    with open(queue_file, 'a', encoding='utf-8') as f:
                        f.write(command + '\n')
                    logger.info(f"Command queued for {server_id}: {command}")
                    return jsonify({"success": True, "message": "Command sent"})
                except Exception as e:
                    logger.error(f"Failed to queue command: {e}")
                    return jsonify({"error": "Failed to send command"}), 500
                    
            except Exception as e:
                logger.error(f"Send command error: {e}")
                return jsonify({"error": "Failed to send command"}), 500

        @app.route('/api/servers/<server_id>/restart', methods=['POST'])
        @require_auth
        def api_restart_server(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500
                    
                result = self.server_manager.restart_server(server_id)
                if result:
                    return jsonify({"success": True, "message": f"Server {server_id} restarted successfully"})
                return jsonify({"error": f"Failed to restart server {server_id}"}), 400
            except Exception as e:
                logger.error(f"Restart server error: {e}")
                return jsonify({"error": "Failed to restart server"}), 500

        @app.route('/api/servers/<server_id>/test-motd', methods=['POST'])
        @require_auth
        def api_test_motd(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500

                # Get automation settings
                from Modules.common import load_automation_settings
                try:
                    server_config = self.db_manager.get_server_config(server_id)  # type: ignore
                    if not server_config:
                        return jsonify({"error": "Server configuration not found"}), 404
                    
                    settings = load_automation_settings(server_config)
                    motd_cmd = settings.get('motd_command', '')
                    motd_msg = settings.get('motd_message', '')
                    
                    if not motd_cmd or not motd_msg:
                        return jsonify({"error": "MOTD command or message not configured"}), 400
                    
                    from Modules.server_automation import ServerAutomationManager
                    automation = ServerAutomationManager(self.server_manager)
                    result = automation.send_motd(server_id, motd_msg)
                    
                    if result:
                        return jsonify({"success": True, "message": "MOTD sent successfully"})
                    return jsonify({"error": "Failed to send MOTD"}), 400
                    
                except Exception as e:
                    logger.error(f"Test MOTD error: {e}")
                    return jsonify({"error": "Failed to test MOTD"}), 500

            except Exception as e:
                logger.error(f"Test MOTD API error: {e}")
                return jsonify({"error": "Failed to test MOTD"}), 500

        @app.route('/api/servers/<server_id>/test-save', methods=['POST'])
        @require_auth
        def api_test_save(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500

                from Modules.common import load_automation_settings
                try:
                    server_config = self.db_manager.get_server_config(server_id)  # type: ignore
                    if not server_config:
                        return jsonify({"error": "Server configuration not found"}), 404
                    
                    settings = load_automation_settings(server_config)
                    save_cmd = settings.get('save_command', '')
                    
                    if not save_cmd:
                        return jsonify({"error": "Save command not configured"}), 400
                    
                    from Modules.server_automation import ServerAutomationManager
                    automation = ServerAutomationManager(self.server_manager)
                    result = automation._send_command_to_server(server_id, save_cmd)
                    
                    if result:
                        return jsonify({"success": True, "message": "Save command sent successfully"})
                    return jsonify({"error": "Failed to send save command"}), 400
                    
                except Exception as e:
                    logger.error(f"Test save error: {e}")
                    return jsonify({"error": "Failed to test save command"}), 500

            except Exception as e:
                logger.error(f"Test save API error: {e}")
                return jsonify({"error": "Failed to test save command"}), 500

        @app.route('/api/servers/<server_id>/test-warning', methods=['POST'])
        @require_auth
        def api_test_warning(server_id):
            try:
                if self.server_manager is None:
                    return jsonify({"error": "Server manager not available"}), 500

                data = request.get_json() or {}
                minutes = data.get('minutes', 5)  # Default 5 minutes
                
                # Get automation settings
                from Modules.common import load_automation_settings
                try:
                    server_config = self.db_manager.get_server_config(server_id)  # type: ignore
                    if not server_config:
                        return jsonify({"error": "Server configuration not found"}), 404
                    
                    settings = load_automation_settings(server_config)
                    warning_cmd = settings.get('warning_command', '')
                    warning_msg = settings.get('warning_message_template', 'Server restarting in {message}')
                    
                    if not warning_cmd:
                        return jsonify({"error": "Warning command not configured"}), 400
                    
                    # Replace {message} placeholder if present in command
                    if '{message}' in warning_cmd:
                        message = f"{minutes} minute{'s' if minutes != 1 else ''}"
                        command = warning_cmd.replace('{message}', message)
                    else:
                        command = warning_cmd
                        message = f"{minutes} minute{'s' if minutes != 1 else ''}"
                    
                    from Modules.server_automation import ServerAutomationManager
                    automation = ServerAutomationManager(self.server_manager)
                    result = automation._send_command_to_server(server_id, command)
                    
                    if result:
                        return jsonify({"success": True, "message": f"Warning command sent successfully: {command}"})
                    return jsonify({"error": "Failed to send warning command"}), 400
                    
                except Exception as e:
                    logger.error(f"Test warning error: {e}")
                    return jsonify({"error": "Failed to test warning command"}), 500

            except Exception as e:
                logger.error(f"Test warning API error: {e}")
                return jsonify({"error": "Failed to test warning command"}), 500

        @app.route('/api/users', methods=['GET'])
        @require_admin
        def api_get_users():
            try:
                users = safe_auth_call('get_all_users')
                return jsonify(users)
            except Exception as e:
                logger.error(f"Get users error: {e}")
                return jsonify({"error": "Failed to get users"}), 500

        @app.route('/api/users', methods=['POST'])
        @require_admin
        def api_create_user():
            try:
                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                username = InputValidator.sanitize_string(data.get('username', ''), max_length=50)
                email = InputValidator.sanitize_string(data.get('email', ''), max_length=254)
                password = data.get('password', '')
                is_admin_flag = data.get('is_admin', False)

                if not username or not password:
                    return jsonify({"error": "Username and password are required"}), 400

                # Validate username and password with security rules
                valid, err = InputValidator.validate_username(username)
                if not valid:
                    return jsonify({"error": err}), 400
                valid, err = InputValidator.validate_password(password)
                if not valid:
                    return jsonify({"error": err}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.add_user(username, password, email, is_admin_flag)
                        if success:
                            return jsonify({"message": "User created successfully"})
                        else:
                            return jsonify({"error": "Failed to create user - user may already exist"}), 409
                    except Exception as e:
                        logger.error(f"SQL user creation error: {e}")
                        return jsonify({"error": "Failed to create user"}), 500
                else:
                    try:
                        result = safe_auth_call('add_user', username, password, is_admin_flag)
                        if result:
                            return jsonify({"message": "User created successfully"})
                        else:
                            return jsonify({"error": "Failed to create user"}), 500
                    except Exception as e:
                        logger.error(f"Legacy user creation error: {e}")
                        return jsonify({"error": "Failed to create user"}), 500

            except Exception as e:
                logger.error(f"Create user error: {e}")
                return jsonify({"error": "Failed to create user"}), 500

        @app.route('/api/users/<username>', methods=['DELETE'])
        @require_admin
        def api_delete_user(username):
            try:
                # Prevent deletion of current user
                if request.token_data["username"] == username:  # type: ignore[attr-defined]
                    return jsonify({"error": "Cannot delete your own account"}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.delete_user(username)
                        if success:
                            return jsonify({"message": "User deleted successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"SQL user deletion error: {e}")
                        return jsonify({"error": "Failed to delete user"}), 500
                else:
                    try:
                        result = safe_auth_call('delete_user', username)
                        if result:
                            return jsonify({"message": "User deleted successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"Legacy user deletion error: {e}")
                        return jsonify({"error": "Failed to delete user"}), 500

            except Exception as e:
                logger.error(f"Delete user error: {e}")
                return jsonify({"error": "Failed to delete user"}), 500

        @app.route('/api/users/<username>/password', methods=['PUT'])
        @require_admin
        def api_reset_password(username):
            try:
                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                new_password = data.get('password', '')
                if not new_password:
                    return jsonify({"error": "New password is required"}), 400

                is_valid, pwd_msg = InputValidator.validate_password(new_password)
                if not is_valid:
                    return jsonify({"error": pwd_msg}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    try:
                        success = self.sql_auth.user_manager.update_user(username, password=new_password)
                        if success:
                            return jsonify({"message": "Password updated successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"SQL password reset error: {e}")
                        return jsonify({"error": "Failed to reset password"}), 500
                else:
                    try:
                        result = safe_auth_call('change_password', username, new_password)
                        if result:
                            return jsonify({"message": "Password updated successfully"})
                        else:
                            return jsonify({"error": "User not found"}), 404
                    except Exception as e:
                        logger.error(f"Legacy password reset error: {e}")
                        return jsonify({"error": "Failed to reset password"}), 500

            except Exception as e:
                logger.error(f"Reset password error: {e}")
                return jsonify({"error": "Failed to reset password"}), 500

        @app.route('/api/profile', methods=['GET'])
        @require_auth
        def api_get_profile():
            try:
                username = request.token_data.get("username")  # type: ignore[attr-defined]
                
                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    user_mgr = self.sql_auth.user_manager
                    user = user_mgr.get_user(username)
                    if user:
                        return jsonify({
                            "username": user.username,
                            "email": user.email or "",
                            "first_name": getattr(user, 'first_name', '') or "",
                            "last_name": getattr(user, 'last_name', '') or "",
                            "display_name": getattr(user, 'display_name', '') or user.username,
                            "avatar": getattr(user, 'avatar', '') or "",
                            "bio": getattr(user, 'bio', '') or "",
                            "timezone": getattr(user, 'timezone', '') or "UTC",
                            "theme_preference": getattr(user, 'theme_preference', 'dark') or "dark",
                            "is_admin": user.is_admin,
                            "two_factor_enabled": getattr(user, 'two_factor_enabled', False),
                            "created_at": getattr(user.created_at, 'isoformat', lambda: None)() if user.created_at is not None else None,
                            "last_login": getattr(user.last_login, 'isoformat', lambda: None)() if user.last_login is not None else None
                        })
                    return jsonify({"error": "User not found"}), 404
                else:
                    return jsonify({
                        "username": username,
                        "email": "",
                        "display_name": username,
                        "is_admin": safe_auth_call('is_admin', username)
                    })

            except Exception as e:
                logger.error(f"Get profile error: {e}")
                return jsonify({"error": "Failed to get profile"}), 500

        @app.route('/api/profile', methods=['PUT'])
        @require_auth
        def api_update_profile():
            try:
                username = request.token_data.get("username")  # type: ignore[attr-defined]
                data = request.json
                
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                # Fields users can update (NOT username)
                allowed_fields = ['email', 'first_name', 'last_name', 'display_name', 
                                  'avatar', 'bio', 'timezone', 'theme_preference']
                
                update_data = {}
                for field in allowed_fields:
                    if field in data:
                        update_data[field] = data[field]

                if not update_data:
                    return jsonify({"error": "No valid fields to update"}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    user_mgr = self.sql_auth.user_manager
                    success = user_mgr.update_user(username, **update_data)
                    if success:
                        return jsonify({"message": "Profile updated successfully"})
                    return jsonify({"error": "Failed to update profile"}), 500
                else:
                    return jsonify({"error": "Profile updates not available"}), 501

            except Exception as e:
                logger.error(f"Update profile error: {e}")
                return jsonify({"error": "Failed to update profile"}), 500

        @app.route('/api/profile/password', methods=['PUT'])
        @require_auth
        def api_change_own_password():
            try:
                username = request.token_data.get("username")  # type: ignore[attr-defined]
                data = request.json
                
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                current_password = data.get('current_password', '')
                new_password = data.get('new_password', '')
                
                if not current_password or not new_password:
                    return jsonify({"error": "Current and new passwords required"}), 400

                if len(new_password) < 8:
                    return jsonify({"error": "New password must be at least 8 characters"}), 400

                is_valid, pwd_msg = InputValidator.validate_password(new_password)
                if not is_valid:
                    return jsonify({"error": pwd_msg}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth:
                    auth_result = self.sql_auth.authenticate(username, current_password)
                    if not auth_result:
                        return jsonify({"error": "Current password is incorrect"}), 401
                    
                    user_mgr = self.sql_auth.user_manager
                    if user_mgr:
                        success = user_mgr.update_user(username, password=new_password)
                    else:
                        return jsonify({"error": "User manager not available"}), 501
                    if success:
                        return jsonify({"message": "Password changed successfully"})
                    return jsonify({"error": "Failed to change password"}), 500
                else:
                    return jsonify({"error": "Password change not available"}), 501

            except Exception as e:
                logger.error(f"Change password error: {e}")
                return jsonify({"error": "Failed to change password"}), 500

        @app.route('/api/profile/avatar', methods=['POST'])
        @require_auth
        def api_upload_avatar():
            try:
                username = request.token_data.get("username")  # type: ignore[attr-defined]
                data = request.json
                
                if not data or 'avatar' not in data:
                    return jsonify({"error": "No avatar data provided"}), 400

                avatar_data = data.get('avatar', '')
                
                # Validate it's a reasonable size (max ~500KB base64)
                if len(avatar_data) > 700000:
                    return jsonify({"error": "Avatar too large (max 500KB)"}), 400

                if self.sql_available and hasattr(self, 'sql_auth') and self.sql_auth and hasattr(self.sql_auth, 'user_manager') and self.sql_auth.user_manager:
                    user_mgr = self.sql_auth.user_manager
                    success = user_mgr.update_user(username, avatar=avatar_data)
                    if success:
                        return jsonify({"message": "Avatar updated successfully"})
                    return jsonify({"error": "Failed to update avatar"}), 500
                else:
                    return jsonify({"error": "Avatar upload not available"}), 501

            except Exception as e:
                logger.error(f"Upload avatar error: {e}")
                return jsonify({"error": "Failed to upload avatar"}), 500

        @app.route('/api/system-settings', methods=['GET'])
        @require_admin
        def api_get_system_settings():
            try:
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
        @require_admin
        def api_save_system_settings():
            try:
                data = request.json
                if not data:
                    return jsonify({"error": "No data provided"}), 400

                # For now, just return success - settings would be saved to database/config in a real implementation
                logger.info(f"System settings update requested by {request.token_data['username']}: {data}")  # type: ignore[attr-defined]
                return jsonify({"message": "Settings saved successfully"})

            except Exception as e:
                logger.error(f"Save system settings error: {e}")
                return jsonify({"error": "Failed to save system settings"}), 500

        @app.route('/api/settings', methods=['GET'])
        @require_auth
        def api_get_settings():
            try:
                return jsonify({
                    "autoUpdate": True,
                    "backupSchedule": 24,
                    "notificationsEnabled": True
                })
            except Exception as e:
                logger.error(f"Get settings error: {e}")
                return jsonify({"error": "Failed to get settings"}), 500

        @app.route('/api/cluster/role', methods=['GET'])
        @require_auth
        def api_cluster_role():
            return jsonify({
                "role": self.host_type,
                "hostAddress": self.host_address
            })

        @app.route('/api/tracker/dashboards', methods=['GET'])
        @require_auth
        def api_tracker_dashboards():
            try:
                if self.tracker is None or not hasattr(self.tracker, 'get_dashboards'):
                    return jsonify({"error": "Dashboard tracker not available"}), 500
                return jsonify(self.tracker.get_dashboards())
            except Exception as e:
                logger.error(f"Tracker dashboards error: {e}")
                return jsonify({"error": "Dashboard tracker not available"}), 500

        @app.route('/api/tracker/servers', methods=['GET', 'POST', 'DELETE', 'PATCH'])
        @require_auth
        def api_tracker_servers():
            try:
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
                    
                    try:
                        from Modules.Database.server_configs_database import ServerConfigManager
                        manager = ServerConfigManager()
                        
                        existing = manager.get_server(name)
                        if existing:
                            return jsonify({"error": "Server already exists"}), 409
                        
                        result = manager.update_server(name, config)
                        if not result:
                            return jsonify({"error": "Failed to save server config"}), 500
                            
                        if self.tracker and hasattr(self.tracker, 'refresh'):
                            self.tracker.refresh()
                        return jsonify({"success": True})
                    except Exception as db_err:
                        logger.error(f"Database error creating server: {db_err}")
                        return jsonify({"error": "Failed to create server configuration"}), 500

                if request.method == 'DELETE':
                    data = request.json
                    if not data or not isinstance(data, dict):
                        return jsonify({"error": "Invalid request body"}), 400
                    name = data.get("Name")
                    if not name or not isinstance(name, str):
                        return jsonify({"error": "Missing or invalid server name"}), 400
                    
                    try:
                        from Modules.Database.server_configs_database import ServerConfigManager
                        manager = ServerConfigManager()
                        
                        existing = manager.get_server(name)
                        if not existing:
                            return jsonify({"error": "Server not found"}), 404
                        
                        result = manager.delete_server(name)
                        if not result:
                            return jsonify({"error": "Failed to delete server"}), 500
                            
                        if self.tracker and hasattr(self.tracker, 'refresh'):
                            self.tracker.refresh()
                        return jsonify({"success": True})
                    except Exception as db_err:
                        logger.error(f"Database error deleting server: {db_err}")
                        return jsonify({"error": "Failed to delete server"}), 500

                if request.method == 'PATCH':
                    data = request.json
                    if not data or not isinstance(data, dict):
                        return jsonify({"error": "Invalid request body"}), 400
                    name = data.get("Name")
                    action = data.get("Action")
                    if not name or not action or not isinstance(name, str) or not isinstance(action, str):
                        return jsonify({"error": "Missing or invalid server name or action"}), 400
                    
                    try:
                        from Modules.Database.server_configs_database import ServerConfigManager
                        manager = ServerConfigManager()
                        
                        config = manager.get_server(name)
                        if not config:
                            return jsonify({"error": "Server not found"}), 404
                        
                        if action == "start":
                            config["Status"] = "Running"
                        elif action == "stop":
                            config["Status"] = "Stopped"
                        elif action == "restart":
                            config["Status"] = "Restarting"
                        else:
                            return jsonify({"error": "Unknown action"}), 400
                        
                        result = manager.update_server(name, config)
                        if not result:
                            return jsonify({"error": "Failed to update server"}), 500
                            
                        if self.tracker and hasattr(self.tracker, 'refresh'):
                            self.tracker.refresh()
                        return jsonify({"success": True, "status": config["Status"]})
                    except Exception as db_err:
                        logger.error(f"Database error updating server: {db_err}")
                        return jsonify({"error": "Failed to update server"}), 500

                return jsonify({"error": "Unsupported method"}), 405
            except Exception as e:
                logger.error(f"Tracker servers error: {e}")
                return jsonify({"error": "Failed to process tracker request"}), 500

        @app.route('/api/analytics/metrics', methods=['GET'])
        @require_auth
        def api_analytics_metrics():
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                
                assert self.analytics is not None  # For type checker
                    
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
        @require_auth
        def api_analytics_metric_history(metric_name):
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                
                assert self.analytics is not None  # For type checker
                    
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
        @require_auth
        def api_analytics_servers():
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                
                assert self.analytics is not None  # For type checker
                    
                return jsonify(self.analytics.get_server_summary())
                
            except Exception as e:
                logger.error(f"Analytics servers error: {e}")
                return jsonify({"error": "Failed to get server analytics"}), 500

        @app.route('/api/analytics/health', methods=['GET'])
        @require_auth
        def api_analytics_health():
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                
                assert self.analytics is not None  # For type checker
                    
                return jsonify(self.analytics.get_system_health())
                
            except Exception as e:
                logger.error(f"Analytics health error: {e}")
                return jsonify({"error": "Failed to get system health"}), 500

        @app.route('/api/analytics/snmp', methods=['GET'])
        @require_auth
        def api_analytics_snmp():
            try:
                if not self.analytics:
                    return jsonify({"error": "Analytics not available"}), 503
                
                assert self.analytics is not None  # For type checker
                    
                snmp_metrics = self.analytics.get_snmp_metrics()
                if not snmp_metrics or not isinstance(snmp_metrics, dict):
                    return jsonify({"error": "No SNMP metrics available"}), 503
                
                # Format as SNMP walk output if requested
                if request.args.get('format') == 'walk':
                    output_lines = []
                    for oid, value in dict(snmp_metrics).items():
                        output_lines.append(f"{oid} = {value}")
                    return '\n'.join(output_lines), 200, {'Content-Type': 'text/plain'}
                
                return jsonify(snmp_metrics)
                
            except Exception as e:
                logger.error(f"Analytics SNMP error: {e}")
                return jsonify({"error": "Failed to get SNMP metrics"}), 500

        # Prometheus metrics endpoint (commonly used path)
        @app.route('/metrics', methods=['GET'])
        @require_auth
        def prometheus_metrics():
            try:
                if not self.analytics:
                    return "# Analytics not available\n", 503, {'Content-Type': 'text/plain'}
                
                assert self.analytics is not None  # For type checker
                    
                return self.analytics.get_prometheus_metrics(), 200, {'Content-Type': 'text/plain'}
                
            except Exception as e:
                logger.error(f"Prometheus metrics error: {e}")
                return "# Error collecting metrics\n", 500, {'Content-Type': 'text/plain'}

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

        @app.route('/<path:filename>')
        def serve_static_files(filename):
            # Skip API routes - these should be handled by blueprints
            if filename.startswith('api/'):
                return jsonify({"error": "API endpoint not found"}), 404
            
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
            logger.debug(f"Starting web server on port {self.web_port}")
            
            cluster_thread = None
            try:
                host_type = get_host_type()
                
                if host_type == "Host":
                    logger.debug("Starting cluster API server on port 5001")
                    cluster_thread = threading.Thread(target=self._run_cluster_server, daemon=True)
                    cluster_thread.start()
                    # Give the cluster server a moment to start
                    import time
                    time.sleep(2)
                    logger.debug("Cluster API server thread started")
            except Exception as e:
                logger.error(f"Cluster API startup failed: {e}")
                import traceback
                logger.error(f"Cluster API startup traceback: {traceback.format_exc()}")
            
            # Default to localhost only for security
            default_host = "127.0.0.1"
            
            # Load security configuration from database (TODO: implement security_config table)
            security_config = None

            # Check if this is a cluster host that needs external access
            try:
                host_type = get_host_type()
                cluster_enabled = is_cluster_enabled()
                
                if security_config:
                    cluster_enabled = security_config.get("security", {}).get("cluster_enabled", cluster_enabled)
                    bind_localhost_only = security_config.get("security", {}).get("bind_localhost_only", True)
                    
                    if bind_localhost_only:
                        logger.debug("SECURITY: Security config enforcing localhost-only binding")
                    elif host_type == "Host" and cluster_enabled:
                        # For cluster hosts, allow external binding but log security warning
                        default_host = "0.0.0.0"
                        logger.warning("SECURITY: Binding to all interfaces (0.0.0.0) for cluster host - ensure firewall is configured!")
                    else:
                        logger.debug("SECURITY: Using secure default localhost binding (127.0.0.1)")
                else:
                    # Legacy behaviour - only bind to all interfaces if explicitly configured as cluster host
                    if host_type == "Host" and cluster_enabled:
                        # For cluster hosts, allow external binding but log security warning
                        default_host = "0.0.0.0"
                        logger.warning("SECURITY: Binding to all interfaces (0.0.0.0) for cluster host - ensure firewall is configured!")
                    else:
                        logger.debug("SECURITY: Using secure default localhost binding (127.0.0.1)")
            except Exception as e:
                logger.debug(f"Could not read cluster config from registry: {e}")
                if security_config and security_config.get("security", {}).get("bind_localhost_only", True):
                    logger.debug("SECURITY: Security config enforcing localhost-only binding")
                else:
                    logger.debug("SECURITY: Using secure default localhost binding (127.0.0.1)")
            
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
            
            ssl_cert_path = os.path.join(self.paths["root"], "ssl", "server.crt")
            ssl_key_path = os.path.join(self.paths["root"], "ssl", "server.key")
            ssl_enabled = os.path.exists(ssl_cert_path) and os.path.exists(ssl_key_path)
            
            if ssl_enabled:
                logger.info(f"SSL enabled with certificate and key files on {host}:{self.web_port}")
                
                redirect_thread = threading.Thread(
                    target=self._run_http_redirect_server,
                    args=(host, 8081, self.web_port),
                    daemon=True
                )
                redirect_thread.start()
                logger.info(f"HTTP redirect server started on port 8081 -> HTTPS port {self.web_port}")
            else:
                logger.debug(f"SSL disabled - running HTTP only on {host}:{self.web_port}")
            
            if not self.app:
                logger.error("Flask app not initialised - cannot start server")
                return False
                
            self._start_console_monitoring()
            
            if ssl_enabled:
                logger.info(f"Starting HTTPS server on {host}:{self.web_port}")
                # Use Waitress with SSL instead of Flask dev server for production
                import ssl as ssl_module
                ssl_context = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_SERVER)
                ssl_context.minimum_version = ssl_module.TLSVersion.TLSv1_2
                ssl_context.load_cert_chain(ssl_cert_path, ssl_key_path)
                # Disable weak ciphers
                ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS:!RC4')
                
                from waitress import create_server  # type: ignore[attr-defined]
                server = create_server(self.app, host=host, port=self.web_port, threads=8)
                server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
                logger.info(f"HTTPS server ready (TLS 1.2+, Waitress WSGI)")
                server.run()
            else:
                logger.debug(f"Starting HTTP server on {host}:{self.web_port}")
                serve(self.app, host=host, port=self.web_port, threads=8)
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
        try:
            import http.server
            import socketserver
            import urllib.request
            import urllib.parse
            
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
                        target_url = f"http://127.0.0.1:8080{self.path}"
                        
                        headers = {}
                        for header_name, header_value in self.headers.items():
                            if header_name.lower() not in ['host', 'content-length']:
                                headers[header_name] = header_value
                        
                        data = None
                        if self.command == 'POST':
                            content_length = int(self.headers.get('Content-Length', 0))
                            if content_length > 0:
                                data = self.rfile.read(content_length)
                                headers['Content-Type'] = self.headers.get('Content-Type', 'application/json')
                        
                        req = urllib.request.Request(target_url, data=data, headers=headers, method=self.command)
                        
                        try:
                            with urllib.request.urlopen(req, timeout=30) as response:
                                self.send_response(response.getcode())
                                
                                for header_name, header_value in response.headers.items():
                                    if header_name.lower() not in ['server', 'date']:
                                        self.send_header(header_name, header_value)
                                self.end_headers()
                                
                                response_data = response.read()
                                self.wfile.write(response_data)
                        except urllib.request.HTTPError as e:
                            # Handle HTTP error responses (like 304, 404, etc.)
                            self.send_response(e.code)
                            
                            for header_name, header_value in e.headers.items():
                                if header_name.lower() not in ['server', 'date']:
                                    self.send_header(header_name, header_value)
                            self.end_headers()
                            
                            response_data = e.read()
                            self.wfile.write(response_data)
                            
                    except Exception as e:
                        logger.error(f"Cluster proxy error: {e}")
                        self.send_error(502, "Bad Gateway")
            
            with socketserver.TCPServer(("0.0.0.0", 5001), ClusterAPIProxy) as httpd:
                logger.info("Cluster API proxy server started on 0.0.0.0:5001 (forwarding to 127.0.0.1:8080)")
                httpd.serve_forever()
                
        except Exception as e:
            logger.error(f"Cluster proxy server error: {e}")
            import traceback
            logger.error(f"Cluster proxy server traceback: {traceback.format_exc()}")

    def _run_http_redirect_server(self, host, redirect_port, https_port):
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler
            
            class RedirectHandler(BaseHTTPRequestHandler):
                def __init__(self, https_port, *args, **kwargs):
                    self.https_port = https_port
                    super().__init__(*args, **kwargs)
                
                def do_GET(self):
                    self.redirect_to_https()
                
                def do_POST(self):
                    self.redirect_to_https()
                
                def do_PUT(self):
                    self.redirect_to_https()
                
                def do_DELETE(self):
                    self.redirect_to_https()
                
                def do_HEAD(self):
                    self.redirect_to_https()
                
                def redirect_to_https(self):
                    https_url = f"https://{self.headers.get('Host', f'localhost:{self.https_port}')}{self.path}"
                    if ':' in self.headers.get('Host', ''):
                        host_part = self.headers['Host'].split(':')[0]
                        https_url = f"https://{host_part}:{self.https_port}{self.path}"
                    
                    self.send_response(301)
                    self.send_header('Location', https_url)
                    self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
                    self.end_headers()
                    
                    logger.debug(f"Redirected HTTP request to: {https_url}")
                
                def log_message(self, format, *args):
                    # Suppress default HTTP server logging
                    return
            
            try:
                server = HTTPServer((host, redirect_port), lambda *args: RedirectHandler(https_port, *args))
                logger.info(f"HTTP redirect server listening on {host}:{redirect_port}")
                server.serve_forever()
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    logger.warning(f"Port {redirect_port} already in use, skipping HTTP redirect server")
                else:
                    logger.error(f"Failed to start HTTP redirect server on port {redirect_port}: {e}")
                    
        except Exception as e:
            logger.error(f"HTTP redirect server error: {e}")
            import traceback
            logger.error(f"HTTP redirect server traceback: {traceback.format_exc()}")

    def _start_console_monitoring(self):
        try:
            if self.console_monitor_thread and self.console_monitor_thread.is_alive():
                return  # Already running
            
            self.console_monitor_active = True
            self.console_monitor_thread = threading.Thread(
                target=self._console_monitor_loop,
                daemon=True,
                name="WebServer-ConsoleMonitor"
            )
            self.console_monitor_thread.start()
            logger.info("Started HTTPS console monitoring thread")
        except Exception as e:
            logger.error(f"Error starting console monitoring: {e}")
    
    def _console_monitor_loop(self):
        try:
            while self.console_monitor_active:
                try:
                    self._update_console_states()
                    time.sleep(1.0)  # Check every second
                except Exception as e:
                    logger.debug(f"Console monitor error: {e}")
                    time.sleep(5)
        except Exception as e:
            logger.error(f"Fatal console monitor error: {e}")
    
    def _update_console_states(self):
        try:
            if not self.server_manager:
                return
            
            try:
                servers = self.server_manager.get_all_servers()
            except Exception as e:
                logger.debug(f"Could not get servers for console monitoring: {e}")
                return
            
            for server_name, server_config in servers.items():
                try:
                    self._update_server_console_state(server_name, server_config)
                except Exception as e:
                    logger.debug(f"Error updating console state for {server_name}: {e}")
                    
        except Exception as e:
            logger.debug(f"Error in console state update: {e}")
    
    def _update_server_console_state(self, server_name, server_config):
        try:
            pid = server_config.get('ProcessId') or server_config.get('PID')
            if not pid:
                return
            
            try:
                import psutil
                if not psutil.pid_exists(pid):
                    return
                process = psutil.Process(pid)
                if not process.is_running():
                    return
            except Exception:
                return
            
            # Check if the desktop console is already actively saving state for this server
            # If the DB was updated recently (within 5 seconds), skip log file monitoring
            # to avoid conflicts with the desktop console's authoritative data
            try:
                from Modules.Database.console_database import load_console_state_db
                existing_output, _ = load_console_state_db(server_name)
                if existing_output is not None and len(existing_output) > 0:
                    # Desktop console is actively saving - check if the data is fresh
                    # The desktop console saves every 3 seconds, so if data exists and is recent,
                    # the desktop console is handling updates. We only need to fill in gaps
                    # when there's no existing data.
                    last_entry = existing_output[-1] if existing_output else None
                    if last_entry and isinstance(last_entry, dict) and last_entry.get('timestamp'):
                        # Desktop console is providing updates, skip log-based monitoring
                        return
            except Exception:
                pass  # If check fails, proceed with log file monitoring
            
            log_files = self._discover_server_log_files(server_name, server_config)
            if not log_files:
                return

            # Read new output from log files - batch file operations for efficiency
            new_output = []
            files_to_read = []

            for log_file in log_files:
                try:
                    current_size = os.path.getsize(log_file)
                    last_pos = self.console_log_positions.get(server_name, {}).get(log_file, 0)

                    # For first time tracking, start from end to avoid dumping historical data
                    if server_name not in self.console_log_positions:
                        self.console_log_positions[server_name] = {}
                    if log_file not in self.console_log_positions.get(server_name, {}):
                        self.console_log_positions[server_name][log_file] = current_size
                        continue

                    if current_size > last_pos:
                        files_to_read.append((log_file, current_size, last_pos))
                except Exception as e:
                    logger.debug(f"Error checking log file {log_file} for {server_name}: {e}")

            for log_file, current_size, last_pos in files_to_read:
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_pos)
                        content = f.read()

                        if content:
                            lines = content.splitlines()
                            for line in lines:
                                line = line.strip()
                                if line and not self._is_old_console_entry(line):
                                    new_output.append({
                                        'text': line,
                                        'type': 'stdout',
                                        'timestamp': datetime.datetime.now().strftime("%H:%M:%S")
                                    })

                    self.console_log_positions.setdefault(server_name, {})[log_file] = current_size

                except Exception as e:
                    logger.debug(f"Error reading log file {log_file} for {server_name}: {e}")

            if new_output:
                self._append_to_console_state(server_name, new_output)
                
        except Exception as e:
            logger.debug(f"Error updating console state for {server_name}: {e}")
    
    def _discover_server_log_files(self, server_name, server_config):
        try:
            log_files = []
            
            stdout_log = server_config.get('LogStdout')
            stderr_log = server_config.get('LogStderr')
            
            if stdout_log and os.path.exists(stdout_log):
                log_files.append(stdout_log)
            if stderr_log and os.path.exists(stderr_log) and stderr_log != stdout_log:
                log_files.append(stderr_log)
            
            install_dir = server_config.get('InstallDir', '')
            if install_dir and os.path.exists(install_dir):
                for pattern in ['*.log', '*.txt', 'logs/*.log', 'logs/*.txt']:
                    full_pattern = os.path.join(install_dir, pattern)
                    for log_file in glob.glob(full_pattern):
                        if log_file not in log_files:
                            log_files.append(log_file)
            
            return log_files
        except Exception as e:
            logger.debug(f"Error discovering log files for {server_name}: {e}")
            return []
    
    def _is_old_console_entry(self, line):
        try:
            skip_patterns = [
                '--- Server started at',
                'Command:',
                'Setting breakpad',
                'SteamInternal_',
                'Looking up breakpad',
                'Calling BreakpadMiniDumpSystemInit',
                'Using breakpad'
            ]
            return any(pattern in line for pattern in skip_patterns)
        except Exception:
            return False
    
    def _append_to_console_state(self, server_name, new_output):
        try:
            try:
                from Modules.Database.console_database import save_console_state_db, load_console_state_db

                existing_output, command_history = load_console_state_db(server_name)
                if existing_output is None:
                    existing_output = []

                existing_output.extend(new_output)

                # Keep only last 2000 entries
                if len(existing_output) > 2000:
                    existing_output = existing_output[-2000:]

                save_console_state_db(
                    server_name=server_name,
                    output_buffer=existing_output,
                    command_history=command_history or [],
                    is_active=True
                )
                return
            except ImportError:
                logger.warning("Console database not available, cannot append to console state")

        except Exception as e:
            logger.debug(f"Error appending to console state for {server_name}: {e}")

    def cleanup(self):
        try:
            self.console_monitor_active = False
            if self.console_monitor_thread and self.console_monitor_thread.is_alive():
                logger.info("Stopping console monitoring thread...")
                self.console_monitor_thread.join(timeout=5)
                if self.console_monitor_thread.is_alive():
                    logger.warning("Console monitoring thread did not stop gracefully")
            
            self.shutdown_cluster_status()
            
            if hasattr(self, 'analytics') and self.analytics:
                logger.info("Stopping analytics collection...")
                self.analytics.stop_collection()
                
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
        try:
            logger.info("Testing authentication modules...")
            
            if self.sql_auth:
                try:
                    users = self.sql_auth.get_all_users()
                    logger.info(f"SQL authentication available with {len(users)} users")
                except Exception as e:
                    logger.warning(f"SQL authentication test failed: {e}")
            
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
        def heartbeat_worker():
            shutdown = getattr(self, '_shutdown_event', threading.Event())
            while not shutdown.is_set():
                try:
                    if hasattr(self, 'cluster_db') and self.cluster_db:
                        self.cluster_db.heartbeat()
                    shutdown.wait(30)  # Heartbeat every 30 seconds (interruptible)
                except Exception as e:
                    logger.error(f"Host heartbeat error: {e}")
                    shutdown.wait(60)  # Wait longer on error (interruptible)
        
        heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
        heartbeat_thread.start()
        logger.info("Host heartbeat thread started")
    
    def shutdown_cluster_status(self):
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

def main():
    try:
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
