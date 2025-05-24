import os
import sys
import json
import logging
import winreg
import threading
import time
import signal
import argparse
from pathlib import Path
from datetime import datetime

# Import Flask and related packages
try:
    from flask import Flask, render_template, request, jsonify, send_from_directory
except ImportError:
    import subprocess
    print("Required packages not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, render_template, request, jsonify, send_from_directory

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("WebServer")

class ServerManagerWebServer:
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.web_port = 8080
        self.app = Flask(__name__)
        self.debug_mode = False
        self.servers = {}
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Server Manager Web Server')
        parser.add_argument('--debug', action='store_true', help='Enable debug mode')
        parser.add_argument('--port', type=int, help='Web server port')
        args = parser.parse_args()
        
        # Set debug mode if requested
        if args.debug:
            self.debug_mode = True
            logger.setLevel(logging.DEBUG)
            
        # Override port if specified
        if args.port:
            self.web_port = args.port
            
        # Initialize the web server
        self.initialize()
        
    def initialize(self):
        """Initialize paths and configuration from registry"""
        try:
            # Read registry for paths
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
            self.server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
            
            # Get web port from registry if not overridden by command line
            if hasattr(self, 'web_port_override') and self.web_port_override:
                self.web_port = self.web_port_override
            else:
                self.web_port = int(winreg.QueryValueEx(key, "WebPort")[0])
                
            winreg.CloseKey(key)
            
            # Define paths structure
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "config": os.path.join(self.server_manager_dir, "config"),
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "scripts": os.path.join(self.server_manager_dir, "scripts"),
                "static": os.path.join(self.server_manager_dir, "static"),
                "templates": os.path.join(self.server_manager_dir, "templates"),
                "servers": os.path.join(self.server_manager_dir, "servers")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            # Set up file logging
            log_file = os.path.join(self.paths["logs"], "webserver.log")
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            # Write PID file
            self.write_pid_file("webserver", os.getpid())
            
            # Set up Flask routes
            self.setup_routes()
            
            logger.info(f"Initialization complete. Server Manager directory: {self.server_manager_dir}")
            logger.info(f"Web server port: {self.web_port}")
            
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False
            
    def write_pid_file(self, process_type, pid):
        """Write process ID to file"""
        try:
            pid_file = os.path.join(self.paths["temp"], f"{process_type}.pid")
            
            # Create PID info dictionary
            pid_info = {
                "ProcessId": pid,
                "StartTime": datetime.now().isoformat(),
                "ProcessType": process_type
            }
            
            # Write PID info to file as JSON
            with open(pid_file, 'w') as f:
                json.dump(pid_info, f)
                
            logger.debug(f"PID file created for {process_type}: {pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to write PID file for {process_type}: {str(e)}")
            return False
            
    def setup_routes(self):
        """Set up Flask routes"""
        # Register route handlers
        @self.app.route('/')
        def index():
            try:
                # Check if template exists
                template_path = os.path.join(self.paths["templates"], "index.html")
                if os.path.exists(template_path):
                    return render_template("index.html")
                else:
                    # Provide a basic HTML if template doesn't exist
                    return """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Server Manager</title>
                        <style>
                            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
                            h1 { color: #333; }
                            .container { max-width: 800px; margin: 0 auto; }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>Server Manager Dashboard</h1>
                            <p>Welcome to the Server Manager dashboard.</p>
                            <ul>
                                <li><a href="/servers">View Servers</a></li>
                                <li><a href="/status">System Status</a></li>
                            </ul>
                        </div>
                    </body>
                    </html>
                    """
            except Exception as e:
                logger.error(f"Error rendering index: {str(e)}")
                return f"Error: {str(e)}", 500
                
        @self.app.route('/servers')
        def servers():
            try:
                servers = self.get_servers()
                return jsonify(servers)
            except Exception as e:
                logger.error(f"Error getting servers: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/server/<server_name>')
        def server_detail(server_name):
            try:
                server = self.get_server_detail(server_name)
                if server:
                    return jsonify(server)
                else:
                    return jsonify({"error": "Server not found"}), 404
            except Exception as e:
                logger.error(f"Error getting server detail: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/server/<server_name>/start', methods=['POST'])
        def start_server(server_name):
            try:
                success = self.start_server(server_name)
                return jsonify({"success": success})
            except Exception as e:
                logger.error(f"Error starting server: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/server/<server_name>/stop', methods=['POST'])
        def stop_server(server_name):
            try:
                success = self.stop_server(server_name)
                return jsonify({"success": success})
            except Exception as e:
                logger.error(f"Error stopping server: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/server/<server_name>/restart', methods=['POST'])
        def restart_server(server_name):
            try:
                success = self.restart_server(server_name)
                return jsonify({"success": success})
            except Exception as e:
                logger.error(f"Error restarting server: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/status')
        def status():
            try:
                status = self.get_system_status()
                return jsonify(status)
            except Exception as e:
                logger.error(f"Error getting system status: {str(e)}")
                return jsonify({"error": str(e)}), 500
                
        @self.app.route('/static/<path:path>')
        def serve_static(path):
            try:
                return send_from_directory(self.paths["static"], path)
            except Exception as e:
                logger.error(f"Error serving static file: {str(e)}")
                return f"Error: {str(e)}", 404
                
        # Add error handlers
        @self.app.errorhandler(404)
        def page_not_found(e):
            return jsonify({"error": "Not found"}), 404
            
        @self.app.errorhandler(500)
        def server_error(e):
            return jsonify({"error": "Internal server error"}), 500
            
    def get_servers(self):
        """Get list of all servers"""
        servers = []
        servers_dir = self.paths["servers"]
        
        try:
            if os.path.exists(servers_dir):
                for filename in os.listdir(servers_dir):
                    if filename.endswith(".json"):
                        server_path = os.path.join(servers_dir, filename)
                        with open(server_path, 'r') as f:
                            server = json.load(f)
                            servers.append(server)
            return servers
        except Exception as e:
            logger.error(f"Error getting servers: {str(e)}")
            return []
            
    def get_server_detail(self, server_name):
        """Get detailed information about a specific server"""
        server_path = os.path.join(self.paths["servers"], f"{server_name}.json")
        
        try:
            if os.path.exists(server_path):
                with open(server_path, 'r') as f:
                    server = json.load(f)
                    
                # Check if server is running
                if "PID" in server and server["PID"]:
                    try:
                        import psutil
                        if psutil.pid_exists(server["PID"]):
                            process = psutil.Process(server["PID"])
                            server["IsRunning"] = True
                            server["CPU"] = process.cpu_percent()
                            server["Memory"] = process.memory_info().rss / (1024 * 1024)  # MB
                            server["Threads"] = len(process.threads())
                        else:
                            server["IsRunning"] = False
                            server["Status"] = "Stopped"
                    except ImportError:
                        server["IsRunning"] = False
                        
                return server
            else:
                return None
        except Exception as e:
            logger.error(f"Error getting server detail: {str(e)}")
            return None
            
    def start_server(self, server_name):
        """Start a server"""
        try:
            script_path = os.path.join(self.paths["scripts"], "start_server.py")
            if os.path.exists(script_path):
                import subprocess
                result = subprocess.run([sys.executable, script_path, server_name], capture_output=True, text=True)
                logger.info(f"Start server result: {result.stdout}")
                return result.returncode == 0
            else:
                logger.error(f"Start server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error starting server: {str(e)}")
            return False
            
    def stop_server(self, server_name):
        """Stop a server"""
        try:
            script_path = os.path.join(self.paths["scripts"], "stop_server.py")
            if os.path.exists(script_path):
                import subprocess
                result = subprocess.run([sys.executable, script_path, server_name], capture_output=True, text=True)
                logger.info(f"Stop server result: {result.stdout}")
                return result.returncode == 0
            else:
                logger.error(f"Stop server script not found: {script_path}")
                return False
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            return False
            
    def restart_server(self, server_name):
        """Restart a server"""
        try:
            # Just call stop and then start
            if self.stop_server(server_name):
                time.sleep(2)  # Wait for server to fully stop
                return self.start_server(server_name)
            return False
        except Exception as e:
            logger.error(f"Error restarting server: {str(e)}")
            return False
            
    def get_system_status(self):
        """Get system status information"""
        try:
            # Try to use psutil for better system info
            try:
                import psutil
                
                # Get CPU, memory, and disk info
                cpu_percent = psutil.cpu_percent(interval=0.5)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                
                # Get network info
                net_io = psutil.net_io_counters()
                
                # Format uptime
                uptime_seconds = time.time() - psutil.boot_time()
                uptime = {
                    "days": int(uptime_seconds / 86400),
                    "hours": int((uptime_seconds % 86400) / 3600),
                    "minutes": int((uptime_seconds % 3600) / 60),
                    "seconds": int(uptime_seconds % 60)
                }
                
                return {
                    "cpu": cpu_percent,
                    "memory": {
                        "total": memory.total / (1024 * 1024 * 1024),  # GB
                        "available": memory.available / (1024 * 1024 * 1024),  # GB
                        "percent": memory.percent
                    },
                    "disk": {
                        "total": disk.total / (1024 * 1024 * 1024),  # GB
                        "free": disk.free / (1024 * 1024 * 1024),  # GB
                        "percent": disk.percent
                    },
                    "network": {
                        "bytes_sent": net_io.bytes_sent,
                        "bytes_recv": net_io.bytes_recv
                    },
                    "uptime": uptime,
                    "server_count": len(self.get_servers()),
                    "running_servers": sum(1 for s in self.get_servers() if s.get("Status") == "Running")
                }
                
            except ImportError:
                # Fallback to basic info if psutil is not available
                return {
                    "server_count": len(self.get_servers()),
                    "uptime": "Unknown (psutil not available)",
                    "cpu": "Unknown",
                    "memory": "Unknown"
                }
                
        except Exception as e:
            logger.error(f"Error getting system status: {str(e)}")
            return {"error": str(e)}
            
    def run(self):
        """Run the Flask web server"""
        try:
            # Start the Flask app
            logger.info(f"Starting web server on port {self.web_port}")
            
            # Run in a separate thread to allow clean shutdown
            threading.Thread(
                target=self.app.run,
                kwargs={
                    'host': '0.0.0.0',
                    'port': self.web_port,
                    'debug': self.debug_mode,
                    'use_reloader': False  # Disable reloader to prevent duplicate processes
                }
            ).start()
            
            # Wait for shutdown signal
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down...")
            return 0
            
        except Exception as e:
            logger.error(f"Error running web server: {str(e)}")
            return 1
            
        finally:
            # Clean up
            try:
                pid_file = os.path.join(self.paths["temp"], "webserver.pid")
                if os.path.exists(pid_file):
                    os.remove(pid_file)
            except Exception as e:
                logger.error(f"Error removing PID file: {str(e)}")

def main():
    # Register signal handlers
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(0))
    
    try:
        # Create and run web server
        web_server = ServerManagerWebServer()
        return web_server.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
