import os
import sys
import json
import logging
import subprocess
import winreg
import time
import psutil
import urllib.request
import threading
from datetime import datetime
import os
import logging

try:
    from Modules.server_logging import get_component_logger, log_server_action, log_exception
    logger = get_component_logger("ServerManager")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("ServerManager")

if os.environ.get("SERVERMANAGER_DEBUG") in ("1", "true", "True"):
    logger.setLevel(logging.DEBUG)
    logger.debug("ServerManager module debug mode enabled via environment")

def get_subprocess_creation_flags(hide_window=True, new_process_group=False):
    """Get appropriate creation flags for subprocess calls on Windows to prevent console windows.
    
    Args:
        hide_window (bool): If True, prevents console window from opening (saves DWM resources)
        new_process_group (bool): If True, creates a new process group for better process control
    
    Returns:
        int: Creation flags for Windows, 0 for other platforms
    """
    if sys.platform != 'win32':
        return 0
    
    flags = 0
    if hide_window:
        flags |= subprocess.CREATE_NO_WINDOW
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    
    return flags

def should_hide_server_consoles(config=None):
    """Check if server consoles should be hidden based on configuration.
    
    Args:
        config (dict): Configuration dictionary (optional)
        
    Returns:
        bool: True if consoles should be hidden, False otherwise
    """
    if config and 'configuration' in config:
        return config['configuration'].get('hideServerConsoles', True)
    return True  # Default to hiding consoles

# Import Minecraft-specific functions
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Modules'))

# Define fallback functions with correct types
def _fallback_fetch_minecraft_versions():
    return []

def _fallback_get_minecraft_server_jar_url(version_id, versions_list):
    return None

def _fallback_fetch_fabric_installer_url(mc_version):
    return None

def _fallback_fetch_forge_installer_url(mc_version):
    return None

def _fallback_fetch_neoforge_installer_url(mc_version):
    return None

try:
    from Modules.minecraft import (
        fetch_minecraft_versions, get_minecraft_server_jar_url,
        fetch_fabric_installer_url, fetch_forge_installer_url,
        fetch_neoforge_installer_url
    )
except ImportError:
    logger.warning("Minecraft helper functions not available")
    # Use fallback functions
    fetch_minecraft_versions = _fallback_fetch_minecraft_versions
    get_minecraft_server_jar_url = _fallback_get_minecraft_server_jar_url
    fetch_fabric_installer_url = _fallback_fetch_fabric_installer_url
    fetch_forge_installer_url = _fallback_fetch_forge_installer_url
    fetch_neoforge_installer_url = _fallback_fetch_neoforge_installer_url

from Modules.common import ServerManagerModule

class ServerManager(ServerManagerModule):
    """Main class for server management"""
    def __init__(self):
        super().__init__("ServerManager")
        self.servers = {}
        
        # Load configuration and server list
        self.load_config()
        self.load_servers()
    def get_server_process(self, server_name):
        """Get the active process object for a server"""
        if hasattr(self, 'active_processes') and server_name in self.active_processes:
            process = self.active_processes[server_name]
            # Check if process is still running
            if process.poll() is None:
                return process
            else:
                # Clean up dead process
                del self.active_processes[server_name]
        return None
        
    def get_servers(self):
        """Get dictionary of all servers and their configurations"""
        return self.servers
        
    def load_config(self):
        """Load configuration from file"""
        try:
            config_file = os.path.join(self.paths["config"], "config.json")
            
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                # Update the inherited config
                self._config_manager.config.update(config_data)
                logger.info(f"Configuration loaded from {config_file}")
            else:
                # Create default configuration
                default_config = {
                    "version": "1.0.0",
                    "web_port": 8080,
                    "log_level": "INFO",
                    "steam_cmd_path": os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD"),
                    "auto_update_check_interval": 3600,  # seconds
                    "max_log_files": 10,
                    "max_log_size": 10 * 1024 * 1024  # 10 MB
                }
                
                # Update the inherited config
                self._config_manager.config.update(default_config)
                
                # Save default configuration
                with open(config_file, 'w') as f:
                    json.dump(default_config, f, indent=4)
                    
                logger.info(f"Default configuration created at {config_file}")
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
            
    def load_servers(self):
        """Load list of servers from config directory"""
        try:
            servers_dir = self.paths["servers"]
            
            if not os.path.exists(servers_dir):
                os.makedirs(servers_dir, exist_ok=True)
                logger.info(f"Created servers directory: {servers_dir}")
                return
                
            for file in os.listdir(servers_dir):
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(servers_dir, file), 'r') as f:
                            server_config = json.load(f)
                            
                        server_name = server_config.get("Name")
                        if server_name:
                            self.servers[server_name] = server_config
                    except Exception as e:
                        logger.error(f"Error loading server config {file}: {str(e)}")
                        
            logger.info(f"Loaded {len(self.servers)} server configurations")
        except Exception as e:
            logger.error(f"Error loading servers: {str(e)}")
            
    def get_server_config(self, server_name):
        """Get configuration for a specific server"""
        if server_name in self.servers:
            return self.servers[server_name]
            
        # Try to load from file if not in memory
        config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    server_config = json.load(f)
                    
                # Cache the config
                self.servers[server_name] = server_config
                return server_config
            except Exception as e:
                logger.error(f"Error loading server config {server_name}: {str(e)}")
                
        return None
        
    def save_server_config(self, server_name, config):
        """Save configuration for a specific server"""
        try:
            config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
                
            # Update cache
            self.servers[server_name] = config
            
            logger.info(f"Server configuration saved for {server_name}")
            return True
        except Exception as e:
            logger.error(f"Error saving server config {server_name}: {str(e)}")
            return False
            
    def get_server_list(self):
        """Get list of all configured servers"""
        return list(self.servers.values())
    
    def get_all_servers(self):
        """Get all servers as a dictionary with server names as keys"""
        return self.servers.copy()
            
    def start_server(self, server_name):
        """Start a server using the appropriate script"""
        try:
            script_path = os.path.join(self.paths["scripts"], "start_server.py")
            
            if not os.path.exists(script_path):
                logger.error(f"Start server script not found: {script_path}")
                return False
                
            # Use CREATE_NO_WINDOW to prevent console window from opening (configurable)
            hide_consoles = should_hide_server_consoles(self.config)
            result = subprocess.run([sys.executable, script_path, server_name], 
                                   capture_output=True, text=True, 
                                   creationflags=get_subprocess_creation_flags(hide_window=hide_consoles))
                                   
            if result.returncode != 0:
                logger.error(f"Error starting server {server_name}: {result.stderr}")
                return False
                
            logger.info(f"Server {server_name} started successfully")
            return True
        except Exception as e:
            logger.error(f"Error starting server {server_name}: {str(e)}")
            return False
            
    def stop_server(self, server_name, force=False):
        """Stop a server using the appropriate script"""
        try:
            script_path = os.path.join(self.paths["scripts"], "stop_server.py")
            
            if not os.path.exists(script_path):
                logger.error(f"Stop server script not found: {script_path}")
                return False
                
            cmd = [sys.executable, script_path, server_name]
            if force:
                cmd.append("--force")
                
            # Use CREATE_NO_WINDOW to prevent console window from opening (configurable)
            hide_consoles = should_hide_server_consoles(self.config)
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   creationflags=get_subprocess_creation_flags(hide_window=hide_consoles))
                                   
            if result.returncode != 0:
                logger.error(f"Error stopping server {server_name}: {result.stderr}")
                return False
                
            logger.info(f"Server {server_name} stopped successfully")
            return True
        except Exception as e:
            logger.error(f"Error stopping server {server_name}: {str(e)}")
            return False

    def start_server_advanced(self, server_name, callback=None):
        """Start the selected game server (Steam/Minecraft/Other) - Advanced version with proper process management"""
        try:
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"
                
            with open(config_file, 'r') as f:
                server_config = json.load(f)
            
            # Clean up orphaned process ID first
            if 'ProcessId' in server_config:
                if self.is_process_running(server_config['ProcessId']):
                    logger.info(f"Server '{server_name}' is already running with PID {server_config['ProcessId']}.")
                    if callback:
                        callback(f"Server '{server_name}' is already running")
                    return False, f"Server '{server_name}' is already running with PID {server_config['ProcessId']}."
                else:
                    # Clean up dead process ID
                    logger.info(f"Cleaning up dead process ID {server_config['ProcessId']} for server '{server_name}'")
                    server_config.pop('ProcessId', None)
                    server_config.pop('StartTime', None)
                    server_config['LastUpdate'] = datetime.now().isoformat()
                    self.save_server_config(server_name, server_config)
                
            server_type = server_config.get("Type", "Other")
            install_dir = server_config.get('InstallDir', '')
            executable_path = server_config.get('ExecutablePath', '')
            startup_args = server_config.get('StartupArgs', '')
            use_config_file = server_config.get('UseConfigFile', False)
            config_file_path = server_config.get('ConfigFilePath', '')
            config_argument = server_config.get('ConfigArgument', '--config')
            additional_args = server_config.get('AdditionalArgs', '')
            
            if not executable_path:
                logger.error("No executable specified. Please configure the server startup settings.")
                return False, "No executable specified. Please configure the server startup settings."
                
            # Resolve executable path
            exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
            # Normalize path separators for Windows compatibility
            exe_full = os.path.normpath(exe_full)
            if not os.path.exists(exe_full):
                logger.error(f"Executable not found: {exe_full}")
                return False, f"Executable not found: {exe_full}"
            
            # Build command with config file support
            cmd_parts = [f'"{exe_full}"']
            
            # Resolve config file path if needed
            config_full = None
            if use_config_file and config_file_path:
                config_full = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                # Normalize config file path separators
                config_full = os.path.normpath(config_full)
            
            if use_config_file:
                # Config file mode
                # Add additional arguments first (if any)
                if additional_args:
                    cmd_parts.append(additional_args)
                
                # Add config file argument
                if config_file_path and config_argument and config_full:
                    if os.path.exists(config_full):
                        cmd_parts.append(f'{config_argument} "{config_full}"')
                        logger.info(f"Using config file: {config_full}")
                    else:
                        logger.warning(f"Config file not found: {config_full}, starting without config file")
            else:
                # Manual arguments mode
                if startup_args:
                    cmd_parts.append(startup_args)
            
            # Build final command based on executable type (unified for all server types)
            if exe_full.lower().endswith(('.bat', '.cmd')):
                # For batch files, run them directly without using 'start' command
                # This allows proper process tracking and prevents the "error" issue
                cmd = ' '.join(cmd_parts)
                shell = True
            elif exe_full.lower().endswith('.ps1'):
                # For PowerShell scripts, use PowerShell to execute them
                ps_cmd_parts = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', f'"{exe_full}"']
                if use_config_file:
                    if additional_args:
                        ps_cmd_parts.extend(additional_args.split())
                    if config_file_path and config_argument and config_full and os.path.exists(config_full):
                        ps_cmd_parts.extend([config_argument, f'"{config_full}"'])
                else:
                    if startup_args:
                        ps_cmd_parts.extend(startup_args.split())
                cmd = ' '.join(ps_cmd_parts)
                shell = True
            elif exe_full.lower().endswith('.sh'):
                # For shell scripts, handle both Windows (via WSL/Git Bash) and Unix systems
                if sys.platform == 'win32':
                    # On Windows, try to use bash (Git Bash, WSL, etc.)
                    bash_cmd_parts = ['bash', f'"{exe_full}"']
                    if use_config_file:
                        if additional_args:
                            bash_cmd_parts.extend(additional_args.split())
                        if config_file_path and config_argument and config_full and os.path.exists(config_full):
                            bash_cmd_parts.extend([config_argument, f'"{config_full}"'])
                    else:
                        if startup_args:
                            bash_cmd_parts.extend(startup_args.split())
                    cmd = ' '.join(bash_cmd_parts)
                    shell = True
                else:
                    # On Unix systems, use the shell directly
                    cmd = ['/bin/sh', exe_full]
                    if use_config_file:
                        if additional_args:
                            cmd.extend(additional_args.split())
                        if config_file_path and config_argument and config_full and os.path.exists(config_full):
                            cmd.extend([config_argument, config_full])
                    else:
                        if startup_args:
                            cmd.extend(startup_args.split())
                    shell = False
            elif exe_full.lower().endswith('.jar'):
                # For JAR files, use Java command (special handling for Minecraft)
                if server_type == "Minecraft":
                    cmd = f'java -Xmx1024M -Xms1024M -jar "{exe_full}" nogui'
                else:
                    cmd = f'java -jar "{exe_full}"'
                
                if use_config_file:
                    if additional_args:
                        cmd += f' {additional_args}'
                    if config_file_path and config_argument and config_full and os.path.exists(config_full):
                        cmd += f' {config_argument} "{config_full}"'
                else:
                    if startup_args:
                        cmd += f' {startup_args}'
                shell = True
            else:
                # For regular executables (.exe, etc.) - Default handling for most servers like Factorio
                # Use shell=False with proper argument list to avoid shell parsing issues
                cmd = [exe_full]
                if use_config_file:
                    # Config file mode
                    if additional_args:
                        # Parse arguments and remove quotes since shell=False handles escaping
                        args = []
                        for arg in additional_args.split():
                            args.append(arg.strip('"\''))
                        cmd.extend(args)
                    if config_file_path and config_argument and config_full and os.path.exists(config_full):
                        cmd.extend([config_argument, config_full])
                else:
                    # Manual arguments mode
                    if startup_args:
                        # Parse arguments and remove quotes since shell=False handles escaping
                        args = []
                        for arg in startup_args.split():
                            args.append(arg.strip('"\''))
                        cmd.extend(args)
                shell = False
            
            server_logs_dir = os.path.join(install_dir, "logs")
            os.makedirs(server_logs_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stdout_log = os.path.join(server_logs_dir, f"server_stdout_{timestamp}.log")
            stderr_log = os.path.join(server_logs_dir, f"server_stderr_{timestamp}.log")
            
            logger.info(f"Starting server '{server_name}' with command: {cmd}")
            
            if callback:
                callback(f"Starting server '{server_name}'...")
            
            # Initialize log files (console will handle the actual logging)
            with open(stdout_log, 'w') as stdout_file, open(stderr_log, 'w') as stderr_file:
                start_time = datetime.now()
                time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
                cmd_str = cmd if isinstance(cmd, str) else ' '.join(f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd)
                stdout_file.write(f"--- Server started at {time_str} ---\n")
                stdout_file.write(f"Command: {cmd_str}\n\n")
                stderr_file.write(f"--- Server started at {time_str} ---\n")
                stderr_file.write(f"Command: {cmd_str}\n\n")
                
            # Create process with pipes for real-time console interaction
            hide_consoles = should_hide_server_consoles(self.config)
            
            # For Steam/Source servers, try to force console output to stdout
            cmd_str_check = cmd if isinstance(cmd, str) else ' '.join(cmd)
            if "srcds" in cmd_str_check.lower() or "steamcmd" in cmd_str_check.lower():
                # Add console output flags for Source servers
                if isinstance(cmd, str):
                    if "-console" not in cmd:
                        cmd += " -console"
                    if "-condebug" not in cmd:
                        cmd += " -condebug"
                else:
                    if "-console" not in cmd:
                        cmd.append("-console")
                    if "-condebug" not in cmd:
                        cmd.append("-condebug")
                    
            if shell:
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=install_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Redirect stderr to stdout for combined output
                    text=True,
                    bufsize=0,  # Unbuffered for real-time output
                    universal_newlines=True,
                    creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                )
            else:
                process = subprocess.Popen(
                    cmd,
                    cwd=install_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Redirect stderr to stdout for combined output
                    text=True,
                    bufsize=0,  # Unbuffered for real-time output
                    universal_newlines=True,
                    creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                )
            time.sleep(1)
            if not psutil.pid_exists(process.pid):
                logger.error(f"Server process terminated immediately after starting. Check logs at {stderr_log}")
                if callback:
                    callback(f"Server '{server_name}' failed to start")
                return False, f"Server process terminated immediately after starting. Check logs at {stderr_log}"
            
            # Update server configuration
            server_config['ProcessId'] = process.pid
            server_config['PID'] = process.pid  # For console manager compatibility
            server_config['StartTime'] = start_time.isoformat()
            server_config['LastUpdate'] = datetime.now().isoformat()
            server_config['LogStdout'] = stdout_log
            server_config['LogStderr'] = stderr_log
            
            # Save updated configuration
            self.save_server_config(server_name, server_config)
            
            # Store the process object for console access
            if not hasattr(self, 'active_processes'):
                self.active_processes = {}
            self.active_processes[server_name] = process
            
            if callback:
                callback(f"Server '{server_name}' started successfully")
            
            logger.info(f"Server '{server_name}' started successfully with PID {process.pid}.")
            return True, process  # Return the process object for console
            
        except Exception as e:
            logger.error(f"Error starting server '{server_name}': {str(e)}")
            if callback:
                callback(f"Error starting server '{server_name}': {str(e)}")
            return False, f"Error starting server '{server_name}': {str(e)}"

    def stop_server_advanced(self, server_name, callback=None):
        """Stop the selected game server - Advanced version with proper process management"""
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"
                
            # Read server configuration
            with open(config_file, 'r') as f:
                server_config = json.load(f)
                
            # Check if server has a process ID registered
            if 'ProcessId' not in server_config:
                logger.info(f"Server '{server_name}' is not running.")
                if callback:
                    callback(f"Server '{server_name}' is not running")
                return False, f"Server '{server_name}' is not running."
                
            process_id = server_config['ProcessId']
            
            # Check if process is still running
            if not self.is_process_running(process_id):
                logger.info(f"Server process (PID {process_id}) is not running.")
                
                # Clean up the process ID in the config
                server_config.pop('ProcessId', None)
                server_config.pop('StartTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                
                # Save updated configuration
                self.save_server_config(server_name, server_config)
                
                if callback:
                    callback(f"Server '{server_name}' was not running")
                return False, f"Server process (PID {process_id}) is not running."
                
            if callback:
                callback(f"Stopping server '{server_name}'...")
                
            # Try to use custom stop command if available
            if 'StopCommand' in server_config and server_config['StopCommand']:
                try:
                    stop_cmd = server_config['StopCommand']
                    install_dir = server_config.get('InstallDir', '')
                    
                    logger.info(f"Executing custom stop command: {stop_cmd}")
                    
                    # Execute stop command with timeout
                    stop_process = subprocess.Popen(
                        stop_cmd, 
                        shell=True, 
                        cwd=install_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=get_subprocess_creation_flags(hide_window=True)  # Always hide for stop commands
                    )
                    
                    try:
                        stdout, stderr = stop_process.communicate(timeout=30)
                        if stderr:
                            logger.warning(f"Stop command produced error output: {stderr.decode('utf-8', errors='replace')}")
                    except subprocess.TimeoutExpired:
                        stop_process.kill()
                        logger.warning("Stop command timed out after 30 seconds")
                    
                    # Wait a bit to see if the process stops
                    for _ in range(5):  # Try for 5 seconds
                        if not self.is_process_running(process_id):
                            # Process stopped successfully
                            server_config.pop('ProcessId', None)
                            server_config.pop('StartTime', None)
                            server_config['LastUpdate'] = datetime.now().isoformat()
                            
                            # Save updated configuration
                            self.save_server_config(server_name, server_config)
                            
                            logger.info(f"Server '{server_name}' stopped successfully.")
                            return True, f"Server '{server_name}' stopped successfully."
                        time.sleep(1)
                        
                    logger.warning(f"Custom stop command did not stop the server, using force termination")
                except Exception as e:
                    logger.error(f"Error executing custom stop command: {str(e)}")
            
            # If we got here, either the custom stop command failed or wasn't available
            # Try to terminate the process
            try:
                process = psutil.Process(process_id)
                
                # Get all child processes
                children = []
                try:
                    children = process.children(recursive=True)
                except:
                    logger.warning(f"Could not get child processes for PID {process_id}")
                
                # First try graceful termination
                try:
                    process.terminate()
                    logger.info(f"Sent termination signal to process {process_id}")
                except:
                    logger.warning(f"Failed to terminate process {process_id}")
                
                # Wait up to 5 seconds for the process to terminate
                gone, alive = psutil.wait_procs([process], timeout=5)
                
                if process in alive:
                    # If it doesn't terminate, kill it forcefully
                    logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                    process.kill()
                
                # Terminate any remaining child processes
                if children:
                    for child in children:
                        try:
                            if child.is_running():
                                child.kill()
                                logger.info(f"Killed child process with PID {child.pid}")
                        except:
                            pass
                
                logger.info(f"Terminated process PID {process_id}")
                
                # Update server configuration
                server_config.pop('ProcessId', None)
                server_config.pop('StartTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                
                # Save updated configuration
                self.save_server_config(server_name, server_config)
                
                if callback:
                    callback(f"Server '{server_name}' stopped successfully")
                
                logger.info(f"Server '{server_name}' stopped successfully.")
                return True, f"Server '{server_name}' stopped successfully."
                
            except Exception as e:
                logger.error(f"Failed to stop server process: {str(e)}")
                if callback:
                    callback(f"Failed to stop server: {str(e)}")
                return False, f"Failed to stop server: {str(e)}"
                
        except Exception as e:
            logger.error(f"Error stopping server: {str(e)}")
            if callback:
                callback(f"Error stopping server: {str(e)}")
            return False, f"Failed to stop server: {str(e)}"

    def restart_server_advanced(self, server_name, callback=None):
        """Restart the selected game server - Advanced version with proper process management"""
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"
                
            # Read server configuration
            with open(config_file, 'r') as f:
                server_config = json.load(f)
            
            # Check if server is running
            is_running = False
            if 'ProcessId' in server_config:
                process_id = server_config['ProcessId']
                is_running = self.is_process_running(process_id)
            
            if callback:
                callback(f"Restarting server '{server_name}'...")
            
            # If running, stop first (without confirmation dialog)
            if is_running:
                try:
                    # Try to use custom stop command if available
                    if 'StopCommand' in server_config and server_config['StopCommand']:
                        try:
                            stop_cmd = server_config['StopCommand']
                            install_dir = server_config.get('InstallDir', '')
                            
                            logger.info(f"Executing custom stop command for restart: {stop_cmd}")
                            
                            # Execute stop command with timeout
                            stop_process = subprocess.Popen(
                                stop_cmd, 
                                shell=True, 
                                cwd=install_dir,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                creationflags=get_subprocess_creation_flags(hide_window=True)  # Always hide for stop commands
                            )
                            
                            try:
                                stdout, stderr = stop_process.communicate(timeout=30)
                                if stderr:
                                    logger.warning(f"Stop command produced error output: {stderr.decode('utf-8', errors='replace')}")
                            except subprocess.TimeoutExpired:
                                stop_process.kill()
                                logger.warning("Stop command timed out after 30 seconds")
                        
                            # Wait a bit to see if the process stops
                            for _ in range(5):  # Try for 5 seconds
                                if not self.is_process_running(process_id):
                                    # Process stopped successfully
                                    break
                                time.sleep(1)
                            else:
                                logger.warning(f"Custom stop command did not stop the server, using force termination")
                                raise Exception("Custom stop command failed")
                        
                        except Exception as e:
                            logger.error(f"Error executing custom stop command: {str(e)}")
                            # Fall through to force termination
                    
                    # If we got here, either the custom stop command failed or wasn't available
                    # Try to terminate the process
                    if self.is_process_running(process_id):
                        process = psutil.Process(process_id)
                        
                        # Get all child processes
                        children = []
                        try:
                            children = process.children(recursive=True)
                        except:
                            logger.warning(f"Could not get child processes for PID {process_id}")
                        
                        # First try graceful termination
                        try:
                            process.terminate()
                            logger.info(f"Sent termination signal to process {process_id} for restart")
                        except:
                            logger.warning(f"Failed to terminate process {process_id}")
                        
                        # Wait up to 5 seconds for the process to terminate
                        gone, alive = psutil.wait_procs([process], timeout=5)
                        
                        if process in alive:
                            # If it doesn't terminate, kill it forcefully
                            logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                            process.kill()
                        
                        # Terminate any remaining child processes
                        if children:
                            for child in children:
                                try:
                                    if child.is_running():
                                        child.kill()
                                        logger.info(f"Killed child process with PID {child.pid}")
                                except:
                                    pass
                
                except Exception as e:
                    logger.error(f"Failed to stop server process during restart: {str(e)}")
                    if callback:
                        callback(f"Failed to stop server for restart: {str(e)}")
                    return False, f"Failed to stop server for restart: {str(e)}"
                
                # Wait a moment for process to fully terminate
                time.sleep(2)
            
            # Start the server
            success, message = self.start_server_advanced(server_name, callback)
            if success:
                if callback:
                    callback(f"Server '{server_name}' restarted successfully")
                logger.info(f"Server '{server_name}' restarted successfully.")
                return True, f"Server '{server_name}' restarted successfully."
            else:
                if callback:
                    callback(f"Failed to start server after stopping: {message}")
                return False, f"Failed to start server after stopping: {message}"
            
        except Exception as e:
            logger.error(f"Error restarting server: {str(e)}")
            if callback:
                callback(f"Error restarting server: {str(e)}")
            return False, f"Failed to restart server: {str(e)}"

    def remove_server_config(self, server_name):
        """Remove a server configuration"""
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"
                
            # Check if server is running
            with open(config_file, 'r') as f:
                server_config = json.load(f)
                
            if 'ProcessId' in server_config and self.is_process_running(server_config['ProcessId']):
                logger.error(f"Cannot remove server '{server_name}' while it is running.")
                return False, f"Cannot remove server '{server_name}' while it is running. Please stop the server first."
                
            # Remove the configuration file
            os.remove(config_file)
            logger.info(f"Removed server configuration: {server_name}")
            
            # Remove from cache
            if server_name in self.servers:
                del self.servers[server_name]
            
            return True, f"Server '{server_name}' configuration removed successfully."
            
        except Exception as e:
            logger.error(f"Error removing server: {str(e)}")
            return False, f"Failed to remove server: {str(e)}"

    def update_server_config(self, server_name, executable_path, startup_args="", stop_command="", 
                           use_config_file=False, config_file_path="", config_argument="--config", 
                           additional_args=""):
        """Update server configuration with new settings"""
        try:
            # Get server config file path
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"
                
            # Read current configuration
            with open(config_file, 'r') as f:
                server_config = json.load(f)
            
            # Update configuration
            server_config.update({
                'ExecutablePath': executable_path,
                'StartupArgs': startup_args,
                'StopCommand': stop_command,
                'UseConfigFile': use_config_file,
                'ConfigFilePath': config_file_path,
                'ConfigArgument': config_argument,
                'AdditionalArgs': additional_args,
                'LastUpdate': datetime.now().isoformat()
            })
            
            # Save updated configuration
            self.save_server_config(server_name, server_config)
            
            logger.info(f"Updated configuration for server: {server_name}")
            return True, f"Configuration for '{server_name}' updated successfully."
            
        except Exception as e:
            logger.error(f"Error updating server configuration: {str(e)}")
            return False, f"Failed to update server configuration: {str(e)}"

    def import_server_config(self, server_name, server_type, install_dir, executable_path, startup_args=""):
        """Import an existing server from a directory"""
        try:
            # Check if server name already exists
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            if os.path.exists(config_file):
                logger.error(f"A server with name '{server_name}' already exists")
                return False, f"A server with name '{server_name}' already exists."
            
            # Validate install directory
            if not os.path.exists(install_dir):
                logger.error(f"Installation directory not found: {install_dir}")
                return False, f"Installation directory not found: {install_dir}"
            
            # For Minecraft servers, try to auto-detect a better executable if none provided
            if server_type == "Minecraft" and not executable_path:
                # Try to import minecraft module for detection
                try:
                    from Modules.minecraft import MinecraftServerManager
                    mc_manager = MinecraftServerManager(self.server_manager_dir, self.config)
                    exec_type, detected_path = mc_manager.detect_server_executable(install_dir)
                    if detected_path:
                        executable_path = os.path.basename(detected_path)
                        logger.info(f"Auto-detected Minecraft executable: {executable_path}")
                except ImportError:
                    logger.warning("Minecraft module not available for auto-detection")
            
            # If still no executable, try auto-detect with general method
            if not executable_path:
                detected_files = self.auto_detect_server_executable(install_dir)
                if detected_files:
                    executable_path = detected_files[0]
                    logger.info(f"Auto-detected executable: {executable_path}")
            
            # Validate executable path
            if executable_path:
                exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
                if not os.path.exists(exe_full):
                    logger.warning(f"Executable not found: {exe_full}")
                    # Don't fail import, just warn
            else:
                logger.warning(f"No executable found for server '{server_name}' in {install_dir}")
            
            # Create server configuration
            server_config = {
                "Name": server_name,
                "Type": server_type,
                "AppID": "",
                "InstallDir": install_dir,
                "ExecutablePath": executable_path or "",
                "StartupArgs": startup_args,
                "Created": datetime.now().isoformat(),
                "LastUpdate": datetime.now().isoformat(),
                "Imported": True
            }
            
            # Save configuration
            self.save_server_config(server_name, server_config)
            
            logger.info(f"Imported server: {server_name} from {install_dir}")
            return True, f"Server '{server_name}' imported successfully!"
            
        except Exception as e:
            logger.error(f"Error importing server: {str(e)}")
            return False, f"Failed to import server: {str(e)}"

    def auto_detect_server_executable(self, install_dir):
        """Auto-detect server executable in a directory"""
        try:
            if not os.path.exists(install_dir):
                return []
            
            found_files = []
            
            # Look for common server executables (prioritize by type)
            for file in os.listdir(install_dir):
                file_lower = file.lower()
                
                # Minecraft-specific executables
                if any(pattern in file_lower for pattern in [
                    'server.jar', 'minecraft_server', 'forge', 'fabric', 'spigot', 'paper',
                    'neoforge', 'bukkit', 'folia'
                ]) and file_lower.endswith('.jar'):
                    found_files.append(file)
                
                # Batch files for Minecraft servers
                elif any(pattern in file_lower for pattern in [
                    'run.bat', 'start.bat', 'server.bat', 'launch.bat'
                ]) and file_lower.endswith(('.bat', '.cmd')):
                    found_files.append(file)
                
                # Script files for servers (PowerShell and shell scripts)
                elif any(pattern in file_lower for pattern in [
                    'run.ps1', 'start.ps1', 'server.ps1', 'launch.ps1'
                ]) and file_lower.endswith('.ps1'):
                    found_files.append(file)
                
                elif any(pattern in file_lower for pattern in [
                    'run.sh', 'start.sh', 'server.sh', 'launch.sh'
                ]) and file_lower.endswith('.sh'):
                    found_files.append(file)
                
                # General server executables
                elif any(pattern in file_lower for pattern in [
                    'server.exe', 'dedicated', 'srcds'
                ]) and file_lower.endswith('.exe'):
                    found_files.append(file)
            
            # Sort to prioritize JAR files over scripts over executables
            found_files.sort(key=lambda x: (
                0 if x.lower().endswith('.jar') else
                1 if x.lower().endswith(('.bat', '.cmd')) else
                2 if x.lower().endswith(('.ps1', '.sh')) else
                3
            ))
            
            return found_files
            
        except Exception as e:
            logger.error(f"Error during auto-detect: {str(e)}")
            return []

    def get_server_status(self, server_name):
        """Get the current status of a server"""
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                return "Unknown", None
            
            if 'ProcessId' in server_config:
                pid = server_config['ProcessId']
                if self.is_process_running(pid):
                    return "Running", pid
                else:
                    return "Stopped", None
            else:
                return "Stopped", None
                
        except Exception as e:
            logger.error(f"Error getting server status: {str(e)}")
            return "Error", None
            
    def get_running_servers(self):
        """Get list of currently running servers"""
        try:
            running_servers = []
            for server_name in self.servers.keys():
                status, pid = self.get_server_status(server_name)
                if status == "Running" and pid:
                    running_servers.append(server_name)
            return running_servers
        except Exception as e:
            logger.error(f"Error getting running servers: {str(e)}")
            return []

    def validate_server_config(self, server_config, install_dir):
        """Validate a server configuration"""
        errors = []
        warnings = []
        
        try:
            # Check executable path
            executable_path = server_config.get('ExecutablePath', '')
            if not executable_path:
                errors.append("Executable path is required")
            else:
                exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
                if not os.path.exists(exe_full):
                    warnings.append(f"Executable not found: {exe_full}")
            
            # Check install directory
            if not install_dir or not os.path.exists(install_dir):
                errors.append(f"Installation directory not found: {install_dir}")
            
            # Check config file settings if enabled
            if server_config.get('UseConfigFile', False):
                config_file_path = server_config.get('ConfigFilePath', '')
                config_arg = server_config.get('ConfigArgument', '')
                
                if not config_file_path:
                    errors.append("Config file path is required when using config file mode")
                elif install_dir:
                    config_full = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                    if not os.path.exists(config_full):
                        warnings.append(f"Config file not found: {config_full}")
                
                if not config_arg:
                    errors.append("Config argument is required when using config file mode")
            
            return errors, warnings
            
        except Exception as e:
            logger.error(f"Error validating server config: {str(e)}")
            return [f"Validation error: {str(e)}"], []

    def install_steam_server(self, server_name, app_id, install_dir, steam_cmd_path, credentials, progress_callback=None, cancel_flag=None):
        """Install a Steam server using SteamCMD"""
        try:
            # Check for cancellation before starting
            if cancel_flag and cancel_flag.get():
                if progress_callback:
                    progress_callback("[INFO] Installation cancelled before starting")
                return False, "Installation cancelled by user"
                
            if progress_callback:
                progress_callback(f"[INFO] Starting Steam server installation for {server_name}")
            
            steam_cmd_exe = os.path.join(steam_cmd_path, "steamcmd.exe")
            if not os.path.exists(steam_cmd_exe):
                raise Exception(f"SteamCmd executable not found at: {steam_cmd_exe}")
            
            # Create install directory only if specified
            if install_dir:
                os.makedirs(install_dir, exist_ok=True)
                if progress_callback:
                    progress_callback(f"[INFO] Created installation directory: {install_dir}")
            else:
                if progress_callback:
                    progress_callback(f"[INFO] Using SteamCMD default installation location")
            
            # Build SteamCMD command
            login_cmd = "+login anonymous" if credentials.get("anonymous", True) else f"+login \"{credentials['username']}\" \"{credentials['password']}\""
            steam_cmd_args = [
                steam_cmd_exe,
                login_cmd,
            ]
            
            # Only add force_install_dir if install_dir is specified
            if install_dir:
                steam_cmd_args.append(f"+force_install_dir \"{install_dir}\"")
            
            steam_cmd_args.extend([
                f"+app_update {app_id} validate",
                "+quit"
            ])
            
            if progress_callback:
                progress_callback(f"[INFO] Running SteamCMD: {' '.join(steam_cmd_args)}")
            
            # Execute SteamCMD (always hide console for installation processes)
            process = subprocess.Popen(
                " ".join(steam_cmd_args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=get_subprocess_creation_flags(hide_window=True)
            )
            
            installation_success = False
            # Read output in real-time
            while True:
                # Check for cancellation
                if cancel_flag and cancel_flag.get():
                    if progress_callback:
                        progress_callback("[INFO] Installation cancelled by user, terminating SteamCMD...")
                    
                    # Terminate the SteamCMD process
                    try:
                        if progress_callback:
                            progress_callback("[INFO] Attempting to terminate SteamCMD gracefully...")
                        
                        # First try to terminate gracefully
                        process.terminate()
                        try:
                            # Wait for process to terminate gracefully
                            process.wait(timeout=5)
                            if progress_callback:
                                progress_callback("[INFO] SteamCMD terminated gracefully")
                        except subprocess.TimeoutExpired:
                            # If it doesn't terminate gracefully, force kill it
                            if progress_callback:
                                progress_callback("[WARN] SteamCMD did not terminate gracefully, killing forcefully...")
                            
                            # Kill the main process
                            process.kill()
                            
                            # Also kill any child processes on Windows
                            try:
                                import psutil
                                parent = psutil.Process(process.pid)
                                children = parent.children(recursive=True)
                                for child in children:
                                    try:
                                        child.kill()
                                        if progress_callback:
                                            progress_callback(f"[INFO] Killed child process {child.pid}")
                                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                                        pass
                                parent.kill()
                            except (ImportError, psutil.NoSuchProcess, psutil.AccessDenied):
                                # Fallback to Windows taskkill if psutil fails
                                try:
                                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                except:
                                    pass
                            
                            process.wait()
                            
                        if progress_callback:
                            progress_callback("[INFO] SteamCMD process terminated successfully")
                        return False, "Installation cancelled by user"
                    except Exception as e:
                        if progress_callback:
                            progress_callback(f"[ERROR] Failed to terminate SteamCMD process: {str(e)}")
                        return False, f"Installation cancelled, but failed to terminate process: {str(e)}"
                
                if process.stdout is not None:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        line = line.strip()
                        if progress_callback:
                            progress_callback(line)
                        if "Success! App" in line and "fully installed" in line:
                            installation_success = True
                    else:
                        # Small delay to make cancellation more responsive when no output
                        time.sleep(0.1)
                else:
                    if process.poll() is not None:
                        break
                    # Small delay when no stdout available
                    time.sleep(0.1)
            
            # Check for errors
            if process.stderr is not None:
                error_output = process.stderr.read()
                if error_output and progress_callback:
                    progress_callback(f"[WARN] SteamCMD Errors: {error_output}")
            
            exit_code = process.returncode
            if progress_callback:
                progress_callback(f"[INFO] SteamCMD process completed with exit code: {exit_code}")
            
            if exit_code != 0 and not installation_success:
                raise Exception(f"SteamCMD failed with exit code: {exit_code}")
            
            return True, "Steam server installed successfully"
            
        except Exception as e:
            logger.error(f"Steam server installation failed: {str(e)}")
            return False, f"Installation failed: {str(e)}"

    def install_minecraft_server(self, server_name, install_dir, version, modloader="Vanilla", progress_callback=None, cancel_flag=None):
        """Install a Minecraft server"""
        try:
            # Check for cancellation before starting
            if cancel_flag and cancel_flag.get():
                if progress_callback:
                    progress_callback("[INFO] Installation cancelled before starting")
                return False, "Installation cancelled by user"
                
            if progress_callback:
                progress_callback(f"[INFO] Starting Minecraft server installation for {server_name}")
            
            # Create install directory
            os.makedirs(install_dir, exist_ok=True)
            if progress_callback:
                progress_callback(f"[INFO] Created installation directory: {install_dir}")
            
            executable_path = None
            
            # Get Minecraft versions if needed
            mc_versions = fetch_minecraft_versions()
            if not mc_versions:
                raise Exception("Could not fetch Minecraft versions from Mojang")
            
            if modloader == "Vanilla":
                jar_url = get_minecraft_server_jar_url(version, mc_versions)
                if not jar_url:
                    raise Exception(f"Could not find server jar for version {version}")
                
                if progress_callback:
                    progress_callback(f"[INFO] Downloading Minecraft Vanilla server {version}...")
                
                jar_path = os.path.join(install_dir, f"minecraft_server.{version}.jar")
                urllib.request.urlretrieve(jar_url, jar_path)
                executable_path = jar_path
                
                if progress_callback:
                    progress_callback("[INFO] Download complete.")
                
            elif modloader == "Fabric":
                if progress_callback:
                    progress_callback(f"[INFO] Downloading Fabric installer for {version}...")
                
                fabric_url = fetch_fabric_installer_url(version)
                if not fabric_url:
                    raise Exception("Could not fetch Fabric installer")
                
                fabric_installer = os.path.join(install_dir, "fabric-installer.jar")
                urllib.request.urlretrieve(fabric_url, fabric_installer)
                
                if progress_callback:
                    progress_callback("[INFO] Fabric installer downloaded. Running installer...")
                
                # Run Fabric installer (always hide console for installation processes)
                subprocess.run([
                    "java", "-jar", fabric_installer, "server", 
                    "-mcversion", version, "-downloadMinecraft"
                ], cwd=install_dir, check=True, 
                creationflags=get_subprocess_creation_flags(hide_window=True))
                
                # Find fabric-server-launch.jar
                for fname in os.listdir(install_dir):
                    if fname.startswith("fabric-server-launch") and fname.endswith(".jar"):
                        executable_path = os.path.join(install_dir, fname)
                        break
                else:
                    raise Exception("Fabric server jar not found after install")
                
                if progress_callback:
                    progress_callback("[INFO] Fabric server installed successfully.")
                
            elif modloader == "Forge":
                if progress_callback:
                    progress_callback(f"[INFO] Downloading Forge installer for {version}...")
                
                forge_url = fetch_forge_installer_url(version)
                if not forge_url:
                    raise Exception("Could not fetch Forge installer")
                
                forge_installer = os.path.join(install_dir, "forge-installer.jar")
                urllib.request.urlretrieve(forge_url, forge_installer)
                
                if progress_callback:
                    progress_callback("[INFO] Forge installer downloaded. Running installer...")
                
                # Run Forge installer (always hide console for installation processes)
                subprocess.run([
                    "java", "-jar", forge_installer, "--installServer"
                ], cwd=install_dir, check=True,
                creationflags=get_subprocess_creation_flags(hide_window=True))
                
                # Find forge jar
                for fname in os.listdir(install_dir):
                    if fname.startswith("forge-") and fname.endswith(".jar") and "installer" not in fname:
                        executable_path = os.path.join(install_dir, fname)
                        break
                else:
                    raise Exception("Forge server jar not found after install")
                
                if progress_callback:
                    progress_callback("[INFO] Forge server installed successfully.")
                
            elif modloader == "NeoForge":
                if progress_callback:
                    progress_callback(f"[INFO] Downloading NeoForge installer for {version}...")
                
                neoforge_url = fetch_neoforge_installer_url(version)
                if not neoforge_url:
                    raise Exception("Could not fetch NeoForge installer")
                
                neoforge_installer = os.path.join(install_dir, "neoforge-installer.jar")
                urllib.request.urlretrieve(neoforge_url, neoforge_installer)
                
                if progress_callback:
                    progress_callback("[INFO] NeoForge installer downloaded. Running installer...")
                
                # Run NeoForge installer (always hide console for installation processes)
                subprocess.run([
                    "java", "-jar", neoforge_installer, "--installServer"
                ], cwd=install_dir, check=True,
                creationflags=get_subprocess_creation_flags(hide_window=True))
                
                # Find neoforge jar
                for fname in os.listdir(install_dir):
                    if fname.startswith("neoforge-") and fname.endswith(".jar") and "installer" not in fname:
                        executable_path = os.path.join(install_dir, fname)
                        break
                else:
                    raise Exception("NeoForge server jar not found after install")
                
                if progress_callback:
                    progress_callback("[INFO] NeoForge server installed successfully.")
            else:
                raise Exception(f"Unknown mod loader: {modloader}")
            
            # Accept EULA
            eula_path = os.path.join(install_dir, "eula.txt")
            with open(eula_path, "w") as f:
                f.write("eula=true\n")
            
            if progress_callback:
                progress_callback("[INFO] EULA accepted.")
            
            return True, executable_path
            
        except Exception as e:
            logger.error(f"Minecraft server installation failed: {str(e)}")
            return False, f"Installation failed: {str(e)}"

    def create_server_config(self, server_name, server_type, install_dir, executable_path, startup_args="", 
                           app_id="", version="", modloader="", additional_config=None):
        """Create and save a server configuration"""
        try:
            # Check if server name already exists
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            if os.path.exists(config_file):
                return False, "A server with this name already exists"
            
            # Create server configuration
            server_config = {
                "Name": server_name,
                "Type": server_type,
                "AppID": app_id,
                "InstallDir": install_dir,
                "ExecutablePath": executable_path,
                "StartupArgs": startup_args,
                "Created": datetime.now().isoformat(),
                "LastUpdate": datetime.now().isoformat()
            }
            
            # Add type-specific configuration
            if server_type == "Minecraft":
                server_config["Version"] = version
                server_config["ModLoader"] = modloader
            
            # Add any additional configuration
            if additional_config:
                server_config.update(additional_config)
            
            # Save configuration
            os.makedirs(self.paths["servers"], exist_ok=True)
            with open(config_file, 'w') as f:
                json.dump(server_config, f, indent=4)
            
            logger.info(f"Server configuration saved: {server_name}")
            return True, "Server configuration created successfully"
            
        except Exception as e:
            logger.error(f"Error creating server config: {str(e)}")
            return False, f"Failed to create server configuration: {str(e)}"

    def install_server_complete(self, server_name, server_type, install_dir, executable_path="", 
                               startup_args="", app_id="", version="", modloader="", steam_cmd_path="", 
                               credentials=None, progress_callback=None, cancel_flag=None):
        """Complete server installation process"""
        try:
            installation_success = False
            actual_executable = executable_path
            
            if server_type == "Steam":
                if not app_id:
                    return False, "Steam App ID is required"
                if not steam_cmd_path:
                    return False, "SteamCMD path is required"
                
                success, message = self.install_steam_server(
                    server_name, app_id, install_dir, steam_cmd_path, 
                    credentials or {"anonymous": True}, progress_callback, cancel_flag
                )
                if not success:
                    return False, message
                installation_success = True
                
            elif server_type == "Minecraft":
                if not version:
                    return False, "Minecraft version is required"
                
                success, result = self.install_minecraft_server(
                    server_name, install_dir, version, modloader or "Vanilla", progress_callback, cancel_flag
                )
                if not success:
                    return False, result
                actual_executable = result  # Minecraft returns the actual executable path
                installation_success = True
                
            elif server_type == "Other":
                # For "Other" servers, just create the directory and use provided executable
                os.makedirs(install_dir, exist_ok=True)
                if progress_callback:
                    progress_callback(f"[INFO] Created directory for {server_type} server: {install_dir}")
                installation_success = True
                
            else:
                return False, f"Unsupported server type: {server_type}"
            
            # Create server configuration
            if installation_success:
                success, message = self.create_server_config(
                    server_name, server_type, install_dir, actual_executable, 
                    startup_args, app_id, version, modloader
                )
                if not success:
                    return False, message
                
                if progress_callback:
                    progress_callback(f"[SUCCESS] Server '{server_name}' installed and configured successfully!")
                
                return True, f"Server '{server_name}' installed successfully"
            
            return False, "Installation failed"
            
        except Exception as e:
            logger.error(f"Complete server installation failed: {str(e)}")
            return False, f"Installation failed: {str(e)}"

    def get_minecraft_versions(self):
        """Get available Minecraft versions"""
        try:
            return fetch_minecraft_versions()
        except Exception as e:
            logger.error(f"Error fetching Minecraft versions: {str(e)}")
            return []

    def get_supported_server_types(self):
        """Get list of supported server types"""
        return ["Steam", "Minecraft", "Other"]

    def uninstall_server(self, server_name, remove_files=False, progress_callback=None):
        """Uninstall a server (remove config and optionally files)"""
        try:
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            
            if not os.path.exists(config_file):
                return False, "Server configuration not found"
            
            # Load server config to get install directory
            install_dir = None
            if remove_files:
                try:
                    with open(config_file, 'r') as f:
                        server_config = json.load(f)
                    install_dir = server_config.get('InstallDir')
                except Exception as e:
                    logger.warning(f"Could not read server config for file removal: {str(e)}")
            
            # Stop server if running
            if progress_callback:
                progress_callback(f"[INFO] Stopping server {server_name} if running...")
            
            success, message = self.stop_server_advanced(server_name)
            if not success and "not running" not in message.lower():
                logger.warning(f"Could not stop server before removal: {message}")
            
            # Remove configuration file
            if progress_callback:
                progress_callback(f"[INFO] Removing server configuration...")
            
            os.remove(config_file)
            
            # Remove files if requested
            if remove_files and install_dir and os.path.exists(install_dir):
                if progress_callback:
                    progress_callback(f"[INFO] Removing server files from {install_dir}...")
                
                import shutil
                try:
                    shutil.rmtree(install_dir)
                    if progress_callback:
                        progress_callback(f"[INFO] Server files removed successfully")
                except Exception as e:
                    logger.warning(f"Could not remove server files: {str(e)}")
                    if progress_callback:
                        progress_callback(f"[WARN] Could not remove all server files: {str(e)}")
            
            if progress_callback:
                progress_callback(f"[SUCCESS] Server '{server_name}' uninstalled successfully!")
            
            logger.info(f"Server uninstalled: {server_name} (files removed: {remove_files})")
            return True, f"Server '{server_name}' uninstalled successfully"
            
        except Exception as e:
            logger.error(f"Error uninstalling server: {str(e)}")
            return False, f"Failed to uninstall server: {str(e)}"

# Create singleton instance
server_manager = ServerManager()
