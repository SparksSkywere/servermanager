import os
import winreg
from flask import Blueprint, jsonify

cluster_api = Blueprint("cluster_api", __name__)

def get_cluster_role():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\Servermanager")
        role = winreg.QueryValueEx(key, "HostType")[0]
        try:
            host_address = winreg.QueryValueEx(key, "HostAddress")[0]
        except Exception:
            host_address = None
        winreg.CloseKey(key)
        return role, host_address
    except Exception:
        return "Unknown", None

@cluster_api.route("/api/cluster/role", methods=["GET"])
def api_cluster_role():
    role, host_address = get_cluster_role()
    return jsonify({
        "role": role,
        "hostAddress": host_address
    })
