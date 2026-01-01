#!/usr/bin/env python3
# Admin password reset utility
import os
import sys
import hashlib

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from user_database import initialise_user_manager

def reset_admin_password():
    # Reset admin to default credentials
    print("=== Resetting Admin Password ===")
    
    try:
        engine, user_manager = initialise_user_manager()
        
        print("Setting admin password to 'admin'...")
        
        success = user_manager.update_user("admin", password="admin")
        if success:
            print("Admin password reset")
            
            # Verify
            print("\nTesting auth...")
            user = user_manager.authenticate_user("admin", "admin")
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