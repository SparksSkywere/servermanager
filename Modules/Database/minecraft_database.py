# Minecraft servers database
import os
import sys
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.core.common import setup_module_path, setup_module_logging
setup_module_path()

from .database_utils import get_engine_by_type

logger: logging.Logger = setup_module_logging("MinecraftDatabase")

def get_minecraft_engine():
    # SQLAlchemy engine for MC DB
    return get_engine_by_type("minecraft")
