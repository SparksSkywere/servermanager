#!/usr/bin/env python3
# Admin 2FA reset utility
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.Database.user_database import initialise_user_manager

def reset_admin_2fa():
    # Reset admin 2FA
    print("=== Resetting Admin 2FA ===")

    try:
        engine, user_manager = initialise_user_manager()

        print("Disabling 2FA for admin...")
        success, message = user_manager.disable_2fa("admin")

        if success:
            print("Admin 2FA disabled")
        else:
            print(f"Failed: {message}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reset_admin_2fa()