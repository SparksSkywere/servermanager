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
        self.geometry("600x450")
        self.create_widgets()
        self.refresh_user_list()

    def create_widgets(self):
        self.user_listbox = tk.Listbox(self, width=80)
        self.user_listbox.pack(pady=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=5)

        tk.Button(btn_frame, text="Add User", command=self.add_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Edit User", command=self.edit_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete User", command=self.delete_user).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Reset 2FA", command=self.reset_2fa).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Refresh", command=self.refresh_user_list).pack(side=tk.LEFT, padx=5)

    def refresh_user_list(self):
        self.user_listbox.delete(0, tk.END)
        users = self.user_manager.list_users()
        for user in users:
            admin_flag = " (admin)" if user.is_admin else ""
            twofa_flag = " [2FA]" if getattr(user, "two_factor_enabled", False) else ""
            self.user_listbox.insert(
                tk.END,
                f"{user.username}{admin_flag}{twofa_flag} - {user.email}"
            )

    def add_user(self):
        username = simpledialog.askstring("Username", "Enter username:", parent=self)
        if not username:
            return
        password = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
        email = simpledialog.askstring("Email", "Enter email:", parent=self)
        is_admin = messagebox.askyesno("Admin", "Is this user an admin?", parent=self)
        enable_2fa = messagebox.askyesno("2FA", "Enable 2FA for this user?", parent=self)
        two_factor_secret = None
        if enable_2fa:
            import pyotp
            two_factor_secret = pyotp.random_base32()
        try:
            # Add user with 2FA fields
            session = self.user_manager.Session()
            from user_management import User
            user = User(
                username=username,
                password=password,
                email=email,
                is_admin=is_admin,
                two_factor_enabled=enable_2fa,
                two_factor_secret=two_factor_secret
            )
            session.add(user)
            session.commit()
            session.close()
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
        enable_2fa = messagebox.askyesno("2FA", "Enable 2FA for this user?", default="yes" if user.two_factor_enabled else "no", parent=self)
        two_factor_secret = user.two_factor_secret
        if enable_2fa and not user.two_factor_enabled:
            import pyotp
            two_factor_secret = pyotp.random_base32()
        elif not enable_2fa:
            two_factor_secret = None
        try:
            self.user_manager.update_user(
                username,
                email=new_email,
                is_admin=is_admin,
                two_factor_enabled=enable_2fa,
                two_factor_secret=two_factor_secret
            )
            self.refresh_user_list()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def reset_2fa(self):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        username = self.user_listbox.get(selection[0]).split(" ")[0]
        if not messagebox.askyesno("Reset 2FA", f"Reset 2FA for user {username}?", parent=self):
            return
        try:
            self.user_manager.update_user(
                username,
                two_factor_enabled=False,
                two_factor_secret=None
            )
            self.refresh_user_list()
            messagebox.showinfo("2FA Reset", f"2FA has been reset for user {username}.", parent=self)
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
