# Database schema update GUI tool for Server Manager with automated column creation and migration
import sys
import os
import traceback
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import logging
from datetime import datetime

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# Setup module path and logging
from Modules.common import setup_module_path, setup_module_logging, handle_generic_error
setup_module_path()
logger: logging.Logger = setup_module_logging("DatabaseUpdate")

class DatabaseUpdateGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Database Schema Update")
        self.root.geometry("700x500")
        
        # Create GUI elements
        self.create_widgets()
        
        # Start update process
        self.root.after(1000, self.start_update)
    
    def create_widgets(self):
        # Title
        title_label = tk.Label(self.root, text="Database Schema Update", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Progress text area
        self.text_area = scrolledtext.ScrolledText(self.root, width=80, height=25, 
                                                  font=("Courier", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Status frame
        status_frame = tk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.status_label = tk.Label(status_frame, text="Initialising...", 
                                   relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.close_button = tk.Button(status_frame, text="Close", 
                                     command=self.root.quit, state=tk.DISABLED)
        self.close_button.pack(side=tk.RIGHT, padx=(10, 0))
    
    def log_message(self, message):
        # Add message to text area
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_message = f"[{timestamp}] {message}\n"
        self.text_area.insert(tk.END, formatted_message)
        self.text_area.see(tk.END)
        self.root.update()
    
    def update_status(self, status):
        # Update status label
        self.status_label.config(text=status)
        self.root.update()
    
    def start_update(self):
        # Start the database update process in a separate thread
        def update_thread():
            try:
                self.run_database_update()
            except Exception as e:
                self.log_message(f"CRITICAL ERROR: {e}")
                self.log_message(traceback.format_exc())
                self.update_status("Update failed!")
                messagebox.showerror("Error", f"Database update failed:\n{str(e)}")
            finally:
                self.close_button.config(state=tk.NORMAL)
        
        threading.Thread(target=update_thread, daemon=True).start()
    
    def run_database_update(self):
        # Run the actual database update process
        self.log_message("Starting database schema update process")
        self.update_status("Loading modules...")
        
        try:
            from Modules.Database.user_database import get_user_engine
            from sqlalchemy import inspect, text
            self.log_message("Successfully imported required modules")
        except ImportError as e:
            handle_generic_error("importing database modules", e, logger)
            self.log_message(f"FAILED to import modules: {e}")
            raise
        
        # Define required columns
        REQUIRED_COLUMNS = {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "username": "VARCHAR(64) UNIQUE NOT NULL",
            "password": "VARCHAR(256) NOT NULL",
            "email": "VARCHAR(128) UNIQUE",
            "first_name": "VARCHAR(64)",
            "last_name": "VARCHAR(64)",
            "display_name": "VARCHAR(128)",
            "account_number": "VARCHAR(16) UNIQUE",
            "is_admin": "BOOLEAN DEFAULT 0",
            "is_active": "BOOLEAN DEFAULT 1",
            "created_at": "DATETIME",
            "last_login": "DATETIME",
            "two_factor_enabled": "BOOLEAN DEFAULT 0",
            "two_factor_secret": "VARCHAR(64)"
        }
        
        def get_column_type_for_backend(col, backend):
            if backend == "sqlite":
                mapping = {
                    "INTEGER PRIMARY KEY AUTOINCREMENT": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "VARCHAR(64) UNIQUE NOT NULL": "TEXT UNIQUE NOT NULL",
                    "VARCHAR(256) NOT NULL": "TEXT NOT NULL",
                    "VARCHAR(128) UNIQUE": "TEXT UNIQUE",
                    "VARCHAR(64)": "TEXT",
                    "VARCHAR(128)": "TEXT",
                    "VARCHAR(16) UNIQUE": "TEXT",  # Remove UNIQUE for ALTER TABLE
                    "BOOLEAN DEFAULT 0": "INTEGER DEFAULT 0",
                    "BOOLEAN DEFAULT 1": "INTEGER DEFAULT 1",
                    "DATETIME": "TEXT",
                }
            elif backend == "mysql" or backend == "mariadb":
                mapping = {
                    "INTEGER PRIMARY KEY AUTOINCREMENT": "INT AUTO_INCREMENT PRIMARY KEY",
                    "VARCHAR(64) UNIQUE NOT NULL": "VARCHAR(64) UNIQUE NOT NULL",
                    "VARCHAR(256) NOT NULL": "VARCHAR(256) NOT NULL",
                    "VARCHAR(128) UNIQUE": "VARCHAR(128) UNIQUE",
                    "VARCHAR(64)": "VARCHAR(64)",
                    "VARCHAR(128)": "VARCHAR(128)",
                    "VARCHAR(16) UNIQUE": "VARCHAR(16) UNIQUE",
                    "BOOLEAN DEFAULT 0": "BOOLEAN DEFAULT 0",
                    "BOOLEAN DEFAULT 1": "BOOLEAN DEFAULT 1",
                    "DATETIME": "DATETIME",
                }
            elif backend == "mssql":
                mapping = {
                    "INTEGER PRIMARY KEY AUTOINCREMENT": "INT IDENTITY(1,1) PRIMARY KEY",
                    "VARCHAR(64) UNIQUE NOT NULL": "NVARCHAR(64) UNIQUE NOT NULL",
                    "VARCHAR(256) NOT NULL": "NVARCHAR(256) NOT NULL",
                    "VARCHAR(128) UNIQUE": "NVARCHAR(128) UNIQUE",
                    "VARCHAR(64)": "NVARCHAR(64)",
                    "VARCHAR(128)": "NVARCHAR(128)",
                    "VARCHAR(16) UNIQUE": "NVARCHAR(16) UNIQUE",
                    "BOOLEAN DEFAULT 0": "BIT DEFAULT 0",
                    "BOOLEAN DEFAULT 1": "BIT DEFAULT 1",
                    "DATETIME": "DATETIME2",
                }
            else:
                mapping = {k: k for k in REQUIRED_COLUMNS.values()}
            return mapping.get(REQUIRED_COLUMNS[col], REQUIRED_COLUMNS[col])
        
        try:
            self.update_status("Connecting to database...")
            self.log_message("Step 1: Getting database engine...")
            try:
                engine = get_user_engine()
                self.log_message(f"Engine created successfully: {engine.url}")
            except Exception as e:
                self.log_message(f"FAILED to create engine: {e}")
                self.log_message(traceback.format_exc())
                raise
            
            self.log_message("Step 2: Testing database connection...")
            try:
                with engine.connect() as test_conn:
                    self.log_message("Database connection test successful")
            except Exception as e:
                self.log_message(f"FAILED to connect to database: {e}")
                self.log_message(traceback.format_exc())
                raise
            
            self.update_status("Inspecting database...")
            self.log_message("Step 3: Creating database inspector...")
            try:
                inspector = inspect(engine)
                backend = engine.url.get_backend_name()
                self.log_message(f"Database backend: {backend}")
            except Exception as e:
                self.log_message(f"FAILED to create inspector: {e}")
                self.log_message(traceback.format_exc())
                raise
            
            # Normalise backend name
            if backend.startswith("mssql"):
                backend = "mssql"
            elif backend.startswith("mysql"):
                backend = "mysql"
            elif backend.startswith("mariadb"):
                backend = "mariadb"
            elif backend.startswith("sqlite"):
                backend = "sqlite"
            
            self.log_message(f"Normalised backend: {backend}")

            # Check if users table exists
            self.log_message("Step 4: Getting table names...")
            try:
                table_names = inspector.get_table_names()
                self.log_message(f"Existing tables: {table_names}")
            except Exception as e:
                self.log_message(f"FAILED to get table names: {e}")
                self.log_message(traceback.format_exc())
                raise
            
            if "users" not in table_names:
                self.update_status("Creating users table...")
                self.log_message("Table 'users' does not exist. Creating table...")
                
                try:
                    # Compose CREATE TABLE statement
                    col_defs = []
                    for col, typ in REQUIRED_COLUMNS.items():
                        col_type = get_column_type_for_backend(col, backend)
                        col_defs.append(f"{col} {col_type}")
                        self.log_message(f"  Column: {col} -> {col_type}")
                    
                    create_sql = f"CREATE TABLE users ({', '.join(col_defs)})"
                    self.log_message(f"Executing CREATE TABLE...")
                    
                    with engine.begin() as conn:
                        conn.execute(text(create_sql))
                    self.log_message("Table 'users' created successfully.")
                    
                    # Create default admin user
                    self.update_status("Creating default admin user...")
                    self.log_message("Creating default admin user...")
                    
                    import hashlib
                    import uuid
                    
                    admin_password = hashlib.sha256("admin".encode()).hexdigest()
                    account_number = str(uuid.uuid4())[:8].upper()
                    
                    insert_params = {
                        "username": "admin",
                        "password": admin_password,
                        "email": "admin@localhost",
                        "first_name": "System",
                        "last_name": "Administrator", 
                        "display_name": "Admin",
                        "account_number": account_number,
                        "is_admin": 1,
                        "is_active": 1,
                        "created_at": datetime.utcnow()
                    }
                    
                    insert_sql = """
                        INSERT INTO users (username, password, email, first_name, last_name, display_name, 
                                         account_number, is_admin, is_active, created_at) 
                        VALUES (:username, :password, :email, :first_name, :last_name, :display_name,
                               :account_number, :is_admin, :is_active, :created_at)
                    """
                    
                    with engine.begin() as conn:
                        conn.execute(text(insert_sql), insert_params)
                    
                    self.log_message(f"Default admin user created with account number: {account_number}")
                    self.update_status("Database creation completed!")
                    self.log_message("SUCCESS: Database creation completed!")
                    
                except Exception as e:
                    self.log_message(f"FAILED during table creation: {e}")
                    self.log_message(traceback.format_exc())
                    raise
                
                return

            # Table exists, check columns
            self.update_status("Checking existing columns...")
            self.log_message("Table 'users' exists. Checking columns...")
            
            try:
                existing_columns = inspector.get_columns("users")
                column_names = {col["name"] for col in existing_columns}
                self.log_message(f"Existing columns: {sorted(column_names)}")
                
                required_columns = set(REQUIRED_COLUMNS.keys())
                self.log_message(f"Required columns: {sorted(required_columns)}")
                
                missing = [col for col in REQUIRED_COLUMNS if col not in column_names]
                
            except Exception as e:
                self.log_message(f"FAILED to check columns: {e}")
                self.log_message(traceback.format_exc())
                raise
            
            if not missing:
                self.log_message("All required columns exist.")
                
                # Check account numbers
                self.update_status("Checking account numbers...")
                try:
                    with engine.begin() as conn:
                        try:
                            result = conn.execute(text("SELECT COUNT(*) FROM users WHERE account_number IS NULL OR account_number = ''"))
                            count = result.scalar()
                            count = count if count is not None else 0
                            self.log_message(f"Found {count} users without account numbers")
                            
                            if count > 0:
                                self.log_message("Generating account numbers...")
                                import uuid
                                
                                result = conn.execute(text("SELECT id, username FROM users WHERE account_number IS NULL OR account_number = ''"))
                                users_without_accounts = result.fetchall()
                                
                                for user_id, username in users_without_accounts:
                                    account_number = str(uuid.uuid4())[:8].upper()
                                    conn.execute(text("UPDATE users SET account_number = :account_number WHERE id = :id"), {
                                        "account_number": account_number,
                                        "id": user_id
                                    })
                                    self.log_message(f"  Generated {account_number} for {username}")
                        except Exception as e:
                            self.log_message(f"Note: Could not check account numbers: {e}")
                            
                except Exception as e:
                    self.log_message(f"FAILED during account number check: {e}")
                    self.log_message(traceback.format_exc())
                    raise
                
                self.update_status("No updates needed")
                self.log_message("SUCCESS: No database updates needed.")
            else:
                self.update_status("Adding missing columns...")
                self.log_message(f"Missing columns: {missing}")
                
                try:
                    with engine.begin() as conn:
                        for col in missing:
                            col_type = get_column_type_for_backend(col, backend)
                            try:
                                if backend == "sqlite":
                                    sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                                elif backend == "mysql" or backend == "mariadb":
                                    sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                                elif backend == "mssql":
                                    sql = f"ALTER TABLE users ADD {col} {col_type}"
                                else:
                                    sql = f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                                
                                self.log_message(f"Adding column: {col}")
                                conn.execute(text(sql))
                                self.log_message(f"  SUCCESS: Added {col}")
                            except Exception as e:
                                self.log_message(f"  FAILED: {col} - {e}")
                        
                        # Generate account numbers if needed
                        if "account_number" in missing:
                            self.log_message("Generating account numbers for existing users...")
                            import uuid
                            
                            try:
                                # First, verify the column exists
                                try:
                                    conn.execute(text("SELECT account_number FROM users LIMIT 1"))
                                    self.log_message("account_number column verified")
                                except Exception as e:
                                    self.log_message(f"account_number column verification failed: {e}")
                                    raise
                                
                                # Get all users that need account numbers
                                result = conn.execute(text("SELECT id, username FROM users WHERE account_number IS NULL OR account_number = ''"))
                                users = result.fetchall()
                                self.log_message(f"Found {len(users)} users needing account numbers")
                                
                                for user_id, username in users:
                                    account_number = str(uuid.uuid4())[:8].upper()
                                    try:
                                        conn.execute(text("UPDATE users SET account_number = :account_number WHERE id = :id"), {
                                            "account_number": account_number,
                                            "id": user_id
                                        })
                                        self.log_message(f"  Generated {account_number} for {username}")
                                    except Exception as e:
                                        self.log_message(f"  Failed to update user {username}: {e}")
                                        
                                # After generating account numbers, create a unique index for future integrity
                                try:
                                    self.log_message("Creating unique index on account_number...")
                                    conn.execute(text("CREATE UNIQUE INDEX idx_users_account_number ON users(account_number)"))
                                    self.log_message("Unique index created successfully")
                                except Exception as e:
                                    self.log_message(f"Note: Could not create unique index (may already exist): {e}")
                                    
                            except Exception as e:
                                self.log_message(f"Failed to generate account numbers: {e}")
                                
                    self.update_status("Update completed!")
                    self.log_message("SUCCESS: Database schema updated!")
                    
                except Exception as e:
                    self.log_message(f"FAILED during column addition: {e}")
                    self.log_message(traceback.format_exc())
                    raise

        except Exception as e:
            self.update_status("Update failed!")
            self.log_message(f"CRITICAL ERROR: {e}")
            self.log_message(traceback.format_exc())
            raise
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = DatabaseUpdateGUI()
    app.run()
