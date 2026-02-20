# -*- coding: utf-8 -*-
# File-based command queue for server stdin
import os
import sys
import time
import json
import threading
from pathlib import Path
from typing import Optional, Tuple, List, Callable
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_logging

logger = setup_module_logging("CommandQueue")

def _get_queue_dir() -> Path:
    # Queue directory path
    queue_dir = Path(__file__).parent.parent / "temp" / "command_queues"
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir

def _sanitise_name(server_name: str) -> str:
    # Filesystem-safe name
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in server_name)


def get_queue_file(server_name: str) -> Path:
    # Queue file path for server
    return _get_queue_dir() / f"{_sanitise_name(server_name)}_commands.txt"

def get_relay_info_file(server_name: str) -> Path:
    # Relay info file path
    return _get_queue_dir() / f"{_sanitise_name(server_name)}_relay.json"

# Active relay registry
_active_relays: dict = {}
_relays_lock = threading.Lock()

class CommandQueueRelay:
    # Reads commands from queue file, writes to server stdin
    def __init__(self, server_name: str, stdin_writer: Callable[[str], bool]):
        # server_name: Server name
        # stdin_writer: Func that writes to stdin, returns True on success
        self.server_name = server_name
        self.stdin_writer = stdin_writer
        self.queue_file = get_queue_file(server_name)
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self._processed_commands: set = set()
    
    def start(self):
        # Start relay thread
        if self.thread and self.thread.is_alive():
            logger.debug(f"Relay already running for {self.server_name}")
            return
        
        # Clear queue on start
        try:
            self.queue_file.write_text("")
        except OSError:
            pass
        
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._relay_loop,
            name=f"CmdQueueRelay-{self.server_name}",
            daemon=False  # Non-daemon - survives main thread exit briefly
        )
        self.thread.start()
        
        # Save relay info
        info = {
            'server_name': self.server_name,
            'started_at': time.time(),
            'pid': os.getpid(),
            'thread_id': self.thread.ident
        }
        try:
            get_relay_info_file(self.server_name).write_text(json.dumps(info, indent=2))
        except Exception as e:
            logger.warning(f"Could not save relay info: {e}")
        
        logger.info(f"Started command queue relay for {self.server_name}")
    
    def stop(self):
        # Stop the relay thread
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        
        # Clean up info file
        try:
            get_relay_info_file(self.server_name).unlink()
        except OSError:
            pass
        
        logger.info(f"Stopped command queue relay for {self.server_name}")
    
    def _relay_loop(self):
        # Main relay loop - polls queue file and sends commands
        logger.debug(f"Relay loop started for {self.server_name}")
        
        while not self.stop_event.is_set():
            try:
                # Read pending commands
                commands = self._read_pending_commands()
                
                for cmd_id, command in commands:
                    if cmd_id in self._processed_commands:
                        continue
                    
                    logger.debug(f"Processing command for {self.server_name}: {command}")
                    
                    try:
                        if self.stdin_writer(command):
                            self._processed_commands.add(cmd_id)
                            logger.info(f"Sent command to {self.server_name}: {command}")
                        else:
                            logger.warning(f"Failed to send command to {self.server_name}: {command}")
                    except Exception as e:
                        logger.error(f"Error sending command: {e}")
                        # If stdin fails, the server might be dead
                        if "closed" in str(e).lower() or "broken" in str(e).lower():
                            logger.info(f"Stdin appears closed for {self.server_name}, stopping relay")
                            self.stop_event.set()
                            break
                
                # Clear processed commands from file periodically
                if len(self._processed_commands) > 100:
                    self._clean_queue_file()
                
            except Exception as e:
                logger.error(f"Error in relay loop: {e}")
            
            # Poll every 100ms
            self.stop_event.wait(0.1)
        
        logger.debug(f"Relay loop ended for {self.server_name}")
    
    def _read_pending_commands(self) -> List[Tuple[str, str]]:
        # Read commands from the queue file
        if not self.queue_file.exists():
            return []
        
        try:
            content = self.queue_file.read_text(encoding='utf-8')
            commands = []
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Each line is: timestamp:command
                if ':' in line:
                    cmd_id, command = line.split(':', 1)
                    commands.append((cmd_id, command))
            return commands
        except Exception as e:
            logger.debug(f"Error reading queue file: {e}")
            return []
    
    def _clean_queue_file(self):
        # Remove processed commands from the queue file
        try:
            if not self.queue_file.exists():
                return
            
            content = self.queue_file.read_text(encoding='utf-8')
            remaining = []
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                if ':' in line:
                    cmd_id = line.split(':', 1)[0]
                    if cmd_id not in self._processed_commands:
                        remaining.append(line)
            
            self.queue_file.write_text('\n'.join(remaining) + '\n' if remaining else '')
            self._processed_commands.clear()
        except Exception as e:
            logger.debug(f"Error cleaning queue file: {e}")

def queue_command(server_name: str, command: str) -> Tuple[bool, str]:
    # Queue a command for a server. The relay will pick it up and send it.
    # Args: server_name - Name of the server, command - Command to send
    # Returns: Tuple of (success, message)
    queue_file = get_queue_file(server_name)
    
    try:
        # Generate unique command ID
        cmd_id = f"{time.time():.6f}"
        
        # Append to queue file
        with open(queue_file, 'a', encoding='utf-8') as f:
            f.write(f"{cmd_id}:{command}\n")
        
        logger.debug(f"Queued command for {server_name}: {command}")
        return True, f"Command queued: {command}"
        
    except Exception as e:
        logger.error(f"Error queueing command: {e}")
        return False, str(e)


def is_relay_active(server_name: str) -> bool:
    # Check if a command relay is active for the server
    info_file = get_relay_info_file(server_name)
    if not info_file.exists():
        return False
    
    try:
        info = json.loads(info_file.read_text())
        pid = info.get('pid')
        
        # Check if the process is still running
        import psutil
        if pid and psutil.pid_exists(pid):
            return True
        
        # Process is gone, clean up
        info_file.unlink()
        return False
        
    except Exception as e:
        logger.debug(f"Error checking relay status: {e}")
        return False

def start_command_relay(server_name: str, process: subprocess.Popen) -> Optional[CommandQueueRelay]:
    # Start a command queue relay for a server
    # Args: server_name - Name of the server, process - The subprocess.Popen object with stdin
    # Returns: The relay object, or None if failed
    if not hasattr(process, 'stdin') or process.stdin is None:
        logger.error(f"Process for {server_name} has no stdin")
        return None
    
    def stdin_writer(command: str) -> bool:
        # Write command to the process stdin
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write(command + '\n')
                process.stdin.flush()
                return True
        except Exception as e:
            logger.error(f"Error writing to stdin: {e}")
        return False
    
    relay = CommandQueueRelay(server_name, stdin_writer)
    relay.start()
    
    # Register in global registry
    with _relays_lock:
        _active_relays[server_name] = relay
    
    return relay

def stop_command_relay(server_name: str):
    # Stop the command relay for a server
    with _relays_lock:
        relay = _active_relays.pop(server_name, None)
    
    if relay:
        relay.stop()

def get_active_relay(server_name: str) -> Optional[CommandQueueRelay]:
    # Get the active relay for a server, if any
    with _relays_lock:
        return _active_relays.get(server_name)
