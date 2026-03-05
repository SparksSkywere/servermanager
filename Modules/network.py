# Network management
import os
import sys
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_logging
logger: logging.Logger = setup_module_logging("Network")