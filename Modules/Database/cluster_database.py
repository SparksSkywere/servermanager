import sqlite3
import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.server_logging import get_component_logger

logger = get_component_logger("ClusterDatabase")

class ClusterDatabase:
    """Database manager for cluster information"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Try to get the server manager directory from registry first
            try:
                import winreg
                from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
                key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
                try:
                    # Try multiple possible registry keys
                    server_manager_dir = None
                    for key_name in ["ServerManagerDirectory", "InstallPath", "Directory"]:
                        try:
                            server_manager_dir = winreg.QueryValueEx(key, key_name)[0]
                            logger.info(f"Found {key_name} in registry: {server_manager_dir}")
                            break
                        except:
                            continue
                    
                    if server_manager_dir:
                        db_dir = os.path.join(server_manager_dir, 'db')
                        logger.info(f"Using registry-configured database directory: {db_dir}")
                    else:
                        # Check if production path exists as fallback
                        production_path = r"C:\SteamCMD\Servermanager"
                        if os.path.exists(production_path):
                            db_dir = os.path.join(production_path, 'db')
                            logger.info(f"Using detected production path: {db_dir}")
                        else:
                            # Fallback to relative path
                            db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'db')
                            logger.info(f"No registry keys found, using relative path: {db_dir}")
                    
                except Exception as inner_e:
                    # Check if production path exists as fallback
                    production_path = r"C:\SteamCMD\Servermanager"
                    if os.path.exists(production_path):
                        db_dir = os.path.join(production_path, 'db')
                        logger.info(f"Registry keys not found, using detected production path: {db_dir}")
                    else:
                        # Fallback to relative path
                        db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'db')
                        logger.info(f"Registry keys not found, using relative path: {db_dir}")
                        
                winreg.CloseKey(key)
            except Exception as e:
                # Check if production path exists as fallback
                production_path = r"C:\SteamCMD\Servermanager"
                if os.path.exists(production_path):
                    db_dir = os.path.join(production_path, 'db')
                    logger.warning(f"Registry access failed, using detected production path: {db_dir} - Error: {e}")
                else:
                    # Fallback to relative path
                    db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'db')
                    logger.warning(f"Registry access failed, using relative path: {db_dir} - Error: {e}")
            
            os.makedirs(db_dir, exist_ok=True)
            self.db_path = os.path.join(db_dir, 'servermanager.db')
        else:
            self.db_path = db_path
            
        logger.info(f"ClusterDatabase initialized with path: {self.db_path}")
        self.init_database()
    
    def init_database(self):
        """Initialize the cluster database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Cluster configuration table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cluster_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        host_type TEXT NOT NULL DEFAULT 'Host',
                        cluster_name TEXT,
                        cluster_secret TEXT,
                        master_ip TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Cluster nodes table  
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cluster_nodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        ip_address TEXT NOT NULL,
                        port INTEGER DEFAULT 8080,
                        node_type TEXT DEFAULT 'node',
                        status TEXT DEFAULT 'unknown',
                        last_ping DATETIME,
                        cluster_token TEXT,
                        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Cluster authentication tokens table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cluster_tokens (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_hash TEXT NOT NULL UNIQUE,
                        node_name TEXT,
                        node_ip TEXT,
                        expires_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        revoked INTEGER DEFAULT 0
                    )
                ''')
                
                # Cluster communication log
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cluster_communication_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_ip TEXT NOT NULL,
                        target_ip TEXT,
                        action TEXT NOT NULL,
                        status TEXT DEFAULT 'success',
                        message TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Pending cluster approval requests
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pending_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_name TEXT NOT NULL,
                        ip_address TEXT NOT NULL,
                        port INTEGER DEFAULT 8080,
                        machine_name TEXT,
                        os_info TEXT,
                        request_data TEXT,
                        status TEXT DEFAULT 'pending',
                        requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        approved_by TEXT,
                        approved_at DATETIME,
                        approval_token TEXT
                    )
                ''')
                
                # Host status tracking for halt/resume functionality
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS host_status (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        status TEXT NOT NULL DEFAULT 'online',
                        last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
                        dashboard_active INTEGER DEFAULT 1,
                        maintenance_mode INTEGER DEFAULT 0,
                        status_message TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.commit()
                logger.info(f"Cluster database initialized at: {self.db_path}")
                
        except Exception as e:
            logger.error(f"Failed to initialize cluster database: {e}")
            raise
    
    def get_cluster_config(self) -> Optional[Dict]:
        """Get current cluster configuration"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT host_type, cluster_name, cluster_secret, master_ip, 
                           created_at, updated_at
                    FROM cluster_config ORDER BY id DESC LIMIT 1
                ''')
                
                row = cursor.fetchone()
                if row:
                    return {
                        'host_type': row[0],
                        'cluster_name': row[1],
                        'cluster_secret': row[2],
                        'master_ip': row[3],
                        'created_at': row[4],
                        'updated_at': row[5]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get cluster config: {e}")
            return None
    
    def set_cluster_config(self, host_type: str = 'Host', cluster_name: Optional[str] = None,
                          cluster_secret: Optional[str] = None, master_ip: Optional[str] = None) -> bool:
        """Set cluster configuration"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Clear existing config and insert new one
                cursor.execute('DELETE FROM cluster_config')
                cursor.execute('''
                    INSERT INTO cluster_config 
                    (host_type, cluster_name, cluster_secret, master_ip, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (host_type, cluster_name, cluster_secret, master_ip, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Cluster config updated: type={host_type}, master_ip={master_ip}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to set cluster config: {e}")
            return False
    
    def add_cluster_node(self, name: str, ip_address: str, port: int = 8080, 
                        node_type: str = 'node', cluster_token: Optional[str] = None) -> bool:
        """Add a new cluster node"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO cluster_nodes 
                    (name, ip_address, port, node_type, cluster_token, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (name, ip_address, port, node_type, cluster_token, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Added cluster node: {name} at {ip_address}:{port}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add cluster node {name}: {e}")
            return False
    
    def remove_cluster_node(self, name: str) -> bool:
        """Remove a cluster node"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cluster_nodes WHERE name = ?', (name,))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Removed cluster node: {name}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to remove cluster node {name}: {e}")
            return False
    
    def get_cluster_node(self, name: str) -> Optional[Dict]:
        """Get a specific cluster node"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name, ip_address, port, node_type, status, last_ping, 
                           cluster_token, added_at, updated_at
                    FROM cluster_nodes WHERE name = ?
                ''', (name,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'name': row[0],
                        'ip_address': row[1],
                        'port': row[2],
                        'node_type': row[3],
                        'status': row[4],
                        'last_ping': row[5],
                        'cluster_token': row[6],
                        'added_at': row[7],
                        'updated_at': row[8]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get cluster node {name}: {e}")
            return None
    
    def get_all_cluster_nodes(self) -> List[Dict]:
        """Get all cluster nodes"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name, ip_address, port, node_type, status, last_ping, 
                           cluster_token, added_at, updated_at
                    FROM cluster_nodes ORDER BY name
                ''')
                
                nodes = []
                for row in cursor.fetchall():
                    nodes.append({
                        'name': row[0],
                        'ip_address': row[1],
                        'port': row[2],
                        'node_type': row[3],
                        'status': row[4],
                        'last_ping': row[5],
                        'cluster_token': row[6],
                        'added_at': row[7],
                        'updated_at': row[8]
                    })
                
                return nodes
                
        except Exception as e:
            logger.error(f"Failed to get cluster nodes: {e}")
            return []
    
    def update_node_status(self, name: str, status: str, last_ping: Optional[datetime] = None) -> bool:
        """Update node status and ping time"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                ping_time = last_ping or datetime.now()
                
                cursor.execute('''
                    UPDATE cluster_nodes 
                    SET status = ?, last_ping = ?, updated_at = ?
                    WHERE name = ?
                ''', (status, ping_time.isoformat(), datetime.now().isoformat(), name))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to update node status for {name}: {e}")
            return False
    
    def add_cluster_token(self, token_hash: str, node_name: Optional[str] = None, 
                         node_ip: Optional[str] = None, expires_at: Optional[datetime] = None) -> bool:
        """Add a cluster authentication token"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO cluster_tokens 
                    (token_hash, node_name, node_ip, expires_at)
                    VALUES (?, ?, ?, ?)
                ''', (token_hash, node_name, node_ip, 
                      expires_at.isoformat() if expires_at else None))
                
                conn.commit()
                logger.info(f"Added cluster token for node: {node_name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add cluster token: {e}")
            return False
    
    def revoke_cluster_token(self, token_hash: str) -> bool:
        """Revoke a cluster token"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE cluster_tokens 
                    SET revoked = 1 
                    WHERE token_hash = ?
                ''', (token_hash,))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info("Cluster token revoked")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to revoke cluster token: {e}")
            return False
    
    def validate_cluster_token(self, token_hash: str) -> bool:
        """Validate a cluster token"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM cluster_tokens 
                    WHERE token_hash = ? AND revoked = 0 
                    AND (expires_at IS NULL OR expires_at > ?)
                ''', (token_hash, datetime.now().isoformat()))
                
                return cursor.fetchone() is not None
                
        except Exception as e:
            logger.error(f"Failed to validate cluster token: {e}")
            return False
    
    def log_cluster_communication(self, source_ip: str, target_ip: Optional[str] = None, 
                                 action: str = '', status: str = 'success', 
                                 message: Optional[str] = None) -> bool:
        """Log cluster communication events"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO cluster_communication_log 
                    (source_ip, target_ip, action, status, message)
                    VALUES (?, ?, ?, ?, ?)
                ''', (source_ip, target_ip, action, status, message))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to log cluster communication: {e}")
            return False
    
    def get_cluster_communication_log(self, limit: int = 100) -> List[Dict]:
        """Get recent cluster communication log entries"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT source_ip, target_ip, action, status, message, timestamp
                    FROM cluster_communication_log 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,))
                
                logs = []
                for row in cursor.fetchall():
                    logs.append({
                        'source_ip': row[0],
                        'target_ip': row[1],
                        'action': row[2],
                        'status': row[3],
                        'message': row[4],
                        'timestamp': row[5]
                    })
                
                return logs
                
        except Exception as e:
            logger.error(f"Failed to get cluster communication log: {e}")
            return []
    
    def migrate_from_json(self, json_file_path: str) -> bool:
        """Migrate existing JSON cluster data to database"""
        try:
            if not os.path.exists(json_file_path):
                logger.info("No JSON file to migrate from")
                return True
                
            with open(json_file_path, 'r') as f:
                data = json.load(f)
            
            # Migrate nodes
            nodes = data.get('nodes', [])
            for node_data in nodes:
                name = node_data.get('name', '')
                ip = node_data.get('ip', '')
                if name and ip:
                    self.add_cluster_node(name, ip)
            
            logger.info(f"Migrated {len(nodes)} nodes from JSON to database")
            
            # Backup and remove JSON file
            backup_path = json_file_path + '.backup'
            if os.path.exists(json_file_path):
                os.rename(json_file_path, backup_path)
                logger.info(f"JSON file backed up to: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate from JSON: {e}")
            return False
    
    def cleanup_old_tokens(self, days: int = 30) -> bool:
        """Clean up expired and old revoked tokens"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cutoff_date = datetime.now()
                cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
                
                cursor.execute('''
                    DELETE FROM cluster_tokens 
                    WHERE (revoked = 1 AND created_at < ?) 
                    OR (expires_at IS NOT NULL AND expires_at < ?)
                ''', (cutoff_date.isoformat(), datetime.now().isoformat()))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old cluster tokens")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to cleanup old tokens: {e}")
            return False
    
    # === Pending Request Management ===
    
    def add_pending_request(self, node_name: str, ip_address: str, port: int = 8080, 
                           machine_name: Optional[str] = None, os_info: Optional[str] = None,
                           request_data: Optional[str] = None) -> Optional[int]:
        """Add a pending cluster join request"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO pending_requests 
                    (node_name, ip_address, port, machine_name, os_info, request_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (node_name, ip_address, port, machine_name, os_info, request_data))
                
                request_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Added pending request from {node_name} ({ip_address})")
                return request_id
                
        except Exception as e:
            logger.error(f"Failed to add pending request: {e}")
            return None
    
    def get_pending_requests(self) -> List[Dict]:
        """Get all pending cluster join requests"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, node_name, ip_address, port, machine_name, os_info, 
                           request_data, status, requested_at, approved_by, approved_at, approval_token
                    FROM pending_requests 
                    WHERE status = 'pending'
                    ORDER BY requested_at ASC
                ''')
                
                requests = []
                for row in cursor.fetchall():
                    requests.append({
                        'id': row[0],
                        'node_name': row[1],
                        'ip_address': row[2],
                        'port': row[3],
                        'machine_name': row[4],
                        'os_info': row[5],
                        'request_data': row[6],
                        'status': row[7],
                        'requested_at': row[8],
                        'approved_by': row[9],
                        'approved_at': row[10],
                        'approval_token': row[11]
                    })
                
                return requests
                
        except Exception as e:
            logger.error(f"Failed to get pending requests: {e}")
            return []
    
    def approve_request(self, request_id: int, approved_by: str, approval_token: str) -> bool:
        """Approve a pending cluster join request"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE pending_requests 
                    SET status = 'approved', approved_by = ?, approved_at = ?, approval_token = ?
                    WHERE id = ? AND status = 'pending'
                ''', (approved_by, datetime.now().isoformat(), approval_token, request_id))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Approved cluster request ID: {request_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to approve request {request_id}: {e}")
            return False
    
    def reject_request(self, request_id: int, rejected_by: str) -> bool:
        """Reject a pending cluster join request"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE pending_requests 
                    SET status = 'rejected', approved_by = ?, approved_at = ?
                    WHERE id = ? AND status = 'pending'
                ''', (rejected_by, datetime.now().isoformat(), request_id))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Rejected cluster request ID: {request_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to reject request {request_id}: {e}")
            return False
    
    def get_request_by_id(self, request_id: int) -> Optional[Dict]:
        """Get a specific pending request by ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, node_name, ip_address, port, machine_name, os_info, 
                           request_data, status, requested_at, approved_by, approved_at, approval_token
                    FROM pending_requests WHERE id = ?
                ''', (request_id,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'node_name': row[1],
                        'ip_address': row[2],
                        'port': row[3],
                        'machine_name': row[4],
                        'os_info': row[5],
                        'request_data': row[6],
                        'status': row[7],
                        'requested_at': row[8],
                        'approved_by': row[9],
                        'approved_at': row[10],
                        'approval_token': row[11]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get request {request_id}: {e}")
            return None
    
    def cleanup_old_requests(self, days: int = 7) -> bool:
        """Clean up old approved/rejected requests"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cutoff_date = datetime.now()
                cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
                
                cursor.execute('''
                    DELETE FROM pending_requests 
                    WHERE status IN ('approved', 'rejected') AND approved_at < ?
                ''', (cutoff_date.isoformat(),))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old cluster requests")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to cleanup old requests: {e}")
            return False
    
    # === Host Status Management ===
    
    def update_host_status(self, status: str = 'online', dashboard_active: bool = True, 
                          maintenance_mode: bool = False, status_message: Optional[str] = None) -> bool:
        """Update host status for halt/resume functionality"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Clear existing status and insert new one
                cursor.execute('DELETE FROM host_status')
                cursor.execute('''
                    INSERT INTO host_status 
                    (status, last_heartbeat, dashboard_active, maintenance_mode, status_message, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (status, datetime.now().isoformat(), 1 if dashboard_active else 0,
                      1 if maintenance_mode else 0, status_message, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Host status updated: {status}, dashboard_active={dashboard_active}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update host status: {e}")
            return False
    
    def get_host_status(self) -> Optional[Dict]:
        """Get current host status"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT status, last_heartbeat, dashboard_active, maintenance_mode, 
                           status_message, updated_at
                    FROM host_status ORDER BY id DESC LIMIT 1
                ''')
                
                row = cursor.fetchone()
                if row:
                    return {
                        'status': row[0],
                        'last_heartbeat': row[1],
                        'dashboard_active': bool(row[2]),
                        'maintenance_mode': bool(row[3]),
                        'status_message': row[4],
                        'updated_at': row[5]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get host status: {e}")
            return None
    
    def heartbeat(self) -> bool:
        """Update heartbeat timestamp to show host is alive"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE host_status 
                    SET last_heartbeat = ?, updated_at = ?
                    WHERE id = (SELECT MAX(id) FROM host_status)
                ''', (datetime.now().isoformat(), datetime.now().isoformat()))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    return True
                else:
                    # No status record exists, create one
                    self.update_host_status()
                    return True
                
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {e}")
            return False
