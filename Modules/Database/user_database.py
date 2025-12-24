# User database management
# - Auth connections, login dialogs, user manager init

import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from sqlalchemy import text

from .database_utils import get_sql_config_from_registry, build_db_url, get_engine_by_type

from Modules.common import setup_module_logging, setup_module_path
setup_module_path()
logger = setup_module_logging("UserDatabase")

def get_user_sql_config_from_registry():
    # User DB config from registry
    return get_sql_config_from_registry("user")

def build_user_db_url(config):
    # SQLAlchemy URL for user DB
    return build_db_url(config)

def get_user_engine():
    # SQLAlchemy engine for user DB
    return get_engine_by_type("user")

def ensure_root_admin(engine):
    # Create root admin if missing
    try:
        with engine.connect() as conn:
            # Create users table with full schema
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
            
            result = conn.execute(text("SELECT COUNT(*) FROM users WHERE username = 'admin'"))
            count = result.scalar()
            
            if count == 0:
                import bcrypt
                from datetime import datetime
                import uuid
                admin_password = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
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
        logger.error(f"Root admin creation failed: {e}")
        raise

def initialise_user_manager():
    # Init user management, return engine + user_manager
    try:
        engine = get_user_engine()
        from Modules.user_management import UserManager
        user_manager = UserManager(engine)
        logger.info("User management initialised")
        return engine, user_manager
    except Exception as e:
        logger.error(f"User manager init failed: {e}")
        raise

# Backward compat
initialize_user_manager = initialise_user_manager

def sql_login(user_manager, parent_window=None):
    # SQL login dialog
    # - Returns (success, user) tuple
    max_attempts = 3
    attempts = 0
    
    while attempts < max_attempts:
        login_dialog = tk.Toplevel() if parent_window else tk.Tk()
        if parent_window:
            login_dialog.transient(parent_window)
        login_dialog.title("Server Manager Login")
        login_dialog.geometry("420x320")
        login_dialog.resizable(False, False)
        login_dialog.grab_set()
        
        # Centre the dialog
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
                    # Check if 2FA is enabled for this user
                    two_factor_enabled = getattr(user, 'two_factor_enabled', False)
                    if two_factor_enabled:
                        # Show 2FA dialog
                        if not handle_2fa_login(user_manager, username, login_dialog):
                            status_var.set("2FA verification failed")
                            password_var.set("")
                            return
                    
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

def handle_2fa_login(user_manager, username, parent_window=None):
    # Handle 2FA verification during login process
    try:
        # Create 2FA dialog
        twofa_dialog = tk.Toplevel() if parent_window else tk.Tk()
        if parent_window:
            twofa_dialog.transient(parent_window)
        
        twofa_dialog.title("Two-Factor Authentication")
        twofa_dialog.geometry("380x200")
        twofa_dialog.resizable(False, False)
        twofa_dialog.grab_set()
        
        # Centre the dialog
        twofa_dialog.update_idletasks()
        x = (twofa_dialog.winfo_screenwidth() // 2) - (190)
        y = (twofa_dialog.winfo_screenheight() // 2) - (100)
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
        code_entry = ttk.Entry(main_frame, textvariable=code_var, width=20, font=("Courier", 14), justify="center")
        code_entry.pack(pady=(0, 15))
        
        # Status label
        status_var = tk.StringVar()
        status_label = ttk.Label(main_frame, textvariable=status_var, foreground="red")
        status_label.pack(pady=(0, 15))
        
        # Result variable
        result = [False]
        
        def on_verify():
            token = code_var.get().strip()
            if not token:
                status_var.set("Please enter the 6-digit code")
                return
            
            if len(token) != 6 or not token.isdigit():
                status_var.set("Code must be 6 digits")
                return
            
            # Verify the token
            if user_manager.verify_2fa(username, token):
                result[0] = True
                twofa_dialog.destroy()
            else:
                status_var.set("Invalid code. Please try again.")
                code_var.set("")
        
        def on_cancel():
            result[0] = False
            twofa_dialog.destroy()
        
        def on_key_press(event):
            if event.keysym == 'Return':
                on_verify()
            elif event.keysym == 'Escape':
                on_cancel()
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        verify_button = ttk.Button(button_frame, text="Verify", command=on_verify)
        verify_button.pack(side=tk.RIGHT, padx=(5, 0))
        
        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
        cancel_button.pack(side=tk.RIGHT)
        
        # Bind keyboard events
        twofa_dialog.bind('<Key>', on_key_press)
        code_entry.bind('<Return>', lambda e: on_verify())
        code_entry.focus_set()
        
        # Show dialog and wait
        twofa_dialog.wait_window()
        
        return result[0]
        
    except Exception as e:
        logger.error(f"Error in 2FA login: {e}")
        return False
    # Handle 2FA authentication process with GUI dialog
    # Create 2FA dialog
    twofa_dialog = tk.Toplevel() if parent_window else tk.Tk()
    if parent_window:
        twofa_dialog.transient(parent_window)
    
    twofa_dialog.title("Two-Factor Authentication")
    twofa_dialog.geometry("380x200")
    twofa_dialog.resizable(False, False)
    
    # Centre the dialog
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
