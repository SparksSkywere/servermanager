import os
import sys
# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tkinter as tk
from tkinter import messagebox, simpledialog
from user_management import UserManager
from Modules.SQL_Connection import get_engine

def main():
    engine = get_engine()
    um = UserManager(engine)
    app = AdminDashboard(um)
    app.mainloop()

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

if __name__ == "__main__":
    main()

from flask import Blueprint, request, jsonify, session
from Scripts.user_management import UserManager
from Modules.SQL_Connection import get_engine

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    auth_type = data.get("authType", "Local")
    token_2fa = data.get("token2fa")  # Optional: 2FA token from frontend

    if auth_type == "Database":
        engine = get_engine()
        um = UserManager(engine)
        user = um.get_user(username)
        if not user or not user.is_active:
            return jsonify({"error": "Invalid credentials"}), 401
        # TODO: Use password hashing in production!
        if user.password != password:
            return jsonify({"error": "Invalid credentials"}), 401
        # 2FA check if enabled
        if getattr(user, "two_factor_enabled", False):
            if not token_2fa or not um.verify_2fa(username, token_2fa):
                return jsonify({"error": "2FA required"}), 401
        # Set session or return token as needed
        session["username"] = user.username
        session["is_admin"] = user.is_admin
        return jsonify({"success": True, "username": user.username, "isAdmin": user.is_admin})
    else:
        # ...existing Windows/Local authentication...
        pass