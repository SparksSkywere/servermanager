# Server management core
import os
import sys
import json
import logging
import subprocess
import time
import psutil
import urllib.request
from datetime import datetime

from Modules.common import (
    get_subprocess_creation_flags, should_hide_server_consoles, 
    setup_module_logging, REGISTRY_ROOT, REGISTRY_PATH
)
from Modules.server_logging import get_component_logger, log_server_action, log_exception

# Import stdin relay for persistent command input
try:
    from services.stdin_relay import start_relay_for_server, send_command_via_relay
    _STDIN_RELAY_AVAILABLE = True
except ImportError:
    _STDIN_RELAY_AVAILABLE = False

# Import persistent stdin pipe (allows commands after dashboard restart)
try:
    from services.persistent_stdin import (
        PersistentStdinPipe, 
        send_command_to_stdin_pipe, 
        is_stdin_pipe_available
    )
    _PERSISTENT_STDIN_AVAILABLE = True
except ImportError:
    _PERSISTENT_STDIN_AVAILABLE = False

# Import command queue relay (file-based command queuing)
try:
    from services.command_queue import (
        start_command_relay,
        stop_command_relay,
        queue_command,
        is_relay_active
    )
    _COMMAND_QUEUE_AVAILABLE = True
except ImportError:
    _COMMAND_QUEUE_AVAILABLE = False

logger = setup_module_logging("ServerManager")

# Import Minecraft-specific functions (NO FALLBACKS)
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Modules'))

try:
    from Modules.minecraft import (
        fetch_minecraft_versions, get_minecraft_server_jar_url,
        fetch_fabric_installer_url, fetch_forge_installer_url,
        fetch_neoforge_installer_url
    )
except ImportError as e:
    error_msg = f"Minecraft helper functions not available: {e}"
    logger.error(error_msg)
    raise Exception(f"Minecraft module unavailable: {error_msg}")

from Modules.common import ServerManagerModule

class ServerManager(ServerManagerModule):
    # - Handles all server operations
    # - Start, stop, restart, status, config
    def __init__(self):
        super().__init__("ServerManager")
        self.servers = {}
        
        self.load_config()
        self.load_servers()

    def get_server_process(self, server_name):
        # Get active process-None if dead
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
        # All servers dict
        return self.servers
        
    def load_config(self):
        # Pull config from database
        try:
            from Modules.Database.cluster_database import ClusterDatabase
            db = ClusterDatabase()
            
            # Get main config from database
            config_data = db.get_main_config()
            
            # Migrate from JSON if database is empty
            if not config_data and self.server_manager_dir:
                # Try to find config.json in the server manager directory
                config_file = os.path.join(self.server_manager_dir, "config", "config.json")
                if os.path.exists(config_file):
                    logger.debug("Migrating main config from JSON to database")
                    db.migrate_main_config_from_json(config_file)
                    # Reload after migration
                    config_data = db.get_main_config()
            
            # Update the inherited config
            self._config_manager.config.update(config_data)
            logger.debug("Configuration loaded from database")
            
        except Exception as e:
            logger.error(f"Error loading configuration from database: {str(e)}")
            # Create default configuration in database
            self.create_default_config()
            
    def create_default_config(self):
        # Create default configuration in database
        try:
            from Modules.Database.cluster_database import ClusterDatabase
            db = ClusterDatabase()
            
            default_config = {
                "version": "1.0.0",
                "web_port": 8080,
                "log_level": "INFO",
                "steam_cmd_path": os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), "SteamCMD"),
                "auto_update_check_interval": 3600,  # seconds
                "max_log_files": 10,
                "max_log_size": 10 * 1024 * 1024  # 10 MB
            }
            
            # Set each config value individually
            for key, value in default_config.items():
                config_type = 'integer' if isinstance(value, int) else 'string'
                db.set_main_config(key, value, config_type)
            self._config_manager.config.update(default_config)
            logger.debug("Default configuration created in database")
            
        except Exception as e:
            logger.error(f"Error creating default configuration: {str(e)}")
            
    def load_servers(self):
        # Load list of servers from config directory
        try:
            servers_dir = self.paths["servers"]
            
            if not os.path.exists(servers_dir):
                os.makedirs(servers_dir, exist_ok=True)
                logger.debug(f"Created servers directory: {servers_dir}")
                return
                
            for file in os.listdir(servers_dir):
                if file.endswith(".json"):
                    self._load_server_config_with_retry(os.path.join(servers_dir, file))
                        
            logger.debug(f"Loaded {len(self.servers)} server configurations")
        except Exception as e:
            logger.error(f"Error loading servers: {str(e)}")
    
    def _load_server_config_with_retry(self, file_path, max_retries=3, delay=0.1):
        # Load server config with retry on file access errors
        import time
        for attempt in range(max_retries):
            try:
                with open(file_path, 'r') as f:
                    server_config = json.load(f)
                    
                server_name = server_config.get("Name")
                if server_name:
                    self.servers[server_name] = server_config
                return
            except IOError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Retrying load of {file_path} after IOError: {str(e)}")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to load server config {file_path} after {max_retries} attempts: {str(e)}")
            except Exception as e:
                logger.error(f"Error loading server config {file_path}: {str(e)}")
                return
            
    def get_server_config(self, server_name):
        # Get configuration for a specific server
        if server_name in self.servers:
            return self.servers[server_name]
            
        # Try to load from file if not in memory
        config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
        if os.path.exists(config_path):
            self._load_server_config_with_retry(config_path)
            return self.servers.get(server_name)
                
        return None
        
    def save_server_config(self, server_name, config):
        # Save configuration for a specific server
        import time
        max_retries = 3
        delay = 0.1
        for attempt in range(max_retries):
            try:
                config_path = os.path.join(self.paths["servers"], f"{server_name}.json")
                
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                    
                # Update cache
                self.servers[server_name] = config
                
                logger.debug(f"Server configuration saved for {server_name}")
                return True
            except IOError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Retrying save of {server_name} after IOError: {str(e)}")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to save server config {server_name} after {max_retries} attempts: {str(e)}")
                    return False
            except Exception as e:
                logger.error(f"Error saving server config {server_name}: {str(e)}")
                return False
            
    def get_server_list(self):
        # Get list of all configured servers
        return list(self.servers.values())
    
    def get_all_servers(self):
        return self.servers.copy()
    
    def reload_servers(self):
        # Reload all server configurations from disk
        self.servers.clear()
        self.load_servers()
    
    def reload_server(self, server_name):
        # Reload a specific server configuration from disk
        try:
            servers_dir = self.paths["servers"]
            config_file = os.path.join(servers_dir, f"{server_name}.json")
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    server_config = json.load(f)
                self.servers[server_name] = server_config
                return True
        except Exception as e:
            logger.error(f"Error reloading server config for {server_name}: {e}")
        return False
            
    def is_process_running(self, pid):
        # Check if a process with the given ID is running
        try:
            if pid is None:
                return False
            return psutil.pid_exists(pid)
        except Exception:
            return False
    
    def is_server_process_valid(self, server_name, process_id, server_config=None):
        # Validate that a PID actually belongs to the server it's claimed to be
        # This prevents issues with Windows PID reuse where an old PID might now
        # belong to a completely different process
        # Enhanced with corruption detection and system state validation
        # Returns: (is_valid, process_or_none)
        try:
            if process_id is None:
                return False, None

            if not psutil.pid_exists(process_id):
                return False, None

            try:
                process = psutil.Process(process_id)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False, None

            if not process.is_running():
                return False, None

            # Get server config if not provided
            if server_config is None:
                server_config = self.get_server_config(server_name)

            if not server_config:
                # No config to validate against, just check if process exists
                return True, process

            # Validate the process matches the server
            install_dir = server_config.get('InstallDir', '')
            executable_path = server_config.get('ExecutablePath', '')
            server_type = server_config.get('Type', '').lower()

            try:
                proc_exe = process.exe().lower() if process.exe() else ''
                proc_cwd = process.cwd().lower() if process.cwd() else ''
                proc_name = process.name().lower() if process.name() else ''

                # Try to get command line
                try:
                    cmdline = process.cmdline()
                    cmdline_str = ' '.join(cmdline).lower() if cmdline else ''
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    cmdline_str = ''

                # Enhanced: Check for process corruption indicators
                try:
                    # Check if process has abnormally high memory usage (potential memory corruption)
                    memory_percent = process.memory_percent()
                    if memory_percent > 90:  # Over 90% memory usage is suspicious
                        logger.warning(f"Process {process_id} for {server_name} using {memory_percent:.1f}% memory - possible corruption")
                        # Don't immediately invalidate, but log for monitoring

                    # Check if process is in zombie state
                    if process.status() == psutil.STATUS_ZOMBIE:
                        logger.warning(f"Process {process_id} for {server_name} is in zombie state")
                        return False, None

                    # Check for unusual CPU usage patterns (stuck processes)
                    cpu_times = process.cpu_times()
                    if cpu_times and hasattr(cpu_times, 'user'):
                        # If process has been running for > 5 minutes but minimal CPU time, might be stuck
                        try:
                            create_time = process.create_time()
                            runtime_seconds = time.time() - create_time
                            total_cpu_time = cpu_times.user + cpu_times.system
                            if runtime_seconds > 300 and total_cpu_time < 1.0:  # 5 minutes, < 1 second CPU
                                logger.warning(f"Process {process_id} for {server_name} appears stuck (runtime: {runtime_seconds:.0f}s, CPU: {total_cpu_time:.1f}s)")
                        except:
                            pass

                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            except (psutil.AccessDenied, psutil.NoSuchProcess):
                # Can't access process info, assume invalid
                logger.debug(f"Cannot access process {process_id} info for validation")
                return False, None

            # Validation checks
            install_dir_lower = install_dir.lower() if install_dir else ''
            executable_lower = executable_path.lower() if executable_path else ''

            # Check 1: Working directory matches install directory
            if install_dir_lower and proc_cwd:
                if os.path.normpath(proc_cwd) == os.path.normpath(install_dir_lower):
                    logger.debug(f"PID {process_id} validated: CWD matches install dir")
                    return True, process

            # Check 2: Executable path matches
            if executable_lower and proc_exe:
                exe_basename = os.path.basename(executable_lower)
                proc_exe_basename = os.path.basename(proc_exe)
                if exe_basename == proc_exe_basename:
                    logger.debug(f"PID {process_id} validated: executable name matches")
                    return True, process

            # Check 3: Install directory in executable path
            if install_dir_lower and proc_exe and install_dir_lower in proc_exe:
                logger.debug(f"PID {process_id} validated: install dir in exe path")
                return True, process

            # Check 4: Command line contains server-specific info
            if cmdline_str:
                if install_dir_lower and install_dir_lower in cmdline_str:
                    logger.debug(f"PID {process_id} validated: install dir in cmdline")
                    return True, process
                if executable_lower and executable_lower in cmdline_str:
                    logger.debug(f"PID {process_id} validated: executable in cmdline")
                    return True, process

            # Check 5: Type-specific validation
            if server_type == 'minecraft':
                # For Minecraft, the java process should have the server jar in cmdline
                if 'java' in proc_name or 'javaw' in proc_name:
                    if cmdline_str and (install_dir_lower in cmdline_str or 'server.jar' in cmdline_str):
                        logger.debug(f"PID {process_id} validated: Minecraft java process")
                        return True, process

            # Check 6: Stored process creation time (if available)
            stored_create_time = server_config.get('ProcessCreateTime')
            if stored_create_time:
                try:
                    actual_create_time = process.create_time()
                    # Allow 2 second tolerance for timing differences
                    if abs(actual_create_time - stored_create_time) < 2:
                        logger.debug(f"PID {process_id} validated: create time matches")
                        return True, process
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            # Enhanced: Check for system state corruption indicators
            try:
                # Check if install directory still exists and is accessible
                if install_dir and not os.path.exists(install_dir):
                    logger.error(f"Install directory missing for {server_name}: {install_dir}")
                    return False, None

                # Check if executable still exists
                if executable_path and not os.path.exists(executable_path):
                    logger.error(f"Executable missing for {server_name}: {executable_path}")
                    return False, None

                # Check for config file corruption (basic JSON validation)
                config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
                if os.path.exists(config_file):
                    try:
                        with open(config_file, 'r', encoding='utf-8') as f:
                            json.load(f)  # Just validate JSON structure
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        logger.error(f"Config file corrupted for {server_name}: {e}")
                        return False, None

            except Exception as e:
                logger.debug(f"Error during system state validation for {server_name}: {e}")

            # If we get here, the process doesn't match the server
            logger.warning(f"PID {process_id} does NOT match server '{server_name}' (process: {proc_name}, cwd: {proc_cwd})")
            return False, None

        except Exception as e:
            logger.error(f"Error validating server process for {server_name}: {e}")
            return False, None
    
    def clear_stale_pid(self, server_name, server_config=None):
        # Clear stale PID from server config if it's no longer valid
        try:
            if server_config is None:
                server_config = self.get_server_config(server_name)
            
            if not server_config:
                return False
            
            pid = server_config.get('ProcessId') or server_config.get('PID')
            if not pid:
                return False
            
            is_valid, _ = self.is_server_process_valid(server_name, pid, server_config)
            if not is_valid:
                logger.info(f"Clearing stale PID {pid} for server '{server_name}'")
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                self.save_server_config(server_name, server_config)
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error clearing stale PID for {server_name}: {e}")
            return False

    def detect_and_recover_system_corruption(self, server_name, server_config=None, callback=None):
        # Detect and recover from system corruption after BSODs, power failures, or bad starts
        # Performs comprehensive system state validation and automatic recovery
        # Returns: (recovery_needed, recovery_actions_taken, errors)
        recovery_needed = False
        recovery_actions = []
        errors = []

        try:
            if server_config is None:
                server_config = self.get_server_config(server_name)

            if not server_config:
                errors.append(f"No configuration found for server {server_name}")
                return False, [], errors

            logger.info(f"Performing corruption detection and recovery for {server_name}")

            # 1. Check for config file corruption
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)

                    # Validate required fields
                    required_fields = ['InstallDir', 'ExecutablePath', 'Type']
                    missing_fields = [field for field in required_fields if field not in config_data]
                    if missing_fields:
                        errors.append(f"Config file missing required fields: {missing_fields}")
                        recovery_needed = True
                        recovery_actions.append("Config file validation failed")

                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    errors.append(f"Config file corrupted: {e}")
                    recovery_needed = True
                    recovery_actions.append("Config file corruption detected")

                    # Attempt to backup and recreate config
                    try:
                        backup_file = f"{config_file}.corrupted.{int(time.time())}"
                        os.rename(config_file, backup_file)
                        recovery_actions.append(f"Backed up corrupted config to {backup_file}")

                        # Create minimal recovery config
                        recovery_config = {
                            'Type': 'Other',
                            'InstallDir': '',
                            'ExecutablePath': '',
                            'LastUpdate': datetime.now().isoformat(),
                            'CorruptionRecovery': True
                        }
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump(recovery_config, f, indent=2)
                        recovery_actions.append("Created recovery config file")

                    except Exception as backup_error:
                        errors.append(f"Failed to backup corrupted config: {backup_error}")

            # 2. Check install directory integrity
            install_dir = server_config.get('InstallDir', '')
            if install_dir:
                if not os.path.exists(install_dir):
                    errors.append(f"Install directory missing: {install_dir}")
                    recovery_needed = True
                    recovery_actions.append("Install directory missing")
                else:
                    # Check if directory is accessible
                    try:
                        os.listdir(install_dir)
                    except PermissionError:
                        errors.append(f"Install directory not accessible: {install_dir}")
                        recovery_needed = True
                        recovery_actions.append("Install directory access denied")

            # 3. Check executable integrity
            executable_path = server_config.get('ExecutablePath', '')
            if executable_path:
                if not os.path.exists(executable_path):
                    errors.append(f"Executable missing: {executable_path}")
                    recovery_needed = True
                    recovery_actions.append("Executable file missing")
                else:
                    # Check if executable is accessible
                    try:
                        with open(executable_path, 'rb') as f:
                            f.read(1)  # Just check if we can read
                    except Exception as e:
                        errors.append(f"Executable not accessible: {e}")
                        recovery_needed = True
                        recovery_actions.append("Executable access failed")

            # 4. Check for orphaned process entries
            pid = server_config.get('ProcessId') or server_config.get('PID')
            if pid:
                is_valid, process = self.is_server_process_valid(server_name, pid, server_config)
                if not is_valid:
                    logger.warning(f"Stale PID {pid} detected for {server_name} during corruption check")
                    recovery_needed = True
                    recovery_actions.append(f"Cleaned up stale PID {pid}")

                    # Clean up stale entries
                    server_config.pop('ProcessId', None)
                    server_config.pop('PID', None)
                    server_config.pop('StartTime', None)
                    server_config.pop('ProcessCreateTime', None)
                    server_config['LastUpdate'] = datetime.now().isoformat()
                    self.save_server_config(server_name, server_config)

            # 5. Check log file integrity
            try:
                logs_dir = os.path.join(self.paths.get("logs", "logs"))
                if os.path.exists(logs_dir):
                    # Check for corrupted log files
                    for root, dirs, files in os.walk(logs_dir):
                        for file in files:
                            if file.endswith('.log'):
                                log_path = os.path.join(root, file)
                                try:
                                    # Quick corruption check - try to read last few lines
                                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        f.seek(0, 2)  # Seek to end
                                        size = f.tell()
                                        if size > 1000:  # If file is large, check last 1000 bytes
                                            f.seek(max(0, size - 1000), 0)
                                            content = f.read()
                                            if '\x00' in content:  # Null bytes indicate corruption
                                                errors.append(f"Log file corrupted: {log_path}")
                                                recovery_needed = True
                                                recovery_actions.append(f"Corrupted log file detected: {file}")
                                except Exception as e:
                                    errors.append(f"Error checking log file {log_path}: {e}")
            except Exception as e:
                logger.debug(f"Error during log integrity check: {e}")

            # 6. Check for system crash indicators (Windows event logs, etc.)
            try:
                if sys.platform == 'win32':
                    # Check for recent system crashes (basic check)
                    import winreg
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                           r"SYSTEM\CurrentControlSet\Control\CrashControl")
                        # This is a basic check - could be expanded
                        recovery_needed = True  # Assume recovery needed if we can access crash control
                        recovery_actions.append("System crash recovery indicators detected")
                    except:
                        pass
            except:
                pass

            # 7. Attempt automatic recovery if issues found
            if recovery_needed:
                logger.info(f"Recovery needed for {server_name}. Actions taken: {recovery_actions}")

                # Update config with recovery timestamp
                server_config['LastCorruptionCheck'] = datetime.now().isoformat()
                server_config['CorruptionRecoveryActions'] = recovery_actions
                self.save_server_config(server_name, server_config)

                if callback:
                    callback(f"Corruption recovery completed for {server_name}")

            return recovery_needed, recovery_actions, errors

        except Exception as e:
            error_msg = f"Error during corruption detection for {server_name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            return True, recovery_actions, errors

    def start_server(self, server_name):
        # Start a server using the appropriate script
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
        # Stop a server using the appropriate script
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
        # Start the selected game server (Steam/Minecraft/Other) - Advanced version with proper process management
        # Enhanced with corruption detection and automatic recovery
        try:
            config_file = os.path.join(self.paths["servers"], f"{server_name}.json")
            if not os.path.exists(config_file):
                logger.error(f"Server configuration file not found: {config_file}")
                return False, f"Server configuration file not found: {config_file}"

            with open(config_file, 'r') as f:
                server_config = json.load(f)

            # Enhanced: Perform corruption detection and recovery before starting
            logger.debug(f"Performing pre-startup corruption check for {server_name}")
            recovery_needed, recovery_actions, recovery_errors = self.detect_and_recover_system_corruption(
                server_name, server_config, callback
            )

            if recovery_errors:
                logger.warning(f"Corruption recovery errors for {server_name}: {recovery_errors}")
                # Don't fail startup for recovery errors, but log them

            if recovery_needed:
                logger.info(f"System corruption detected and recovered for {server_name}: {recovery_actions}")
                # Reload config after recovery
                try:
                    with open(config_file, 'r') as f:
                        server_config = json.load(f)
                except Exception as reload_error:
                    logger.error(f"Failed to reload config after recovery: {reload_error}")

            # Clean up orphaned process ID first - use proper validation
            if 'ProcessId' in server_config:
                pid = server_config['ProcessId']
                is_valid, _ = self.is_server_process_valid(server_name, pid, server_config)
                
                if is_valid:
                    logger.info(f"Server '{server_name}' is already running with PID {pid}.")
                    if callback:
                        callback(f"Server '{server_name}' is already running")
                    return False, f"Server '{server_name}' is already running with PID {pid}."
                else:
                    # PID is stale or belongs to different process - clean up
                    logger.debug(f"Cleaning up stale/invalid process ID {pid} for server '{server_name}'")
                    server_config.pop('ProcessId', None)
                    server_config.pop('PID', None)
                    server_config.pop('StartTime', None)
                    server_config.pop('ProcessCreateTime', None)
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
                return False, "No executable specified. Please configure the server startup settings in the server configuration dialog."
                
            # Resolve executable path
            exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
            # Normalise path separators for Windows compatibility
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
                # Normalise config file path separators
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
                        logger.debug(f"Using config file: {config_full}")
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
            
            logger.debug(f"Starting server '{server_name}' with command: {cmd}")
            
            if callback:
                callback(f"Starting server '{server_name}'...")
            
            # Initialise log files (console will handle the actual logging)
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

            # Create process with pipes for real-time console interaction
            hide_consoles = should_hide_server_consoles(self.config)

            # For Steam/Source servers, try to force console output to stdout
            cmd_str_check = cmd if isinstance(cmd, str) else ' '.join(cmd)
            if "srcds" in cmd_str_check.lower() or "steamcmd" in cmd_str_check.lower():
                # Add console output flags for Source servers
                if isinstance(cmd, str):
                    if "-condebug" not in cmd:
                        cmd += " -condebug"
                else:
                    if "-condebug" not in cmd:
                        cmd.append("-condebug")

            # Standard process creation
            if shell:
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=install_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=0,
                    universal_newlines=True,
                    creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                )
            else:
                process = subprocess.Popen(
                    cmd,
                    cwd=install_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=0,
                    universal_newlines=True,
                    creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                )
            time.sleep(1)

            # Enhanced: Automatic retry logic for failed startups
            max_retries = 3
            retry_delay = 2  # seconds
            startup_success = False

            for attempt in range(max_retries):
                if psutil.pid_exists(process.pid):
                    # Additional validation: check if process is actually running and not stuck
                    try:
                        ps_process = psutil.Process(process.pid)
                        if ps_process.is_running() and ps_process.status() != psutil.STATUS_ZOMBIE:
                            # Quick health check - ensure process hasn't exited immediately
                            time.sleep(0.5)  # Brief wait to see if process stays alive
                            if psutil.pid_exists(process.pid):
                                startup_success = True
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                if attempt < max_retries - 1:  # Don't retry on last attempt
                    logger.warning(f"Server process terminated immediately (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay}s...")
                    if callback:
                        callback(f"Server '{server_name}' failed to start (attempt {attempt + 1}), retrying...")

                    # Clean up failed process
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except:
                        try:
                            process.kill()
                        except:
                            pass

                    time.sleep(retry_delay)

                    # Retry process creation
                    try:
                        if shell:
                            process = subprocess.Popen(
                                cmd,
                                shell=True,
                                cwd=install_dir,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                bufsize=0,
                                universal_newlines=True,
                                creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                            )
                        else:
                            process = subprocess.Popen(
                                cmd,
                                cwd=install_dir,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                bufsize=0,
                                universal_newlines=True,
                                creationflags=get_subprocess_creation_flags(hide_window=hide_consoles, new_process_group=True)
                            )
                        time.sleep(1)  # Wait for process to initialise
                    except Exception as retry_error:
                        logger.error(f"Failed to retry process creation: {retry_error}")
                        break
                else:
                    logger.error(f"Server process terminated immediately after {max_retries} attempts. Check logs at {stderr_log}")
                    if callback:
                        callback(f"Server '{server_name}' failed to start after {max_retries} attempts")
                    return False, f"Server process terminated immediately after {max_retries} attempts. Check logs at {stderr_log}"

            if not startup_success:
                return False, f"Server process failed to start after {max_retries} attempts. Check logs at {stderr_log}"

            # Get process creation time for PID validation
            process_create_time = None
            try:
                ps_process = psutil.Process(process.pid)
                process_create_time = ps_process.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            # Update server configuration
            server_config['ProcessId'] = process.pid
            server_config['PID'] = process.pid  # For console manager compatibility
            server_config['StartTime'] = start_time.isoformat()
            server_config['LastUpdate'] = datetime.now().isoformat()
            server_config['LogStdout'] = stdout_log
            server_config['LogStderr'] = stderr_log
            
            # Store process creation time for PID validation on reattachment
            if process_create_time:
                server_config['ProcessCreateTime'] = process_create_time
            
            # Save updated configuration
            self.save_server_config(server_name, server_config)
            
            # Store the process object for console access
            if not hasattr(self, 'active_processes'):
                self.active_processes = {}
            self.active_processes[server_name] = process
            
            # Start command queue relay for persistent command input
            # This relay reads from a file and writes to stdin, allowing
            # commands to be queued even from other processes
            if _COMMAND_QUEUE_AVAILABLE:
                try:
                    from services.command_queue import start_command_relay
                    start_command_relay(server_name, process)
                    logger.debug(f"Started command queue relay for {server_name}")
                except Exception as e:
                    logger.warning(f"Failed to start command queue relay for {server_name}: {e}")
            
            # Also start the named pipe stdin relay as a backup method
            if _STDIN_RELAY_AVAILABLE:
                try:
                    from services.stdin_relay import start_relay_for_server
                    start_relay_for_server(server_name, process, process.pid)
                    logger.debug(f"Started stdin relay for {server_name}")
                except Exception as e:
                    logger.warning(f"Failed to start stdin relay for {server_name}: {e}")
            
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
        # Stop the selected game server - Advanced version with proper process management
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
            
            # Validate that the PID actually belongs to this server
            # This prevents stopping the wrong process if Windows reused the PID
            is_valid, validated_process = self.is_server_process_valid(server_name, process_id, server_config)
            
            if not is_valid:
                logger.warning(f"PID {process_id} is no longer valid for server '{server_name}' (stale or reused PID)")
                
                # Clean up the stale process ID in the config
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                
                # Save updated configuration
                self.save_server_config(server_name, server_config)
                
                if callback:
                    callback(f"Server '{server_name}' was not running (stale PID cleared)")
                return False, f"Server '{server_name}' was not running (stale PID {process_id} cleared)."
                
            if callback:
                callback(f"Stopping server '{server_name}'...")
                
            # Try to use custom stop command if available
            if 'StopCommand' in server_config and server_config['StopCommand']:
                try:
                    stop_cmd = server_config['StopCommand']
                    install_dir = server_config.get('InstallDir', '')
                    
                    logger.debug(f"Executing custom stop command: {stop_cmd}")
                    
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
                            # Process stopped successfully - clear all process-related fields
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
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
            # Try to terminate the process gracefully
            try:
                process = psutil.Process(process_id)
                
                # Store the process creation time to verify children belong to this server's process tree
                try:
                    server_process_create_time = process.create_time()
                except:
                    server_process_create_time = None
                
                # Get all child processes BEFORE terminating parent
                # Only include children that were started after the parent (same process tree)
                children = []
                try:
                    all_children = process.children(recursive=True)
                    for child in all_children:
                        try:
                            # Only include children created after the parent process
                            # This helps avoid killing unrelated processes that happen to share a common ancestor
                            if server_process_create_time is not None:
                                child_create_time = child.create_time()
                                if child_create_time >= server_process_create_time:
                                    children.append(child)
                            else:
                                children.append(child)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception as e:
                    logger.warning(f"Could not get child processes for PID {process_id}: {e}")
                
                logger.info(f"Initiating graceful shutdown for server '{server_name}' (PID {process_id}, {len(children)} child processes)")
                
                # STEP 1: Try graceful shutdown methods
                graceful_stopped = False
                
                # On Windows, try sending CTRL_BREAK_EVENT first (works for console apps)
                if sys.platform == 'win32':
                    try:
                        import signal
                        # CTRL_BREAK_EVENT is more likely to trigger graceful shutdown
                        os.kill(process_id, signal.CTRL_BREAK_EVENT)
                        logger.debug(f"Sent CTRL_BREAK_EVENT to process {process_id}")
                    except Exception as e:
                        logger.debug(f"CTRL_BREAK_EVENT failed: {e}")
                
                # Wait for graceful shutdown (up to 10 seconds for game servers)
                for i in range(10):
                    if not process.is_running():
                        logger.info(f"Process {process_id} stopped gracefully after {i+1} seconds")
                        graceful_stopped = True
                        break
                    time.sleep(1)
                
                # STEP 2: If still running, try terminate()
                if not graceful_stopped and process.is_running():
                    try:
                        process.terminate()
                        logger.debug(f"Sent SIGTERM to process {process_id}")
                    except psutil.NoSuchProcess:
                        graceful_stopped = True
                    except Exception as e:
                        logger.warning(f"Failed to terminate process {process_id}: {e}")
                    
                    # Wait up to 5 more seconds for termination
                    if not graceful_stopped:
                        gone, alive = psutil.wait_procs([process], timeout=5)
                        if process in gone:
                            graceful_stopped = True
                            logger.info(f"Process {process_id} terminated after SIGTERM")
                
                # STEP 3: If still running, force kill
                if not graceful_stopped and process.is_running():
                    logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
                    
                    # On Windows, use taskkill as backup for stubborn processes
                    if sys.platform == 'win32':
                        try:
                            subprocess.call(['taskkill', '/F', '/T', '/PID', str(process_id)],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                        except Exception:
                            pass
                
                # STEP 4: Terminate any remaining child processes (only those from this server's tree)
                if children:
                    logger.debug(f"Cleaning up {len(children)} child processes for server '{server_name}'")
                    for child in children:
                        try:
                            if child.is_running():
                                # First try graceful termination
                                try:
                                    child.terminate()
                                except:
                                    pass
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    
                    # Wait briefly for children to terminate gracefully
                    time.sleep(1)
                    
                    # Force kill any remaining children
                    for child in children:
                        try:
                            if child.is_running():
                                child.kill()
                                # Backup with taskkill on Windows
                                if sys.platform == 'win32':
                                    try:
                                        subprocess.call(['taskkill', '/F', '/PID', str(child.pid)],
                                                       stdout=subprocess.DEVNULL,
                                                       stderr=subprocess.DEVNULL)
                                    except Exception:
                                        pass
                                logger.debug(f"Force killed child process with PID {child.pid}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                
                # Verify all processes are dead
                time.sleep(0.5)
                if self.is_process_running(process_id):
                    logger.warning(f"Process {process_id} still running after kill, forcing with taskkill")
                    if sys.platform == 'win32':
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(process_id)],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                    time.sleep(0.5)
                    if self.is_process_running(process_id):
                        logger.error(f"Failed to kill process {process_id}")
                        return False, f"Failed to stop server process {process_id}"
                
                logger.debug(f"Terminated process PID {process_id}")
                
                # Update server configuration - clear all process-related fields
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
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
        # Restart the selected game server - Advanced version with proper process management
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
            process_id = server_config.get('ProcessId')
            if process_id:
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
                            
                            logger.debug(f"Executing custom stop command for restart: {stop_cmd}")
                            
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
                            logger.debug(f"Sent termination signal to process {process_id} for restart")
                        except:
                            logger.warning(f"Failed to terminate process {process_id}")
                        
                        # Wait up to 5 seconds for the process to terminate
                        gone, alive = psutil.wait_procs([process], timeout=5)
                        
                        if process in alive:
                            # If it doesn't terminate, kill it forcefully
                            logger.warning(f"Process {process_id} did not terminate gracefully, using force kill")
                            process.kill()
                            
                            # On Windows, use taskkill as backup for stubborn processes
                            if sys.platform == 'win32':
                                try:
                                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(process_id)],
                                                   stdout=subprocess.DEVNULL,
                                                   stderr=subprocess.DEVNULL)
                                except Exception:
                                    pass
                        
                        # Terminate any remaining child processes
                        if children:
                            for child in children:
                                try:
                                    if child.is_running():
                                        child.kill()
                                        # Backup with taskkill on Windows
                                        if sys.platform == 'win32':
                                            try:
                                                subprocess.call(['taskkill', '/F', '/PID', str(child.pid)],
                                                               stdout=subprocess.DEVNULL,
                                                               stderr=subprocess.DEVNULL)
                                            except Exception:
                                                pass
                                        logger.debug(f"Killed child process with PID {child.pid}")
                                except:
                                    pass
                        
                        # Verify process is dead before restarting
                        time.sleep(0.5)
                        if self.is_process_running(process_id):
                            logger.warning(f"Process {process_id} still running, forcing with taskkill")
                            if sys.platform == 'win32':
                                subprocess.call(['taskkill', '/F', '/T', '/PID', str(process_id)],
                                               stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
                
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
        # Remove a server configuration
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
        # Update server configuration with new settings
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

    def import_server_config(self, server_name, server_type, install_dir, executable_path, startup_args="", app_id=""):
        # Import an existing server from a directory
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
                        logger.debug(f"Auto-detected Minecraft executable: {executable_path}")
                except ImportError:
                    logger.warning("Minecraft module not available for auto-detection")
            
            # If still no executable, try auto-detect with general method
            if not executable_path:
                detected_files = self.auto_detect_server_executable(install_dir)
                if detected_files:
                    executable_path = detected_files[0]
                    logger.debug(f"Auto-detected executable: {executable_path}")
            
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
                "AppID": app_id,
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
        # Auto-detect server executable in a directory
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
        # Get the current status of a server
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
        # Get list of currently running servers
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
        # Validate a server configuration
        errors = []
        warnings = []
        
        try:
            # Check executable path - REMOVED: Executable path is no longer required during initial setup
            # executable_path = server_config.get('ExecutablePath', '')
            # if not executable_path:
            #     errors.append("Executable path is required")
            # else:
            #     exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
            #     if not os.path.exists(exe_full):
            #         warnings.append(f"Executable not found: {exe_full}")
            
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

    def get_steamcmd_error_description(self, exit_code):
        # Get human-readable description for SteamCMD exit codes
        error_codes = {
            0: "Success - No error occurred",
            1: "Unknown error - General failure",
            2: "Invalid arguments - Command line arguments were invalid",
            3: "Network error - Connection or download failed",
            4: "Disk space error - Not enough disk space for installation",
            5: "Authentication failed - Login credentials are incorrect",
            6: "License error - Steam license validation failed",
            7: "No subscription - App is not owned or subscription expired",
            8: "Password required - Password authentication is required but not provided",
            9: "Two-factor authentication required - Steam Guard code needed",
            10: "Access denied - Insufficient permissions",
            11: "Service unavailable - Steam service is temporarily unavailable",
            12: "Connection timeout - Network connection timed out",
            13: "Disk write error - Unable to write to disk",
            14: "Steam client not found - SteamCMD executable not found or corrupted",
            15: "App not found - The specified App ID does not exist",
            16: "App not available - App is not available for download",
            17: "Corrupted download - Downloaded files are corrupted",
            18: "App already installed - App is already up to date",
            19: "SteamCMD busy - Another SteamCMD process is running",
            20: "Rate limited - Too many requests, rate limit exceeded",
            21: "Region restricted - App not available in your region",
            22: "Parental controls - Parental controls blocking download",
            23: "Purchase required - App requires purchase",
            24: "Beta access required - Beta branch access required",
            25: "Invalid platform - App not available for this platform",
            26: "Depot not found - Required depot not found",
            27: "Missing executable - Required executable not found",
            28: "SteamCMD version too old - SteamCMD needs to be updated",
            29: "Content servers busy - All content servers are busy",
            30: "Disk read error - Unable to read from disk",
            31: "App manifest error - App manifest is corrupted or invalid",
            32: "App not compatible - App not compatible with this version of SteamCMD",
            33: "Workshop item not found - Workshop item does not exist",
            34: "Workshop quota exceeded - Workshop upload/download quota exceeded",
            35: "Workshop access denied - No permission to access workshop item",
            36: "Workshop file corrupted - Workshop file is corrupted",
            37: "Workshop dependency missing - Required workshop dependency not found",
            38: "Workshop item private - Workshop item is private",
            39: "Workshop item removed - Workshop item has been removed",
            40: "Workshop service unavailable - Workshop service is down"
        }
        
        return error_codes.get(exit_code, f"Unknown error code {exit_code} - Check SteamCMD documentation for details")

    def install_steam_server(self, server_name, app_id, install_dir, steam_cmd_path, credentials, progress_callback=None, cancel_flag=None):
        # Install a Steam server using SteamCMD
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
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
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
                error_description = self.get_steamcmd_error_description(exit_code)
                
                # Log detailed error information
                logger.error(f"SteamCMD installation failed with exit code {exit_code}: {error_description}")
                
                raise Exception(f"SteamCMD failed with exit code {exit_code}: {error_description}")
            
            return True, "Steam server installed successfully"
            
        except Exception as e:
            logger.error(f"Steam server installation failed: {str(e)}")
            return False, f"Installation failed: {str(e)}"

    def install_minecraft_server(self, server_name, install_dir, version, modloader="Vanilla", progress_callback=None, cancel_flag=None):
        # Install a Minecraft server
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
            
            if modloader.lower() == "vanilla":
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
                
            elif modloader.lower() == "fabric":
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
                
            elif modloader.lower() == "forge":
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
                
            elif modloader.lower() == "neoforge":
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
        # Create and save a server configuration
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
            
            # Add to in-memory server list immediately
            self.servers[server_name] = server_config
            
            logger.info(f"Server configuration saved: {server_name}")
            return True, "Server configuration created successfully"
            
        except Exception as e:
            logger.error(f"Error creating server config: {str(e)}")
            return False, f"Failed to create server configuration: {str(e)}"

    def install_server_complete(self, server_name, server_type, install_dir, executable_path="", 
                               startup_args="", app_id="", version="", modloader="", steam_cmd_path="", 
                               credentials=None, progress_callback=None, cancel_flag=None):
        # Complete server installation process
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
                
                # If install_dir was empty (using SteamCMD default), determine the actual installation path
                if not install_dir:
                    # SteamCMD default installation path is <steamcmd_path>/steamapps/common/<app_name>
                    steamapps_common = os.path.join(steam_cmd_path, "steamapps", "common")
                    if os.path.exists(steamapps_common):
                        # Look for the most recently modified directory (likely our installation)
                        try:
                            directories = []
                            for d in os.listdir(steamapps_common):
                                dir_path = os.path.join(steamapps_common, d)
                                if os.path.isdir(dir_path):
                                    directories.append((d, os.path.getmtime(dir_path)))
                            
                            if directories:
                                # Sort by modification time (most recent first)
                                directories.sort(key=lambda x: x[1], reverse=True)
                                most_recent_dir = directories[0][0]
                                install_dir = os.path.join(steamapps_common, most_recent_dir)
                                
                                if progress_callback:
                                    progress_callback(f"[INFO] Auto-detected installation directory: {install_dir}")
                                logger.debug(f"Auto-detected Steam server installation directory: {install_dir}")
                            else:
                                # No directories found, use steamapps/common as fallback
                                install_dir = steamapps_common
                                if progress_callback:
                                    progress_callback(f"[WARN] No game directories found, using steamapps/common: {install_dir}")
                                logger.warning(f"No directories in steamapps/common, using: {install_dir}")
                        except Exception as e:
                            # Error accessing directories, use steamapps as fallback
                            install_dir = os.path.join(steam_cmd_path, "steamapps")
                            if progress_callback:
                                progress_callback(f"[WARN] Error detecting installation directory ({str(e)}), using: {install_dir}")
                            logger.warning(f"Error detecting installation directory: {str(e)}, using fallback: {install_dir}")
                    else:
                        # steamapps/common doesn't exist, create it and use as install_dir
                        try:
                            os.makedirs(steamapps_common, exist_ok=True)
                            install_dir = steamapps_common
                            if progress_callback:
                                progress_callback(f"[INFO] Created steamapps/common directory: {install_dir}")
                            logger.debug(f"Created steamapps/common directory: {install_dir}")
                        except Exception as e:
                            # Final fallback: use steamcmd root
                            install_dir = steam_cmd_path
                            if progress_callback:
                                progress_callback(f"[WARN] Could not create steamapps directories, using SteamCMD root: {install_dir}")
                            logger.warning(f"Could not create steamapps directories: {str(e)}, using SteamCMD root: {install_dir}")
                
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
        # Get available Minecraft versions from database (NO FALLBACKS)
        try:
            from Modules.Database.MinecraftIDScanner import MinecraftIDScanner
            scanner = MinecraftIDScanner(use_database=True, debug_mode=False)
            servers = scanner.get_servers_from_database(modloader=None, dedicated_only=True)
            scanner.close()

            if not servers:
                servers = []

            # Convert to expected format
            versions = []
            for server in servers:
                versions.append({
                    "id": server["version_id"],
                    "type": server["version_type"],
                    "modloader": server["modloader"],
                    "modloader_version": server["modloader_version"],
                    "java_requirement": server["java_requirement"]
                })

            # Sort by version (newest first)
            versions.sort(key=lambda x: x["id"], reverse=True)
            return versions

        except ImportError as e:
            error_msg = f"Minecraft database modules not available: {e}"
            logger.error(error_msg)
            raise Exception(f"Minecraft database unavailable: {error_msg}")

        except Exception as e:
            error_msg = f"Failed to retrieve Minecraft versions from database: {e}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_supported_server_types(self):
        # Get list of supported server types
        return ["Steam", "Minecraft", "Other"]

    def uninstall_server(self, server_name, remove_files=False, progress_callback=None):
        # Uninstall a server (remove config and optionally files)
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
            
            # Remove from in-memory cache
            if server_name in self.servers:
                del self.servers[server_name]
            
            logger.info(f"Server uninstalled: {server_name} (files removed: {remove_files})")
            return True, f"Server '{server_name}' uninstalled successfully"
            
        except Exception as e:
            logger.error(f"Error uninstalling server: {str(e)}")
            return False, f"Failed to uninstall server: {str(e)}"

# Create singleton instance
server_manager = ServerManager()
