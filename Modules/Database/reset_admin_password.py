#!/usr/bin/env python3
# Emergency admin password reset utility - resets to "admin"/"admin"
# WARNING: This resets admin credentials to insecure default!
import os
import sys
import hashlib

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from user_database import initialize_user_manager

def reset_admin_password():
    # Reset admin password to default 'admin' credentials
    print("=== Resetting Admin Password ===")
    
    try:
        # Initialize user manager
        engine, user_manager = initialize_user_manager()
        
        # Reset to insecure default credentials (plain text will be hashed automatically)
        print("Setting admin password to 'admin'...")
        
        success = user_manager.update_user("admin", password="admin")
        if success:
            print("Admin password reset to 'admin' successfully")
            
            # Verify the password reset worked by testing authentication
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
    # Run password reset when executed directly
    reset_admin_password()
