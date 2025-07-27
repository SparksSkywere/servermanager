import os
import sys
import logging
import winreg
import hashlib
import datetime
import json
import tkinter as tk
from tkinter import ttk, messagebox
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("SQL_Connection")

def get_sql_config_from_registry():
    """Get SQL configuration from Windows registry"""
    try:
        registry_path = r"Software\SkywereIndustries\Servermanager"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
        
        # Try to get SQL type
        try:
            sql_type = winreg.QueryValueEx(key, "SQLType")[0]
        except:
            sql_type = "SQLite"  # Default to SQLite
        
        # Get database path/connection info based on type
        if sql_type.lower() == "sqlite":
            try:
                db_path = winreg.QueryValueEx(key, "SQLDatabasePath")[0]
            except:
                # Default SQLite path
                try:
                    server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                    db_path = os.path.join(server_manager_dir, "config", "servermanager.db")
                except:
                    db_path = "servermanager.db"
            
            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types (MySQL, PostgreSQL, etc.)
            config = {
                "type": sql_type.lower(),
                "host": winreg.QueryValueEx(key, "SQLHost")[0],
                "port": winreg.QueryValueEx(key, "SQLPort")[0],
                "database": winreg.QueryValueEx(key, "SQLDatabase")[0],
                "username": winreg.QueryValueEx(key, "SQLUsername")[0],
                "password": winreg.QueryValueEx(key, "SQLPassword")[0]
            }
        
        winreg.CloseKey(key)
        return config
        
    except Exception as e:
        logger.error(f"Failed to read SQL config from registry: {e}")
        # Return default SQLite config
        return {
            "type": "sqlite",
            "db_path": "servermanager.db"
        }

def build_db_url(config):
    """Build SQLAlchemy database URL from config"""
    if config["type"] == "sqlite":
        # For SQLite, use absolute path
        db_path = config["db_path"]
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(db_path)
        return f"sqlite:///{db_path}"
    elif config["type"] == "mysql":
        return f"mysql+pymysql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    elif config["type"] == "postgresql":
        return f"postgresql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    else:
        raise ValueError(f"Unsupported database type: {config['type']}")

def get_engine():
    """Get SQLAlchemy engine"""
    config = get_sql_config_from_registry()
    db_url = build_db_url(config)
    
    # Create engine with appropriate settings
    if config["type"] == "sqlite":
        engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
    else:
        engine = create_engine(db_url, echo=False)
    
    return engine

def ensure_root_admin(engine):
    """Ensure root admin user exists in database"""
    try:
        # This is a placeholder - implement based on your user table structure
        with engine.connect() as conn:
            # Check if users table exists and create if needed with all columns
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    display_name TEXT,
                    account_number TEXT UNIQUE,
                    is_admin BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME,
                    last_login DATETIME,
                    two_factor_enabled BOOLEAN DEFAULT 0,
                    two_factor_secret TEXT
                )
            """))
            
            # Check if admin user exists
            result = conn.execute(text("SELECT COUNT(*) FROM users WHERE username = 'admin'"))
            count = result.scalar()
            
            if count == 0:
                # Create admin user with default password
                import hashlib
                from datetime import datetime
                import uuid
                admin_password = hashlib.sha256("admin".encode()).hexdigest()
                account_number = str(uuid.uuid4())[:8].upper()
                conn.execute(text("""
                    INSERT INTO users (username, password, is_admin, is_active, created_at, email, first_name, last_name, display_name, account_number) 
                    VALUES ('admin', :password, 1, 1, :created_at, 'admin@localhost', 'System', 'Administrator', 'Admin', :account_number)
                """), {
                    "password": admin_password,
                    "created_at": datetime.utcnow(),
                    "account_number": account_number
                })
                conn.commit()
                logger.info("Created default admin user")
            
    except Exception as e:
        logger.error(f"Failed to ensure root admin: {e}")
        raise

def initialize_user_manager():
    """Initialize user management system and return engine and user_manager"""
    try:
        engine = get_engine()
        # Import here to avoid circular import
        from Scripts.user_management import UserManager
        user_manager = UserManager(engine)
        logger.info("User management system initialized")
        return engine, user_manager
    except Exception as e:
        logger.error(f"Failed to initialize user management: {e}")
        raise

def sql_login(user_manager, parent_window=None):
    """
    Prompt for login using SQL database authentication. 
    Returns (success, user) tuple where success is True if successful, 
    False if cancelled, and user is the authenticated user object or None
    """
    max_attempts = 3
    attempts = 0
    
    while attempts < max_attempts:
        # Create login dialog window
        login_dialog = tk.Toplevel() if parent_window else tk.Tk()
        if parent_window:
            login_dialog.transient(parent_window)
        login_dialog.title("Server Manager Login")
        login_dialog.geometry("420x320")
        login_dialog.resizable(False, False)
        login_dialog.grab_set()
        
        # Center the dialog
        login_dialog.update_idletasks()
        x = (login_dialog.winfo_screenwidth() // 2) - (login_dialog.winfo_width() // 2)
        y = (login_dialog.winfo_screenheight() // 2) - (login_dialog.winfo_height() // 2)
        login_dialog.geometry(f"+{x}+{y}")
        
        # Main frame with better padding
        main_frame = ttk.Frame(login_dialog, padding=25)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title with better spacing
        title_label = ttk.Label(main_frame, text="Server Manager Login", font=("Segoe UI", 16, "bold"))
        title_label.pack(pady=(0, 25))
        
        # Username field with improved spacing
        ttk.Label(main_frame, text="Username:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        username_var = tk.StringVar()
        username_entry = ttk.Entry(main_frame, textvariable=username_var, width=35, font=("Segoe UI", 11))
        username_entry.pack(fill=tk.X, pady=(0, 15))
        
        # Password field with improved spacing
        ttk.Label(main_frame, text="Password:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        password_var = tk.StringVar()
        password_entry = ttk.Entry(main_frame, textvariable=password_var, width=35, show="*", font=("Segoe UI", 11))
        password_entry.pack(fill=tk.X, pady=(0, 25))
        
        # Result variables
        login_result = {"success": False, "username": "", "password": "", "cancelled": False}
        
        # Button actions
        def on_login():
            login_result["success"] = True
            login_result["username"] = username_var.get()
            login_result["password"] = password_var.get()
            login_dialog.destroy()
        
        def on_cancel():
            login_result["cancelled"] = True
            login_dialog.destroy()
        
        # Button frame with better spacing
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Buttons with improved layout
        offline_button = ttk.Button(button_frame, text="Offline Mode", command=on_cancel, width=15)
        offline_button.pack(side=tk.LEFT)
        
        # Right side buttons
        button_right_frame = ttk.Frame(button_frame)
        button_right_frame.pack(side=tk.RIGHT)
        
        cancel_button = ttk.Button(button_right_frame, text="Cancel", command=on_cancel, width=12)
        cancel_button.pack(side=tk.LEFT, padx=(0, 10))
        
        login_button = ttk.Button(button_right_frame, text="Login", command=on_login, width=12)
        login_button.pack(side=tk.LEFT)
        
        # Bind Enter key to login
        def on_enter(event):
            on_login()
        
        login_dialog.bind('<Return>', on_enter)
        username_entry.bind('<Return>', on_enter)
        password_entry.bind('<Return>', on_enter)
        
        # Focus username field
        username_entry.focus_set()
        
        # Handle window close
        login_dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        
        # Wait for dialog to close
        if parent_window:
            parent_window.wait_window(login_dialog)
        else:
            login_dialog.mainloop()
        
        # Check if cancelled
        if login_result["cancelled"]:
            logger.info("User cancelled login, enabling offline mode")
            return False, None
        
        # Get credentials
        username = login_result["username"].strip()
        password = login_result["password"].strip()
        
        if not username or not password:
            attempts += 1
            if attempts < max_attempts:
                messagebox.showerror("Login Failed", 
                                   f"Username and password are required. {max_attempts - attempts} attempts remaining.")
            else:
                messagebox.showerror("Login Failed", 
                                   "Maximum login attempts exceeded. Running in offline mode.")
            continue
        
        try:
            # Get user from database
            user = user_manager.get_user(username)
            if not user:
                logger.warning(f"User not found: {username}")
                attempts += 1
                if attempts < max_attempts:
                    messagebox.showerror("Login Failed", 
                                       f"Invalid username or password. {max_attempts - attempts} attempts remaining.")
                else:
                    messagebox.showerror("Login Failed", 
                                       "Maximum login attempts exceeded. Running in offline mode.")
                continue
            
            # Check if user is active
            if not getattr(user, 'is_active', True):
                logger.warning(f"Inactive user attempted login: {username}")
                attempts += 1
                if attempts < max_attempts:
                    messagebox.showerror("Login Failed", 
                                       f"Account is inactive. {max_attempts - attempts} attempts remaining.")
                else:
                    messagebox.showerror("Login Failed", 
                                       "Maximum login attempts exceeded. Running in offline mode.")
                continue
            
            # Verify password
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            if user.password != hashed_password:
                logger.warning(f"Invalid password for user: {username}")
                attempts += 1
                if attempts < max_attempts:
                    messagebox.showerror("Login Failed", 
                                       f"Invalid username or password. {max_attempts - attempts} attempts remaining.")
                else:
                    messagebox.showerror("Login Failed", 
                                       "Maximum login attempts exceeded. Running in offline mode.")
                continue
            
            # Check 2FA if enabled
            if getattr(user, 'two_factor_enabled', False):
                success, token = handle_2fa_authentication(parent_window)
                if not success:
                    return False, None
                
                if not token or not user_manager.verify_2fa(username, token):
                    logger.warning(f"Invalid 2FA token for user: {username}")
                    attempts += 1
                    if attempts < max_attempts:
                        messagebox.showerror("2FA Failed", 
                                           f"Invalid 2FA token. {max_attempts - attempts} attempts remaining.")
                    else:
                        messagebox.showerror("2FA Failed", 
                                           "Maximum login attempts exceeded. Running in offline mode.")
                    continue
            
            # Successful login
            logger.info(f"Successfully logged in as {username}")
            
            # Update last login time
            try:
                user_manager.update_user(username, last_login=datetime.datetime.now())
            except Exception as e:
                logger.warning(f"Failed to update last login time: {e}")
            
            return True, user
            
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            attempts += 1
            if attempts < max_attempts:
                messagebox.showerror("Database Error", 
                                   f"Database error during login. {max_attempts - attempts} attempts remaining.")
            else:
                messagebox.showerror("Database Error", 
                                   f"Cannot access user database. Running in offline mode.")
    
    # If we get here after max attempts, return failure
    logger.info("Login failed after max attempts, running in offline mode")
    return False, None

def handle_2fa_authentication(parent_window=None):
    """
    Handle 2FA authentication dialog.
    Returns (success, token) tuple where success is True if successful,
    False if cancelled, and token is the entered token or None
    """
    # Create 2FA dialog
    twofa_dialog = tk.Toplevel() if parent_window else tk.Tk()
    if parent_window:
        twofa_dialog.transient(parent_window)
    twofa_dialog.title("2FA Authentication")
    twofa_dialog.geometry("300x150")
    twofa_dialog.resizable(False, False)
    twofa_dialog.grab_set()
    
    # Center the 2FA dialog
    twofa_dialog.update_idletasks()
    x = (twofa_dialog.winfo_screenwidth() // 2) - (twofa_dialog.winfo_width() // 2)
    y = (twofa_dialog.winfo_screenheight() // 2) - (twofa_dialog.winfo_height() // 2)
    twofa_dialog.geometry(f"+{x}+{y}")
    
    twofa_frame = ttk.Frame(twofa_dialog, padding=20)
    twofa_frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(twofa_frame, text="Enter your 2FA token:", font=("Segoe UI", 12)).pack(pady=(0, 10))
    
    token_var = tk.StringVar()
    token_entry = ttk.Entry(twofa_frame, textvariable=token_var, width=20, justify=tk.CENTER)
    token_entry.pack(pady=(0, 15))
    
    twofa_result = {"success": False, "token": "", "cancelled": False}
    
    def on_twofa_submit():
        twofa_result["success"] = True
        twofa_result["token"] = token_var.get()
        twofa_dialog.destroy()
    
    def on_twofa_cancel():
        twofa_result["cancelled"] = True
        twofa_dialog.destroy()
    
    twofa_button_frame = ttk.Frame(twofa_frame)
    twofa_button_frame.pack(fill=tk.X)
    
    ttk.Button(twofa_button_frame, text="Submit", command=on_twofa_submit, width=10).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(twofa_button_frame, text="Cancel", command=on_twofa_cancel, width=10).pack(side=tk.RIGHT)
    
    # Bind Enter key
    twofa_dialog.bind('<Return>', lambda e: on_twofa_submit())
    token_entry.bind('<Return>', lambda e: on_twofa_submit())
    
    token_entry.focus_set()
    twofa_dialog.protocol("WM_DELETE_WINDOW", on_twofa_cancel)
    
    if parent_window:
        parent_window.wait_window(twofa_dialog)
    else:
        twofa_dialog.mainloop()
    
    if twofa_result["cancelled"]:
        logger.info("User cancelled 2FA, enabling offline mode")
        return False, None
    
    return True, twofa_result["token"].strip()
