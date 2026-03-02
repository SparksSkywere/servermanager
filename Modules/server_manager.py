# Server management core
import os
import sys
import logging
import subprocess
import time
import psutil
import urllib.request
from datetime import datetime

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import (
    setup_module_path, get_subprocess_creation_flags, should_hide_server_consoles, 
    setup_module_logging
)
setup_module_path()

# Import stdin relay for persistent command input
try:
    from services.stdin_relay import send_command_via_relay
    _STDIN_RELAY_AVAILABLE = True
except ImportError:
    _STDIN_RELAY_AVAILABLE = False

# Import persistent stdin pipe (allows commands after dashboard restart)
try:
    from services.persistent_stdin import (
        send_command_to_stdin_pipe, 
        is_stdin_pipe_available
    )
    _PERSISTENT_STDIN_AVAILABLE = True
except ImportError:
    _PERSISTENT_STDIN_AVAILABLE = False

# Import command queue relay (file-based command queuing)
try:
    from services.command_queue import (
        queue_command,
        is_relay_active
    )
    _COMMAND_QUEUE_AVAILABLE = True
except ImportError:
    _COMMAND_QUEUE_AVAILABLE = False

logger: logging.Logger = setup_module_logging("ServerManager")

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
    def __init__(self):
        super().__init__("ServerManager")
        self.servers = {}
        
        self.load_config()
        self.load_servers()
        
    def get_servers(self):
        return self.servers
        
    def load_config(self):
        # Pull config from database
        try:
            from Modules.Database.cluster_database import ClusterDatabase
            db = ClusterDatabase()
            
            config_data = db.get_main_config()
            
            # Migrate from JSON if database is empty
            if not config_data and self.server_manager_dir:
                config_file = os.path.join(self.server_manager_dir, "config", "config.json")
                if os.path.exists(config_file):
                    logger.debug("Migrating main config from JSON to database")
                    db.migrate_main_config_from_json(config_file)
                    config_data = db.get_main_config()
            
            self._config_manager.config.update(config_data)
            logger.debug("Configuration loaded from database")
            
        except Exception as e:
            logger.error(f"Error loading configuration from database: {str(e)}")
            self.create_default_config()
            
    def create_default_config(self):
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
            
            for key, value in default_config.items():
                config_type = 'integer' if isinstance(value, int) else 'string'
                db.set_main_config(key, value, config_type)
            self._config_manager.config.update(default_config)
            logger.debug("Default configuration created in database")
            
        except Exception as e:
            logger.error(f"Error creating default configuration: {str(e)}")
            
    def load_servers(self):
        try:
            from Modules.Database.server_configs_database import get_server_config_manager
            manager = get_server_config_manager()
            servers = manager.get_all_servers()
            
            # Convert to dict keyed by name
            self.servers = {server['Name']: server for server in servers}
                        
            logger.debug(f"Loaded {len(self.servers)} server configurations from database")
        except Exception as e:
            logger.error(f"Error loading servers from database: {str(e)}")
            self.servers = {}
    

            
    def get_server_config(self, server_name):
        if server_name in self.servers:
            return self.servers[server_name]
            
        # Try to load from database if not in memory
        try:
            from Modules.Database.server_configs_database import get_server_config_manager
            manager = get_server_config_manager()
            server_config = manager.get_server(server_name)
            
            if server_config:
                self.servers[server_name] = server_config
                return server_config
                
        except Exception as e:
            logger.error(f"Error loading server config {server_name} from database: {e}")
                
        return None
        
    def update_server(self, server_name, config):
        try:
            from Modules.Database.server_configs_database import get_server_config_manager
            manager = get_server_config_manager()
            
            # Update existing server or create new one
            if manager.get_server(server_name):
                success = manager.update_server(server_name, config)
            else:
                success = manager.create_server(config)
            
            if success:
                self.servers[server_name] = config
                logger.debug(f"Server configuration saved for {server_name}")
                return True
            else:
                logger.error(f"Failed to save server config {server_name} to database")
                return False
                
        except Exception as e:
            logger.error(f"Error saving server config {server_name}: {str(e)}")
            return False
            
    def get_server_list(self):
        return list(self.servers.values())
    
    def get_all_servers(self):
        return self.servers.copy()
    
    def reload_server(self, server_name):
        try:
            from Modules.Database.server_configs_database import get_server_config_manager
            manager = get_server_config_manager()
            server_config = manager.get_server(server_name)
            
            if server_config:
                self.servers[server_name] = server_config
                return True
            else:
                logger.warning(f"Server {server_name} not found in database")
                return False
                
        except Exception as e:
            logger.error(f"Error reloading server config for {server_name}: {e}")
            return False
            
    def is_process_running(self, pid):
        try:
            if pid is None:
                return False
            return psutil.pid_exists(pid)
        except Exception:
            return False
    
    def is_server_process_valid(self, server_name, process_id, server_config=None):
        # Validate that a PID belongs to the expected server process
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

            if server_config is None:
                server_config = self.get_server_config(server_name)

            if not server_config:
                # No config to validate against, just check if process exists
                return True, process

            # PRIMARY CHECK: Stored process creation time (most secure validation)
            # Definitive way to verify PID ownership since creation time
            # is unique and won't match if Windows reuses the PID for another process
            stored_create_time = server_config.get('ProcessCreateTime')
            if stored_create_time:
                try:
                    actual_create_time = process.create_time()
                    # Allow 2 second tolerance for timing differences
                    if abs(actual_create_time - stored_create_time) < 2:
                        logger.debug(f"PID {process_id} validated: create time matches (secure)")
                        return True, process
                    else:
                        # Creation time doesn't match - this is definitely a different process
                        logger.debug(f"PID {process_id} rejected: create time mismatch (stored: {stored_create_time}, actual: {actual_create_time})")
                        return False, None
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            # FALLBACK: If no ProcessCreateTime stored, use heuristic checks
            install_dir = server_config.get('InstallDir', '')
            executable_path = server_config.get('ExecutablePath', '')
            server_type = server_config.get('Type', '').lower()

            try:
                proc_exe = process.exe().lower() if process.exe() else ''
                proc_cwd = process.cwd().lower() if process.cwd() else ''
                proc_name = process.name().lower() if process.name() else ''

                try:
                    cmdline = process.cmdline()
                    cmdline_str = ' '.join(cmdline).lower() if cmdline else ''
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    cmdline_str = ''

            except (psutil.AccessDenied, psutil.NoSuchProcess):
                # Can't access process info, assume invalid without create time
                logger.debug(f"Cannot access process {process_id} info for validation")
                return False, None

            install_dir_lower = install_dir.lower() if install_dir else ''
            executable_lower = executable_path.lower() if executable_path else ''
            
            # Resolve relative executable path
            if executable_lower and install_dir_lower and not os.path.isabs(executable_path):
                full_exe_path = os.path.join(install_dir_lower, executable_lower)
            else:
                full_exe_path = executable_lower

            # Check 1: Working directory matches install directory
            if install_dir_lower and proc_cwd:
                if os.path.normpath(proc_cwd) == os.path.normpath(install_dir_lower):
                    logger.debug(f"PID {process_id} validated: CWD matches install dir")
                    return True, process

            # Check 2: Executable path matches (handle relative paths)
            if executable_lower and proc_exe:
                exe_basename = os.path.basename(executable_lower)
                proc_exe_basename = os.path.basename(proc_exe)
                # For batch files, java may be running instead
                if exe_basename == proc_exe_basename:
                    logger.debug(f"PID {process_id} validated: executable name matches")
                    return True, process
                if install_dir_lower and proc_exe.startswith(os.path.normpath(install_dir_lower)):
                    logger.debug(f"PID {process_id} validated: process exe in install dir")
                    return True, process

            # Check 3: Install directory in executable path or command line
            if install_dir_lower:
                if proc_exe and install_dir_lower in proc_exe:
                    logger.debug(f"PID {process_id} validated: install dir in exe path")
                    return True, process
                if cmdline_str and install_dir_lower in cmdline_str:
                    logger.debug(f"PID {process_id} validated: install dir in cmdline")
                    return True, process

            # Check 4: Type-specific validation
            if server_type == 'minecraft' or server_type == 'other':
                # For Minecraft/modded servers, java process with install dir in cmdline
                if 'java' in proc_name or 'javaw' in proc_name:
                    if cmdline_str and install_dir_lower and install_dir_lower in cmdline_str:
                        logger.debug(f"PID {process_id} validated: Java process with install dir")
                        return True, process

            # If we get here without ProcessCreateTime, we can't reliably validate
            # Log at debug level to avoid spam
            logger.debug(f"PID {process_id} could not be validated for '{server_name}' (no ProcessCreateTime, heuristics failed)")
            return False, None

        except Exception as e:
            logger.error(f"Error validating server process for {server_name}: {e}")
            return False, None
    
    def clear_stale_pid(self, server_name, server_config=None):
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
                logger.debug(f"Clearing stale PID {pid} for server '{server_name}'")
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                self.update_server(server_name, server_config)
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error clearing stale PID for {server_name}: {e}")
            return False

    def detect_and_recover_system_corruption(self, server_name, server_config=None, callback=None):
        # Detect and recover from system corruption after BSODs, power failures, or bad starts
        # Performs system state validation and automatic recovery
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

            logger.debug(f"Running corruption detection for {server_name}")

            # 1. Check for config data corruption in database
            config_data = self.servers.get(server_name)
            if config_data:
                required_fields = ['InstallDir', 'ExecutablePath', 'Type']
                missing_fields = [field for field in required_fields if field not in config_data]
                if missing_fields:
                    errors.append(f"Config missing required fields: {missing_fields}")
                    recovery_needed = True
                    recovery_actions.append("Config validation failed")
            else:
                errors.append("Server configuration not found in database")
                recovery_needed = True
                recovery_actions.append("Server config missing from database")

            # 2. Check install directory integrity
            install_dir = server_config.get('InstallDir', '')
            if install_dir:
                if not os.path.exists(install_dir):
                    errors.append(f"Install directory missing: {install_dir}")
                    recovery_needed = True
                    recovery_actions.append("Install directory missing")
                else:
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
                    logger.debug(f"Stale PID {pid} detected for {server_name} during corruption check")
                    recovery_needed = True
                    recovery_actions.append(f"Cleaned up stale PID {pid}")

                    server_config.pop('ProcessId', None)
                    server_config.pop('PID', None)
                    server_config.pop('StartTime', None)
                    server_config.pop('ProcessCreateTime', None)
                    server_config['LastUpdate'] = datetime.now().isoformat()
                    self.update_server(server_name, server_config)

            # 5. Check log file integrity - batch file operations for efficiency
            try:
                logs_dir = os.path.join(self.paths.get("logs", "logs"))
                if os.path.exists(logs_dir):
                    corrupted_files = []
                    for root, dirs, files in os.walk(logs_dir):
                        for file in files:
                            if file.endswith('.log'):
                                log_path = os.path.join(root, file)
                                try:
                                    # Quick corruption check - try to read last few lines
                                    file_size = os.path.getsize(log_path)
                                    if file_size > 1000:  # If file is large, check last 1000 bytes
                                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                            f.seek(max(0, file_size - 1000), 0)
                                            content = f.read()
                                            if '\x00' in content:  # Null bytes indicate corruption
                                                corrupted_files.append(log_path)
                                except Exception as e:
                                    errors.append(f"Error checking log file {log_path}: {e}")

                    for corrupted_file in corrupted_files:
                        errors.append(f"Log file corrupted: {corrupted_file}")
                        recovery_needed = True
                        recovery_actions.append(f"Corrupted log file detected: {os.path.basename(corrupted_file)}")
            except Exception as e:
                logger.debug(f"Error during log integrity check: {e}")

            # 6. Check for system crash indicators (Windows event logs, etc.)
            # Should check for actual crash events, not just registry key existence
            # The CrashControl key always exists on Windows, so we need to check for actual crash dumps
            try:
                if sys.platform == 'win32':
                    pass
                    # Check for recent crash dumps instead of just key existence
                    crash_dump_folder = os.path.join(os.environ.get('SystemRoot', 'C:\\Windows'), 'Minidump')
                    if os.path.exists(crash_dump_folder):
                        # Check for crash dumps created within the last 24 hours
                        import glob
                        crash_files = glob.glob(os.path.join(crash_dump_folder, '*.dmp'))
                        recent_crashes = []
                        for crash_file in crash_files:
                            try:
                                file_mtime = os.path.getmtime(crash_file)
                                if time.time() - file_mtime < 86400:  # 24 hours
                                    recent_crashes.append(crash_file)
                            except OSError:
                                pass
                        if recent_crashes:
                            recovery_needed = True
                            recovery_actions.append(f"Recent system crash detected ({len(recent_crashes)} dump files)")
            except Exception as e:
                logger.debug(f"Error checking for system crash indicators: {e}")

            # 7. Attempt automatic recovery if issues found
            if recovery_needed:
                logger.debug(f"Recovery needed for {server_name}. Actions: {recovery_actions}")

                server_config['LastCorruptionCheck'] = datetime.now().isoformat()
                server_config['CorruptionRecoveryActions'] = recovery_actions
                self.update_server(server_name, server_config)

                if callback:
                    callback(f"Corruption recovery completed for {server_name}")

            return recovery_needed, recovery_actions, errors

        except Exception as e:
            error_msg = f"Error during corruption detection for {server_name}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
            return True, recovery_actions, errors

    def start_server(self, server_name):
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
        # Start the selected game server (Steam/Minecraft/Other) with proper process management
        # Includes corruption detection and automatic recovery
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                logger.error(f"Server configuration not found in database: {server_name}")
                return False, f"Server configuration not found in database: {server_name}"

            # Perform corruption detection and recovery before starting
            logger.debug(f"Performing pre-startup corruption check for {server_name}")
            recovery_needed, recovery_actions, recovery_errors = self.detect_and_recover_system_corruption(
                server_name, server_config, callback
            )

            if recovery_errors:
                logger.debug(f"Corruption recovery errors for {server_name}: {recovery_errors}")
                # Don't fail startup for recovery errors, but log them

            if recovery_needed:
                logger.debug(f"System corruption detected and recovered for {server_name}: {recovery_actions}")
                # Reload config after recovery from database
                try:
                    server_config = self.get_server_config(server_name)
                    if not server_config:
                        logger.error(f"Failed to reload config after recovery: config not found in database")
                        return False, f"Failed to reload server configuration after recovery"
                except Exception as reload_error:
                    logger.error(f"Failed to reload config after recovery: {reload_error}")
                    return False, f"Failed to reload server configuration after recovery: {reload_error}"

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
                    self.update_server(server_name, server_config)
                
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
                
            exe_full = executable_path if os.path.isabs(executable_path) else os.path.join(install_dir, executable_path)
            exe_full = os.path.normpath(exe_full)
            if not os.path.exists(exe_full):
                logger.error(f"Executable not found: {exe_full}")
                return False, f"Executable not found: {exe_full}"
            
            # Resolve config file path
            config_full = None
            if use_config_file and config_file_path:
                config_full = config_file_path if os.path.isabs(config_file_path) else os.path.join(install_dir, config_file_path)
                config_full = os.path.normpath(config_full)
            
            def _build_extra_args(additional_args, startup_args, use_config_file, config_file_path, config_argument, config_full):
                # Build extra arguments list for subprocess (shell=False safe)
                args = []
                if use_config_file:
                    if additional_args:
                        args.extend(arg.strip('"\'' ) for arg in additional_args.split())
                    if config_file_path and config_argument and config_full and os.path.exists(config_full):
                        args.extend([config_argument, config_full])
                        logger.debug(f"Using config file: {config_full}")
                elif startup_args:
                    args.extend(arg.strip('"\'' ) for arg in startup_args.split())
                return args
            
            extra_args = _build_extra_args(additional_args, startup_args, use_config_file, config_file_path, config_argument, config_full)
            
            # Build command as list (shell=False) to prevent shell injection
            if exe_full.lower().endswith(('.bat', '.cmd')):
                # Batch files need cmd.exe to interpret them
                cmd = ['cmd.exe', '/c', exe_full] + extra_args
            elif exe_full.lower().endswith('.ps1'):
                cmd = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', exe_full] + extra_args
            elif exe_full.lower().endswith('.sh'):
                if sys.platform == 'win32':
                    cmd = ['bash', exe_full] + extra_args
                else:
                    cmd = ['/bin/sh', exe_full] + extra_args
            elif exe_full.lower().endswith('.jar'):
                # JAR files via Java (Minecraft gets default JVM args)
                if server_type == "Minecraft":
                    cmd = ['java', '-Xmx1024M', '-Xms1024M', '-jar', exe_full, 'nogui'] + extra_args
                else:
                    cmd = ['java', '-jar', exe_full] + extra_args
            else:
                # Regular executables (.exe, etc.)
                cmd = [exe_full] + extra_args
            
            server_logs_dir = os.path.join(install_dir, "logs")
            os.makedirs(server_logs_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stdout_log = os.path.join(server_logs_dir, f"server_stdout_{timestamp}.log")
            stderr_log = os.path.join(server_logs_dir, f"server_stderr_{timestamp}.log")
            
            logger.debug(f"Starting server '{server_name}' with command: {cmd}")
            
            if callback:
                callback(f"Starting server '{server_name}'...")
            
            # Initialise log files
            with open(stdout_log, 'w') as stdout_file, open(stderr_log, 'w') as stderr_file:
                start_time = datetime.now()
                time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
                cmd_str = ' '.join(f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd)
                stdout_file.write(f"--- Server started at {time_str} ---\n")
                stdout_file.write(f"Command: {cmd_str}\n\n")
                stderr_file.write(f"--- Server started at {time_str} ---\n")
                stderr_file.write(f"Command: {cmd_str}\n\n")
                
            hide_consoles = should_hide_server_consoles(self.config)

            # Add console output flags for Steam/Source servers
            cmd_str_check = ' '.join(cmd)
            if "srcds" in cmd_str_check.lower() or "steamcmd" in cmd_str_check.lower():
                if "-console" not in cmd:
                    cmd.append("-console")
                if "-condebug" not in cmd:
                    cmd.append("-condebug")

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

            # Automatic retry logic for failed startups
            max_retries = 3
            retry_delay = 2  # seconds
            startup_success = False

            for attempt in range(max_retries):
                if psutil.pid_exists(process.pid):
                    # Check if process is running and not stuck
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
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            process.kill()
                        except OSError:
                            pass

                    time.sleep(retry_delay)

                    try:
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
            
            server_config['ProcessId'] = process.pid
            server_config['PID'] = process.pid  # For console manager
            server_config['StartTime'] = start_time.isoformat()
            server_config['LastUpdate'] = datetime.now().isoformat()
            server_config['LogStdout'] = stdout_log
            server_config['LogStderr'] = stderr_log
            
            # Store process creation time for PID validation on reattachment
            if process_create_time:
                server_config['ProcessCreateTime'] = process_create_time
            
            self.update_server(server_name, server_config)
            
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
            # Temporarily disabled due to pipe busy errors causing dashboard instability
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
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                logger.error(f"Server configuration not found in database: {server_name}")
                return False, f"Server configuration not found in database: {server_name}"
                
            if 'ProcessId' not in server_config:
                logger.info(f"Server '{server_name}' is not running.")
                if callback:
                    callback(f"Server '{server_name}' is not running")
                return False, f"Server '{server_name}' is not running."
                
            process_id = server_config['ProcessId']
            
            # Validate that the PID actually belongs to this server
            # Prevents stopping the wrong process if Windows reused the PID
            is_valid, validated_process = self.is_server_process_valid(server_name, process_id, server_config)
            
            if not is_valid:
                logger.warning(f"PID {process_id} is no longer valid for server '{server_name}' (stale or reused PID)")
                
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                
                self.update_server(server_name, server_config)
                
                if callback:
                    callback(f"Server '{server_name}' was not running (stale PID cleared)")
                return False, f"Server '{server_name}' was not running (stale PID {process_id} cleared)."
                
            if callback:
                callback(f"Stopping server '{server_name}'...")
                
            stop_command_used = False
            if 'StopCommand' in server_config and server_config['StopCommand']:
                try:
                    stop_cmd = server_config['StopCommand']
                    
                    logger.debug(f"Sending custom stop command to server: {stop_cmd}")
                    command_sent = False
                    
                    # Try multiple methods to ensure the stop command is delivered
                    # Method 1: Try persistent stdin pipe first (most reliable if available)
                    if _PERSISTENT_STDIN_AVAILABLE and not command_sent:
                        try:
                            if is_stdin_pipe_available(server_name):  # type: ignore
                                success, message = send_command_to_stdin_pipe(server_name, stop_cmd)  # type: ignore
                                if success:
                                    logger.info(f"Stop command sent via persistent stdin pipe: {stop_cmd}")
                                    command_sent = True
                        except Exception as e:
                            logger.debug(f"Persistent stdin pipe failed: {e}")
                    
                    # Method 2: Try command queue relay (file-based)
                    if _COMMAND_QUEUE_AVAILABLE and not command_sent:
                        try:
                            if is_relay_active(server_name):  # type: ignore
                                success, message = queue_command(server_name, stop_cmd)  # type: ignore
                                if success:
                                    logger.info(f"Stop command queued successfully: {stop_cmd}")
                                    command_sent = True
                                else:
                                    logger.debug(f"Failed to queue stop command: {message}")
                        except Exception as e:
                            logger.debug(f"Command queue failed: {e}")
                    
                    # Method 3: Try stdin relay (named pipe)
                    if _STDIN_RELAY_AVAILABLE and not command_sent:
                        try:
                            success, message = send_command_via_relay(server_name, stop_cmd)  # type: ignore
                            if success:
                                logger.info(f"Stop command sent via stdin relay: {stop_cmd}")
                                command_sent = True
                        except Exception as e:
                            logger.debug(f"Stdin relay failed: {e}")
                    
                    # Method 4: Try direct stdin write if we have the process
                    if not command_sent:
                        if hasattr(self, 'active_processes') and server_name in self.active_processes:
                            proc = self.active_processes[server_name]
                            if proc and hasattr(proc, 'stdin') and proc.stdin and not proc.stdin.closed:
                                try:
                                    proc.stdin.write(stop_cmd + '\n')
                                    proc.stdin.flush()
                                    logger.info(f"Stop command sent via direct stdin: {stop_cmd}")
                                    command_sent = True
                                except Exception as e:
                                    logger.debug(f"Direct stdin write failed: {e}")
                    
                    if command_sent:
                        stop_command_used = True
                        # Wait longer for graceful shutdown with save - game servers may need time to save
                        if callback:
                            callback(f"Waiting for '{server_name}' to save and shutdown gracefully...")
                        
                        for i in range(15):  # Try for 15 seconds (increased from 10)
                            if not self.is_process_running(process_id):
                                server_config.pop('ProcessId', None)
                                server_config.pop('PID', None)
                                server_config.pop('StartTime', None)
                                server_config.pop('ProcessCreateTime', None)
                                server_config['LastUpdate'] = datetime.now().isoformat()
                                
                                self.update_server(server_name, server_config)
                                
                                logger.info(f"Server '{server_name}' stopped successfully via stop command after {i+1} seconds.")
                                if callback:
                                    callback(f"Server '{server_name}' stopped successfully.")
                                return True, f"Server '{server_name}' stopped successfully."
                            time.sleep(1)
                            
                        logger.warning(f"Custom stop command did not stop the server within 15 seconds")
                    else:
                        logger.warning(f"Could not send stop command to {server_name} via any method")
                        
                except Exception as e:
                    logger.error(f"Error sending custom stop command: {str(e)}")
            
            # If no custom stop command was available or it failed, send CTRL+C and wait up to 5 minutes
            if not stop_command_used:
                logger.info(f"No custom stop command available for '{server_name}', sending CTRL+C and waiting up to 5 minutes")
                if callback:
                    callback(f"Sending CTRL+C to '{server_name}' and waiting up to 5 minutes for graceful shutdown...")
                
                try:
                    # Send CTRL+C event to the process
                    if sys.platform == 'win32':
                        import signal
                        os.kill(process_id, signal.CTRL_C_EVENT)
                        logger.debug(f"Sent CTRL_C_EVENT to process {process_id}")
                    
                    # Wait up to 5 minutes (300 seconds) for graceful shutdown
                    for i in range(300):  # 300 seconds = 5 minutes
                        if not self.is_process_running(process_id):
                            server_config.pop('ProcessId', None)
                            server_config.pop('PID', None)
                            server_config.pop('StartTime', None)
                            server_config.pop('ProcessCreateTime', None)
                            server_config['LastUpdate'] = datetime.now().isoformat()
                            
                            self.update_server(server_name, server_config)
                            
                            logger.info(f"Server '{server_name}' stopped successfully via CTRL+C after {i+1} seconds.")
                            if callback:
                                callback(f"Server '{server_name}' stopped successfully.")
                            return True, f"Server '{server_name}' stopped successfully."
                        
                        # Update progress every 30 seconds
                        if i > 0 and i % 30 == 0:
                            remaining_minutes = (300 - i) // 60
                            if callback:
                                callback(f"Still waiting for '{server_name}' to shutdown... ({remaining_minutes} minutes remaining)")
                        
                        time.sleep(1)
                        
                    logger.warning(f"Server did not stop after 5 minutes of waiting for CTRL+C")
                    
                except Exception as e:
                    logger.error(f"Error sending CTRL+C to process {process_id}: {str(e)}")
            
            logger.warning(f"Custom stop command and CTRL+C failed or timed out, using force termination")
            try:
                process = psutil.Process(process_id)
                
                # Store the process creation time to verify children belong to this server's process tree
                try:
                    server_process_create_time = process.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
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
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    
                    # Wait briefly for children to terminate gracefully
                    time.sleep(1)
                    
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
                
                server_config.pop('ProcessId', None)
                server_config.pop('PID', None)
                server_config.pop('StartTime', None)
                server_config.pop('ProcessCreateTime', None)
                server_config['LastUpdate'] = datetime.now().isoformat()
                
                self.update_server(server_name, server_config)
                
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
        try:
            server_config = self.servers.get(server_name)
            
            if not server_config:
                logger.error(f"Server configuration not found for: {server_name}")
                return False, f"Server configuration not found for: {server_name}"
            
            is_running = False
            process_id = server_config.get('ProcessId')
            if process_id:
                is_running = self.is_process_running(process_id)
            
            if callback:
                callback(f"Restarting server '{server_name}'...")
            
            if is_running:
                try:
                    if 'StopCommand' in server_config and server_config['StopCommand']:
                        try:
                            stop_cmd = server_config['StopCommand']
                            
                            logger.debug(f"Sending custom stop command for restart: {stop_cmd}")
                            
                            if _COMMAND_QUEUE_AVAILABLE:
                                from services.command_queue import queue_command as queue_cmd_func
                                success, message = queue_cmd_func(server_name, stop_cmd)
                                if not success:
                                    logger.warning(f"Failed to queue stop command: {message}")
                                else:
                                    logger.debug(f"Stop command queued successfully: {stop_cmd}")
                            else:
                                logger.warning("Command queue not available, cannot send stop command")
                        
                            for _ in range(10):  # Try for 10 seconds
                                if not self.is_process_running(process_id):
                                    break
                                time.sleep(1)
                            else:
                                logger.warning(f"Custom stop command did not stop the server within 10 seconds, using force termination")
                                raise Exception("Custom stop command failed")
                        
                        except Exception as e:
                            logger.error(f"Error sending custom stop command: {str(e)}")
                            # Fall through to force termination
                    
                    if self.is_process_running(process_id):
                        process = psutil.Process(process_id)
                        
                        children = []
                        try:
                            children = process.children(recursive=True)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            logger.warning(f"Could not get child processes for PID {process_id}")
                        
                        try:
                            process.terminate()
                            logger.debug(f"Sent termination signal to process {process_id} for restart")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            logger.warning(f"Failed to terminate process {process_id}")
                        
                        # Wait up to 5 seconds for the process to terminate
                        gone, alive = psutil.wait_procs([process], timeout=5)
                        
                        if process in alive:
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
                        
                        if children:
                            for child in children:
                                try:
                                    if child.is_running():
                                        child.kill()
                                        if sys.platform == 'win32':
                                            try:
                                                subprocess.call(['taskkill', '/F', '/PID', str(child.pid)],
                                                               stdout=subprocess.DEVNULL,
                                                               stderr=subprocess.DEVNULL)
                                            except Exception:
                                                pass
                                        logger.debug(f"Killed child process with PID {child.pid}")
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
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

    def update_server_config(self, server_name, executable_path, startup_args="", stop_command="", 
                           use_config_file=False, config_file_path="", config_argument="--config", 
                           additional_args=""):
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                logger.error(f"Server configuration not found in database: {server_name}")
                return False, f"Server configuration not found in database: {server_name}"
                
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
            
            self.update_server(server_name, server_config)
            
            logger.info(f"Updated configuration for server: {server_name}")
            return True, f"Configuration for '{server_name}' updated successfully."
            
        except Exception as e:
            logger.error(f"Error updating server configuration: {str(e)}")
            return False, f"Failed to update server configuration: {str(e)}"

    def import_server_config(self, server_name, server_type, install_dir, executable_path, startup_args="", app_id=""):
        # Import an existing server from a directory
        try:
            # Check if server name already exists in database
            if server_name in self.servers:
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
            
            self.update_server(server_name, server_config)
            
            logger.info(f"Imported server: {server_name} from {install_dir}")
            return True, f"Server '{server_name}' imported successfully!"
            
        except Exception as e:
            logger.error(f"Error importing server: {str(e)}")
            return False, f"Failed to import server: {str(e)}"

    def auto_detect_server_executable(self, install_dir):
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
        # Uses process validation to ensure PID belongs to correct server
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                return "Unknown", None
            
            if 'ProcessId' in server_config:
                pid = server_config['ProcessId']
                # Use process validation - not just pid_exists
                # Handles Windows PID reuse where old PID might be a different process
                is_valid, process = self.is_server_process_valid(server_name, pid, server_config)
                if is_valid and process:
                    return "Running", pid
                else:
                    # PID is stale or belongs to different process - clear it
                    if pid:
                        logger.debug(f"Clearing stale PID {pid} for {server_name} (process no longer valid)")
                        self.clear_stale_pid(server_name, server_config)
                    return "Stopped", None
            else:
                return "Stopped", None
                
        except Exception as e:
            logger.error(f"Error getting server status: {str(e)}")
            return "Error", None
            
    def get_running_servers(self):
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

    def is_server_running(self, server_name):
        try:
            status, pid = self.get_server_status(server_name)
            return status == "Running" and pid is not None
        except Exception as e:
            logger.error(f"Error checking if server {server_name} is running: {str(e)}")
            return False

    def get_steamcmd_error_description(self, exit_code):
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
        try:
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
            
            # Build SteamCMD command as list to avoid shell injection
            steam_cmd_args = [steam_cmd_exe]
            
            if credentials.get("anonymous", True):
                steam_cmd_args.extend(["+login", "anonymous"])
            else:
                steam_cmd_args.extend(["+login", credentials['username'], credentials['password']])
            
            if install_dir:
                steam_cmd_args.extend(["+force_install_dir", install_dir])
            
            steam_cmd_args.extend([
                "+app_update", str(app_id), "validate",
                "+quit"
            ])
            
            if progress_callback:
                # Log sanitised command (hide password)
                safe_args = [a if a != credentials.get('password', '') else '***' for a in steam_cmd_args]
                progress_callback(f"[INFO] Running SteamCMD: {' '.join(safe_args)}")
            
            # Execute SteamCMD with list args (shell=False for security)
            process = subprocess.Popen(
                steam_cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=get_subprocess_creation_flags(hide_window=True)
            )
            
            installation_success = False
            while True:
                if cancel_flag and cancel_flag.get():
                    if progress_callback:
                        progress_callback("[INFO] Installation cancelled by user, terminating SteamCMD...")
                    
                    try:
                        if progress_callback:
                            progress_callback("[INFO] Attempting to terminate SteamCMD gracefully...")
                        
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                            if progress_callback:
                                progress_callback("[INFO] SteamCMD terminated gracefully")
                        except subprocess.TimeoutExpired:
                            # If it doesn't terminate gracefully, force kill it
                            if progress_callback:
                                progress_callback("[WARN] SteamCMD did not terminate gracefully, killing forcefully...")
                            
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
                                except (OSError, subprocess.SubprocessError):
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
            
            if process.stderr is not None:
                error_output = process.stderr.read()
                if error_output and progress_callback:
                    progress_callback(f"[WARN] SteamCMD Errors: {error_output}")
            
            exit_code = process.returncode
            if progress_callback:
                progress_callback(f"[INFO] SteamCMD process completed with exit code: {exit_code}")
            
            if exit_code != 0 and not installation_success:
                error_description = self.get_steamcmd_error_description(exit_code)
                
                logger.error(f"SteamCMD installation failed with exit code {exit_code}: {error_description}")
                
                raise Exception(f"SteamCMD failed with exit code {exit_code}: {error_description}")
            
            return True, "Steam server installed successfully"
            
        except Exception as e:
            logger.error(f"Steam server installation failed: {str(e)}")
            return False, f"Installation failed: {str(e)}"

    def install_minecraft_server(self, server_name, install_dir, version, modloader="Vanilla", progress_callback=None, cancel_flag=None):
        try:
            if cancel_flag and cancel_flag.get():
                if progress_callback:
                    progress_callback("[INFO] Installation cancelled before starting")
                return False, "Installation cancelled by user"
                
            if progress_callback:
                progress_callback(f"[INFO] Starting Minecraft server installation for {server_name}")
            
            os.makedirs(install_dir, exist_ok=True)
            if progress_callback:
                progress_callback(f"[INFO] Created installation directory: {install_dir}")
            
            executable_path = None
            
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
        try:
            if server_name in self.servers:
                return False, "A server with this name already exists"
            
            server_config = {
                "Name": server_name,
                "Type": server_type,
                "AppID": app_id,
                "InstallDir": install_dir,
                "ExecutablePath": executable_path,
                "StartupArgs": startup_args,
                "Category": "Uncategorized",  # Default category for new servers
                "Created": datetime.now().isoformat(),
                "LastUpdate": datetime.now().isoformat()
            }
            
            if server_type == "Minecraft":
                server_config["Version"] = version
                server_config["ModLoader"] = modloader
            
            if additional_config:
                server_config.update(additional_config)
            
            success = self.update_server(server_name, server_config)
            if not success:
                return False, "Failed to save server configuration to database"
            
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

    def get_supported_server_types(self):
        return ["Steam", "Minecraft", "Other"]

    def uninstall_server(self, server_name, remove_files=False, progress_callback=None):
        try:
            server_config = self.get_server_config(server_name)
            if not server_config:
                return False, "Server configuration not found in database"
            
            install_dir = server_config.get('InstallDir') if remove_files else None
            
            if progress_callback:
                progress_callback(f"[INFO] Stopping server {server_name} if running...")
            
            success, message = self.stop_server_advanced(server_name)
            if not success and "not running" not in message.lower():
                logger.warning(f"Could not stop server before removal: {message}")
            
            if progress_callback:
                progress_callback(f"[INFO] Removing server configuration...")
            
            from Modules.Database.server_configs_database import get_server_config_manager
            manager = get_server_config_manager()
            success = manager.delete_server(server_name)
            
            if not success:
                return False, "Failed to remove server configuration from database"
            
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
