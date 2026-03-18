# Server Manager stop script wrapper that executes the main stop_servermanager.py module
import os
import subprocess
import sys

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Path to the stop script
stop_script_path = os.path.join(script_dir, "Modules", "services", "stop_servermanager.py")

# Use subprocess with CREATE_NO_WINDOW flag to hide console
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = 0  # SW_HIDE

# Run the stop script
subprocess.Popen([sys.executable, stop_script_path], startupinfo=startupinfo)
