# Network management
import os
import sys
import socket
import logging
import subprocess
import requests
import time
import psutil

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_logging, get_server_manager_dir, get_subprocess_creation_flags

logger: logging.Logger = setup_module_logging("Network")


class NetworkManager:
    # - Network ops and server connectivity
    # - Uses registry for paths
    def __init__(self):
        self.registry_path = r"Software\SkywereIndustries\Servermanager"
        self.server_manager_dir = None
        self.paths = {}
        
        self.initialise_from_registry()
    
    def initialise_from_registry(self):
        # Pull paths from registry
        try:
            self.server_manager_dir = get_server_manager_dir()
            
            self.paths = {
                "root": self.server_manager_dir,
                "logs": os.path.join(self.server_manager_dir, "logs"),
                "servers": os.path.join(self.server_manager_dir, "servers"),
                "temp": os.path.join(self.server_manager_dir, "temp")
            }
            
            for path in self.paths.values():
                os.makedirs(path, exist_ok=True)
            
            logger.info("Network manager ready")
            return True
            
        except Exception as e:
            logger.error(f"Network init failed: {str(e)}")
            return False
    
    def get_local_ip_addresses(self):
        # All local IPs from network interfaces
        try:
            ip_list = []
            
            hostname = socket.gethostname()
            
            try:
                host_ip = socket.gethostbyname(hostname)
                ip_list.append({"interface": "hostname", "ip": host_ip})
            except socket.gaierror:
                pass
            
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip_list.append({"interface": iface, "ip": addr.address})
            
            if not ip_list:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                ip_list.append({"interface": "default", "ip": ip})
            
            return ip_list
        except Exception as e:
            logger.error(f"Error getting local IP addresses: {str(e)}")
            return []
    
    def get_external_ip(self):
        # Get external IP address using public services
        try:
            # Try multiple services in case one fails
            services = [
                "https://api.ipify.org?format=json",
                "https://ipinfo.io/json",
                "https://api.myip.com"
            ]
            
            for service in services:
                try:
                    response = requests.get(service, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Different services return IP in different formats
                        if "ip" in data:
                            return data["ip"]
                        
                        return None
                except (requests.RequestException, ValueError, KeyError):
                    continue
            
            return None
        except Exception as e:
            logger.error(f"Error getting external IP: {str(e)}")
            return None
    
    def is_port_in_use(self, port, host='0.0.0.0'):
        # Check if a port is in use on the specified host
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.bind((host, port))
            s.close()
            return False
        except socket.error:
            return True
    
    def scan_port_range(self, start_port, end_port, host='0.0.0.0'):
        # Scan a range of ports to check if they are in use
        result = []
        for port in range(start_port, end_port + 1):
            in_use = self.is_port_in_use(port, host)
            result.append({"port": port, "in_use": in_use})
        return result
    
    def ping_host(self, host, count=4, timeout=1000):
        # Ping a host to check connectivity
        try:
            logger.debug(f"[SUBPROCESS_TRACE] ping_host called for host: {host}")
            # Use different ping command based on OS
            if sys.platform.startswith('win'):
                command = ['ping', '-n', str(count), '-w', str(timeout), host]
            else:
                command = ['ping', '-c', str(count), '-W', str(timeout / 1000), host]
            
            # Use CREATE_NO_WINDOW to prevent console popup on Windows
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = get_subprocess_creation_flags(hide_window=True)
                logger.debug(f"[SUBPROCESS_TRACE] ping using creationflags: {creationflags}")
            
            logger.debug(f"[SUBPROCESS_TRACE] Executing ping command: {command}")
            result = subprocess.run(command, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=creationflags)
            logger.debug(f"[SUBPROCESS_TRACE] ping completed with returncode: {result.returncode}")
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr
            }
        except Exception as e:
            logger.error(f"Error pinging host {host}: {str(e)}")
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
    
    def traceroute(self, host, max_hops=30):
        # Perform a traceroute to a host
        try:
            logger.debug(f"[SUBPROCESS_TRACE] traceroute called for host: {host}")
            # Use different traceroute command based on OS
            if sys.platform.startswith('win'):
                command = ['tracert', '-h', str(max_hops), host]
            else:
                command = ['traceroute', '-m', str(max_hops), host]
            
            # Use centralized subprocess creation flags
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = get_subprocess_creation_flags(hide_window=True)
                logger.debug(f"[SUBPROCESS_TRACE] traceroute using creationflags: {creationflags}")
            
            logger.debug(f"[SUBPROCESS_TRACE] Executing traceroute command: {command}")
            result = subprocess.run(command, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=creationflags)
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr
            }
        except Exception as e:
            logger.error(f"Error performing traceroute to {host}: {str(e)}")
            return {
                "success": False,
                "output": "",
                "error": str(e)
            }
    
    def check_internet_connectivity(self):
        # Check if internet connection is available
        hosts = ["8.8.8.8", "1.1.1.1", "google.com", "cloudflare.com"]
        
        for host in hosts:
            try:
                result = self.ping_host(host, count=1, timeout=1000)
                if result["success"]:
                    return True
            except Exception:
                continue
        
        return False
    
    def get_network_usage(self):
        # Get current network usage statistics
        try:
            # Get network usage using psutil
            net_io = psutil.net_io_counters()
            
            # Wait a moment to calculate rate
            time.sleep(1)
            
            net_io_after = psutil.net_io_counters()
            
            # Calculate send/receive rates
            bytes_sent_rate = net_io_after.bytes_sent - net_io.bytes_sent
            bytes_recv_rate = net_io_after.bytes_recv - net_io.bytes_recv
            
            return {
                "bytes_sent": net_io_after.bytes_sent,
                "bytes_recv": net_io_after.bytes_recv,
                "bytes_sent_rate": bytes_sent_rate,
                "bytes_recv_rate": bytes_recv_rate,
                "packets_sent": net_io_after.packets_sent,
                "packets_recv": net_io_after.packets_recv
            }
        except Exception as e:
            logger.error(f"Error getting network usage: {str(e)}")
            return {}
    
    def check_dns_resolution(self, hostname):
        # Check DNS resolution for a hostname
        try:
            ip_addresses = socket.gethostbyname_ex(hostname)
            return {
                "success": True,
                "hostname": hostname,
                "canonical_name": ip_addresses[0],
                "ip_addresses": ip_addresses[2]
            }
        except Exception as e:
            logger.error(f"Error resolving DNS for {hostname}: {str(e)}")
            return {
                "success": False,
                "hostname": hostname,
                "error": str(e)
            }
    
    def get_firewall_status(self):
        # Get Windows firewall status for all profiles
        try:
            if not sys.platform.startswith('win'):
                return {"error": "Only supported on Windows"}
            
            # Check Windows firewall status using netsh
            command = ['netsh', 'advfirewall', 'show', 'allprofiles']
            
            # Use centralized subprocess creation flags
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            
            result = subprocess.run(command, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=get_subprocess_creation_flags(hide_window=True))
            
            # Parse the output
            output = result.stdout
            profiles = {}
            current_profile = None
            
            for line in output.splitlines():
                line = line.strip()
                
                # Check for profile headers
                if line.startswith('Domain Profile'):
                    current_profile = "Domain"
                    profiles[current_profile] = {}
                elif line.startswith('Private Profile'):
                    current_profile = "Private"
                    profiles[current_profile] = {}
                elif line.startswith('Public Profile'):
                    current_profile = "Public"
                    profiles[current_profile] = {}
                
                # Parse status for current profile
                if current_profile and ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == "State":
                        profiles[current_profile]["enabled"] = value == "ON"
                    elif key in ["Inbound connections", "Outbound connections"]:
                        profiles[current_profile][key] = value
            
            return profiles
        except Exception as e:
            logger.error(f"Error getting firewall status: {str(e)}")
            return {"error": str(e)}
    
    def open_firewall_port(self, port, protocol="TCP", name=None, direction="in"):
        # Open a port in the Windows firewall
        try:
            if not sys.platform.startswith('win'):
                return {"error": "Only supported on Windows"}
            
            # Create rule name if not provided
            if not name:
                name = f"ServerManager_{protocol}_{port}_{direction}"
            
            # Create firewall rule
            command = [
                'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                f'name={name}',
                f'dir={direction}',
                f'protocol={protocol}',
                f'localport={port}',
                'action=allow'
            ]
            
            # Use CREATE_NO_WINDOW to prevent console popup
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            
            result = subprocess.run(command, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "port": port,
                "protocol": protocol,
                "name": name,
                "direction": direction
            }
        except Exception as e:
            logger.error(f"Error opening firewall port {port}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def close_firewall_port(self, name):
        # Close a port in the Windows firewall by rule name
        try:
            if not sys.platform.startswith('win'):
                return {"error": "Only supported on Windows"}
            
            # Delete firewall rule
            command = [
                'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                f'name={name}'
            ]
            
            # Use CREATE_NO_WINDOW to prevent console popup
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            
            result = subprocess.run(command, capture_output=True, text=True,
                                   startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "name": name
            }
        except Exception as e:
            logger.error(f"Error closing firewall rule {name}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_network_interfaces(self):
        # Get information about network interfaces
        try:
            interfaces = []
            
            # Get all network interfaces using psutil
            for iface, addrs in psutil.net_if_addrs().items():
                interface_info = {
                    "name": iface,
                    "addresses": []
                }
                
                for addr in addrs:
                    address_info = {
                        "family": addr.family,
                        "address": addr.address
                    }
                    
                    if addr.family == socket.AF_INET:  # IPv4
                        address_info["type"] = "IPv4"
                        if hasattr(addr, 'netmask') and addr.netmask:
                            address_info["netmask"] = addr.netmask
                        if hasattr(addr, 'broadcast') and addr.broadcast:
                            address_info["broadcast"] = addr.broadcast
                    elif addr.family == socket.AF_INET6:  # IPv6
                        address_info["type"] = "IPv6"
                    else:
                        address_info["type"] = "Other"
                    
                    interface_info["addresses"].append(address_info)
                
                # Get interface statistics if available
                try:
                    stats = psutil.net_if_stats().get(iface)
                    if stats:
                        interface_info["speed"] = stats.speed
                        interface_info["mtu"] = stats.mtu
                        interface_info["up"] = stats.isup
                except (psutil.Error, OSError, KeyError):
                    pass
                
                interfaces.append(interface_info)
            
            return interfaces
        except Exception as e:
            logger.error(f"Error getting network interfaces: {str(e)}")
            return []
    
    def check_port_connectivity(self, host, port, timeout=5):
        # Check if a remote port is accessible
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            
            return {
                "host": host,
                "port": port,
                "accessible": result == 0
            }
        except Exception as e:
            logger.error(f"Error checking connectivity to {host}:{port}: {str(e)}")
            return {
                "host": host,
                "port": port,
                "accessible": False,
                "error": str(e)
            }
