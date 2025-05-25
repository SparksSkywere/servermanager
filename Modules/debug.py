import os
import sys
import json
import logging
import platform
import datetime
import traceback
import psutil
import winreg
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("DebugModule")

class DebugManager:
    """Simplified class for system diagnostics and debugging"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.debug_enabled = False
        
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
                "temp": os.path.join(self.server_manager_dir, "temp"),
                "debug": os.path.join(self.server_manager_dir, "logs", "debug")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
            logger.info(f"Debug manager initialized from registry")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize debug manager from registry: {str(e)}")
            
            # Use a fallback path
            self.server_manager_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "debug": os.path.join(self.server_manager_dir, "logs", "debug")
            }
            
            # Ensure directories exist
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
                
            return False
    
    def set_debug_mode(self, enabled=True):
        """Enable or disable debug mode"""
        self.debug_enabled = enabled
        level = logging.DEBUG if enabled else logging.INFO
        logger.setLevel(level)
        
        # Update root logger as well
        logging.getLogger().setLevel(level)
        
        logger.info(f"Debug mode {'enabled' if enabled else 'disabled'}")
        return True
    
    def is_debug_enabled(self):
        """Check if debug mode is enabled"""
        return self.debug_enabled
    
    def get_system_info(self):
        """Get basic system information"""
        try:
            # Basic system info
            system_info = {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.architecture(),
                "processor": platform.processor(),
                "python_version": platform.python_version()
            }
            
            # CPU info
            cpu_info = {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "cpu_percent": psutil.cpu_percent(interval=0.1)
            }
            
            # Memory info
            memory = psutil.virtual_memory()
            memory_info = {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent
            }
            
            # Disk info
            disk = psutil.disk_usage('/')
            disk_info = {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            }
            
            # Network info
            net_io = psutil.net_io_counters()
            network_info = {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            }
            
            # Server Manager info
            sm_info = {
                "install_dir": self.server_manager_dir,
                "debug_enabled": self.debug_enabled
            }
            
            # Combine all info
            info = {
                "system": system_info,
                "cpu": cpu_info,
                "memory": memory_info,
                "disk": disk_info,
                "network": network_info,
                "server_manager": sm_info,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            return info
        except Exception as e:
            logger.error(f"Failed to get system information: {str(e)}")
            return {"error": str(e)}
    
    def get_process_info(self, pid):
        """Get information about a specific process"""
        try:
            if not pid or not psutil.pid_exists(pid):
                return None
                
            process = psutil.Process(pid)
            
            info = {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "created": datetime.datetime.fromtimestamp(process.create_time()).isoformat(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_info": {
                    "rss": process.memory_info().rss,
                    "vms": process.memory_info().vms
                }
            }
            
            return info
        except Exception as e:
            logger.error(f"Failed to get process information for PID {pid}: {str(e)}")
            return None
    
    def get_server_status(self, server_name=None):
        """Get status of a specific server"""
        try:
            servers_dir = os.path.join(self.server_manager_dir, "servers")
            
            if not os.path.exists(servers_dir):
                return {"error": "Servers directory not found"}
            
            if server_name:
                # Get status for specific server
                server_file = os.path.join(servers_dir, f"{server_name}.json")
                if not os.path.exists(server_file):
                    return {"error": f"Server configuration not found: {server_name}"}
                
                with open(server_file, 'r') as f:
                    server_config = json.load(f)
                
                # Check if process is running
                if "PID" in server_config and server_config["PID"]:
                    try:
                        pid = int(server_config["PID"])
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            server_config["IsRunning"] = process.is_running()
                            server_config["CPU"] = process.cpu_percent(interval=0.1)
                            server_config["Memory"] = process.memory_info().rss
                        else:
                            server_config["IsRunning"] = False
                    except:
                        server_config["IsRunning"] = False
                else:
                    server_config["IsRunning"] = False
                
                return server_config
            else:
                # Get status for all servers
                servers = []
                for filename in os.listdir(servers_dir):
                    if filename.endswith(".json"):
                        server_name = filename[:-5]  # Remove .json extension
                        server_status = self.get_server_status(server_name)
                        servers.append(server_status)
                
                return servers
        except Exception as e:
            logger.error(f"Failed to get server status: {str(e)}")
            return {"error": str(e)}
    
    def create_diagnostic_report(self):
        """Create a simplified diagnostic report"""
        try:
            report = {
                "timestamp": datetime.datetime.now().isoformat(),
                "system_info": self.get_system_info(),
                "servers": self.get_server_status()
            }
            
            # Add basic registry information
            try:
                registry_info = {}
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.registry_path)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        registry_info[name] = value
                        i += 1
                    except WindowsError:
                        break
                winreg.CloseKey(key)
                report["registry"] = registry_info
            except:
                report["registry"] = {"error": "Failed to read registry"}
            
            # Add file system check
            try:
                fs_check = {}
                for path_name, path in self.paths.items():
                    fs_check[path_name] = {
                        "path": path,
                        "exists": os.path.exists(path),
                        "is_dir": os.path.isdir(path) if os.path.exists(path) else False,
                        "writable": os.access(path, os.W_OK) if os.path.exists(path) else False
                    }
                report["file_system_check"] = fs_check
            except:
                report["file_system_check"] = {"error": "Failed to check file system"}
            
            # Save report to file
            report_path = os.path.join(self.paths["debug"], f"diagnostic_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"Diagnostic report created: {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"Failed to create diagnostic report: {str(e)}")
            return None
    
    def log_exception(self, e, message="An exception occurred"):
        """Log an exception with traceback"""
        exc_info = sys.exc_info()
        if exc_info[0] is not None:
            tb_text = ''.join(traceback.format_exception(*exc_info))
            logger.error(f"{message}: {str(e)}\n{tb_text}")
        else:
            logger.error(f"{message}: {str(e)}")

# Create a global instance for easy access
debug_manager = DebugManager()

# Export functions for easy access
def get_system_info():
    """Get basic system information"""
    return debug_manager.get_system_info()

def create_diagnostic_report():
    """Create a diagnostic report"""
    return debug_manager.create_diagnostic_report()

def enable_debug():
    """Enable debug mode"""
    return debug_manager.set_debug_mode(True)

def disable_debug():
    """Disable debug mode"""
    return debug_manager.set_debug_mode(False)

def is_debug_enabled():
    """Check if debug mode is enabled"""
    return debug_manager.is_debug_enabled()

def get_process_info(pid):
    """Get information about a specific process"""
    return debug_manager.get_process_info(pid)

def get_server_status(server_name=None):
    """Get status of a specific server or all servers"""
    return debug_manager.get_server_status(server_name)

def log_exception(e, message="An exception occurred"):
    """Log an exception with traceback"""
    debug_manager.log_exception(e, message)
