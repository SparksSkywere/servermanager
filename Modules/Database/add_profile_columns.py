#!/usr/bin/env python3
# Add profile columns to user database
# Run this script to migrate existing databases

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from Modules.Database.user_database import get_user_engine
from sqlalchemy import text

def add_profile_columns():
    print("=== Adding Profile Columns to Database ===")
    
    try:
        engine = get_user_engine()
        
        columns_to_add = [
            ("avatar", "TEXT"),
            ("bio", "TEXT"),
            ("timezone", "TEXT DEFAULT 'UTC'"),
            ("theme_preference", "TEXT DEFAULT 'dark'")
        ]
        
        with engine.connect() as conn:
            for col_name, col_type in columns_to_add:
                try:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                    print(f"  Added column: {col_name}")
                except Exception as e:
                    if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                        print(f"  Column {col_name} already exists")
                    else:
                        print(f"  Error adding {col_name}: {e}")
            
            conn.commit()
        
        print("\nProfile columns migration complete!")
        
        # Now reset admin password
        print("\n=== Resetting Admin Password ===")
        from Modules.Database.user_database import initialise_user_manager
        engine, user_manager = initialise_user_manager()
        
        success = user_manager.update_user("admin", password="admin")
        if success:
            print("Admin password reset to: admin")
        else:
            print("Failed to reset password")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    add_profile_columns()
