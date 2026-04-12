# Minecraft modded/modpack servers database (ATLauncher, FTB, Technic, CurseForge)
import os
import sys
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from Modules.core.common import setup_module_path, setup_module_logging
setup_module_path()

from .database_utils import get_engine_by_type

logger: logging.Logger = setup_module_logging("MinecraftModdedDatabase")

def get_minecraft_modded_engine():
    # SQLAlchemy engine for the modded packs DB (minecraft_modded_ID.db)
    return get_engine_by_type("minecraft_modded")
