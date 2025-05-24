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
import time
import tempfile
import socket
import uuid
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("DebugModule")

class DebugManager:
    """Class for system diagnostics and debugging"""
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        self.debug_enabled = False
        self.start_time = datetime.datetime.now()
        
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
                "servers": os.path.join(self.server_manager_dir, "servers"),
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
    
    def enable_debug(self):
        """Enable debug mode"""
        self.debug_enabled = True
        logger.setLevel(logging.DEBUG)
        return True
    
    def disable_debug(self):
        """Disable debug mode"""
        self.debug_enabled = False
        logger.setLevel(logging.INFO)
        return True
    
    def is_debug_enabled(self):
        """Check if debug mode is enabled"""
        return self.debug_enabled
    
    def get_system_info(self):
        """Get detailed system information"""
        try:
            # Basic system info
            system_info = {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.architecture(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "hostname": socket.gethostname(),
                "ip_address": socket.gethostbyname(socket.gethostname()),
                "mac_address": ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff) 
                                       for elements in range(0, 48, 8)][::-1]),
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation()
            }
            
            # CPU info
            cpu_info = {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "cpu_percent": psutil.cpu_percent(interval=1, percpu=True),
                "cpu_freq": {
                    "current": psutil.cpu_freq().current if psutil.cpu_freq() else None,
                    "min": psutil.cpu_freq().min if psutil.cpu_freq() else None,
                    "max": psutil.cpu_freq().max if psutil.cpu_freq() else None
                }
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
            disk_info = []
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append({
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent
                    })
                except:
                    pass
            
            # Network info
            network_info = {}
            net_io = psutil.net_io_counters(pernic=True)
            for interface, stats in net_io.items():
                network_info[interface] = {
                    "bytes_sent": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "errin": stats.errin if hasattr(stats, 'errin') else None,
                    "errout": stats.errout if hasattr(stats, 'errout') else None,
                    "dropin": stats.dropin if hasattr(stats, 'dropin') else None,
                    "dropout": stats.dropout if hasattr(stats, 'dropout') else None
                }
            
            # Server Manager info
            sm_info = {
                "install_dir": self.server_manager_dir,
                "uptime": str(datetime.datetime.now() - self.start_time),
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
    
    def get_process_info(self, pid=None):
        """Get detailed information about a process or all processes"""
        try:
            if pid:
                # Get info for specific process
                try:
                    process = psutil.Process(pid)
                    return self._get_single_process_info(process)
                except psutil.NoSuchProcess:
                    return {"error": f"Process with PID {pid} not found"}
            else:
                # Get info for all processes
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'username']):
                    try:
                        proc_info = proc.info
                        proc_info['cpu_percent'] = proc.cpu_percent(interval=0.1)
                        proc_info['memory_percent'] = proc.memory_percent()
                        proc_info['status'] = proc.status()
                        proc_info['create_time'] = datetime.datetime.fromtimestamp(proc.create_time()).isoformat()
                        processes.append(proc_info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
                return processes
        except Exception as e:
            logger.error(f"Failed to get process information: {str(e)}")
            return {"error": str(e)}
    
    def _get_single_process_info(self, process):
        """Get detailed information about a single process"""
        try:
            info = {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "created": datetime.datetime.fromtimestamp(process.create_time()).isoformat(),
                "username": process.username(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_info": {
                    "rss": process.memory_info().rss,
                    "vms": process.memory_info().vms
                }
            }
            
            # Try to get additional information (may fail due to permissions)
            try:
                info["cmdline"] = process.cmdline()
            except:
                pass
                
            try:
                info["cwd"] = process.cwd()
            except:
                pass
                
            try:
                info["exe"] = process.exe()
            except:
                pass
                
            try:
                info["connections"] = [
                    {
                        "fd": c.fd,
                        "family": c.family,
                        "type": c.type,
                        "laddr": f"{c.laddr.ip}:{c.laddr.port}" if hasattr(c.laddr, 'ip') else str(c.laddr),
                        "raddr": f"{c.raddr.ip}:{c.raddr.port}" if hasattr(c.raddr, 'ip') and c.raddr else "None"
                    }
                    for c in process.connections()
                ]
            except:
                pass
                
            try:
                info["threads"] = [
                    {"id": t.id, "user_time": t.user_time, "system_time": t.system_time}
                    for t in process.threads()
                ]
            except:
                pass
                
            try:
                info["open_files"] = [f.path for f in process.open_files()]
            except:
                pass
            
            return info
        except Exception as e:
            logger.error(f"Failed to get detailed process information: {str(e)}")
            return {"error": str(e)}
    
    def get_server_status(self, server_name=None):
        """Get status of all servers or a specific server"""
        try:
            servers_dir = self.paths.get("servers")
            if not servers_dir or not os.path.exists(servers_dir):
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
                            server_config["ProcessInfo"] = self._get_single_process_info(process)
                            server_config["IsRunning"] = True
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
    
    def create_diagnostic_report(self, include_servers=True, include_processes=True):
        """Create a comprehensive diagnostic report"""
        try:
            report = {
                "timestamp": datetime.datetime.now().isoformat(),
                "system_info": self.get_system_info()
            }
            
            if include_servers:
                report["servers"] = self.get_server_status()
            
            if include_processes:
                report["processes"] = self.get_process_info()
            
            # Add registry information
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
                        "writable": os.access(path, os.W_OK) if os.path.exists(path) else False,
                        "readable": os.access(path, os.R_OK) if os.path.exists(path) else False
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
    
    def memory_usage_log(self, duration=60, interval=1):
        """Log memory usage over time"""
        try:
            log_data = []
            start_time = time.time()
            end_time = start_time + duration
            
            while time.time() < end_time:
                # Get memory usage
                memory = psutil.virtual_memory()
                
                # Record timestamp and memory usage
                timestamp = datetime.datetime.now().isoformat()
                memory_usage = {
                    "timestamp": timestamp,
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "percent": memory.percent
                }
                
                log_data.append(memory_usage)
                
                # Wait for next interval
                time.sleep(interval)
            
            # Save log to file
            log_file = os.path.join(self.paths["debug"], f"memory_usage_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            
            logger.info(f"Memory usage log created: {log_file}")
            return log_file
        except Exception as e:
            logger.error(f"Failed to create memory usage log: {str(e)}")
            return None
    
    def cpu_usage_log(self, duration=60, interval=1):
        """Log CPU usage over time"""
        try:
            log_data = []
            start_time = time.time()
            end_time = start_time + duration
            
            while time.time() < end_time:
                # Get CPU usage
                cpu_percent = psutil.cpu_percent(interval=0.5, percpu=True)
                
                # Record timestamp and CPU usage
                timestamp = datetime.datetime.now().isoformat()
                cpu_usage = {
                    "timestamp": timestamp,
                    "overall": sum(cpu_percent) / len(cpu_percent),
                    "per_cpu": cpu_percent
                }
                
                log_data.append(cpu_usage)
                
                # Wait for next interval
                time.sleep(max(0, interval - 0.5))  # Adjust for the interval in cpu_percent
            
            # Save log to file
            log_file = os.path.join(self.paths["debug"], f"cpu_usage_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            
            logger.info(f"CPU usage log created: {log_file}")
            return log_file
        except Exception as e:
            logger.error(f"Failed to create CPU usage log: {str(e)}")
            return None
    
    def network_usage_log(self, duration=60, interval=1):
        """Log network usage over time"""
        try:
            log_data = []
            start_time = time.time()
            end_time = start_time + duration
            
            # Get initial network counters
            previous_counters = psutil.net_io_counters()
            previous_time = start_time
            
            while time.time() < end_time:
                time.sleep(interval)
                
                # Get current network counters
                current_counters = psutil.net_io_counters()
                current_time = time.time()
                
                # Calculate rates
                time_diff = current_time - previous_time
                bytes_sent_rate = (current_counters.bytes_sent - previous_counters.bytes_sent) / time_diff
                bytes_recv_rate = (current_counters.bytes_recv - previous_counters.bytes_recv) / time_diff
                
                # Record timestamp and network usage
                timestamp = datetime.datetime.now().isoformat()
                network_usage = {
                    "timestamp": timestamp,
                    "bytes_sent": current_counters.bytes_sent,
                    "bytes_recv": current_counters.bytes_recv,
                    "bytes_sent_rate": bytes_sent_rate,
                    "bytes_recv_rate": bytes_recv_rate,
                    "packets_sent": current_counters.packets_sent,
                    "packets_recv": current_counters.packets_recv
                }
                
                log_data.append(network_usage)
                
                # Update previous values
                previous_counters = current_counters
                previous_time = current_time
            
            # Save log to file
            log_file = os.path.join(self.paths["debug"], f"network_usage_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            
            logger.info(f"Network usage log created: {log_file}")
            return log_file
        except Exception as e:
            logger.error(f"Failed to create network usage log: {str(e)}")
            return None
    
    def capture_thread_dump(self, pid=None):
        """Capture a thread dump of a process or all processes"""
        try:
            if pid:
                # Get thread dump for specific process
                try:
                    process = psutil.Process(pid)
                    threads = process.threads()
                    
                    thread_dump = {
                        "pid": pid,
                        "name": process.name(),
                        "threads": [
                            {
                                "id": t.id,
                                "user_time": t.user_time,
                                "system_time": t.system_time
                            }
                            for t in threads
                        ]
                    }
                    
                    # Save thread dump to file
                    dump_file = os.path.join(self.paths["debug"], f"thread_dump_{pid}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                    with open(dump_file, 'w') as f:
                        json.dump(thread_dump, f, indent=2)
                    
                    logger.info(f"Thread dump created for PID {pid}: {dump_file}")
                    return dump_file
                    
                except psutil.NoSuchProcess:
                    logger.error(f"Process with PID {pid} not found")
                    return None
            else:
                # Get thread dump for all processes
                all_thread_dumps = {}
                
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        pid = proc.info['pid']
                        name = proc.info['name']
                        
                        threads = proc.threads()
                        
                        all_thread_dumps[pid] = {
                            "name": name,
                            "threads": [
                                {
                                    "id": t.id,
                                    "user_time": t.user_time,
                                    "system_time": t.system_time
                                }
                                for t in threads
                            ]
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                
                # Save thread dumps to file
                dump_file = os.path.join(self.paths["debug"], f"all_thread_dumps_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                with open(dump_file, 'w') as f:
                    json.dump(all_thread_dumps, f, indent=2)
                
                logger.info(f"Thread dumps created for all processes: {dump_file}")
                return dump_file
        except Exception as e:
            logger.error(f"Failed to capture thread dump: {str(e)}")
            return None
    
    def capture_log_snapshot(self, log_dir=None, max_age_hours=24):
        """Capture a snapshot of recent log files"""
        try:
            if not log_dir:
                log_dir = self.paths["logs"]
            
            # Create a temporary directory for the snapshot
            snapshot_dir = os.path.join(self.paths["debug"], f"log_snapshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(snapshot_dir, exist_ok=True)
            
            # Get current time
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            
            # Find all log files that are recent enough
            log_files = []
            for root, _, files in os.walk(log_dir):
                for filename in files:
                    if filename.endswith(".log") or filename.endswith(".txt"):
                        file_path = os.path.join(root, filename)
                        file_age = current_time - os.path.getmtime(file_path)
                        
                        # Check if file is recent enough
                        if file_age <= max_age_seconds:
                            log_files.append(file_path)
            
            # Copy log files to snapshot directory
            for file_path in log_files:
                # Create relative path structure in snapshot
                rel_path = os.path.relpath(file_path, log_dir)
                snapshot_path = os.path.join(snapshot_dir, rel_path)
                
                # Create directory if needed
                os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                
                # Copy the file
                shutil.copy2(file_path, snapshot_path)
            
            logger.info(f"Log snapshot created: {snapshot_dir}")
            
            # Create a zip file of the snapshot
            zip_path = f"{snapshot_dir}.zip"
            shutil.make_archive(snapshot_dir, 'zip', snapshot_dir)
            
            # Remove the temporary directory
            shutil.rmtree(snapshot_dir)
            
            logger.info(f"Log snapshot compressed: {zip_path}")
            return zip_path
        except Exception as e:
            logger.error(f"Failed to capture log snapshot: {str(e)}")
            return None
    
    def analyze_memory_leak(self, pid, duration=300, interval=10):
        """Analyze a process for potential memory leaks"""
        try:
            try:
                process = psutil.Process(pid)
            except psutil.NoSuchProcess:
                logger.error(f"Process with PID {pid} not found")
                return None
            
            logger.info(f"Starting memory leak analysis for PID {pid} ({process.name()})")
            
            # Record memory usage over time
            memory_data = []
            start_time = time.time()
            end_time = start_time + duration
            
            while time.time() < end_time:
                try:
                    if not process.is_running():
                        logger.warning(f"Process with PID {pid} is no longer running")
                        break
                    
                    # Get memory info
                    memory_info = process.memory_info()
                    
                    memory_data.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "rss": memory_info.rss,
                        "vms": memory_info.vms
                    })
                    
                    time.sleep(interval)
                except psutil.NoSuchProcess:
                    logger.warning(f"Process with PID {pid} is no longer running")
                    break
            
            # Analyze memory data
            if len(memory_data) < 3:
                logger.warning("Not enough data points to analyze memory usage")
                return None
            
            # Calculate growth rates
            growth_rates = []
            for i in range(1, len(memory_data)):
                previous = memory_data[i-1]["rss"]
                current = memory_data[i]["rss"]
                growth = current - previous
                growth_rates.append(growth)
            
            # Calculate average growth rate
            avg_growth_rate = sum(growth_rates) / len(growth_rates)
            
            # Determine if there's a potential memory leak
            has_leak = avg_growth_rate > 1024 * 1024  # 1 MB per interval
            
            # Create report
            report = {
                "pid": pid,
                "process_name": process.name(),
                "start_time": memory_data[0]["timestamp"],
                "end_time": memory_data[-1]["timestamp"],
                "duration_seconds": time.time() - start_time,
                "data_points": len(memory_data),
                "initial_memory_mb": memory_data[0]["rss"] / (1024 * 1024),
                "final_memory_mb": memory_data[-1]["rss"] / (1024 * 1024),
                "average_growth_rate_bytes": avg_growth_rate,
                "potential_memory_leak": has_leak,
                "memory_data": memory_data
            }
            
            # Save report to file
            report_file = os.path.join(self.paths["debug"], f"memory_analysis_{pid}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            logger.info(f"Memory leak analysis completed: {report_file}")
            logger.info(f"Potential memory leak: {has_leak}")
            
            return report_file
        except Exception as e:
            logger.error(f"Failed to analyze memory leak: {str(e)}")
            return None
    
    def create_minidump(self, pid):
        """Create a minidump of a process (Windows only)"""
        if platform.system() != "Windows":
            logger.error("Minidump creation is only supported on Windows")
            return None
        
        try:
            import ctypes
            from ctypes import wintypes
            
            # Define necessary Windows constants and structures
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            MiniDumpWithFullMemory = 0x00000002
            
            # Load required DLLs
            dbghelp = ctypes.WinDLL("dbghelp.dll")
            kernel32 = ctypes.WinDLL("kernel32.dll")
            
            # Define function prototypes
            MiniDumpWriteDump = dbghelp.MiniDumpWriteDump
            MiniDumpWriteDump.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.HANDLE,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p
            ]
            MiniDumpWriteDump.restype = wintypes.BOOL
            
            # Open the process
            h_process = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if h_process == 0:
                logger.error(f"Failed to open process with PID {pid}")
                return None
            
            # Create minidump file
            dump_file = os.path.join(self.paths["debug"], f"minidump_{pid}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.dmp")
            
            with open(dump_file, 'wb') as f:
                h_file = msvcrt.get_osfhandle(f.fileno())
                
                # Write the minidump
                success = MiniDumpWriteDump(
                    h_process,
                    pid,
                    h_file,
                    MiniDumpWithFullMemory,
                    None,
                    None,
                    None
                )
                
                if not success:
                    logger.error(f"Failed to write minidump: {ctypes.GetLastError()}")
                    return None
            
            # Close process handle
            kernel32.CloseHandle(h_process)
            
            logger.info(f"Minidump created: {dump_file}")
            return dump_file
            
        except Exception as e:
            logger.error(f"Failed to create minidump: {str(e)}")
            return None

# Create a global instance for easy access
debug_manager = DebugManager()

# Export functions for easy access
def get_system_info():
    return debug_manager.get_system_info()

def create_diagnostic_report(include_servers=True, include_processes=True):
    return debug_manager.create_diagnostic_report(include_servers, include_processes)

def enable_debug():
    return debug_manager.enable_debug()

def disable_debug():
    return debug_manager.disable_debug()

def is_debug_enabled():
    return debug_manager.is_debug_enabled()

def get_process_info(pid=None):
    return debug_manager.get_process_info(pid)

def get_server_status(server_name=None):
    return debug_manager.get_server_status(server_name)

def memory_usage_log(duration=60, interval=1):
    return debug_manager.memory_usage_log(duration, interval)

def cpu_usage_log(duration=60, interval=1):
    return debug_manager.cpu_usage_log(duration, interval)

def network_usage_log(duration=60, interval=1):
    return debug_manager.network_usage_log(duration, interval)

def capture_thread_dump(pid=None):
    return debug_manager.capture_thread_dump(pid)

def capture_log_snapshot(log_dir=None, max_age_hours=24):
    return debug_manager.capture_log_snapshot(log_dir, max_age_hours)

def analyze_memory_leak(pid, duration=300, interval=10):
    return debug_manager.analyze_memory_leak(pid, duration, interval)

def create_minidump(pid):
    return debug_manager.create_minidump(pid)
