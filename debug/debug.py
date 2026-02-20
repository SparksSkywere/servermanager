# System diagnostics and debugging
import os
import sys
import json
import logging
import platform
import datetime
import traceback
import psutil
import winreg
import socket

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path, setup_module_logging, REGISTRY_PATH, get_server_manager_dir
setup_module_path()

try:
    from Modules.server_logging import get_debug_logger
    logger = get_debug_logger("debug")
except Exception:
    logger = setup_module_logging("Debug")


class DebugManager:
    # - System diagnostics
    # - Log collection
    def __init__(self):
        self.registry_path = REGISTRY_PATH
        self.server_manager_dir = None
        self.paths = {}
        self.debug_enabled = False
        self.initialise_from_registry()
    
    def initialise_from_registry(self):
        # Pull paths from registry
        self.server_manager_dir = get_server_manager_dir()
        
        self.paths = {
            "root": self.server_manager_dir,
            "logs": os.path.join(self.server_manager_dir, "logs"),
            "temp": os.path.join(self.server_manager_dir, "temp"),
            "debug": os.path.join(self.server_manager_dir, "logs", "debug")
        }
            
        for path in self.paths.values():
            os.makedirs(path, exist_ok=True)
        
        logger.info(f"Debug manager initialised")
        return True
    
    def set_debug_mode(self, enabled=True):
        # Enable or disable debug mode
        self.debug_enabled = enabled
        level = logging.DEBUG if enabled else logging.INFO
        logger.setLevel(level)
        
        # Update root logger as well
        logging.getLogger().setLevel(level)
        
        logger.info(f"Debug mode {'enabled' if enabled else 'disabled'}")
        return True
    
    def is_debug_enabled(self):
        # Check if debug mode is enabled
        return self.debug_enabled
    
    def get_system_info(self):
        # Get basic system information
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
            
            # Disk info (use C:\ on Windows, fallback to / on other systems)
            try:
                if platform.system() == 'Windows':
                    disk = psutil.disk_usage('C:\\')
                else:
                    disk = psutil.disk_usage('/')
                disk_info = {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                }
            except Exception:
                disk_info = {
                    "total": 0,
                    "used": 0,
                    "free": 0,
                    "percent": 0,
                    "error": "Unable to get disk usage"
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
        # Get information about a specific process
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
        # Get status of a specific server
        try:
            if not self.server_manager_dir:
                return {"error": "Server manager directory not initialised"}
            
            # Get server config from database
            try:
                from Modules.Database.server_configs_database import ServerConfigManager
                manager = ServerConfigManager()
            except Exception as e:
                return {"error": f"Failed to access database: {str(e)}"}
            
            if server_name:
                # Get status for specific server
                server_config = manager.get_server(server_name)
                if not server_config:
                    return {"error": f"Server configuration not found: {server_name}"}
                
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
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
                        server_config["IsRunning"] = False
                else:
                    server_config["IsRunning"] = False
                
                return server_config
            else:
                # Get status for all servers
                all_servers = manager.get_all_servers()
                servers = []
                for server in all_servers:
                    sname = server.get("Name", "Unknown")
                    server_status = self.get_server_status(sname)
                    servers.append(server_status)
                
                return servers
        except Exception as e:
            logger.error(f"Failed to get server status: {str(e)}")
            return {"error": str(e)}
    
    def get_detailed_process_info(self, pid):
        # Get comprehensive process information including children, files, etc.
        try:
            if not pid or not psutil.pid_exists(pid):
                return None
                
            process = psutil.Process(pid)
            
            # Basic process info
            basic_info = {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "created": datetime.datetime.fromtimestamp(process.create_time()).isoformat(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_info": {
                    "rss": process.memory_info().rss,
                    "vms": process.memory_info().vms
                },
                "num_threads": process.num_threads()
            }
            
            # Try to get executable path
            try:
                basic_info["exe"] = process.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                basic_info["exe"] = "Access Denied"
            
            # Try to get command line
            try:
                basic_info["cmdline"] = process.cmdline()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                basic_info["cmdline"] = ["Access Denied"]
            
            # Try to get working directory
            try:
                basic_info["cwd"] = process.cwd()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                basic_info["cwd"] = "Access Denied"
            
            # Get child processes
            children = []
            try:
                for child in process.children(recursive=False):
                    try:
                        child_info = {
                            "pid": child.pid,
                            "name": child.name(),
                            "status": child.status(),
                            "cpu_percent": child.cpu_percent(interval=0.1),
                            "memory_mb": child.memory_info().rss / (1024 * 1024)
                        }
                        children.append(child_info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        # Process might have terminated
                        pass
            except (psutil.AccessDenied, psutil.ZombieProcess):
                pass
            
            basic_info["children"] = children
            
            # Get open files
            try:
                open_files = process.open_files()
                basic_info["open_files_count"] = len(open_files)
                basic_info["open_files"] = [f.path for f in open_files[:10]]  # Limit to first 10
            except (psutil.AccessDenied, psutil.ZombieProcess):
                basic_info["open_files_count"] = "Access Denied"
                basic_info["open_files"] = []
            
            # Get network connections
            try:
                connections = process.connections()
                basic_info["connections_count"] = len(connections)
                basic_info["connections"] = [
                    {
                        "family": conn.family.name if conn.family else "Unknown",
                        "type": conn.type.name if conn.type else "Unknown",
                        "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "N/A",
                        "remote_address": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                        "status": conn.status
                    } for conn in connections[:10]  # Limit to first 10
                ]
            except (psutil.AccessDenied, psutil.ZombieProcess):
                basic_info["connections_count"] = "Access Denied"
                basic_info["connections"] = []
            
            return basic_info
        except Exception as e:
            logger.error(f"Failed to get detailed process information for PID {pid}: {str(e)}")
            return None
    
    def check_port_status(self, host="localhost", port=8080, timeout=1):
        # Check if a port is open on the specified host
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                return result == 0
        except Exception as e:
            logger.error(f"Error checking port {host}:{port}: {str(e)}")
            return False
    
    def get_network_info(self):
        # Get detailed network information
        try:
            network_info = {
                "interfaces": {},
                "connections": [],
                "io_counters": {}
            }
            
            # Get network interfaces
            for interface_name, addresses in psutil.net_if_addrs().items():
                interface_info = []
                for addr in addresses:
                    addr_info = {
                        "family": addr.family.name if hasattr(addr.family, 'name') else str(addr.family),
                        "address": addr.address,
                        "netmask": addr.netmask,
                        "broadcast": addr.broadcast
                    }
                    interface_info.append(addr_info)
                network_info["interfaces"][interface_name] = interface_info
            
            # Get network I/O counters
            io_counters = psutil.net_io_counters(pernic=True)
            for interface, counters in io_counters.items():
                network_info["io_counters"][interface] = {
                    "bytes_sent": counters.bytes_sent,
                    "bytes_recv": counters.bytes_recv,
                    "packets_sent": counters.packets_sent,
                    "packets_recv": counters.packets_recv,
                    "errin": counters.errin,
                    "errout": counters.errout,
                    "dropin": counters.dropin,
                    "dropout": counters.dropout
                }
            
            # Get active connections (limited to first 20)
            try:
                connections = psutil.net_connections()[:20]
                for conn in connections:
                    conn_info = {
                        "family": conn.family.name if conn.family else "Unknown",
                        "type": conn.type.name if conn.type else "Unknown",
                        "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "N/A",
                        "remote_address": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                        "status": conn.status,
                        "pid": conn.pid
                    }
                    network_info["connections"].append(conn_info)
            except psutil.AccessDenied:
                network_info["connections"] = ["Access Denied - requires administrator privileges"]
            
            return network_info
        except Exception as e:
            logger.error(f"Failed to get network information: {str(e)}")
            return {"error": str(e)}
    
    def get_disk_info(self):
        # Get detailed disk information
        try:
            disk_info = {
                "partitions": [],
                "usage": {}
            }
            
            # Get disk partitions
            for partition in psutil.disk_partitions():
                partition_info: dict = {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "opts": partition.opts
                }
                
                # Get usage for this partition
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    usage_dict: dict = {
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": (usage.used / usage.total) * 100 if usage.total > 0 else 0
                    }
                    partition_info["usage"] = usage_dict
                except PermissionError:
                    error_dict: dict = {"error": "Access Denied"}
                    partition_info["usage"] = error_dict
                
                disk_info["partitions"].append(partition_info)
            
            # Get disk I/O counters
            try:
                disk_io = psutil.disk_io_counters(perdisk=True)
                disk_info["io_counters"] = {}
                for disk, counters in disk_io.items():
                    disk_info["io_counters"][disk] = {
                        "read_count": counters.read_count,
                        "write_count": counters.write_count,
                        "read_bytes": counters.read_bytes,
                        "write_bytes": counters.write_bytes,
                        "read_time": counters.read_time,
                        "write_time": counters.write_time
                    }
            except Exception:
                disk_info["io_counters"] = {"error": "Could not retrieve I/O counters"}
            
            return disk_info
        except Exception as e:
            logger.error(f"Failed to get disk information: {str(e)}")
            return {"error": str(e)}
    
    def monitor_process_resources(self, pid, duration=5):
        # Monitor a process's resource usage over time
        try:
            if not psutil.pid_exists(pid):
                return {"error": f"Process {pid} does not exist"}
            
            process = psutil.Process(pid)
            measurements = []
            
            # Take measurements every second for the specified duration
            for i in range(duration):
                try:
                    measurement = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "cpu_percent": process.cpu_percent(interval=1),
                        "memory_info": {
                            "rss": process.memory_info().rss,
                            "vms": process.memory_info().vms
                        },
                        "memory_percent": process.memory_percent(),
                        "num_threads": process.num_threads(),
                        "status": process.status()
                    }
                    measurements.append(measurement)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    break
            
            return {
                "pid": pid,
                "measurements": measurements,
                "duration": duration,
                "sample_count": len(measurements)
            }
        except Exception as e:
            logger.error(f"Failed to monitor process {pid}: {str(e)}")
            return {"error": str(e)}
    
    def create_diagnostic_report(self):
        # Create a comprehensive diagnostic report
        try:
            report = {
                "timestamp": datetime.datetime.now().isoformat(),
                "system_info": self.get_system_info(),
                "servers": self.get_server_status(),
                "network_info": self.get_network_info(),
                "disk_info": self.get_disk_info()
            }
            
            # Add basic registry information
            try:
                from Modules.common import REGISTRY_ROOT
                registry_info = {}
                key = winreg.OpenKey(REGISTRY_ROOT, self.registry_path)
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
            except (FileNotFoundError, OSError):
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
            except OSError:
                report["file_system_check"] = {"error": "Failed to check file system"}
            
            # Add running processes summary
            try:
                running_processes = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        if proc.info['cpu_percent'] > 1.0 or proc.info['memory_percent'] > 1.0:
                            running_processes.append(proc.info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # Sort by CPU usage and take top 10
                running_processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
                report["top_processes"] = running_processes[:10]
            except (psutil.Error, OSError):
                report["top_processes"] = {"error": "Failed to get process list"}
            
            # Add port checks for common server ports
            try:
                port_checks = {}
                common_ports = [8080, 3389, 22, 80, 443, 21, 25, 53, 110, 993, 995]
                for port in common_ports:
                    port_checks[port] = self.check_port_status("localhost", port)
                report["port_status"] = port_checks
            except OSError:
                report["port_status"] = {"error": "Failed to check ports"}
            
            # Save report to file
            report_path = os.path.join(self.paths["debug"], f"diagnostic_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"Comprehensive diagnostic report created: {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"Failed to create diagnostic report: {str(e)}")
            return None
    
    def log_exception(self, e, message="An exception occurred"):
        # Log an exception with traceback
        exc_info = sys.exc_info()
        if exc_info[0] is not None:
            tb_text = ''.join(traceback.format_exception(*exc_info))
            logger.error(f"{message}: {str(e)}\n{tb_text}")
        else:
            logger.error(f"{message}: {str(e)}")
    
    def get_server_process_details(self, server_name):
        # Get detailed process information for a specific server
        try:
            if not self.server_manager_dir:
                return {"error": "Server manager directory not initialised"}
                
            # Get server config from database
            try:
                from Modules.Database.server_configs_database import ServerConfigManager
                manager = ServerConfigManager()
                server_config = manager.get_server(server_name)
            except Exception as e:
                return {"error": f"Failed to access database: {str(e)}"}
            
            if not server_config:
                return {"error": f"Server configuration not found: {server_name}"}
                
            # Check if server has a process ID registered
            if 'ProcessId' not in server_config:
                return {"error": f"Server '{server_name}' is not running"}
                
            process_id = server_config['ProcessId']
            
            # Check if process is still running
            if not psutil.pid_exists(process_id):
                return {"error": f"Server process (PID {process_id}) is not running"}
            
            # Get detailed process information
            process_details = self.get_detailed_process_info(process_id)
            if not process_details:
                return {"error": f"Could not retrieve process details for PID {process_id}"}
            
            # Add server-specific information
            process_details["server_name"] = server_name
            process_details["server_config"] = server_config
            
            # Calculate uptime from server start time if available
            if 'StartTime' in server_config:
                try:
                    start_time = datetime.datetime.fromisoformat(server_config['StartTime'])
                    uptime = datetime.datetime.now() - start_time
                    days = uptime.days
                    hours, remainder = divmod(uptime.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    if days > 0:
                        uptime_str = f"{days}d {hours}h {minutes}m"
                    else:
                        uptime_str = f"{hours}h {minutes}m {seconds}s"
                    
                    process_details["server_uptime"] = uptime_str
                except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
                    process_details["server_uptime"] = "Unknown"
            else:
                process_details["server_uptime"] = "Unknown"
            
            return process_details
            
        except Exception as e:
            logger.error(f"Failed to get server process details for {server_name}: {str(e)}")
            return {"error": str(e)}

# Create a global instance for easy access
debug_manager = DebugManager()

# Export functions for easy access
def get_system_info():
    # Get basic system information
    return debug_manager.get_system_info()

def create_diagnostic_report():
    # Create a comprehensive diagnostic report
    return debug_manager.create_diagnostic_report()

def enable_debug():
    # Enable debug mode
    return debug_manager.set_debug_mode(True)

def disable_debug():
    # Disable debug mode
    return debug_manager.set_debug_mode(False)

def is_debug_enabled():
    # Check if debug mode is enabled
    return debug_manager.is_debug_enabled()

def get_process_info(pid):
    # Get information about a specific process
    return debug_manager.get_process_info(pid)

def get_detailed_process_info(pid):
    # Get comprehensive process information including children, files, etc.
    return debug_manager.get_detailed_process_info(pid)

def get_server_status(server_name=None):
    # Get status of a specific server or all servers
    return debug_manager.get_server_status(server_name)

def get_network_info():
    # Get detailed network information
    return debug_manager.get_network_info()

def get_disk_info():
    # Get detailed disk information
    return debug_manager.get_disk_info()

def check_port_status(host="localhost", port=8080, timeout=1):
    # Check if a port is open on the specified host
    return debug_manager.check_port_status(host, port, timeout)

def monitor_process_resources(pid, duration=5):
    # Monitor a process's resource usage over time
    return debug_manager.monitor_process_resources(pid, duration)

def get_server_process_details(server_name):
    # Get detailed process information for a specific server
    return debug_manager.get_server_process_details(server_name)

def log_exception(e, message="An exception occurred"):
    # Log an exception with traceback
    debug_manager.log_exception(e, message)
