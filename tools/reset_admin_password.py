#!/usr/bin/env python3
# Admin password reset utility
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.Database.user_database import initialise_user_manager

def reset_admin_password():
    # Reset admin to default credentials
    print("=== Resetting Admin Password ===")

    try:
        engine, user_manager = initialise_user_manager()

        # Generate a secure random password
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits + string.punctuation
        new_password = ''.join(secrets.choice(alphabet) for i in range(16))

        print(f"Setting admin password to a secure random password...")

        success = user_manager.update_user("admin", password=new_password)
        if success:
            print("Admin password reset")
            print(f"New password: {new_password}")
            print("Please save this password securely!")

            # Verify
            print("\nTesting auth...")
            user = user_manager.authenticate_user("admin", new_password)
            if user:
                print("Auth test passed!")
                print(f"  User: {user.username}")
                print(f"  Is Admin: {user.is_admin}")
            else:
                print("Auth test failed")
        else:
            print("Password reset failed")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reset_admin_password()