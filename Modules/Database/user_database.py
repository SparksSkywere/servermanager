import os
import sys
import winreg
import hashlib
import datetime
import json
import tkinter as tk
from tkinter import ttk, messagebox
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("UserDatabase")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("UserDatabase")

def get_user_sql_config_from_registry():
    """Get SQL configuration for user database from Windows registry"""
    try:
        from Modules.common import REGISTRY_ROOT, REGISTRY_PATH
        key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH)
        
        # Try to get SQL type
        try:
            sql_type = winreg.QueryValueEx(key, "SQLType")[0]
        except:
            sql_type = "SQLite"  # Default to SQLite
        
        # Get database path/connection info based on type
        if sql_type.lower() == "sqlite":
            try:
                db_path = winreg.QueryValueEx(key, "UsersSQLDatabasePath")[0]
            except:
                # Default SQLite path for users database - using db directory
                try:
                    server_manager_dir = winreg.QueryValueEx(key, "Servermanagerdir")[0]
                    db_path = os.path.join(server_manager_dir, "db", "servermanager_users.db")
                except:
                    db_path = "servermanager_users.db"
            
            config = {
                "type": "sqlite",
                "db_path": db_path
            }
        else:
            # For other SQL types (MySQL, PostgreSQL, etc.) - use separate user database
            try:
                db_name = winreg.QueryValueEx(key, "UsersSQLDatabase")[0]
            except:
                db_name = "servermanager_users"
                
            config = {
                "type": sql_type.lower(),
                "host": winreg.QueryValueEx(key, "SQLHost")[0],
                "port": winreg.QueryValueEx(key, "SQLPort")[0],
                "database": db_name,
                "username": winreg.QueryValueEx(key, "SQLUsername")[0],
                "password": winreg.QueryValueEx(key, "SQLPassword")[0]
            }
        
        winreg.CloseKey(key)
        return config
        
    except Exception as e:
        logger.error(f"Failed to read user SQL config from registry: {e}")
        # Return default SQLite config
        return {
            "type": "sqlite",
            "db_path": "servermanager_users.db"
        }

def build_user_db_url(config):
    """Build SQLAlchemy database URL from config for user database"""
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

def get_user_engine():
    """Get SQLAlchemy engine for user database"""
    config = get_user_sql_config_from_registry()
    db_url = build_user_db_url(config)
    
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
    """Ensure root admin user exists in user database"""
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
                logger.info("Created default admin user in user database")
            
    except Exception as e:
        logger.error(f"Failed to ensure root admin in user database: {e}")
        raise

def initialize_user_manager():
    """Initialize user management system and return engine and user_manager"""
    try:
        engine = get_user_engine()
        # Import here to avoid circular import
        from Modules.user_management import UserManager
        user_manager = UserManager(engine)
        logger.info("User management system initialized with separate user database")
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
        username_entry.pack(pady=(0, 15), fill=tk.X)
        
        # Password field with improved spacing
        ttk.Label(main_frame, text="Password:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        password_var = tk.StringVar()
        password_entry = ttk.Entry(main_frame, textvariable=password_var, show="*", width=35, font=("Segoe UI", 11))
        password_entry.pack(pady=(0, 20), fill=tk.X)
        
        # Status label for error messages
        status_var = tk.StringVar()
        status_label = ttk.Label(main_frame, textvariable=status_var, foreground="red", font=("Segoe UI", 9))
        status_label.pack(pady=(0, 15))
        
        # Login result variables
        login_result = [False, None]  # [success, user]
        dialog_closed = [False]
        
        def on_login():
            username = username_var.get().strip()
            password = password_var.get()
            
            if not username or not password:
                status_var.set("Please enter both username and password")
                return
            
            # Attempt authentication
            try:
                user = user_manager.authenticate_user(username, password)
                if user:
                    login_result[0] = True
                    login_result[1] = user
                    login_dialog.destroy()
                else:
                    status_var.set("Invalid username or password")
                    password_var.set("")  # Clear password on failed attempt
            except Exception as e:
                status_var.set(f"Login error: {str(e)}")
                logger.error(f"Login error: {e}")
        
        def on_cancel():
            dialog_closed[0] = True
            login_dialog.destroy()
        
        def on_key_press(event):
            if event.keysym == 'Return':
                on_login()
            elif event.keysym == 'Escape':
                on_cancel()
        
        # Button frame with improved layout
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        login_button = ttk.Button(button_frame, text="Login", command=on_login, width=12)
        login_button.pack(side=tk.RIGHT, padx=(5, 0))
        
        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel, width=12)
        cancel_button.pack(side=tk.RIGHT)
        
        # Bind keyboard events
        login_dialog.bind('<Key>', on_key_press)
        username_entry.bind('<Return>', lambda e: password_entry.focus_set())
        password_entry.bind('<Return>', lambda e: on_login())
        
        # Focus on username field
        username_entry.focus_set()
        
        # Show dialog and wait
        login_dialog.wait_window()
        
        if dialog_closed[0]:
            return False, None  # User cancelled
        
        if login_result[0]:
            return True, login_result[1]  # Success
        
        attempts += 1
        if attempts < max_attempts:
            messagebox.showwarning(
                "Login Failed", 
                f"Invalid credentials. {max_attempts - attempts} attempts remaining."
            )
    
    # Max attempts reached
    messagebox.showerror("Login Failed", "Maximum login attempts exceeded.")
    return False, None

def handle_2fa_authentication(parent_window=None):
    """Handle 2FA authentication process"""
    # Create 2FA dialog
    twofa_dialog = tk.Toplevel() if parent_window else tk.Tk()
    if parent_window:
        twofa_dialog.transient(parent_window)
    
    twofa_dialog.title("Two-Factor Authentication")
    twofa_dialog.geometry("380x200")
    twofa_dialog.resizable(False, False)
    
    # Center the dialog
    twofa_dialog.update_idletasks()
    x = (twofa_dialog.winfo_screenwidth() // 2) - (twofa_dialog.winfo_width() // 2)
    y = (twofa_dialog.winfo_screenheight() // 2) - (twofa_dialog.winfo_height() // 2)
    twofa_dialog.geometry(f"+{x}+{y}")
    
    # Main frame
    main_frame = ttk.Frame(twofa_dialog, padding=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Title
    title_label = ttk.Label(main_frame, text="Two-Factor Authentication", font=("Segoe UI", 14, "bold"))
    title_label.pack(pady=(0, 20))
    
    # Instructions
    instructions = ttk.Label(main_frame, text="Enter the 6-digit code from your authenticator app:")
    instructions.pack(pady=(0, 15))
    
    # Code entry
    code_var = tk.StringVar()
    code_entry = ttk.Entry(main_frame, textvariable=code_var, width=20, font=("Courier", 14))
    code_entry.pack(pady=(0, 15))
    
    # Status label
    status_var = tk.StringVar()
    status_label = ttk.Label(main_frame, textvariable=status_var, foreground="red")
    status_label.pack(pady=(0, 15))
    
    # Result variables
    result = [False]
    
    def on_verify():
        code = code_var.get().strip()
        if len(code) == 6 and code.isdigit():
            # Here you would verify the 2FA code
            # For now, just accept any 6-digit code
            result[0] = True
            twofa_dialog.destroy()
        else:
            status_var.set("Please enter a valid 6-digit code")
    
    def on_cancel():
        twofa_dialog.destroy()
    
    # Buttons
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X)
    
    verify_button = ttk.Button(button_frame, text="Verify", command=on_verify)
    verify_button.pack(side=tk.RIGHT, padx=(5, 0))
    
    cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side=tk.RIGHT)
    
    # Bind Enter key
    code_entry.bind('<Return>', lambda e: on_verify())
    code_entry.focus_set()
    
    twofa_dialog.wait_window()
    return result[0]
