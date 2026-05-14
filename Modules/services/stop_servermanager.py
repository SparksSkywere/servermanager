# Shutdown utility
import os
import sys
import json
import subprocess
import logging
import argparse
import psutil
import time
import ctypes
import signal

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path, ServerManagerModule, setup_module_logging, is_admin
setup_module_path()

logger: logging.Logger = setup_module_logging("StopServerManager")

def run_as_admin(extra_args=None):
    # Re-run with admin (hidden). Returns True if elevation launch succeeded.
    extra_args = extra_args or []
    if sys.platform == 'win32':
        script_path = os.path.abspath(__file__)
        params = subprocess.list2cmdline([script_path] + list(extra_args))
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 0)
        return result > 32
    else:
        print("Admin required")
        return False

class ServerManagerStopper(ServerManagerModule):
    # - Terminates all SM components
    # - Force option for stubborn processes
    def __init__(self):
        super().__init__("StopServerManager")
        self.debug_mode = False

        parser = argparse.ArgumentParser(description='Stop Server Manager')
        parser.add_argument('--debug', action='store_true', help='Debug mode')
        parser.add_argument('--force', action='store_true', help='Force stop')
        parser.add_argument('--elevated', action='store_true', help=argparse.SUPPRESS)
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)
            self.debug_mode = True

        self.force_stop = args.force
        self.elevated_run = args.elevated

    def stop_process_by_pid(self, pid, process_name=None):
        # Kill process by PID
        try:
            if not psutil.pid_exists(pid):
                logger.debug(f"PID {pid} not running")
                return True

            process = psutil.Process(pid)
            logger.info(f"Stopping process: {process.name()} (PID: {pid})")

            # Get child processes first before killing parent
            children = []
            try:
                children = process.children(recursive=True)
                if children:
                    logger.debug(f"Found {len(children)} child processes for PID {pid}")
            except Exception:
                pass

            # Try graceful termination first
            process.terminate()

            # Wait for process to terminate
            try:
                process.wait(timeout=10)  # Increased timeout to 10 seconds
                logger.info(f"Process {pid} terminated gracefully")
            except psutil.TimeoutExpired:
                # Use more forceful approaches depending on platform
                logger.warning(f"Process {pid} did not terminate gracefully, killing forcefully")
                try:
                    if sys.platform == 'win32':
                        # On Windows, use taskkill with /T to kill entire process tree
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                    else:
                        # On Unix, use SIGKILL
                        os.kill(pid, signal.SIGKILL)
                except Exception as e:
                    logger.error(f"Error forcefully killing process {pid}: {str(e)}")

            # Kill any remaining child processes
            for child in children:
                try:
                    if child.is_running():
                        if sys.platform == 'win32':
                            subprocess.call(['taskkill', '/F', '/PID', str(child.pid)],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
                        else:
                            child.kill()
                        logger.debug(f"Killed child process {child.pid}")
                except Exception:
                    pass

            # Verify process is terminated
            time.sleep(0.5)
            if psutil.pid_exists(pid):
                # Final attempt with taskkill /T
                logger.warning(f"Process {pid} still running, final kill attempt")
                if sys.platform == 'win32':
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                time.sleep(0.5)
                if psutil.pid_exists(pid):
                    logger.error(f"Failed to kill process {pid} forcefully")
                    return False

            return True

        except psutil.NoSuchProcess:
            logger.debug(f"Process {pid} does not exist")
            return True
        except Exception as e:
            logger.error(f"Error stopping process {pid}: {str(e)}")
            return False

    def stop_processes_from_pid_files(self):
        # Stop processes using PID files
        pid_files = [
            "launcher.pid",
            "webserver.pid",
            "trayicon.pid",
            "dashboard.pid",
            "admin_dashboard.pid",
            "server_automation.pid",
            "debug.pid"
        ]

        stopped_count = 0

        for pid_file in pid_files:
            pid_path = os.path.join(self.paths["temp"], pid_file)
            if os.path.exists(pid_path):
                try:
                    with open(pid_path, 'r', encoding='utf-8') as f:
                        pid_data = json.load(f)

                    pid = pid_data.get("ProcessId")
                    process_type = pid_data.get("ProcessType", pid_file.replace(".pid", ""))

                    if pid:
                        logger.info(f"Found PID file for {process_type}: {pid}")
                        if self.stop_process_by_pid(pid, process_type):
                            stopped_count += 1

                    # Remove PID file
                    os.remove(pid_path)

                except Exception as e:
                    logger.error(f"Error processing PID file {pid_file}: {str(e)}")

        return stopped_count

    def _is_servermanager_process(self, proc: psutil.Process) -> bool:
        # Determine whether a process belongs to this ServerManager instance.
        process_names = ["trayicon", "webserver", "launcher", "dashboard", "debug", "server_automation"]
        python_scripts = [
            'launcher.py', 'trayicon.py', 'webserver.py', 'dashboard.py', 'server_automation.py',
            'stdin_relay.py', 'persistent_stdin.py', 'debug_manager.py', 'debug.py',
            'stop_servermanager.py', 'start_servermanager.py', 'admin_dashboard.py'
        ]

        try:
            if proc.pid == os.getpid():
                return False

            proc_name = (proc.info.get('name') or proc.name() or '').lower()
            cmdline = ' '.join(proc.info.get('cmdline') or proc.cmdline() or []).lower()

            proc_match = any(name in proc_name for name in process_names)

            exe_match = False
            if self.server_manager_dir:
                try:
                    exe_path = proc.exe()
                    if exe_path and os.path.isabs(exe_path):
                        exe_match = os.path.abspath(exe_path).lower().startswith(os.path.abspath(self.server_manager_dir).lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                    exe_match = False

            python_script_match = False
            if 'python' in proc_name and cmdline:
                python_script_match = any(script in cmdline for script in python_scripts)
                if self.server_manager_dir and self.server_manager_dir.lower() not in cmdline:
                    python_script_match = False

            return proc_match or exe_match or python_script_match
        except Exception:
            return False

    def get_remaining_processes(self):
        # Return remaining ServerManager process details after shutdown passes.
        remaining = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if self._is_servermanager_process(proc):
                    cmdline = ' '.join(proc.info.get('cmdline') or [])
                    remaining.append((proc.pid, proc.info.get('name', '?'), cmdline[:200]))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue
        return remaining

    def _attempt_elevated_followup(self) -> bool:
        # Try one elevated follow-up pass for stubborn leftovers.
        if sys.platform != 'win32' or is_admin() or self.elevated_run:
            return False
        logger.warning("Residual processes detected; attempting elevated follow-up cleanup")
        launched = run_as_admin(['--force', '--elevated'])
        if not launched:
            logger.error("Failed to launch elevated follow-up cleanup")
            return False
        logger.info("Elevated follow-up cleanup launched")
        return True

    def stop_processes_by_name(self):
        # Stop Server Manager processes by name
        process_names = [
            "trayicon",
            "webserver",
            "launcher",
            "dashboard",  # Added dashboard to ensure it's also terminated
            "debug",
            "server_automation",
        ]

        # Add additional Python scripts to check for
        python_scripts = [
            'launcher.py',
            'trayicon.py',
            'webserver.py',
            'dashboard.py',
            'server_automation.py',
            'stdin_relay.py',
            'persistent_stdin.py',
            'debug_manager.py',
            'debug.py',
            'stop_servermanager.py',
            'start_servermanager.py',
            'admin_dashboard.py'
        ]

        stopped_count = 0

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Skip self
                if proc.pid == os.getpid():
                    continue

                # Check if process name matches
                proc_name = proc.info['name'].lower()
                proc_match = any(name in proc_name for name in process_names)

                # Check if executable resides inside Server Manager directory
                exe_match = False
                if self.server_manager_dir:
                    try:
                        exe_path = proc.exe()
                        if exe_path and os.path.isabs(exe_path) and os.path.abspath(exe_path).lower().startswith(os.path.abspath(self.server_manager_dir).lower()):
                            exe_match = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                        exe_match = False

                cmdline = " ".join(proc.info['cmdline'] or []).lower()

                # Check if Python script matches
                python_script_match = False
                if 'python' in proc_name and cmdline:
                    python_script_match = any(script in cmdline for script in python_scripts)
                    if self.server_manager_dir and self.server_manager_dir.lower() not in cmdline:
                        python_script_match = False

                # Stop matching processes
                if proc_match or exe_match or python_script_match:
                    logger.info(f"Found matching process: {proc.info['name']} (PID: {proc.pid}) - cmdline: {cmdline[:100]}...")
                    if self.stop_process_by_pid(proc.pid, proc.info['name']):
                        stopped_count += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                logger.error(f"Error checking process: {str(e)}")

        return stopped_count

    def final_cleanup_kill(self):
        # Final aggressive cleanup - kill any remaining Python processes related to Server Manager
        logger.info("Performing final aggressive cleanup")

        killed_count = 0

        try:
            # Use taskkill to kill any remaining python processes with servermanager in command line
            if sys.platform == 'win32' and self.server_manager_dir:
                # Kill python processes that have servermanager path in command line
                cmd = ['taskkill', '/F', '/FI', f'IMAGENAME eq python.exe', '/FI', f'COMMANDLINE co {self.server_manager_dir}']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    killed_count += 1
                    logger.info("Killed remaining python processes with servermanager path")

                # Also kill pythonw.exe processes
                cmd = ['taskkill', '/F', '/FI', f'IMAGENAME eq pythonw.exe', '/FI', f'COMMANDLINE co {self.server_manager_dir}']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    killed_count += 1
                    logger.info("Killed remaining pythonw processes with servermanager path")

        except Exception as e:
            logger.error(f"Error in final cleanup: {str(e)}")

        return killed_count

    def stop_all_game_servers(self):
        # Stop all running game servers
        try:
            # First check if the stop_all_servers.py script exists
            stop_all_script = os.path.join(self.paths["scripts"], "stop_all_servers.py")
            if os.path.exists(stop_all_script):
                logger.info("Stopping all game servers using stop_all_servers.py")

                # Run with hidden console
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0  # SW_HIDE

                    subprocess.run(
                        [sys.executable, stop_all_script],
                        timeout=30,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    # Unix platforms
                    subprocess.run(
                        [sys.executable, stop_all_script],
                        timeout=30,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                return True

            # Alternative method: look for PIDS.txt
            if self.server_manager_dir:
                pids_file = os.path.join(self.server_manager_dir, "PIDS.txt")
                if os.path.exists(pids_file):
                    logger.info("Stopping servers listed in PIDS.txt")
                    with open(pids_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split(' - ')
                            if len(parts) >= 2:
                                pid = int(parts[0])
                                server_name = parts[1]
                                logger.info(f"Stopping server: {server_name} (PID: {pid})")
                                self.stop_process_by_pid(pid, server_name)

                    # Clear the PIDS file
                    open(pids_file, 'w', encoding='utf-8').close()
                return True

            return False
        except Exception as e:
            logger.error(f"Error stopping game servers: {str(e)}")
            return False

    def run(self):
        # Main execution method
        try:
            logger.info("Starting Server Manager shutdown process")

            # Stop all game servers first
            self.stop_all_game_servers()

            # Stop processes from PID files
            count1 = self.stop_processes_from_pid_files()

            # Stop processes by name
            count2 = self.stop_processes_by_name()

            logger.info(f"Stopped {count1 + count2} Server Manager processes")

            # Cleanup temp files
            for filename in os.listdir(self.paths["temp"]):
                if filename.endswith('.pid') or filename.startswith('relay_') and filename.endswith('.json'):
                    try:
                        os.remove(os.path.join(self.paths["temp"], filename))
                        logger.debug(f"Removed temp file: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to remove temp file {filename}: {str(e)}")

            # Final checks for any remaining processes. Some components spawn/exit asynchronously,
            # so perform a few bounded cleanup passes in a single stop invocation.
            total_additional = 0
            for pass_index in range(1, 4):
                time.sleep(2)
                pass_count = self.stop_processes_by_name()
                if pass_count > 0:
                    total_additional += pass_count
                    logger.info(f"Stopped {pass_count} additional processes in cleanup pass {pass_index}")
                else:
                    break

            if total_additional > 0:
                logger.info(f"Stopped {total_additional} additional processes in final cleanup passes")

            # Wait a bit more before aggressive cleanup
            time.sleep(1)

            # Final aggressive cleanup
            count4 = self.final_cleanup_kill()
            if count4 > 0:
                logger.info(f"Final cleanup killed {count4} additional processes")

            remaining = self.get_remaining_processes()
            if remaining:
                logger.warning(f"{len(remaining)} Server Manager process(es) still running after stop pass")
                for pid, name, cmdline in remaining[:10]:
                    logger.warning(f"Remaining process: {name} (PID {pid}) cmdline={cmdline}")
                self._attempt_elevated_followup()

            logger.info("Server Manager shutdown complete")
            return 0

        except Exception as e:
            logger.error(f"Error stopping Server Manager: {str(e)}")
            return 1

def main():
    try:
        if not is_admin():
            logger.warning("Running without admin privileges; performing best-effort shutdown")
        # Create and run stopper
        stopper = ServerManagerStopper()
        return stopper.run()
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())


