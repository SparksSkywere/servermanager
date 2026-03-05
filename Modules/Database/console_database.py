# Console states database operations
import os
import sys
import json
import logging
from datetime import datetime

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.common import setup_module_path, setup_module_logging
setup_module_path()

from .steam_database import get_steam_engine

logger: logging.Logger = setup_module_logging("ConsoleDatabase")

def get_console_engine():
    # Get engine for console states (uses steam database)
    return get_steam_engine()

def save_console_state_db(server_name, output_buffer, command_history, process_id=None, is_active=True):
    # Save console state to database
    try:
        from sqlalchemy import text
        engine = get_console_engine()
        with engine.connect() as conn:
            # Convert data to JSON
            output_json = json.dumps(output_buffer, default=str)
            command_json = json.dumps(command_history, default=str)

            # Upsert console state
            conn.execute(text("""
                INSERT INTO console_states (server_name, timestamp, process_id, is_active, output_buffer, command_history)
                VALUES (:server_name, :timestamp, :process_id, :is_active, :output_buffer, :command_history)
                ON CONFLICT(server_name) DO UPDATE SET
                    timestamp = :timestamp,
                    process_id = :process_id,
                    is_active = :is_active,
                    output_buffer = :output_buffer,
                    command_history = :command_history
            """), {
                'server_name': server_name,
                'timestamp': datetime.now(),
                'process_id': process_id,
                'is_active': is_active,
                'output_buffer': output_json,
                'command_history': command_json
            })
            conn.commit()
            logger.debug(f"Saved console state for {server_name} to database")
            return True
    except Exception as e:
        logger.error(f"Failed to save console state for {server_name}: {e}")
        return False

def load_console_state_db(server_name, max_age_seconds=None):
    # Load console state from database
    try:
        from sqlalchemy import text
        engine = get_console_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT output_buffer, command_history, process_id, is_active, timestamp
                FROM console_states
                WHERE server_name = :server_name
            """), {'server_name': server_name}).fetchone()

            if result:
                timestamp = result[4]

                # Apply age check only when max_age_seconds is specified
                if max_age_seconds is not None:
                    if timestamp is None:
                        logger.debug(f"Console state for {server_name} has no timestamp, skipping")
                        return None, None

                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

                    age_seconds = (datetime.now() - timestamp).total_seconds()
                    if age_seconds > max_age_seconds:
                        logger.debug(f"Console state for {server_name} is too old ({age_seconds:.0f}s), skipping")
                        return None, None

                # Parse JSON data
                output_buffer = json.loads(result[0]) if result[0] else []
                command_history = json.loads(result[1]) if result[1] else []

                logger.debug(f"Loaded console state for {server_name} from database ({len(output_buffer)} entries)")
                return output_buffer, command_history

        return None, None
    except Exception as e:
        logger.error(f"Failed to load console state for {server_name}: {e}")
        return None, None

def clear_console_state_db(server_name):
    # Clear console state from database
    try:
        from sqlalchemy import text
        engine = get_console_engine()
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM console_states WHERE server_name = :server_name"), {'server_name': server_name})
            conn.commit()
            logger.debug(f"Cleared console state for {server_name} from database")
            return True
    except Exception as e:
        logger.error(f"Failed to clear console state for {server_name}: {e}")
        return False