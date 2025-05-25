import os
import subprocess
import sys

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Launch the Python launcher script
launcher_path = os.path.join(script_dir, "scripts", "launcher.py")

# Use subprocess with CREATE_NO_WINDOW flag to hide console
startupinfo = subprocess.STARTUPINFO()
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = 0  # SW_HIDE

# Run the launcher script
subprocess.Popen([sys.executable, launcher_path], startupinfo=startupinfo)
