# Cluster database
import sqlite3
import os
import sys
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path, get_server_manager_dir, get_database_connection
setup_module_path()
from Modules.server_logging import get_component_logger

logger: logging.Logger = get_component_logger("ClusterDatabase")

# Singleton instance and lock
_cluster_db_instance = None
_cluster_db_lock = threading.Lock()


def get_cluster_database(db_path: Optional[str] = None) -> 'ClusterDatabase':
    # Singleton ClusterDatabase access
    global _cluster_db_instance
    with _cluster_db_lock:
        if _cluster_db_instance is None:
            _cluster_db_instance = ClusterDatabase(db_path, _singleton=True)
        return _cluster_db_instance


class ClusterDatabase:
    # DB manager for cluster info
    # - Use get_cluster_database() for singleton access
    
    def __init__(self, db_path: Optional[str] = None, _singleton: bool = False):
        if not _singleton:
            logger.debug("Use get_cluster_database() for singleton access")
        
        if db_path is None:
            # Auto-discover DB path from registry
            server_manager_dir = get_server_manager_dir()
            db_dir = os.path.join(server_manager_dir, 'db')
            logger.debug(f"Using registry DB dir: {db_dir}")
            
            os.makedirs(db_dir, exist_ok=True)
            self.db_path = os.path.join(db_dir, 'servermanager.db')
        else:
            self.db_path = db_path
            
        logger.debug(f"ClusterDatabase initialised with path: {self.db_path}")
        self.init_database()
    
    def init_database(self):
        # Initialise comprehensive cluster database schema with all required tables
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Core cluster configuration
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
                        hostname TEXT,
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
                
                # Server categories for organization
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS server_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        display_order INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Dashboard configuration settings
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS dashboard_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        config_key TEXT NOT NULL UNIQUE,
                        config_value TEXT,
                        config_type TEXT DEFAULT 'string',
                        category TEXT DEFAULT 'general',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Update configuration settings
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS update_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        config_key TEXT NOT NULL UNIQUE,
                        config_value TEXT,
                        config_type TEXT DEFAULT 'json',
                        category TEXT DEFAULT 'schedules',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Main configuration settings
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS main_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        config_key TEXT NOT NULL UNIQUE,
                        config_value TEXT,
                        config_type TEXT DEFAULT 'string',
                        category TEXT DEFAULT 'system',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Steam credentials storage (encrypted)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS steam_credentials (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        profile_name TEXT NOT NULL UNIQUE DEFAULT 'default',
                        username TEXT,
                        password_encrypted TEXT,
                        steam_guard_secret TEXT,
                        use_anonymous INTEGER DEFAULT 0,
                        is_default INTEGER DEFAULT 1,
                        last_used DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Insert default "Uncategorized" category if it doesn't exist
                cursor.execute('''
                    INSERT OR IGNORE INTO server_categories (name, display_order)
                    VALUES ('Uncategorized', 0)
                ''')
                
                conn.commit()
                logger.debug(f"Cluster database schema ready at: {self.db_path}")
                
                # Run migrations for existing databases
                self._run_migrations(conn)
                
        except Exception as e:
            logger.error(f"Failed to initialise cluster database: {e}")
            raise
    
    def _run_migrations(self, conn):
        # Run database migrations for existing databases
        cursor = conn.cursor()
        
        # Migration: Add hostname column to cluster_nodes if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(cluster_nodes)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'hostname' not in columns:
                cursor.execute("ALTER TABLE cluster_nodes ADD COLUMN hostname TEXT")
                conn.commit()
                logger.info("Migration: Added hostname column to cluster_nodes table")
        except Exception as e:
            logger.warning(f"Migration warning (hostname column): {e}")
    
    def _get_connection(self):
        # Centralized database connection for this instance
        return get_database_connection(self.db_path)
    
    def get_cluster_config(self) -> Optional[Dict]:
        # Get current cluster configuration
        try:
            with self._get_connection() as conn:
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
        # Set cluster configuration
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
                        node_type: str = 'node', cluster_token: Optional[str] = None,
                        hostname: Optional[str] = None) -> bool:
        # Add a new cluster node
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO cluster_nodes 
                    (name, ip_address, hostname, port, node_type, cluster_token, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (name, ip_address, hostname or name, port, node_type, cluster_token, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Added cluster node: {name} ({hostname}) at {ip_address}:{port}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add cluster node {name}: {e}")
            return False
    
    def remove_cluster_node(self, name: str) -> bool:
        # Remove a cluster node
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
        # Get a specific cluster node
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name, ip_address, hostname, port, node_type, status, last_ping, 
                           cluster_token, added_at, updated_at
                    FROM cluster_nodes WHERE name = ?
                ''', (name,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'name': row[0],
                        'ip_address': row[1],
                        'hostname': row[2] or row[0],
                        'port': row[3],
                        'node_type': row[4],
                        'status': row[5],
                        'last_ping': row[6],
                        'cluster_token': row[7],
                        'added_at': row[8],
                        'updated_at': row[9]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get cluster node {name}: {e}")
            return None
    
    def get_all_cluster_nodes(self) -> List[Dict]:
        # Get all cluster nodes
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name, ip_address, hostname, port, node_type, status, last_ping, 
                           cluster_token, added_at, updated_at
                    FROM cluster_nodes ORDER BY name
                ''')
                
                nodes = []
                for row in cursor.fetchall():
                    nodes.append({
                        'name': row[0],
                        'ip_address': row[1],
                        'hostname': row[2] or row[0],
                        'port': row[3],
                        'node_type': row[4],
                        'status': row[5],
                        'last_ping': row[6],
                        'cluster_token': row[7],
                        'added_at': row[8],
                        'updated_at': row[9]
                    })
                
                return nodes
                
        except Exception as e:
            logger.error(f"Failed to get cluster nodes: {e}")
            return []
    
    def update_node_status(self, name: str, status: str, last_ping: Optional[datetime] = None) -> bool:
        # Update node status and ping time
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
        # Add a cluster authentication token
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
        # Revoke a cluster token
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
        # Validate cluster token - checks if active and not expired
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
        # Log cluster communication events
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
        # Get recent cluster communication log entries
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
        # Migrate legacy JSON cluster data to SQLite database with backup
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
        # Clean up expired and old revoked tokens
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Calculate cutoff date for cleanup
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
        # Add a pending cluster join request
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
        # Get all pending cluster join requests
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
        # Approve a pending cluster join request
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
        # Reject a pending cluster join request
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
        # Get a specific pending request by ID
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
        # Clean up old approved/rejected requests
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
        # Update host status for halt/resume functionality
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
                logger.debug(f"Host status updated: {status}, dashboard_active={dashboard_active}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update host status: {e}")
            return False
    
    def get_host_status(self) -> Optional[Dict]:
        # Get current host status
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
        # Update heartbeat timestamp to show host is alive
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
                    # Initialise status record if none exists
                    self.update_host_status()
                    return True
                
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {e}")
            return False
    
    # Category management methods
    def get_categories(self) -> List[str]:
        # Get all categories ordered by display_order, then by name
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT name FROM server_categories 
                    ORDER BY display_order ASC, name ASC
                ''')
                categories = [row[0] for row in cursor.fetchall()]
                return categories
                
        except Exception as e:
            logger.error(f"Failed to get categories: {e}")
            return ["Uncategorized"]
    
    def add_category(self, name: str, display_order: int = 0) -> bool:
        # Add a new category
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO server_categories (name, display_order, updated_at)
                    VALUES (?, ?, ?)
                ''', (name, display_order, datetime.now().isoformat()))
                conn.commit()
                logger.info(f"Added category: {name}")
                return True
                
        except sqlite3.IntegrityError:
            logger.warning(f"Category '{name}' already exists")
            return False
        except Exception as e:
            logger.error(f"Failed to add category '{name}': {e}")
            return False
    
    def rename_category(self, old_name: str, new_name: str) -> bool:
        # Rename a category
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE server_categories 
                    SET name = ?, updated_at = ?
                    WHERE name = ?
                ''', (new_name, datetime.now().isoformat(), old_name))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Renamed category from '{old_name}' to '{new_name}'")
                    return True
                else:
                    logger.warning(f"Category '{old_name}' not found")
                    return False
                
        except sqlite3.IntegrityError:
            logger.warning(f"Category '{new_name}' already exists")
            return False
        except Exception as e:
            logger.error(f"Failed to rename category '{old_name}' to '{new_name}': {e}")
            return False
    
    def delete_category(self, name: str) -> bool:
        # Delete a category (don't allow deleting "Uncategorized")
        if name == "Uncategorized":
            logger.warning("Cannot delete 'Uncategorized' category")
            return False
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM server_categories WHERE name = ?', (name,))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.info(f"Deleted category: {name}")
                    return True
                else:
                    logger.warning(f"Category '{name}' not found")
                    return False
                
        except Exception as e:
            logger.error(f"Failed to delete category '{name}': {e}")
            return False
    
    def reorder_categories(self, category_order: List[str]) -> bool:
        # Update display order for all categories
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for i, category_name in enumerate(category_order):
                    cursor.execute('''
                        UPDATE server_categories 
                        SET display_order = ?, updated_at = ?
                        WHERE name = ?
                    ''', (i, datetime.now().isoformat(), category_name))
                conn.commit()
                logger.info(f"Reordered categories: {category_order}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to reorder categories: {e}")
            return False
    
    # ===== CONFIGURATION MANAGEMENT METHODS =====
    
    def get_dashboard_config(self) -> Dict:
        # Get all dashboard configuration settings
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT config_key, config_value, config_type FROM dashboard_config')
                rows = cursor.fetchall()
                
                config = {}
                for key, value, config_type in rows:
                    if config_type == 'json' and value:
                        try:
                            config[key] = json.loads(value)
                        except json.JSONDecodeError:
                            config[key] = value
                    elif config_type == 'boolean':
                        config[key] = value.lower() in ('true', '1', 'yes')
                    elif config_type == 'integer' and value:
                        try:
                            config[key] = int(value)
                        except ValueError:
                            config[key] = value
                    else:
                        config[key] = value
                
                logger.debug(f"Retrieved {len(config)} dashboard config settings")
                return config
                
        except Exception as e:
            logger.error(f"Failed to get dashboard config: {e}")
            return {}
    
    def set_dashboard_config(self, key: str, value, config_type: str = 'string', category: str = 'general') -> bool:
        # Set a dashboard configuration value
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert value based on type
                if config_type == 'json':
                    value_str = json.dumps(value) if value is not None else None
                elif config_type == 'boolean':
                    value_str = 'true' if value else 'false'
                else:
                    value_str = str(value) if value is not None else None
                
                cursor.execute('''
                    INSERT OR REPLACE INTO dashboard_config 
                    (config_key, config_value, config_type, category, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (key, value_str, config_type, category, datetime.now().isoformat()))
                
                conn.commit()
                logger.debug(f"Set dashboard config {key} = {value}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to set dashboard config {key}: {e}")
            return False
    
    def migrate_dashboard_config_from_json(self, json_file_path: str) -> bool:
        # Migrate dashboard config from JSON file to database
        try:
            if not os.path.exists(json_file_path):
                logger.info(f"No JSON file to migrate from: {json_file_path}")
                return True
            
            with open(json_file_path, 'r') as f:
                config_data = json.load(f)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Flatten nested config structure
                def flatten_config(data, prefix=''):
                    items = []
                    for key, value in data.items():
                        full_key = f"{prefix}.{key}" if prefix else key
                        if isinstance(value, dict):
                            items.extend(flatten_config(value, full_key))
                        else:
                            config_type = 'boolean' if isinstance(value, bool) else 'integer' if isinstance(value, int) else 'string'
                            items.append((full_key, value, config_type, 'migrated'))
                    return items
                
                config_items = flatten_config(config_data)
                
                for key, value, config_type, category in config_items:
                    if config_type == 'boolean':
                        value_str = 'true' if value else 'false'
                    else:
                        value_str = str(value)
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO dashboard_config 
                        (config_key, config_value, config_type, category, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (key, value_str, config_type, category, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Migrated {len(config_items)} dashboard config items from JSON")
                return True
                
        except Exception as e:
            logger.error(f"Failed to migrate dashboard config from JSON: {e}")
            return False
    
    def get_update_config(self) -> Dict:
        # Get all update configuration settings
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT config_key, config_value, config_type FROM update_config')
                rows = cursor.fetchall()
                
                config = {}
                for key, value, config_type in rows:
                    if config_type == 'json' and value:
                        try:
                            config[key] = json.loads(value)
                        except json.JSONDecodeError:
                            config[key] = value
                    else:
                        config[key] = value
                
                logger.debug(f"Retrieved {len(config)} update config settings")
                return config
                
        except Exception as e:
            logger.error(f"Failed to get update config: {e}")
            return {}
    
    def set_update_config(self, key: str, value, config_type: str = 'json', category: str = 'schedules') -> bool:
        # Set an update configuration value
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert value based on type
                if config_type == 'json':
                    value_str = json.dumps(value) if value is not None else None
                else:
                    value_str = str(value) if value is not None else None
                
                cursor.execute('''
                    INSERT OR REPLACE INTO update_config 
                    (config_key, config_value, config_type, category, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (key, value_str, config_type, category, datetime.now().isoformat()))
                
                conn.commit()
                logger.debug(f"Set update config {key} = {value}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to set update config {key}: {e}")
            return False
    
    def migrate_update_config_from_json(self, json_file_path: str) -> bool:
        # Migrate update config from JSON file to database
        try:
            if not os.path.exists(json_file_path):
                logger.info(f"No JSON file to migrate from: {json_file_path}")
                return True
            
            with open(json_file_path, 'r') as f:
                config_data = json.load(f)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Store the entire config as JSON for complex structures
                cursor.execute('''
                    INSERT OR REPLACE INTO update_config 
                    (config_key, config_value, config_type, category, updated_at)
                    VALUES (?, ?, 'json', 'migrated', ?)
                ''', ('full_config', json.dumps(config_data), datetime.now().isoformat()))
                
                conn.commit()
                logger.info("Migrated update config from JSON")
                return True
                
        except Exception as e:
            logger.error(f"Failed to migrate update config from JSON: {e}")
            return False
    
    def get_main_config(self) -> Dict:
        # Get all main configuration settings
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT config_key, config_value, config_type FROM main_config')
                rows = cursor.fetchall()
                
                config = {}
                for key, value, config_type in rows:
                    if config_type == 'json' and value:
                        try:
                            config[key] = json.loads(value)
                        except json.JSONDecodeError:
                            config[key] = value
                    elif config_type == 'boolean':
                        config[key] = value.lower() in ('true', '1', 'yes')
                    elif config_type == 'integer' and value:
                        try:
                            config[key] = int(value)
                        except ValueError:
                            config[key] = value
                    else:
                        config[key] = value
                
                logger.debug(f"Retrieved {len(config)} main config settings")
                return config
                
        except Exception as e:
            logger.error(f"Failed to get main config: {e}")
            return {}
    
    def set_main_config(self, key: str, value, config_type: str = 'string', category: str = 'system') -> bool:
        # Set a main configuration value
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert value based on type
                if config_type == 'json':
                    value_str = json.dumps(value) if value is not None else None
                elif config_type == 'boolean':
                    value_str = 'true' if value else 'false'
                else:
                    value_str = str(value) if value is not None else None
                
                cursor.execute('''
                    INSERT OR REPLACE INTO main_config 
                    (config_key, config_value, config_type, category, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (key, value_str, config_type, category, datetime.now().isoformat()))
                
                conn.commit()
                logger.debug(f"Set main config {key} = {value}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to set main config {key}: {e}")
            return False
    
    def migrate_main_config_from_json(self, json_file_path: str) -> bool:
        # Migrate main config from JSON file to database
        try:
            if not os.path.exists(json_file_path):
                logger.info(f"No JSON file to migrate from: {json_file_path}")
                return True
            
            with open(json_file_path, 'r') as f:
                config_data = json.load(f)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Flatten nested config structure
                def flatten_config(data, prefix=''):
                    items = []
                    for key, value in data.items():
                        full_key = f"{prefix}.{key}" if prefix else key
                        if isinstance(value, dict):
                            items.extend(flatten_config(value, full_key))
                        else:
                            config_type = 'boolean' if isinstance(value, bool) else 'integer' if isinstance(value, int) else 'string'
                            items.append((full_key, value, config_type, 'migrated'))
                    return items
                
                config_items = flatten_config(config_data)
                
                for key, value, config_type, category in config_items:
                    if config_type == 'boolean':
                        value_str = 'true' if value else 'false'
                    else:
                        value_str = str(value)
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO main_config 
                        (config_key, config_value, config_type, category, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (key, value_str, config_type, category, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Migrated {len(config_items)} main config items from JSON")
                return True
                
        except Exception as e:
            logger.error(f"Failed to migrate main config from JSON: {e}")
            return False

    # Steam credentials management methods
    def _encrypt_password(self, password: str) -> str:
        # Simple XOR encryption with machine-specific key for password storage
        # This provides basic obfuscation - for production, consider using keyring
        import base64
        import hashlib
        import socket
        
        # Create machine-specific key from hostname and a salt
        machine_key = hashlib.sha256(f"{socket.gethostname()}_steam_creds_salt".encode()).digest()
        
        # XOR encrypt
        encrypted = bytes([b ^ machine_key[i % len(machine_key)] for i, b in enumerate(password.encode('utf-8'))])
        return base64.b64encode(encrypted).decode('ascii')
    
    def _decrypt_password(self, encrypted: str) -> str:
        # Decrypt password encrypted with _encrypt_password
        import base64
        import hashlib
        import socket
        
        if not encrypted:
            return ""
        
        try:
            machine_key = hashlib.sha256(f"{socket.gethostname()}_steam_creds_salt".encode()).digest()
            encrypted_bytes = base64.b64decode(encrypted.encode('ascii'))
            decrypted = bytes([b ^ machine_key[i % len(machine_key)] for i, b in enumerate(encrypted_bytes)])
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to decrypt password: {e}")
            return ""
    
    def save_steam_credentials(self, username: str = "", password: str = "", 
                               steam_guard_secret: str = "", use_anonymous: bool = False,
                               profile_name: str = "default") -> bool:
        # Save Steam credentials to database
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Encrypt password if provided
                encrypted_password = self._encrypt_password(password) if password else ""
                
                # Check if profile exists
                cursor.execute('SELECT id FROM steam_credentials WHERE profile_name = ?', (profile_name,))
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute('''
                        UPDATE steam_credentials 
                        SET username = ?, password_encrypted = ?, steam_guard_secret = ?,
                            use_anonymous = ?, updated_at = ?
                        WHERE profile_name = ?
                    ''', (username, encrypted_password, steam_guard_secret,
                          1 if use_anonymous else 0, datetime.now().isoformat(), profile_name))
                else:
                    cursor.execute('''
                        INSERT INTO steam_credentials 
                        (profile_name, username, password_encrypted, steam_guard_secret, 
                         use_anonymous, is_default, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ''', (profile_name, username, encrypted_password, steam_guard_secret,
                          1 if use_anonymous else 0, datetime.now().isoformat(), 
                          datetime.now().isoformat()))
                
                conn.commit()
                logger.debug(f"Steam credentials saved for profile: {profile_name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save Steam credentials: {e}")
            return False
    
    def get_steam_credentials(self, profile_name: str = "default") -> Optional[Dict]:
        # Get Steam credentials from database
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT username, password_encrypted, steam_guard_secret, use_anonymous, last_used
                    FROM steam_credentials WHERE profile_name = ?
                ''', (profile_name,))
                
                row = cursor.fetchone()
                if row:
                    # Update last_used timestamp
                    cursor.execute('''
                        UPDATE steam_credentials SET last_used = ? WHERE profile_name = ?
                    ''', (datetime.now().isoformat(), profile_name))
                    conn.commit()
                    
                    return {
                        'username': row[0] or "",
                        'password': self._decrypt_password(row[1]) if row[1] else "",
                        'steam_guard_secret': row[2] or "",
                        'use_anonymous': bool(row[3]),
                        'anonymous': bool(row[3]),  # Alias for compatibility
                        'last_used': row[4]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get Steam credentials: {e}")
            return None
    
    def get_all_steam_profiles(self) -> List[Dict]:
        # Get all Steam credential profiles
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT profile_name, username, use_anonymous, is_default, last_used
                    FROM steam_credentials ORDER BY is_default DESC, last_used DESC
                ''')
                
                profiles = []
                for row in cursor.fetchall():
                    profiles.append({
                        'profile_name': row[0],
                        'username': row[1] or "Anonymous",
                        'use_anonymous': bool(row[2]),
                        'is_default': bool(row[3]),
                        'last_used': row[4]
                    })
                return profiles
                
        except Exception as e:
            logger.error(f"Failed to get Steam profiles: {e}")
            return []
    
    def delete_steam_credentials(self, profile_name: str = "default") -> bool:
        # Delete Steam credentials profile
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM steam_credentials WHERE profile_name = ?', (profile_name,))
                conn.commit()
                logger.debug(f"Steam credentials deleted for profile: {profile_name}")
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Failed to delete Steam credentials: {e}")
            return False
    
    def has_steam_credentials(self) -> bool:
        # Check if any Steam credentials are stored
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM steam_credentials')
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.error(f"Failed to check Steam credentials: {e}")
            return False
