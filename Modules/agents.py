"""
Remote Agent Management Module for Server Manager Dashboard

This module handles the management of remote agents that can be connected to
the server manager for distributed server monitoring and management.
"""

import os
import sys
import json
import socket
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

# GUI imports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.logging import get_dashboard_logger

# Get logger
logger = get_dashboard_logger()


class RemoteAgent:
    """Represents a remote agent connection"""
    
    def __init__(self, name: str, host: str, port: int, auth_token: Optional[str] = None):
        self.name = name
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.connected = False
        self.last_ping: Optional[datetime] = None
        self.status = "Disconnected"
        self.server_count = 0
        self.system_info = {}
        
    def to_dict(self) -> dict:
        """Convert agent to dictionary for serialization"""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'auth_token': self.auth_token,
            'status': self.status,
            'server_count': self.server_count,
            'last_ping': self.last_ping.isoformat() if self.last_ping else None
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create agent from dictionary"""
        agent = cls(data['name'], data['host'], data['port'], data.get('auth_token'))
        agent.status = data.get('status', 'Disconnected')
        agent.server_count = data.get('server_count', 0)
        if data.get('last_ping'):
            agent.last_ping = datetime.fromisoformat(data['last_ping'])
        return agent


class AgentManager:
    """Manages remote agent connections"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.agents: Dict[str, RemoteAgent] = {}
        self.config_path = config_path or os.path.join(os.path.dirname(__file__), '..', 'data', 'agents.json')
        self.monitoring_thread = None
        self.monitoring_active = False
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        # Load existing agents
        self.load_agents()
    
    def add_agent(self, name: str, host: str, port: int, auth_token: Optional[str] = None) -> bool:
        """Add a new remote agent"""
        try:
            if name in self.agents:
                logger.warning(f"Agent '{name}' already exists")
                return False
            
            agent = RemoteAgent(name, host, port, auth_token)
            self.agents[name] = agent
            
            # Save configuration
            self.save_agents()
            
            logger.info(f"Added remote agent '{name}' ({host}:{port})")
            return True
            
        except Exception as e:
            logger.error(f"Error adding agent '{name}': {str(e)}")
            return False
    
    def remove_agent(self, name: str) -> bool:
        """Remove a remote agent"""
        try:
            if name not in self.agents:
                logger.warning(f"Agent '{name}' not found")
                return False
            
            # Disconnect if connected
            agent = self.agents[name]
            if agent.connected:
                self.disconnect_agent(name)
            
            # Remove from list
            del self.agents[name]
            
            # Save configuration
            self.save_agents()
            
            logger.info(f"Removed remote agent '{name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error removing agent '{name}': {str(e)}")
            return False
    
    def connect_agent(self, name: str) -> bool:
        """Connect to a remote agent"""
        try:
            if name not in self.agents:
                logger.error(f"Agent '{name}' not found")
                return False
            
            agent = self.agents[name]
            
            # Test connection
            if self._test_connection(agent.host, agent.port):
                agent.connected = True
                agent.status = "Connected"
                agent.last_ping = datetime.now()
                logger.info(f"Connected to agent '{name}'")
                return True
            else:
                agent.status = "Connection Failed"
                logger.warning(f"Failed to connect to agent '{name}'")
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to agent '{name}': {str(e)}")
            return False
    
    def disconnect_agent(self, name: str) -> bool:
        """Disconnect from a remote agent"""
        try:
            if name not in self.agents:
                logger.error(f"Agent '{name}' not found")
                return False
            
            agent = self.agents[name]
            agent.connected = False
            agent.status = "Disconnected"
            
            logger.info(f"Disconnected from agent '{name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting from agent '{name}': {str(e)}")
            return False
    
    def get_agent_status(self, name: str) -> Optional[str]:
        """Get the status of a remote agent"""
        if name in self.agents:
            return self.agents[name].status
        return None
    
    def get_all_agents(self) -> List[RemoteAgent]:
        """Get list of all agents"""
        return list(self.agents.values())
    
    def ping_agent(self, name: str) -> bool:
        """Ping a remote agent to check connectivity"""
        try:
            if name not in self.agents:
                return False
            
            agent = self.agents[name]
            if self._test_connection(agent.host, agent.port, timeout=5):
                agent.last_ping = datetime.now()
                if not agent.connected:
                    agent.status = "Available"
                return True
            else:
                if agent.connected:
                    agent.connected = False
                    agent.status = "Connection Lost"
                return False
                
        except Exception as e:
            logger.error(f"Error pinging agent '{name}': {str(e)}")
            return False
    
    def start_monitoring(self):
        """Start monitoring thread for agent connectivity"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("Agent monitoring started")
    
    def stop_monitoring(self):
        """Stop monitoring thread"""
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        logger.info("Agent monitoring stopped")
    
    def _monitoring_loop(self):
        """Background monitoring loop"""
        while self.monitoring_active:
            try:
                for name in list(self.agents.keys()):
                    self.ping_agent(name)
                
                # Sleep for 30 seconds between checks
                for _ in range(30):
                    if not self.monitoring_active:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Error in agent monitoring loop: {str(e)}")
                time.sleep(5)
    
    def _test_connection(self, host: str, port: int, timeout: int = 3) -> bool:
        """Test connection to a host and port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def save_agents(self):
        """Save agents configuration to file"""
        try:
            data = {
                'agents': {name: agent.to_dict() for name, agent in self.agents.items()},
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.debug(f"Saved {len(self.agents)} agents to {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error saving agents configuration: {str(e)}")
    
    def load_agents(self):
        """Load agents configuration from file"""
        try:
            if not os.path.exists(self.config_path):
                logger.info("No agents configuration file found, starting with empty list")
                return
            
            with open(self.config_path, 'r') as f:
                data = json.load(f)
            
            agents_data = data.get('agents', {})
            for name, agent_data in agents_data.items():
                self.agents[name] = RemoteAgent.from_dict(agent_data)
            
            logger.info(f"Loaded {len(self.agents)} agents from {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error loading agents configuration: {str(e)}")


class AgentDialog:
    """Dialog for managing remote agents"""
    
    def __init__(self, parent, agent_manager: AgentManager):
        self.parent = parent
        self.agent_manager = agent_manager
        self.dialog: Optional[tk.Toplevel] = None
        self.agent_tree: Optional[ttk.Treeview] = None
        self.status_label: Optional[ttk.Label] = None
    
    def show_agent_management_dialog(self):
        """Show the agent management dialog"""
        try:
            # Create dialog
            self.dialog = tk.Toplevel(self.parent)
            self.dialog.title("Remote Agent Management")
            self.dialog.geometry("800x600")
            self.dialog.transient(self.parent)
            self.dialog.grab_set()
            
            # Main frame
            main_frame = ttk.Frame(self.dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Header
            header_frame = ttk.Frame(main_frame)
            header_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(header_frame, text="Remote Agent Management", 
                     font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
            
            # Status label
            self.status_label = ttk.Label(header_frame, text="Ready", foreground="green")
            self.status_label.pack(side=tk.RIGHT)
            
            # Agent list
            list_frame = ttk.LabelFrame(main_frame, text="Connected Agents")
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            
            # Create treeview
            columns = ("name", "host", "port", "status", "servers", "last_ping")
            self.agent_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
            
            # Define headings
            self.agent_tree.heading("name", text="Agent Name")
            self.agent_tree.heading("host", text="Host")
            self.agent_tree.heading("port", text="Port")
            self.agent_tree.heading("status", text="Status")
            self.agent_tree.heading("servers", text="Servers")
            self.agent_tree.heading("last_ping", text="Last Ping")
            
            # Configure columns
            self.agent_tree.column("name", width=150)
            self.agent_tree.column("host", width=120)
            self.agent_tree.column("port", width=80)
            self.agent_tree.column("status", width=100)
            self.agent_tree.column("servers", width=80)
            self.agent_tree.column("last_ping", width=150)
            
            # Scrollbar
            tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.agent_tree.yview)
            self.agent_tree.configure(yscrollcommand=tree_scroll.set)
            
            # Pack tree and scrollbar
            tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self.agent_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # Button frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X)
            
            # Buttons
            ttk.Button(button_frame, text="Add Agent", command=self.add_agent_dialog).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Remove Agent", command=self.remove_selected_agent).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Connect", command=self.connect_selected_agent).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Disconnect", command=self.disconnect_selected_agent).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Refresh", command=self.refresh_agents).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side=tk.RIGHT)
            
            # Populate agents
            self.refresh_agents()
            
            # Center dialog
            self.dialog.update_idletasks()
            x = self.parent.winfo_rootx() + (self.parent.winfo_width() - self.dialog.winfo_width()) // 2
            y = self.parent.winfo_rooty() + (self.parent.winfo_height() - self.dialog.winfo_height()) // 2
            self.dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error showing agent management dialog: {str(e)}")
            messagebox.showerror("Error", f"Failed to open agent management: {str(e)}")
    
    def add_agent_dialog(self):
        """Show dialog to add a new agent"""
        try:
            # Create add agent dialog
            add_dialog = tk.Toplevel(self.dialog)
            add_dialog.title("Add Remote Agent")
            add_dialog.geometry("400x250")
            add_dialog.transient(self.dialog)
            add_dialog.grab_set()
            
            # Main frame
            frame = ttk.Frame(add_dialog, padding=20)
            frame.pack(fill=tk.BOTH, expand=True)
            
            # Agent name
            ttk.Label(frame, text="Agent Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
            name_var = tk.StringVar()
            ttk.Entry(frame, textvariable=name_var, width=30).grid(row=0, column=1, sticky=tk.W, pady=5)
            
            # Host
            ttk.Label(frame, text="Host/IP:").grid(row=1, column=0, sticky=tk.W, pady=5)
            host_var = tk.StringVar()
            ttk.Entry(frame, textvariable=host_var, width=30).grid(row=1, column=1, sticky=tk.W, pady=5)
            
            # Port
            ttk.Label(frame, text="Port:").grid(row=2, column=0, sticky=tk.W, pady=5)
            port_var = tk.StringVar(value="8080")
            ttk.Entry(frame, textvariable=port_var, width=30).grid(row=2, column=1, sticky=tk.W, pady=5)
            
            # Auth token (optional)
            ttk.Label(frame, text="Auth Token:").grid(row=3, column=0, sticky=tk.W, pady=5)
            token_var = tk.StringVar()
            ttk.Entry(frame, textvariable=token_var, width=30, show="*").grid(row=3, column=1, sticky=tk.W, pady=5)
            ttk.Label(frame, text="(Optional)", foreground="gray").grid(row=3, column=2, sticky=tk.W, pady=5)
            
            # Buttons
            button_frame = ttk.Frame(frame)
            button_frame.grid(row=4, column=0, columnspan=3, pady=20)
            
            def add_agent():
                try:
                    name = name_var.get().strip()
                    host = host_var.get().strip()
                    port_str = port_var.get().strip()
                    token = token_var.get().strip() or None
                    
                    if not name or not host or not port_str:
                        messagebox.showerror("Error", "Please fill in all required fields.")
                        return
                    
                    try:
                        port = int(port_str)
                        if port < 1 or port > 65535:
                            raise ValueError("Port must be between 1 and 65535")
                    except ValueError as e:
                        messagebox.showerror("Error", f"Invalid port number: {str(e)}")
                        return
                    
                    if self.agent_manager.add_agent(name, host, port, token):
                        messagebox.showinfo("Success", f"Agent '{name}' added successfully.")
                        add_dialog.destroy()
                        self.refresh_agents()
                    else:
                        messagebox.showerror("Error", f"Failed to add agent '{name}'. Name may already exist.")
                        
                except Exception as e:
                    logger.error(f"Error adding agent: {str(e)}")
                    messagebox.showerror("Error", f"Failed to add agent: {str(e)}")
            
            ttk.Button(button_frame, text="Add", command=add_agent).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Cancel", command=add_dialog.destroy).pack(side=tk.LEFT, padx=5)
            
            # Center dialog
            if self.dialog:
                add_dialog.update_idletasks()
                x = self.dialog.winfo_rootx() + (self.dialog.winfo_width() - add_dialog.winfo_width()) // 2
                y = self.dialog.winfo_rooty() + (self.dialog.winfo_height() - add_dialog.winfo_height()) // 2
                add_dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            logger.error(f"Error showing add agent dialog: {str(e)}")
            messagebox.showerror("Error", f"Failed to show add agent dialog: {str(e)}")
    
    def remove_selected_agent(self):
        """Remove the selected agent"""
        try:
            if not self.agent_tree:
                return
            
            selection = self.agent_tree.selection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select an agent to remove.")
                return
            
            # Get agent name
            item = self.agent_tree.item(selection[0])
            agent_name = item['values'][0]
            
            # Confirm removal
            if messagebox.askyesno("Confirm Removal", f"Remove agent '{agent_name}'?"):
                if self.agent_manager.remove_agent(agent_name):
                    messagebox.showinfo("Success", f"Agent '{agent_name}' removed successfully.")
                    self.refresh_agents()
                else:
                    messagebox.showerror("Error", f"Failed to remove agent '{agent_name}'.")
                    
        except Exception as e:
            logger.error(f"Error removing agent: {str(e)}")
            messagebox.showerror("Error", f"Failed to remove agent: {str(e)}")
    
    def connect_selected_agent(self):
        """Connect to the selected agent"""
        try:
            if not self.agent_tree:
                return
            
            selection = self.agent_tree.selection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select an agent to connect.")
                return
            
            # Get agent name
            item = self.agent_tree.item(selection[0])
            agent_name = item['values'][0]
            
            if self.agent_manager.connect_agent(agent_name):
                messagebox.showinfo("Success", f"Connected to agent '{agent_name}'.")
                self.refresh_agents()
            else:
                messagebox.showerror("Error", f"Failed to connect to agent '{agent_name}'.")
                
        except Exception as e:
            logger.error(f"Error connecting to agent: {str(e)}")
            messagebox.showerror("Error", f"Failed to connect to agent: {str(e)}")
    
    def disconnect_selected_agent(self):
        """Disconnect from the selected agent"""
        try:
            if not self.agent_tree:
                return
            
            selection = self.agent_tree.selection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select an agent to disconnect.")
                return
            
            # Get agent name
            item = self.agent_tree.item(selection[0])
            agent_name = item['values'][0]
            
            if self.agent_manager.disconnect_agent(agent_name):
                messagebox.showinfo("Success", f"Disconnected from agent '{agent_name}'.")
                self.refresh_agents()
            else:
                messagebox.showerror("Error", f"Failed to disconnect from agent '{agent_name}'.")
                
        except Exception as e:
            logger.error(f"Error disconnecting from agent: {str(e)}")
            messagebox.showerror("Error", f"Failed to disconnect from agent: {str(e)}")
    
    def refresh_agents(self):
        """Refresh the agent list"""
        try:
            if not self.agent_tree:
                return
            
            # Clear existing items
            for item in self.agent_tree.get_children():
                self.agent_tree.delete(item)
            
            # Add current agents
            for agent in self.agent_manager.get_all_agents():
                last_ping = "Never"
                if agent.last_ping:
                    last_ping = agent.last_ping.strftime("%Y-%m-%d %H:%M:%S")
                
                self.agent_tree.insert("", "end", values=(
                    agent.name,
                    agent.host,
                    agent.port,
                    agent.status,
                    agent.server_count,
                    last_ping
                ))
                
        except Exception as e:
            logger.error(f"Error refreshing agent list: {str(e)}")


def show_agent_management_dialog(parent, agent_manager: AgentManager):
    """Show the agent management dialog"""
    dialog = AgentDialog(parent, agent_manager)
    dialog.show_agent_management_dialog()


def add_agent_placeholder(parent):
    """Placeholder function for add agent functionality"""
    try:
        # For now, show a coming soon message
        messagebox.showinfo("Feature Coming Soon", "Remote agent functionality will be available in a future version.")
    except Exception as e:
        logger.error(f"Error in add agent placeholder: {str(e)}")
        messagebox.showerror("Error", f"Failed to add agent: {str(e)}")
