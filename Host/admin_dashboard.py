import os
import sys
# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tkinter import messagebox, simpledialog
from Scripts.user_management import UserManager
from Modules.SQL_Connection import get_engine, ensure_root_admin

def main():
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
        self.geometry("600x450")
        self.create_widgets()
        self.refresh_user_list()

    def create_widgets(self):
        # Main frame
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = tk.Label(main_frame, text="Server Manager - User Administration", 
                              font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        # User list frame
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # User listbox with scrollbar
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.user_listbox = tk.Listbox(list_frame, width=80, yscrollcommand=scrollbar.set)
        self.user_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.user_listbox.yview)
        
        # Button frame
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        tk.Button(btn_frame, text="Add User", command=self.add_user, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Edit User", command=self.edit_user, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete User", command=self.delete_user, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Reset 2FA", command=self.reset_2fa, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Refresh", command=self.refresh_user_list, width=12).pack(side=tk.LEFT, padx=5)
        
        # Status frame
        status_frame = tk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.status_label = tk.Label(status_frame, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(fill=tk.X)

    def refresh_user_list(self):
        try:
            self.user_listbox.delete(0, tk.END)
            users = self.user_manager.list_users()
            for user in users:
                admin_flag = " (admin)" if user.is_admin else ""
                twofa_flag = " [2FA]" if getattr(user, "two_factor_enabled", False) else ""
                active_flag = "" if getattr(user, "is_active", True) else " [INACTIVE]"
                
                display_text = f"{user.username}{admin_flag}{twofa_flag}{active_flag} - {user.email}"
                self.user_listbox.insert(tk.END, display_text)
            
            self.status_label.config(text=f"Loaded {len(users)} users")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh user list: {str(e)}")
            self.status_label.config(text="Error loading users")

    def add_user(self):
        try:
            username = simpledialog.askstring("Username", "Enter username:", parent=self)
            if not username:
                return
                
            password = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
            if not password:
                return
                
            email = simpledialog.askstring("Email", "Enter email:", parent=self)
            if not email:
                return
                
            is_admin = messagebox.askyesno("Admin", "Is this user an admin?", parent=self)
            enable_2fa = messagebox.askyesno("2FA", "Enable 2FA for this user?", parent=self)
            
            two_factor_secret = None
            if enable_2fa:
                try:
                    import pyotp
                    two_factor_secret = pyotp.random_base32()
                except ImportError:
                    messagebox.showwarning("Warning", "pyotp not installed. 2FA will be disabled.")
                    enable_2fa = False
            
            # Add user with 2FA fields
            session = self.user_manager.Session()
            try:
                from user_management import User
                user = User(
                    username=username,
                    password=password,
                    email=email,
                    is_admin=is_admin,
                    two_factor_enabled=enable_2fa,
                    two_factor_secret=two_factor_secret,
                    is_active=True
                )
                session.add(user)
                session.commit()
                
                self.refresh_user_list()
                self.status_label.config(text=f"User '{username}' added successfully")
                
                if enable_2fa and two_factor_secret:
                    messagebox.showinfo("2FA Secret", 
                                      f"2FA Secret for {username}:\n{two_factor_secret}\n\n"
                                      "Save this secret - it won't be shown again!")
                                      
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add user: {str(e)}")

    def edit_user(self):
        try:
            selection = self.user_listbox.curselection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select a user to edit.")
                return
                
            username = self.user_listbox.get(selection[0]).split(" ")[0]
            user = self.user_manager.get_user(username)
            if not user:
                messagebox.showerror("Error", "User not found.")
                return
            
            new_email = simpledialog.askstring("Email", "Enter new email:", 
                                             initialvalue=user.email, parent=self)
            if new_email is None:  # User cancelled
                return
                
            is_admin = messagebox.askyesno("Admin", "Is this user an admin?", 
                                         default="yes" if user.is_admin else "no", parent=self)
            
            current_2fa = getattr(user, "two_factor_enabled", False)
            enable_2fa = messagebox.askyesno("2FA", "Enable 2FA for this user?", 
                                           default="yes" if current_2fa else "no", parent=self)
            
            two_factor_secret = getattr(user, "two_factor_secret", None)
            if enable_2fa and not current_2fa:
                try:
                    import pyotp
                    two_factor_secret = pyotp.random_base32()
                    messagebox.showinfo("2FA Secret", 
                                      f"New 2FA Secret for {username}:\n{two_factor_secret}\n\n"
                                      "Save this secret - it won't be shown again!")
                except ImportError:
                    messagebox.showwarning("Warning", "pyotp not installed. 2FA will be disabled.")
                    enable_2fa = False
                    two_factor_secret = None
            elif not enable_2fa:
                two_factor_secret = None
            
            self.user_manager.update_user(
                username,
                email=new_email,
                is_admin=is_admin,
                two_factor_enabled=enable_2fa,
                two_factor_secret=two_factor_secret
            )
            
            self.refresh_user_list()
            self.status_label.config(text=f"User '{username}' updated successfully")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to edit user: {str(e)}")

    def reset_2fa(self):
        try:
            selection = self.user_listbox.curselection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select a user to reset 2FA.")
                return
                
            username = self.user_listbox.get(selection[0]).split(" ")[0]
            
            if not messagebox.askyesno("Confirm Reset", 
                                     f"Reset 2FA for user '{username}'?\n\n"
                                     "This will disable 2FA for this user.", parent=self):
                return
            
            self.user_manager.update_user(
                username,
                two_factor_enabled=False,
                two_factor_secret=None
            )
            
            self.refresh_user_list()
            self.status_label.config(text=f"2FA reset for user '{username}'")
            messagebox.showinfo("2FA Reset", f"2FA has been reset for user '{username}'.", parent=self)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset 2FA: {str(e)}")

    def delete_user(self):
        try:
            selection = self.user_listbox.curselection()
            if not selection:
                messagebox.showinfo("No Selection", "Please select a user to delete.")
                return
                
            username = self.user_listbox.get(selection[0]).split(" ")[0]
            
            if username.lower() == "admin":
                messagebox.showerror("Error", "Cannot delete the main admin user.")
                return
            
            if messagebox.askyesno("Confirm Delete", 
                                 f"Are you sure you want to delete user '{username}'?\n\n"
                                 "This action cannot be undone.", parent=self):
                
                self.user_manager.delete_user(username)
                self.refresh_user_list()
                self.status_label.config(text=f"User '{username}' deleted successfully")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete user: {str(e)}")

if __name__ == "__main__":
    main()
