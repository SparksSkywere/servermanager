#!/usr/bin/env python3
# WILL RESET TO "admin" & "admin"
import os
import sys
import hashlib

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from Modules.Database.user_database import initialize_user_manager

def reset_admin_password():
    """Reset admin password to 'admin'"""
    print("=== Resetting Admin Password ===")
    
    try:
        # Initialize user manager
        engine, user_manager = initialize_user_manager()
        
        # Update admin password to 'admin' (pass plain text, let update_user hash it)
        print("Setting admin password to 'admin'...")
        
        success = user_manager.update_user("admin", password="admin")
        if success:
            print("Admin password reset to 'admin' successfully")
            
            # Test authentication
            print("\nTesting authentication...")
            user = user_manager.authenticate_user("admin", "admin")
            if user:
                print("Authentication test successful!")
                print(f"  User: {user.username}")
                print(f"  Is Admin: {user.is_admin}")
            else:
                print("Authentication test failed")
        else:
            print("Failed to reset admin password")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reset_admin_password()
