import os
import sys
import json
import time
import threading
import requests
import winreg
from flask import Flask, jsonify, render_template_string

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import centralized registry constants
from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SubhostDashboard")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SubhostDashboard")

app = Flask(__name__)

# Get configuration from registry
def get_subhost_config():
    """Get subhost configuration from registry"""
    try:
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        try:
            host_address = winreg.QueryValueEx(key, "HostAddress")[0]
        except:
            host_address = "localhost:5001"
        
        try:
            subhost_id = winreg.QueryValueEx(key, "SubhostID")[0]
        except:
            # Generate a unique ID if not set
            import socket
            subhost_id = f"{socket.gethostname()}-{os.getpid()}"
            
        winreg.CloseKey(key)
        return subhost_id, host_address
    except Exception as e:
        logger.warning(f"Could not read subhost config from registry: {e}")
        import socket
        return f"{socket.gethostname()}-{os.getpid()}", "localhost:5001"

SUBHOST_ID, HOST_ADDRESS = get_subhost_config()
HOST_URL = f"http://{HOST_ADDRESS}"
INFO = {
    "os": os.name,
    "cwd": os.getcwd(),
    "api_url": f"http://localhost:8080",  # This subhost's API URL
    "python_version": sys.version,
    "subhost_version": "1.0.0"
}
WEB_API = os.environ.get("WEB_API", "http://localhost:8080/api/tracker/servers")
AUTH_TOKEN = os.environ.get("WEB_API_TOKEN", "")

def get_headers():
    return {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

def report_status():
    """Report status to host with retries and error handling"""
    retry_count = 0
    max_retries = 3
    base_delay = 10
    
    while True:
        payload = {
            "subhost_id": SUBHOST_ID,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "info": INFO
        }
        
        try:
            # Try to register first (idempotent operation)
            register_response = requests.post(f"{HOST_URL}/api/cluster/register", 
                                            json=payload, timeout=5)
            if register_response.status_code == 200:
                logger.debug(f"Registration successful for subhost {SUBHOST_ID}")
            
            # Send heartbeat
            heartbeat_response = requests.post(f"{HOST_URL}/api/cluster/heartbeat", 
                                             json=payload, timeout=5)
            if heartbeat_response.status_code == 200:
                logger.debug(f"Heartbeat sent successfully for subhost {SUBHOST_ID}")
                retry_count = 0  # Reset retry count on success
            else:
                logger.warning(f"Heartbeat failed with status {heartbeat_response.status_code}")
                
        except requests.RequestException as e:
            retry_count += 1
            logger.warning(f"Failed to report status (attempt {retry_count}/{max_retries}): {str(e)}")
            
            if retry_count >= max_retries:
                # Exponential backoff
                delay = base_delay * (2 ** min(retry_count - max_retries, 5))
                logger.error(f"Max retries exceeded, waiting {delay} seconds before next attempt")
                time.sleep(delay)
                retry_count = 0  # Reset after long delay
                continue
        
        # Standard reporting interval
        time.sleep(base_delay)

def fetch_servers():
    """Fetch servers from local API with error handling"""
    try:
        resp = requests.get(WEB_API, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            logger.debug("Successfully fetched server data")
            return resp.json()
        else:
            logger.warning(f"Failed to fetch servers: HTTP {resp.status_code}")
    except requests.RequestException as e:
        logger.error(f"Error fetching servers: {str(e)}")
    return {}

@app.route("/servers")
def servers():
    """Get servers endpoint for cluster communication"""
    servers = fetch_servers()
    return jsonify(servers)

@app.route("/status")  
def status():
    """Get subhost status"""
    return jsonify({
        "subhost_id": SUBHOST_ID,
        "host_url": HOST_URL,
        "status": "active",
        "info": INFO,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route("/")
def index():
    """Main subhost dashboard page"""
    servers = fetch_servers()
    
    # Get cluster status
    cluster_status = "Unknown"
    try:
        resp = requests.get(f"{HOST_URL}/api/cluster/status", timeout=3)
        if resp.status_code == 200:
            cluster_status = "Connected to Host"
        else:
            cluster_status = f"Host connection error: {resp.status_code}"
    except Exception as e:
        cluster_status = f"Host unreachable: {str(e)}"
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subhost Dashboard - {{subhost_id}}</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
            .status-card { background: white; padding: 15px; border-radius: 5px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            .status-good { border-left: 5px solid #27ae60; }
            .status-warning { border-left: 5px solid #f39c12; }
            .status-error { border-left: 5px solid #e74c3c; }
            .server-list { background: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            pre { background: #ecf0f1; padding: 10px; border-radius: 3px; overflow-x: auto; }
            .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
            @media (max-width: 768px) { .info-grid { grid-template-columns: 1fr; } }
        </style>
        <script>
            // Auto-refresh every 30 seconds
            setTimeout(function(){ window.location.reload(); }, 30000);
        </script>
    </head>
    <body>
        <div class="header">
            <h1>🖥️ Subhost Dashboard</h1>
            <p>Subhost ID: <strong>{{subhost_id}}</strong> | Connected to: <strong>{{host_url}}</strong></p>
        </div>
        
        <div class="info-grid">
            <div class="status-card {% if 'Connected' in cluster_status %}status-good{% elif 'error' in cluster_status %}status-error{% else %}status-warning{% endif %}">
                <h3>🔗 Cluster Status</h3>
                <p><strong>{{cluster_status}}</strong></p>
                <small>Last updated: {{timestamp}}</small>
            </div>
            
            <div class="status-card status-good">
                <h3>📊 System Information</h3>
                <p><strong>OS:</strong> {{info.os}}</p>
                <p><strong>Python:</strong> {{info.python_version}}</p>
                <p><strong>Working Directory:</strong> {{info.cwd}}</p>
            </div>
        </div>
        
        <div class="server-list">
            <h2>🎮 Local Servers</h2>
            {% if servers %}
                <pre>{{servers}}</pre>
            {% else %}
                <p>No servers found or unable to connect to local server manager.</p>
            {% endif %}
        </div>
        
        <div class="status-card">
            <h3>🔄 Auto-Reporting</h3>
            <p>This subhost automatically reports its status to the cluster host every 10 seconds.</p>
            <p>The dashboard auto-refreshes every 30 seconds.</p>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, 
                                subhost_id=SUBHOST_ID, 
                                host_url=HOST_URL, 
                                info=INFO,
                                servers=json.dumps(servers, indent=2),
                                cluster_status=cluster_status,
                                timestamp=time.strftime("%Y-%m-%d %H:%M:%S"))

if __name__ == "__main__":
    # Start the status reporting thread
    reporting_thread = threading.Thread(target=report_status, daemon=True)
    reporting_thread.start()
    logger.info(f"Starting subhost dashboard for {SUBHOST_ID} connecting to {HOST_URL}")
    app.run(host="0.0.0.0", port=5002, debug=False)
