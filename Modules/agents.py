# Cluster Agent Management Module
# Manages cluster nodes, handles join requests, provides GUI for cluster administration
# Supports both master and subhost configurations with database persistence

import os
import sys
import requests
import threading
from datetime import datetime
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.server_logging import get_dashboard_logger
from Modules.Database.cluster_database import ClusterDatabase

try:
    from Modules.cluster_security import SimpleClusterManager
except ImportError:
    SimpleClusterManager = None

logger = get_dashboard_logger()


class ClusterNode:
    def __init__(self, name: str, ip: str, status: str = "unknown"):
        # Represents a cluster node with connection status and server tracking
        self.name = name
        self.ip = ip
        self.status = status
        self.last_ping: Optional[datetime] = None
        self.server_count = 0
        self.is_online = False


class AgentManager:
    def __init__(self, config_path: Optional[str] = None):
        # Initialize cluster agent manager with database backend and optional JSON migration
        self.nodes: Dict[str, ClusterNode] = {}
        
        # Initialize database instead of JSON file
        try:
            self.cluster_db = ClusterDatabase()
            logger.info("Cluster database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize cluster database: {e}")
            self.cluster_db = None
        
        self.cluster_manager = None
        if SimpleClusterManager:
            try:
                self.cluster_manager = SimpleClusterManager()
            except Exception as e:
                logger.warning(f"Could not initialize cluster manager: {e}")
        
        # Load existing nodes from database
        self.load_nodes()
        
        # Migrate from JSON if it exists and database is available
        if config_path and self.cluster_db:
            self.migrate_from_json(config_path)
    
    def get_cluster_status(self):
        if not self.cluster_manager:
            return {'error': 'Cluster manager not available'}
        
        try:
            return self.cluster_manager.get_cluster_status()
        except Exception as e:
            logger.error(f"Error getting cluster status: {e}")
            return {'error': str(e)}
    
    def is_master_host(self):
        if not self.cluster_manager:
            return False
        return self.cluster_manager.is_master
    
    def join_cluster(self, master_ip: str) -> bool:
        if not self.cluster_manager:
            return False
        
        if self.cluster_manager.is_master:
            logger.error("Master hosts cannot join clusters")
            return False
        
        try:
            return self.cluster_manager.join_cluster(master_ip)
        except Exception as e:
            logger.error(f"Error joining cluster: {e}")
            return False
    
    def add_node(self, name: str, ip: str) -> bool:
        if name in self.nodes:
            return False
        
        # Add to database
        if self.cluster_db and self.cluster_db.add_cluster_node(name, ip):
            node = ClusterNode(name, ip)
            self.nodes[name] = node
            logger.info(f"Added cluster node: {name} ({ip})")
            return True
        
        logger.error(f"Failed to add cluster node to database: {name}")
        return False
    
    def remove_node(self, name: str) -> bool:
        if name not in self.nodes:
            return False
        
        # Remove from database
        if self.cluster_db and self.cluster_db.remove_cluster_node(name):
            del self.nodes[name]
            logger.info(f"Removed cluster node: {name}")
            return True
        
        logger.error(f"Failed to remove cluster node from database: {name}")
        return False
    
    def get_all_nodes(self) -> List[ClusterNode]:
        return list(self.nodes.values())
    
    def get_pending_requests(self) -> List[dict]:
        # Get all pending cluster join requests for master host approval
        if not self.cluster_db:
            return []
        return self.cluster_db.get_pending_requests()
    
    def approve_request(self, request_id: int, approved_by: str = "admin") -> bool:
        # Approve a pending cluster join request and generate access token
        if not self.cluster_db:
            return False
        
        try:
            # Get the request details
            request = self.cluster_db.get_request_by_id(request_id)
            if not request:
                logger.error(f"Request {request_id} not found")
                return False
            
            # Generate approval token
            import uuid
            approval_token = str(uuid.uuid4())
            
            # Approve the request in database
            success = self.cluster_db.approve_request(request_id, approved_by, approval_token)
            if not success:
                return False
            
            # Add to cluster nodes
            success = self.cluster_db.add_cluster_node(
                name=request['node_name'],
                ip_address=request['ip_address'],
                port=request['port'],
                node_type='subhost',
                cluster_token=approval_token
            )
            
            if success:
                # Reload nodes to include the new one
                self.load_nodes()
                logger.info(f"Approved and registered cluster request: {request['node_name']}")
                return True
            else:
                logger.error(f"Failed to add approved node to cluster")
                return False
                
        except Exception as e:
            logger.error(f"Error approving request {request_id}: {e}")
            return False
    
    def reject_request(self, request_id: int, rejected_by: str = "admin") -> bool:
        # Reject a pending cluster join request
        if not self.cluster_db:
            return False
        
        try:
            success = self.cluster_db.reject_request(request_id, rejected_by)
            if success:
                logger.info(f"Rejected cluster request: {request_id}")
            return success
        except Exception as e:
            logger.error(f"Error rejecting request {request_id}: {e}")
            return False

    def ping_node(self, name: str) -> bool:
        # Ping a specific cluster node and update its status in database
        if name not in self.nodes:
            return False
        
        node = self.nodes[name]
        try:
            response = requests.get(f"http://{node.ip}:8080/api/status", timeout=5)
            if response.status_code == 200:
                node.status = "online"
                node.is_online = True
                node.last_ping = datetime.now()
                data = response.json()
                node.server_count = len(data.get('servers', []))
                # Update status in database
                if self.cluster_db:
                    self.cluster_db.update_node_status(name, "online", node.last_ping)
                return True
        except:
            pass
        
        node.status = "offline"
        node.is_online = False
        # Update status in database
        if self.cluster_db:
            self.cluster_db.update_node_status(name, "offline", datetime.now())
        return False
    
    def ping_all_nodes(self):
        for node_name in self.nodes:
            self.ping_node(node_name)
    
    def get_node_servers(self, node_name: str) -> List[dict]:
        # Get list of servers running on a specific cluster node
        if node_name not in self.nodes:
            return []
        
        node = self.nodes[node_name]
        try:
            response = requests.get(f"http://{node.ip}:8080/api/servers", timeout=10)
            if response.status_code == 200:
                return response.json().get('servers', [])
        except Exception as e:
            logger.error(f"Failed to get servers from node {node_name}: {e}")
        
        return []
    
    def save_nodes(self):
        # No longer needed - database operations handle persistence
        pass
    
    def load_nodes(self):
        # Load cluster nodes from database with status and ping history
        try:
            if not self.cluster_db:
                logger.warning("No cluster database available, cannot load nodes")
                return
            
            db_nodes = self.cluster_db.get_all_cluster_nodes()
            
            for node_data in db_nodes:
                name = node_data['name']
                ip = node_data['ip_address']
                
                node = ClusterNode(name, ip)
                node.status = node_data.get('status', 'unknown')
                if node_data.get('last_ping'):
                    try:
                        node.last_ping = datetime.fromisoformat(node_data['last_ping'])
                        node.is_online = node.status == 'online'
                    except:
                        node.last_ping = None
                        node.is_online = False
                
                self.nodes[name] = node
            
            logger.info(f"Loaded {len(self.nodes)} cluster nodes from database")
            
        except Exception as e:
            logger.error(f"Error loading nodes from database: {str(e)}")
    
    def migrate_from_json(self, json_path: str):
        # Migrate existing JSON configuration to database
        try:
            if not self.cluster_db:
                return
                
            # Try to migrate from the JSON file
            self.cluster_db.migrate_from_json(json_path)
            
            # Reload nodes from database after migration
            self.load_nodes()
            
        except Exception as e:
            logger.error(f"Error migrating from JSON: {e}")


def show_agent_management_dialog(parent, agent_manager: AgentManager):
    # Show the cluster management GUI dialog
    dialog = ClusterManagementDialog(parent, agent_manager)
    dialog.show_dialog()


class ClusterManagementDialog:
    def __init__(self, parent, agent_manager: AgentManager):
        # Initialize cluster management GUI with pending requests and node management
        self.parent = parent
        self.agent_manager = agent_manager
        self.dialog: Optional[tk.Toplevel] = None
        self.nodes_tree = None
        
    def show_dialog(self):
        try:
            self.dialog = tk.Toplevel(self.parent)
            self.dialog.title("Cluster Management")
            self.dialog.geometry("800x600")
            self.dialog.resizable(True, True)
            self.dialog.transient(self.parent)
            self.dialog.grab_set()
            
            main_frame = ttk.Frame(self.dialog, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Cluster status section
            self.create_cluster_status_section(main_frame)
            
            # Pending requests section
            self.create_pending_requests_section(main_frame)
            
            # Nodes management section
            self.create_nodes_section(main_frame)
            
            # Button frame
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            ttk.Button(button_frame, text="Refresh", command=self.refresh_nodes).pack(side=tk.LEFT)
            ttk.Button(button_frame, text="Ping All", command=self.ping_all_nodes).pack(side=tk.LEFT, padx=(10, 0))
            ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side=tk.RIGHT)
            
            self.center_dialog()
            self.refresh_nodes()
            
        except Exception as e:
            logger.error(f"Error creating cluster dialog: {str(e)}")
            messagebox.showerror("Error", f"Failed to create dialog: {str(e)}")
    
    def create_cluster_status_section(self, parent):
        cluster_frame = ttk.LabelFrame(parent, text="Cluster Status", padding=10)
        cluster_frame.pack(fill=tk.X, pady=(0, 10))
        
        cluster_status = self.agent_manager.get_cluster_status()
        
        if 'error' in cluster_status:
            status_text = f"❌ Cluster not configured: {cluster_status['error']}"
        else:
            if cluster_status.get('is_master'):
                status_text = "🏠 Master Host - Managing cluster nodes"
            elif cluster_status.get('cluster_ready'):
                status_text = f"🔗 Cluster Node - Connected to master at {cluster_status.get('master_ip')}"
            else:
                status_text = "❓ Cluster Node - Not connected to master"
        
        status_label = ttk.Label(cluster_frame, text=status_text, font=('Segoe UI', 10))
        status_label.pack(anchor=tk.W)
        
        # Show join cluster option for nodes only
        if cluster_status.get('is_master') == False and not cluster_status.get('cluster_ready'):
            join_frame = ttk.Frame(cluster_frame)
            join_frame.pack(fill=tk.X, pady=(10, 0))
            
            ttk.Label(join_frame, text="Join Cluster - Master IP:").pack(side=tk.LEFT)
            
            self.master_ip_entry = ttk.Entry(join_frame, width=15)
            self.master_ip_entry.pack(side=tk.LEFT, padx=(10, 5))
            
            ttk.Button(join_frame, text="Join Cluster", 
                      command=self.join_cluster_action).pack(side=tk.LEFT, padx=5)
    
    def create_pending_requests_section(self, parent):
        # Create section for pending cluster join requests (master hosts only)
        cluster_status = self.agent_manager.get_cluster_status()
        if not cluster_status.get('is_master'):
            return  # Only show for master hosts
            
        pending_frame = ttk.LabelFrame(parent, text="Pending Join Requests", padding=10)
        pending_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Create treeview for pending requests
        columns = ("Host", "IP Address", "Request Time", "Status")
        self.pending_tree = ttk.Treeview(pending_frame, columns=columns, show="headings", height=6)
        
        # Configure column headings and widths
        self.pending_tree.heading("Host", text="Host Name")
        self.pending_tree.heading("IP Address", text="IP Address") 
        self.pending_tree.heading("Request Time", text="Request Time")
        self.pending_tree.heading("Status", text="Status")
        
        self.pending_tree.column("Host", width=150)
        self.pending_tree.column("IP Address", width=120)
        self.pending_tree.column("Request Time", width=150)
        self.pending_tree.column("Status", width=100)
        
        self.pending_tree.pack(fill=tk.X, pady=(0, 10))
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(pending_frame, orient=tk.VERTICAL, command=self.pending_tree.yview)
        self.pending_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Button frame for actions
        button_frame = ttk.Frame(pending_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="Approve Selected", 
                  command=self.approve_selected_request).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Reject Selected", 
                  command=self.reject_selected_request).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Refresh", 
                  command=self.refresh_pending_requests).pack(side=tk.RIGHT)
        
        # Initial load of pending requests
        self.refresh_pending_requests()
    
    def create_nodes_section(self, parent):
        nodes_frame = ttk.LabelFrame(parent, text="Cluster Nodes", padding=10)
        nodes_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Add node controls (only show for master hosts)
        cluster_status = self.agent_manager.get_cluster_status()
        if cluster_status.get('is_master'):
            add_frame = ttk.Frame(nodes_frame)
            add_frame.pack(fill=tk.X, pady=(0, 10))
            
            ttk.Label(add_frame, text="Add Node - Name:").pack(side=tk.LEFT)
            self.node_name_entry = ttk.Entry(add_frame, width=15)
            self.node_name_entry.pack(side=tk.LEFT, padx=(5, 10))
            
            ttk.Label(add_frame, text="IP:").pack(side=tk.LEFT)
            self.node_ip_entry = ttk.Entry(add_frame, width=15)
            self.node_ip_entry.pack(side=tk.LEFT, padx=(5, 10))
            
            ttk.Button(add_frame, text="Add Node", command=self.add_node_action).pack(side=tk.LEFT, padx=5)
        
        # Nodes tree
        tree_frame = ttk.Frame(nodes_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        self.nodes_tree = ttk.Treeview(tree_frame, columns=("ip", "status", "servers", "last_ping"), show="tree headings")
        self.nodes_tree.heading("#0", text="Node Name")
        self.nodes_tree.heading("ip", text="IP Address")
        self.nodes_tree.heading("status", text="Status")
        self.nodes_tree.heading("servers", text="Servers")
        self.nodes_tree.heading("last_ping", text="Last Ping")
        
        self.nodes_tree.column("#0", width=150)
        self.nodes_tree.column("ip", width=120)
        self.nodes_tree.column("status", width=80)
        self.nodes_tree.column("servers", width=80)
        self.nodes_tree.column("last_ping", width=150)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.nodes_tree.yview)
        self.nodes_tree.configure(yscrollcommand=scrollbar.set)
        
        self.nodes_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Context menu for nodes
        if cluster_status.get('is_master'):
            self.nodes_tree.bind("<Button-3>", self.show_node_context_menu)
    
    def add_node_action(self):
        try:
            name = self.node_name_entry.get().strip()
            ip = self.node_ip_entry.get().strip()
            
            if not name or not ip:
                messagebox.showwarning("Warning", "Please enter both node name and IP address")
                return
            
            if self.agent_manager.add_node(name, ip):
                self.node_name_entry.delete(0, tk.END)
                self.node_ip_entry.delete(0, tk.END)
                self.refresh_nodes()
                messagebox.showinfo("Success", f"Node '{name}' added successfully")
            else:
                messagebox.showerror("Error", f"Failed to add node '{name}' (may already exist)")
                
        except Exception as e:
            logger.error(f"Error adding node: {e}")
            messagebox.showerror("Error", f"Failed to add node: {str(e)}")
    
    def join_cluster_action(self):
        try:
            master_ip = self.master_ip_entry.get().strip()
            if not master_ip:
                messagebox.showwarning("Warning", "Please enter the Master Host IP address")
                return
            
            if self.agent_manager.join_cluster(master_ip):
                messagebox.showinfo("Success", f"Successfully joined cluster managed by {master_ip}")
                if self.dialog:
                    self.dialog.destroy()
                show_agent_management_dialog(self.parent, self.agent_manager)
            else:
                messagebox.showerror("Error", f"Failed to join cluster. Check the Master Host IP address.")
                
        except Exception as e:
            logger.error(f"Error joining cluster: {e}")
            messagebox.showerror("Error", f"Failed to join cluster: {str(e)}")
    
    def refresh_pending_requests(self):
        # Refresh the pending requests treeview
        if not hasattr(self, 'pending_tree'):
            return
            
        # Clear existing items
        for item in self.pending_tree.get_children():
            self.pending_tree.delete(item)
            
        try:
            pending_requests = self.agent_manager.get_pending_requests()
            for request in pending_requests:
                # Format request time
                request_time = request.get('request_time', 'Unknown')
                if request_time and request_time != 'Unknown':
                    try:
                        # Convert timestamp to readable format
                        import datetime
                        dt = datetime.datetime.fromisoformat(request_time.replace('Z', '+00:00'))
                        request_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                
                self.pending_tree.insert('', 'end', values=(
                    request.get('node_name', 'Unknown'),
                    request.get('ip_address', 'Unknown'), 
                    request_time,
                    request.get('status', 'pending')
                ))
        except Exception as e:
            logger.error(f"Error refreshing pending requests: {e}")
    
    def approve_selected_request(self):
        # Approve the selected pending request with token generation
        selection = self.pending_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a request to approve")
            return
            
        # Get selected item data
        item = self.pending_tree.item(selection[0])
        values = item['values']
        if not values:
            return
            
        host_name = values[0]
        host_ip = values[1]
        
        try:
            if self.agent_manager.approve_request(host_ip):
                messagebox.showinfo("Success", f"Approved cluster join request from {host_name} ({host_ip})")
                self.refresh_pending_requests()
                self.refresh_nodes()  # Refresh the nodes list too
            else:
                messagebox.showerror("Error", f"Failed to approve request from {host_name}")
        except Exception as e:
            logger.error(f"Error approving request: {e}")
            messagebox.showerror("Error", f"Failed to approve request: {str(e)}")
    
    def reject_selected_request(self):
        # Reject the selected pending request with confirmation dialog
        selection = self.pending_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a request to reject")
            return
            
        # Get selected item data
        item = self.pending_tree.item(selection[0])
        values = item['values']
        if not values:
            return
            
        host_name = values[0]
        host_ip = values[1]
        
        # Confirm rejection
        if not messagebox.askyesno("Confirm Rejection", 
                                  f"Are you sure you want to reject the cluster join request from {host_name} ({host_ip})?"):
            return
        
        try:
            if self.agent_manager.reject_request(host_ip):
                messagebox.showinfo("Success", f"Rejected cluster join request from {host_name} ({host_ip})")
                self.refresh_pending_requests()
            else:
                messagebox.showerror("Error", f"Failed to reject request from {host_name}")
        except Exception as e:
            logger.error(f"Error rejecting request: {e}")
            messagebox.showerror("Error", f"Failed to reject request: {str(e)}")
    
    def refresh_nodes(self):
        if not self.nodes_tree:
            return
        
        for item in self.nodes_tree.get_children():
            self.nodes_tree.delete(item)
        
        for node in self.agent_manager.get_all_nodes():
            last_ping = node.last_ping.strftime("%Y-%m-%d %H:%M:%S") if node.last_ping else "Never"
            
            self.nodes_tree.insert("", tk.END, text=node.name, values=(
                node.ip,
                node.status,
                str(node.server_count),
                last_ping
            ))
    
    def ping_all_nodes(self):
        try:
            self.agent_manager.ping_all_nodes()
            self.refresh_nodes()
            messagebox.showinfo("Info", "Finished pinging all nodes")
        except Exception as e:
            logger.error(f"Error pinging nodes: {e}")
            messagebox.showerror("Error", f"Failed to ping nodes: {str(e)}")
    
    def show_node_context_menu(self, event):
        if not self.nodes_tree:
            return
            
        item = self.nodes_tree.selection()[0] if self.nodes_tree.selection() else None
        if not item:
            return
        
        node_name = self.nodes_tree.item(item, "text")
        
        context_menu = tk.Menu(self.dialog, tearoff=0)
        context_menu.add_command(label="Ping Node", command=lambda: self.ping_single_node(node_name))
        context_menu.add_command(label="View Servers", command=lambda: self.view_node_servers(node_name))
        context_menu.add_separator()
        context_menu.add_command(label="Remove Node", command=lambda: self.remove_node(node_name))
        
        context_menu.tk_popup(event.x_root, event.y_root)
    
    def ping_single_node(self, node_name):
        try:
            if self.agent_manager.ping_node(node_name):
                messagebox.showinfo("Success", f"Node '{node_name}' is online")
            else:
                messagebox.showwarning("Warning", f"Node '{node_name}' is offline")
            self.refresh_nodes()
        except Exception as e:
            logger.error(f"Error pinging node: {e}")
            messagebox.showerror("Error", f"Failed to ping node: {str(e)}")
    
    def view_node_servers(self, node_name):
        try:
            servers = self.agent_manager.get_node_servers(node_name)
            
            info_dialog = tk.Toplevel(self.dialog)
            info_dialog.title(f"Servers on {node_name}")
            info_dialog.geometry("500x300")
            info_dialog.transient(self.dialog)
            
            frame = ttk.Frame(info_dialog, padding=10)
            frame.pack(fill=tk.BOTH, expand=True)
            
            if not servers:
                ttk.Label(frame, text="No servers found on this node").pack()
            else:
                tree = ttk.Treeview(frame, columns=("status", "type"), show="tree headings")
                tree.heading("#0", text="Server Name")
                tree.heading("status", text="Status")
                tree.heading("type", text="Type")
                
                for server in servers:
                    tree.insert("", tk.END, text=server.get('name', 'Unknown'), values=(
                        server.get('status', 'Unknown'),
                        server.get('type', 'Unknown')
                    ))
                
                tree.pack(fill=tk.BOTH, expand=True)
            
            ttk.Button(frame, text="Close", command=info_dialog.destroy).pack(pady=(10, 0))
            
        except Exception as e:
            logger.error(f"Error viewing node servers: {e}")
            messagebox.showerror("Error", f"Failed to view node servers: {str(e)}")
    
    def remove_node(self, node_name):
        try:
            if messagebox.askyesno("Confirm", f"Remove node '{node_name}' from cluster?"):
                if self.agent_manager.remove_node(node_name):
                    self.refresh_nodes()
                    messagebox.showinfo("Success", f"Node '{node_name}' removed from cluster")
                else:
                    messagebox.showerror("Error", f"Failed to remove node '{node_name}'")
        except Exception as e:
            logger.error(f"Error removing node: {e}")
            messagebox.showerror("Error", f"Failed to remove node: {str(e)}")
    
    def center_dialog(self):
        if self.dialog:
            self.dialog.update_idletasks()
            x = self.parent.winfo_rootx() + (self.parent.winfo_width() - self.dialog.winfo_width()) // 2
            y = self.parent.winfo_rooty() + (self.parent.winfo_height() - self.dialog.winfo_height()) // 2
            self.dialog.geometry(f"+{x}+{y}")
