#!/usr/bin/env python3
# Emergency admin 2FA reset utility - disables 2FA for admin user
# WARNING: This disables 2FA security for the admin account!
import os
import sys

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from user_database import initialize_user_manager

def reset_admin_2fa():
    # Reset admin 2FA settings - disable 2FA and clear secrets
    print("=== Resetting Admin 2FA ===")
    
    try:
        # Initialize user manager
        engine, user_manager = initialize_user_manager()
        
        # Disable 2FA for admin
        print("Disabling 2FA for admin user...")
        success, message = user_manager.disable_2fa("admin")
        
        if success:
            print("Admin 2FA disabled successfully")
        else:
            print(f"Failed to disable admin 2FA: {message}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run 2FA reset when executed directly
    reset_admin_2fa()