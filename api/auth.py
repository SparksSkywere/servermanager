import os
import sys
# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tkinter as tk
from tkinter import messagebox, simpledialog
from flask import Blueprint, request, jsonify, session

# Try to import user management and SQL connection with fallback
try:
    from Scripts.user_management import UserManager
    from Modules.SQL_Connection import get_engine, ensure_root_admin
    SQL_AVAILABLE = True
except ImportError as e:
    print(f"Warning: SQL modules not available: {e}", file=sys.stderr)
    SQL_AVAILABLE = False
    UserManager = None

def main():
    """Main function for standalone admin dashboard"""
    if not SQL_AVAILABLE:
        messagebox.showerror("Error", "SQL connection modules not available. Cannot start admin dashboard.")
        sys.exit(1)
        
    try:
        engine = get_engine()
        ensure_root_admin(engine)  # <-- Ensure root admin is present in SQL
        um = UserManager(engine)
        app = AdminDashboard(um)
        app.mainloop()
    except Exception as e:
        print(f"Error initializing admin dashboard: {e}", file=sys.stderr)
        messagebox.showerror("Initialization Error", f"Failed to start admin dashboard:\n{str(e)}")
        sys.exit(1)

class AdminDashboard(tk.Tk):
    def __init__(self, user_manager):
        super().__init__()
        self.user_manager = user_manager
        self.title("Admin Dashboard - User Management")
        self.geometry("500x400")
        self.create_widgets()
        self.refresh_user_list()

    def create_widgets(self):
        self.user_listbox = tk.Listbox(self, width=60)
        self.user_listbox.pack(pady=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=5)

        tk.Button(btn_frame, text="Add User", command=self.add_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Edit User", command=self.edit_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete User", command=self.delete_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Refresh", command=self.refresh_user_list).pack(side=tk.LEFT, padx=5)

    def refresh_user_list(self):
        self.user_listbox.delete(0, tk.END)
        users = self.user_manager.list_users()
        for user in users:
            admin_flag = " (admin)" if user.is_admin else ""
            self.user_listbox.insert(tk.END, f"{user.username}{admin_flag} - {user.email}")

    def add_user(self):
        username = simpledialog.askstring("Username", "Enter username:", parent=self)
        if not username:
            return
        password = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
        email = simpledialog.askstring("Email", "Enter email:", parent=self)
        is_admin = messagebox.askyesno("Admin", "Is this user an admin?", parent=self)
        try:
            self.user_manager.add_user(username, password, email, is_admin)
            self.refresh_user_list()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def edit_user(self):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        username = self.user_listbox.get(selection[0]).split(" ")[0]
        user = self.user_manager.get_user(username)
        if not user:
            return
        new_email = simpledialog.askstring("Email", "Enter new email:", initialvalue=user.email, parent=self)
        is_admin = messagebox.askyesno("Admin", "Is this user an admin?", default="yes" if user.is_admin else "no", parent=self)
        try:
            self.user_manager.update_user(username, email=new_email, is_admin=is_admin)
            self.refresh_user_list()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def delete_user(self):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        username = self.user_listbox.get(selection[0]).split(" ")[0]
        if messagebox.askyesno("Delete", f"Delete user {username}?", parent=self):
            try:
                self.user_manager.delete_user(username)
                self.refresh_user_list()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self)

# Flask Blueprint for authentication API
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/login', methods=['POST'])
def login():
    """Handle login requests"""
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")
        auth_type = data.get("authType", "Local")
        token_2fa = data.get("token2fa")  # Optional: 2FA token from frontend

        if auth_type == "Database" and SQL_AVAILABLE:
            engine = get_engine()
            um = UserManager(engine)
            user = um.get_user(username)
            if not user or not getattr(user, 'is_active', True):
                return jsonify({"error": "Invalid credentials"}), 401
            
            # TODO: Use proper password hashing in production!
            if user.password != password:
                return jsonify({"error": "Invalid credentials"}), 401
            
            # 2FA check if enabled
            if getattr(user, "two_factor_enabled", False):
                if not token_2fa or not um.verify_2fa(username, token_2fa):
                    return jsonify({"error": "2FA required"}), 401
            
            # Set session or return token as needed
            session["username"] = user.username
            session["is_admin"] = user.is_admin
            return jsonify({
                "success": True, 
                "username": user.username, 
                "isAdmin": user.is_admin
            })
        else:
            # Fallback to simple authentication
            # In production, implement proper Windows/Local authentication
            if username == "admin" and password == "admin":
                session["username"] = username
                session["is_admin"] = True
                return jsonify({
                    "success": True,
                    "username": username,
                    "isAdmin": True
                })
            else:
                return jsonify({"error": "Invalid credentials"}), 401
                
    except Exception as e:
        print(f"Login error: {e}", file=sys.stderr)
        return jsonify({"error": "Authentication error"}), 500

@auth_bp.route('/api/logout', methods=['POST'])
def logout():
    """Handle logout requests"""
    try:
        session.clear()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": "Logout error"}), 500

@auth_bp.route('/api/verify', methods=['GET'])
def verify():
    """Verify current session"""
    try:
        username = session.get("username")
        if username:
            return jsonify({
                "authenticated": True,
                "username": username,
                "isAdmin": session.get("is_admin", False)
            })
        else:
            return jsonify({"authenticated": False}), 401
    except Exception as e:
        return jsonify({"error": "Verification error"}), 500

if __name__ == "__main__":
    main()