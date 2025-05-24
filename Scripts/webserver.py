import os
import sys
import json
import logging
import winreg
import argparse
import datetime
import threading
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("WebServer")

# Import Flask for web server
try:
    from flask import Flask, render_template, request, jsonify, redirect, url_for, session
except ImportError:
    logger.error("Flask not installed. Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, render_template, request, jsonify, redirect, url_for, session

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

# Get the server manager directory and add the modules path to sys.path
server_manager_dir = get_server_manager_dir()
modules_path = os.path.join(server_manager_dir, "modules")
if modules_path not in sys.path:
    sys.path.append(modules_path)

# Now import modules from the determined path
try:
    # Import modules from the modules directory
    from common import paths, process_manager, config_manager
    from server_operations import (
        get_all_servers, get_server_status, start_server, stop_server, 
        restart_server, install_server, check_for_updates
    )
    from authentication import authenticate_user, get_all_users, is_admin_user
    from security import is_admin
    
    logger.info(f"Successfully imported modules from: {modules_path}")
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    logger.error(f"Modules path: {modules_path}")
    logger.error(f"sys.path: {sys.path}")
    sys.exit(1)

class ServerManagerWebServer:
    """Web server for Server Manager"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = server_manager_dir  # Use the already determined directory
        self.web_port = 8080
        self.debug_mode = False
        self.paths = {}
        
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
        
        # Create Flask app
        self.app = Flask(
            __name__,
            template_folder=os.path.join(self.paths.get("root", ""), "templates"),
            static_folder=os.path.join(self.paths.get("root", ""), "static")
        )
        
        # Set up Flask secret key
        self.app.secret_key = os.urandom(24)
        
        # Set up routes
        self.setup_routes()
        
        # Write PID file
        self.write_pid_file()
    
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
                
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "static": os.path.join(self.server_manager_dir, "static")
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
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "static": os.path.join(self.server_manager_dir, "static")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Set up file logging in fallback location
            log_file = os.path.join(self.paths["logs"], "webserver.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            logger.warning(f"Using fallback paths. Server Manager directory: {self.server_manager_dir}")
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
                "Port": self.web_port
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
        
        # Login required decorator
        def login_required(f):
            from functools import wraps
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if 'user' not in session:
                    return redirect(url_for('login', next=request.url))
                return f(*args, **kwargs)
            return decorated_function
        
        # Admin required decorator
        def admin_required(f):
            from functools import wraps
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if 'user' not in session:
                    return redirect(url_for('login', next=request.url))
                if not is_admin_user(session['user']):
                    return jsonify({"error": "Admin privileges required"}), 403
                return f(*args, **kwargs)
            return decorated_function
        
        # Login route
        @app.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                username = request.form.get('username')
                password = request.form.get('password')
                
                if authenticate_user(username, password):
                    session['user'] = username
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard'))
                else:
                    return render_template('login.html', error="Invalid username or password")
            
            return render_template('login.html')
        
        # Logout route
        @app.route('/logout')
        def logout():
            session.pop('user', None)
            return redirect(url_for('login'))
        
        # Dashboard route
        @app.route('/')
        @login_required
        def dashboard():
            servers = get_all_servers()
            return render_template('dashboard.html', 
                                 username=session.get('user'),
                                 is_admin=is_admin_user(session.get('user')),
                                 servers=servers)
        
        # API routes
        
        # Get all servers
        @app.route('/api/servers', methods=['GET'])
        @login_required
        def api_servers():
            servers = get_all_servers()
            return jsonify(servers)
        
        # Get server status
        @app.route('/api/servers/<server_name>', methods=['GET'])
        @login_required
        def api_server_status(server_name):
            status = get_server_status(server_name)
            if status:
                return jsonify(status)
            else:
                return jsonify({"error": "Server not found"}), 404
        
        # Start server
        @app.route('/api/servers/<server_name>/start', methods=['POST'])
        @login_required
        def api_start_server(server_name):
            result = start_server(server_name)
            if result:
                return jsonify({"success": True, "message": f"Server {server_name} started"})
            else:
                return jsonify({"success": False, "error": f"Failed to start server {server_name}"}), 500
        
        # Stop server
        @app.route('/api/servers/<server_name>/stop', methods=['POST'])
        @login_required
        def api_stop_server(server_name):
            force = request.json.get('force', False) if request.is_json else False
            result = stop_server(server_name, force)
            if result:
                return jsonify({"success": True, "message": f"Server {server_name} stopped"})
            else:
                return jsonify({"success": False, "error": f"Failed to stop server {server_name}"}), 500
        
        # Restart server
        @app.route('/api/servers/<server_name>/restart', methods=['POST'])
        @login_required
        def api_restart_server(server_name):
            result = restart_server(server_name)
            if result:
                return jsonify({"success": True, "message": f"Server {server_name} restarted"})
            else:
                return jsonify({"success": False, "error": f"Failed to restart server {server_name}"}), 500
        
        # Check for updates
        @app.route('/api/servers/<server_name>/check-updates', methods=['GET'])
        @login_required
        def api_check_updates(server_name):
            has_updates = check_for_updates(server_name)
            return jsonify({"updates_available": has_updates})
        
        # Install/update server
        @app.route('/api/servers/<server_name>/install', methods=['POST'])
        @login_required
        def api_install_server(server_name):
            validate = request.json.get('validate', True) if request.is_json else True
            result = install_server(server_name, validate)
            if result:
                return jsonify({"success": True, "message": f"Server {server_name} installed/updated"})
            else:
                return jsonify({"success": False, "error": f"Failed to install/update server {server_name}"}), 500
        
        # User management - admin only
        
        # Get all users
        @app.route('/api/users', methods=['GET'])
        @admin_required
        def api_users():
            users = get_all_users()
            return jsonify(users)
        
        # Add more routes as needed
        
        # Error handlers
        @app.errorhandler(404)
        def page_not_found(e):
            return render_template('404.html'), 404
        
        @app.errorhandler(500)
        def internal_server_error(e):
            return render_template('500.html'), 500
    
    def run(self):
        """Run the web server"""
        try:
            logger.info(f"Starting web server on port {self.web_port}")
            
            # Run in a new thread to allow for stopping
            threading.Thread(
                target=self.app.run,
                kwargs={'host': '0.0.0.0', 'port': self.web_port, 'debug': self.debug_mode},
                daemon=True
            ).start()
            
            # Keep the main thread alive
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Web server stopping due to keyboard interrupt")
        except Exception as e:
            logger.error(f"Web server error: {str(e)}")
            return False
        
        return True

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
