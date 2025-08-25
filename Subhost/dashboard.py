import os
import sys
import json
import time
import threading
import requests
from flask import Flask, jsonify, render_template_string

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("SubhostDashboard")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("SubhostDashboard")

app = Flask(__name__)

SUBHOST_ID = os.environ.get("SUBHOST_ID", os.uname().nodename)
HOST_URL = os.environ.get("CLUSTER_HOST_URL", "http://localhost:5001")
INFO = {"os": os.name, "cwd": os.getcwd()}
WEB_API = os.environ.get("WEB_API", "http://localhost:8080/api/tracker/servers")
AUTH_TOKEN = os.environ.get("WEB_API_TOKEN", "")

def get_headers():
    return {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

def report_status():
    while True:
        payload = {
            "subhost_id": SUBHOST_ID,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "info": INFO
        }
        try:
            # Register if not already registered
            requests.post(f"{HOST_URL}/api/register", json=payload, timeout=2)
            # Heartbeat
            requests.post(f"{HOST_URL}/api/heartbeat", json=payload, timeout=2)
            logger.debug(f"Status reported for subhost {SUBHOST_ID}")
        except Exception as e:
            logger.warning(f"Failed to report status: {str(e)}")
        time.sleep(10)

def fetch_servers():
    try:
        resp = requests.get(WEB_API, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            logger.debug("Successfully fetched server data")
            return resp.json()
        else:
            logger.warning(f"Failed to fetch servers: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Error fetching servers: {str(e)}")
    return {}

@app.route("/servers")
def servers():
    servers = fetch_servers()
    return jsonify(servers)

@app.route("/")
def index():
    servers = fetch_servers()
    html = """
    <h1>Subhost Dashboard</h1>
    <ul>
        <li>ID: {{subhost_id}}</li>
        <li>Host: {{host_url}}</li>
        <li>Info: <pre>{{info}}</pre></li>
    </ul>
    <h2>Servers</h2>
    <pre>{{servers}}</pre>
    <p>Status is being reported to the cluster host.</p>
    """
    return render_template_string(html, subhost_id=SUBHOST_ID, host_url=HOST_URL, info=json.dumps(INFO, indent=2), servers=json.dumps(servers, indent=2))

if __name__ == "__main__":
    threading.Thread(target=report_status, daemon=True).start()
    app.run(host="0.0.0.0", port=5002)
