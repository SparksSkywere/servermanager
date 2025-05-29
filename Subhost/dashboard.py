import os
import json
import time
import threading
import requests
from flask import Flask, jsonify, render_template_string

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
        except Exception:
            pass
        time.sleep(10)

def fetch_servers():
    try:
        resp = requests.get(WEB_API, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
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
