# Server configurations database management - Stores server configs in database for better tracking and multi-user access
# pyright: reportArgumentType=false
# pyright: reportAssignmentType=false
# pyright: reportGeneralTypeIssues=false

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional, Any

# Global flag to prevent duplicate logging
_db_initialized = False

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.Database.database_utils import get_engine, get_engine_by_type

from Modules.server_logging import get_component_logger
logger = get_component_logger("ServerConfigsDB")

Base = declarative_base()

class ServerConfig(Base):
    # Server configuration stored in database
    __tablename__ = 'server_configs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    server_type = Column(String(100), default="Unknown")
    app_id = Column(String(50), default="")
    install_dir = Column(Text, default="")
    executable_path = Column(Text, default="")
    startup_args = Column(Text, default="")
    version = Column(String(100), default="")
    mod_loader = Column(String(100), default="")
    category = Column(String(100), default="")

    # Server control settings
    stop_command = Column(String(255), default="")
    save_command = Column(String(255), default="")
    use_config_file = Column(Boolean, default=False)
    config_file_path = Column(Text, default="")
    config_argument = Column(String(255), default="")
    additional_args = Column(Text, default="")
    notes = Column(Text, default="")

    # Scheduled command settings (for shutdown/restart warnings and MOTD)
    # Command to send MOTD/broadcast message, e.g., 'say {message}'
    motd_command = Column(String(512), default="")
    # The MOTD message to broadcast
    motd_message = Column(String(1024), default="")
    # Interval in minutes to send MOTD (0 = disabled)
    motd_interval = Column(Integer, default=0)
    # Command for shutdown/restart warnings, e.g., 'broadcast {message}'
    warning_command = Column(String(512), default="")
    # Minutes before shutdown to warn
    warning_intervals = Column(String(255), default="30,15,10,5,1")
    # Template for warning message
    warning_message_template = Column(String(512), default="Server restarting in {message}")
    # Command to run after server starts
    start_command = Column(String(512), default="")
    # Enable timed restart with warnings
    scheduled_restart_enabled = Column(Boolean, default=False)

    # Minecraft/Java specific
    java_path = Column(Text, default="java")
    ram = Column(Integer, default=1024)
    jvm_args = Column(Text, default="")

    # Status tracking
    auto_start = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    imported = Column(Boolean, default=False)
    last_started = Column(DateTime, nullable=True)
    last_stopped = Column(DateTime, nullable=True)

    # Process info (for running servers)
    process_id = Column(Integer, nullable=True)
    process_create_time = Column(Float, nullable=True)

    # Sync tracking (for cluster mode)
    last_sync = Column(DateTime, nullable=True)
    synced_by = Column(String(255), default="")

    # Logging paths
    log_stdout = Column(Text, default="")
    log_stderr = Column(Text, default="")

    # Corruption tracking
    last_corruption_check = Column(DateTime, nullable=True)
    corruption_recovery_actions = Column(Text, default="[]")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional config as JSON blob (for extensibility)
    extra_config = Column(Text, default="{}")

    # Relationships
    permissions = relationship("ServerPermission", back_populates="server", cascade="all, delete-orphan")

class ServerPermission(Base):
    # User permissions for server access
    __tablename__ = 'server_permissions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey('server_configs.id', ondelete='CASCADE'), nullable=False)
    username = Column(String(255), nullable=False, index=True)

    # Granular permissions
    can_view = Column(Boolean, default=True)
    can_start = Column(Boolean, default=True)
    can_stop = Column(Boolean, default=True)
    can_restart = Column(Boolean, default=True)
    can_console = Column(Boolean, default=True)
    can_edit = Column(Boolean, default=False)

    # Timestamps
    granted_at = Column(DateTime, default=datetime.utcnow)
    granted_by = Column(String(255), nullable=True)

    # Relationship
    server = relationship("ServerConfig", back_populates="permissions")

    # Unique constraint: one permission entry per user per server
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )

def get_server_configs_engine():
    # Get SQLAlchemy engine for server configs database
    return get_engine_by_type("server_configs")

def get_engine_by_type(db_type="server_configs"):
    # Get engine by database type with fallback to default location
    from Modules.common import REGISTRY_PATH, get_server_manager_dir, get_registry_value, get_registry_values

    try:
        sql_type = get_registry_value(REGISTRY_PATH, "SQLType", "SQLite")

        if sql_type.lower() == "sqlite":
            try:
                server_manager_dir = get_server_manager_dir()
                db_path = os.path.join(server_manager_dir, "db", "servermanager_servers.db")
            except Exception:
                db_path = "servermanager_servers.db"

            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types
            sql_conn = get_registry_values(REGISTRY_PATH, ["SQLHost", "SQLPort", "SQLUsername", "SQLPassword"])
            config = {
                "type": sql_type.lower(),
                "host": sql_conn["SQLHost"],
                "port": sql_conn["SQLPort"],
                "database": "server_configs",
                "username": sql_conn["SQLUsername"],
                "password": sql_conn["SQLPassword"]
            }

        return get_engine(config)

    except Exception as e:
        logger.error(f"Failed to get server configs engine: {e}")
        # Return default SQLite engine
        return get_engine({
            "type": "sqlite",
            "db_path": "servermanager_servers.db"
        })

def init_server_configs_db(engine=None):
    # Initialize the server configs database tables
    if engine is None:
        engine = get_server_configs_engine()

    Base.metadata.create_all(engine)
    global _db_initialized
    if not _db_initialized:
        logger.info("Server configs database tables created/verified")
        _db_initialized = True
    return engine

class ServerConfigManager:
    # Manager class for server configurations in database

    def __init__(self, engine=None):
        if engine is None:
            engine = get_server_configs_engine()
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

        # Ensure tables exist
        init_server_configs_db(engine)

    def get_session(self):
        # Get a new database session
        return self.Session()

    def get_all_servers(self) -> List[Dict[str, Any]]:
        # Get all server configurations
        session = self.get_session()
        try:
            servers = session.query(ServerConfig).filter(ServerConfig.is_active == True).all()
            result = []
            for server in servers:
                result.append(self._server_to_dict(server))
            return result
        finally:
            session.close()

    def get_server(self, name: str) -> Optional[Dict[str, Any]]:
        # Get a specific server configuration by name
        session = self.get_session()
        try:
            server = session.query(ServerConfig).filter(ServerConfig.name == name).first()
            if server:
                return self._server_to_dict(server)
            return None
        finally:
            session.close()

    def create_server(self, config: Dict[str, Any], created_by: str = None) -> bool:
        # Create a new server configuration
        session = self.get_session()
        try:
            # Parse corruption recovery actions if it's a list
            corruption_actions = config.get('CorruptionRecoveryActions', [])
            if isinstance(corruption_actions, list):
                corruption_actions = json.dumps(corruption_actions)

            # Parse last corruption check date
            last_corruption_check = None
            if config.get('LastCorruptionCheck'):
                try:
                    last_corruption_check = datetime.fromisoformat(config['LastCorruptionCheck'])
                except (ValueError, TypeError):
                    pass

            # Parse last sync date
            last_sync = None
            if config.get('LastSync'):
                try:
                    last_sync = datetime.fromisoformat(config['LastSync'])
                except (ValueError, TypeError):
                    pass

            # Parse created date
            created_at = datetime.utcnow()
            if config.get('Created'):
                try:
                    created_at = datetime.fromisoformat(config['Created'])
                except (ValueError, TypeError):
                    pass

            # Parse last update date
            updated_at = datetime.utcnow()
            if config.get('LastUpdate'):
                try:
                    updated_at = datetime.fromisoformat(config['LastUpdate'])
                except (ValueError, TypeError):
                    pass

            # Parse AppID - can be string or int
            app_id = config.get('AppID', config.get('appid', config.get('app_id', '')))
            if app_id is not None:
                app_id = str(app_id)
            else:
                app_id = ''

            server = ServerConfig(
                name=config.get('Name', config.get('name', 'Unnamed Server')),
                server_type=config.get('Type', config.get('type', 'Unknown')),
                app_id=app_id,
                install_dir=config.get('InstallDir', config.get('install_dir', '')),
                executable_path=config.get('ExecutablePath', config.get('executable_path', '')),
                startup_args=config.get('StartupArgs', config.get('startup_args', '')),
                version=config.get('Version', config.get('version', '')),
                mod_loader=config.get('ModLoader', config.get('mod_loader', '')),
                category=config.get('Category', config.get('category', 'Uncategorized')) or 'Uncategorized',

                # Server control settings
                stop_command=config.get('StopCommand', config.get('stop_command', '')),
                save_command=config.get('SaveCommand', config.get('save_command', '')),
                use_config_file=config.get('UseConfigFile', config.get('use_config_file', False)),
                config_file_path=config.get('ConfigFilePath', config.get('config_file_path', '')),
                config_argument=config.get('ConfigArgument', config.get('config_argument', '')),
                additional_args=config.get('AdditionalArgs', config.get('additional_args', '')),
                notes=config.get('Notes', config.get('notes', '')),

                # Scheduled command settings
                motd_command=config.get('MotdCommand', config.get('motd_command', '')),
                motd_message=config.get('MotdMessage', config.get('motd_message', '')),
                motd_interval=config.get('MotdInterval', config.get('motd_interval', 0)),
                warning_command=config.get('WarningCommand', config.get('warning_command', '')),
                warning_intervals=config.get('WarningIntervals', config.get('warning_intervals', '30,15,10,5,1')),
                warning_message_template=config.get('WarningMessageTemplate', config.get('warning_message_template', 'Server restarting in {message}')),
                start_command=config.get('StartCommand', config.get('start_command', '')),
                scheduled_restart_enabled=config.get('ScheduledRestartEnabled', config.get('scheduled_restart_enabled', False)),

                # Minecraft/Java specific
                java_path=config.get('JavaPath', config.get('java_path', 'java')),
                ram=config.get('RAM', config.get('ram', 1024)),
                jvm_args=config.get('JVMArgs', config.get('jvm_args', '')),

                # Status tracking
                auto_start=config.get('AutoStart', config.get('auto_start', False)),
                imported=config.get('Imported', config.get('imported', False)),

                # Process info
                process_id=config.get('ProcessId', config.get('PID', config.get('process_id'))),
                process_create_time=config.get('ProcessCreateTime', config.get('process_create_time')),

                # Sync tracking
                last_sync=last_sync,
                synced_by=config.get('SyncedBy', config.get('synced_by', '')),

                # Logging paths
                log_stdout=config.get('LogStdout', config.get('log_stdout', '')),
                log_stderr=config.get('LogStderr', config.get('log_stderr', '')),

                # Corruption tracking
                last_corruption_check=last_corruption_check,
                corruption_recovery_actions=corruption_actions if isinstance(corruption_actions, str) else json.dumps(corruption_actions),

                # Timestamps
                created_at=created_at,
                updated_at=updated_at,

                # Extra config for any remaining fields
                extra_config="{}"
            )

            session.add(server)
            session.commit()

            # Add permissions if provided
            allowed_users = config.get('allowed_users', [])
            user_permissions = config.get('user_permissions', {})

            for username in allowed_users:
                perms = user_permissions.get(username, {})
                self._add_permission(session, server.id, username, perms, created_by)

            session.commit()
            logger.info(f"Created server config: {server.name}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create server config: {e}")
            return False
        finally:
            session.close()

    def update_server(self, name: str, config: Dict[str, Any]) -> bool:
        # Update an existing server configuration
        session = self.get_session()
        try:
            server = session.query(ServerConfig).filter(ServerConfig.name == name).first()
            if not server:
                return False

            # Update basic fields (type: ignore for SQLAlchemy ORM attribute assignment)
            if 'Type' in config or 'type' in config:
                server.server_type = config.get('Type', config.get('type', ''))  # type: ignore[assignment]
            if 'AppID' in config or 'app_id' in config or 'appid' in config:
                app_id = config.get('AppID', config.get('appid', config.get('app_id', '')))
                server.app_id = str(app_id) if app_id else ''  # type: ignore[assignment]
            if 'InstallDir' in config or 'install_dir' in config:
                server.install_dir = config.get('InstallDir', config.get('install_dir', ''))  # type: ignore[assignment]
            if 'ExecutablePath' in config or 'executable_path' in config:
                server.executable_path = config.get('ExecutablePath', config.get('executable_path', ''))  # type: ignore[assignment]
            if 'StartupArgs' in config or 'startup_args' in config:
                server.startup_args = config.get('StartupArgs', config.get('startup_args', ''))  # type: ignore[assignment]
            if 'Version' in config or 'version' in config:
                server.version = config.get('Version', config.get('version', ''))  # type: ignore[assignment]
            if 'ModLoader' in config or 'mod_loader' in config:
                server.mod_loader = config.get('ModLoader', config.get('mod_loader', ''))  # type: ignore[assignment]
            if 'Category' in config or 'category' in config:
                server.category = config.get('Category', config.get('category', ''))  # type: ignore[assignment]
            if 'AutoStart' in config or 'auto_start' in config:
                server.auto_start = config.get('AutoStart', config.get('auto_start', False))  # type: ignore[assignment]

            # Update server control settings
            if 'StopCommand' in config or 'stop_command' in config:
                server.stop_command = config.get('StopCommand', config.get('stop_command', ''))  # type: ignore[assignment]
            if 'SaveCommand' in config or 'save_command' in config:
                server.save_command = config.get('SaveCommand', config.get('save_command', ''))  # type: ignore[assignment]
            if 'UseConfigFile' in config or 'use_config_file' in config:
                server.use_config_file = config.get('UseConfigFile', config.get('use_config_file', False))  # type: ignore[assignment]
            if 'ConfigFilePath' in config or 'config_file_path' in config:
                server.config_file_path = config.get('ConfigFilePath', config.get('config_file_path', ''))  # type: ignore[assignment]
            if 'ConfigArgument' in config or 'config_argument' in config:
                server.config_argument = config.get('ConfigArgument', config.get('config_argument', ''))  # type: ignore[assignment]
            if 'AdditionalArgs' in config or 'additional_args' in config:
                server.additional_args = config.get('AdditionalArgs', config.get('additional_args', ''))  # type: ignore[assignment]
            if 'Notes' in config or 'notes' in config:
                server.notes = config.get('Notes', config.get('notes', ''))  # type: ignore[assignment]

            # Update scheduled command settings
            if 'MotdCommand' in config or 'motd_command' in config:
                server.motd_command = config.get('MotdCommand', config.get('motd_command', ''))  # type: ignore[assignment]
            if 'MotdMessage' in config or 'motd_message' in config:
                server.motd_message = config.get('MotdMessage', config.get('motd_message', ''))  # type: ignore[assignment]
            if 'MotdInterval' in config or 'motd_interval' in config:
                server.motd_interval = config.get('MotdInterval', config.get('motd_interval', 0))  # type: ignore[assignment]
            if 'WarningCommand' in config or 'warning_command' in config:
                server.warning_command = config.get('WarningCommand', config.get('warning_command', ''))  # type: ignore[assignment]
            if 'WarningIntervals' in config or 'warning_intervals' in config:
                server.warning_intervals = config.get('WarningIntervals', config.get('warning_intervals', '30,15,10,5,1'))  # type: ignore[assignment]
            if 'WarningMessageTemplate' in config or 'warning_message_template' in config:
                server.warning_message_template = config.get('WarningMessageTemplate', config.get('warning_message_template', 'Server restarting in {message}'))  # type: ignore[assignment]
            if 'StartCommand' in config or 'start_command' in config:
                server.start_command = config.get('StartCommand', config.get('start_command', ''))  # type: ignore[assignment]
            if 'ScheduledRestartEnabled' in config or 'scheduled_restart_enabled' in config:
                server.scheduled_restart_enabled = config.get('ScheduledRestartEnabled', config.get('scheduled_restart_enabled', False))  # type: ignore[assignment]

            # Update Minecraft/Java settings
            if 'JavaPath' in config or 'java_path' in config:
                server.java_path = config.get('JavaPath', config.get('java_path', 'java'))  # type: ignore[assignment]
            if 'RAM' in config or 'ram' in config:
                server.ram = config.get('RAM', config.get('ram', 1024))  # type: ignore[assignment]
            if 'JVMArgs' in config or 'jvm_args' in config:
                server.jvm_args = config.get('JVMArgs', config.get('jvm_args', ''))  # type: ignore[assignment]

            # Update process info
            if 'ProcessId' in config or 'PID' in config or 'process_id' in config:
                server.process_id = config.get('ProcessId', config.get('PID', config.get('process_id')))  # type: ignore[assignment]
            if 'ProcessCreateTime' in config or 'process_create_time' in config:
                server.process_create_time = config.get('ProcessCreateTime', config.get('process_create_time'))  # type: ignore[assignment]
            if 'StartTime' in config:
                try:
                    server.last_started = datetime.fromisoformat(config['StartTime'])  # type: ignore[assignment]
                except (ValueError, TypeError):
                    pass

            # Update sync tracking
            if 'LastSync' in config or 'last_sync' in config:
                try:
                    sync_val = config.get('LastSync', config.get('last_sync'))
                    if sync_val:
                        server.last_sync = datetime.fromisoformat(sync_val) if isinstance(sync_val, str) else sync_val  # type: ignore[assignment]
                except (ValueError, TypeError):
                    pass
            if 'SyncedBy' in config or 'synced_by' in config:
                server.synced_by = config.get('SyncedBy', config.get('synced_by', ''))  # type: ignore[assignment]

            # Update logging paths
            if 'LogStdout' in config or 'log_stdout' in config:
                server.log_stdout = config.get('LogStdout', config.get('log_stdout', ''))  # type: ignore[assignment]
            if 'LogStderr' in config or 'log_stderr' in config:
                server.log_stderr = config.get('LogStderr', config.get('log_stderr', ''))  # type: ignore[assignment]

            # Update corruption tracking
            if 'LastCorruptionCheck' in config or 'last_corruption_check' in config:
                try:
                    check_val = config.get('LastCorruptionCheck', config.get('last_corruption_check'))
                    if check_val:
                        server.last_corruption_check = datetime.fromisoformat(check_val) if isinstance(check_val, str) else check_val  # type: ignore[assignment]
                except (ValueError, TypeError):
                    pass
            if 'CorruptionRecoveryActions' in config or 'corruption_recovery_actions' in config:
                actions = config.get('CorruptionRecoveryActions', config.get('corruption_recovery_actions', []))
                if isinstance(actions, list):
                    server.corruption_recovery_actions = json.dumps(actions)  # type: ignore[assignment]
                elif isinstance(actions, str):
                    server.corruption_recovery_actions = actions  # type: ignore[assignment]

            server.updated_at = datetime.utcnow()  # type: ignore[assignment]
            session.commit()

            logger.info(f"Updated server config: {name}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update server config: {e}")
            return False
        finally:
            session.close()

    def delete_server(self, name: str) -> bool:
        # Delete a server configuration (soft delete by setting is_active=False)
        session = self.get_session()
        try:
            server = session.query(ServerConfig).filter(ServerConfig.name == name).first()
            if not server:
                return False

            server.is_active = False  # type: ignore[assignment]
            server.updated_at = datetime.utcnow()  # type: ignore[assignment]
            session.commit()

            logger.info(f"Deleted (deactivated) server config: {name}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete server config: {e}")
            return False
        finally:
            session.close()

    def import_from_json_files(self, servers_dir: str) -> int:
        # Import server configurations from JSON files
        if not os.path.exists(servers_dir):
            logger.error(f"Servers directory not found: {servers_dir}")
            return 0

        imported = 0
        # Collect JSON files first, then process them
        json_files = [filename for filename in os.listdir(servers_dir) if filename.endswith('.json')]

        for filename in json_files:
            filepath = os.path.join(servers_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # Skip if server already exists
                if self.get_server(config.get('Name', filename[:-5])):
                    logger.debug(f"Server already exists in DB, skipping: {filename}")
                    continue

                # Set name from filename if not in config
                if 'Name' not in config:
                    config['Name'] = filename[:-5]

                if self.create_server(config):
                    imported += 1
                    logger.info(f"Imported server from JSON: {filename}")

            except Exception as e:
                logger.error(f"Failed to import {filename}: {e}")

        return imported

    def _server_to_dict(self, server: ServerConfig) -> Dict[str, Any]:
        # Convert a ServerConfig object to a dictionary
        extra_config = {}
        try:
            if server.extra_config:
                extra_config = json.loads(server.extra_config)
        except (json.JSONDecodeError, TypeError):
            pass

        # Parse corruption recovery actions
        corruption_actions = []
        try:
            if server.corruption_recovery_actions:
                corruption_actions = json.loads(server.corruption_recovery_actions)
        except (json.JSONDecodeError, TypeError):
            pass

        # Get permissions
        allowed_users = [p.username for p in server.permissions]
        user_permissions = {
            p.username: {
                'view': p.can_view,
                'start': p.can_start,
                'stop': p.can_stop,
                'restart': p.can_restart,
                'console': p.can_console,
                'edit': p.can_edit
            }
            for p in server.permissions
        }

        result = {
            'id': server.id,
            'Name': server.name,
            'Type': server.server_type,
            'AppID': server.app_id,
            'InstallDir': server.install_dir,
            'ExecutablePath': server.executable_path,
            'StartupArgs': server.startup_args,
            'Version': server.version,
            'ModLoader': server.mod_loader,
            'Category': server.category,

            # Server control settings
            'StopCommand': server.stop_command,
            'SaveCommand': server.save_command,
            'UseConfigFile': server.use_config_file,
            'ConfigFilePath': server.config_file_path,
            'ConfigArgument': server.config_argument,
            'AdditionalArgs': server.additional_args,
            'Notes': server.notes,

            # Scheduled command settings
            'MotdCommand': server.motd_command,
            'MotdMessage': server.motd_message,
            'MotdInterval': server.motd_interval,
            'WarningCommand': server.warning_command,
            'WarningIntervals': server.warning_intervals,
            'WarningMessageTemplate': server.warning_message_template,
            'StartCommand': server.start_command,
            'ScheduledRestartEnabled': server.scheduled_restart_enabled,

            # Minecraft/Java specific
            'JavaPath': server.java_path,
            'RAM': server.ram,
            'JVMArgs': server.jvm_args,

            # Status tracking
            'AutoStart': server.auto_start,
            'Imported': server.imported,

            # Process info
            'ProcessId': server.process_id,
            'PID': server.process_id,
            'ProcessCreateTime': server.process_create_time,

            # Sync tracking
            'LastSync': server.last_sync.isoformat() if server.last_sync else None,
            'SyncedBy': server.synced_by,

            # Logging paths
            'LogStdout': server.log_stdout,
            'LogStderr': server.log_stderr,

            # Corruption tracking
            'LastCorruptionCheck': server.last_corruption_check.isoformat() if server.last_corruption_check else None,
            'CorruptionRecoveryActions': corruption_actions,

            # Timestamps
            'Created': server.created_at.isoformat() if server.created_at else None,
            'LastUpdate': server.updated_at.isoformat() if server.updated_at else None,

            # Permissions
            'allowed_users': allowed_users,
            'user_permissions': user_permissions
        }

        # Merge extra config
        result.update(extra_config)

        return result

    def _add_permission(self, session, server_id: int, username: str,
                        perms: Dict[str, bool], granted_by: str = None):
        # Add a permission entry for a user on a server
        permission = ServerPermission(
            server_id=server_id,
            username=username,
            can_view=perms.get('view', True),
            can_start=perms.get('start', True),
            can_stop=perms.get('stop', True),
            can_restart=perms.get('restart', True),
            can_console=perms.get('console', True),
            can_edit=perms.get('edit', False),
            granted_by=granted_by
        )
        session.add(permission)

# Convenience function to get a singleton instance
_config_manager_instance = ServerConfigManager()
_auto_migration_done = False

def get_server_config_manager(auto_migrate: bool = True) -> ServerConfigManager:
    # Get the server config manager singleton
    global _auto_migration_done

    # Auto-migrate from JSON files on first access if DB is empty
    if auto_migrate and not _auto_migration_done:
        _auto_migration_done = True
        try:
            existing_servers = _config_manager_instance.get_all_servers()
            if len(existing_servers) == 0:
                # No servers in DB - try to import from JSON files
                from Modules.common import get_server_manager_dir

                try:
                    server_manager_dir = get_server_manager_dir()

                    servers_dir = os.path.join(server_manager_dir, "servers")
                    if os.path.exists(servers_dir):
                        imported_count = _config_manager_instance.import_from_json_files(servers_dir)
                        if imported_count > 0:
                            logger.info(f"Auto-migrated {imported_count} servers from JSON files to database")
                        else:
                            logger.info("No servers found in JSON files to migrate")
                    else:
                        logger.debug(f"Servers directory not found: {servers_dir}")
                except Exception as e:
                    logger.warning(f"Could not auto-migrate servers: {e}")
        except Exception as e:
            logger.error(f"Error during auto-migration check: {e}")

    return _config_manager_instance