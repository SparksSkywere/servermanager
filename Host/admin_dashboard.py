import os
import sys
import tkinter as tk
# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tkinter import messagebox, simpledialog
from Scripts.user_management import UserManager
from Modules.SQL_Connection import get_engine, ensure_root_admin

# Import pyotp at module level for 2FA functionality
try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False
    print("Warning: pyotp not available. 2FA functionality will be disabled.")

def main():
    try:
        engine = get_engine()
        ensure_root_admin(engine)
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
        self.geometry("800x600")  # Increased size for filters
        self.all_users = []  # Store all users for filtering
        self.current_filter = {"column": "account_number", "text": "", "sort_order": "asc"}
        self.header_buttons = {}  # Store header button references
        self.create_widgets()
        self.refresh_user_list()

    def create_widgets(self):
        # Main frame
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = tk.Label(main_frame, text="Server Manager - User Administration", 
                              font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 15))
        
        # Filter frame with improved layout
        filter_frame = tk.LabelFrame(main_frame, text="Filter & Sort Options", font=("Arial", 10, "bold"), padx=10, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Top row of filter frame
        filter_top_row = tk.Frame(filter_frame)
        filter_top_row.pack(fill=tk.X, pady=(0, 8))
        
        # Filter column selection
        tk.Label(filter_top_row, text="Filter by:", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.filter_column = tk.StringVar(value="account_number")
        filter_dropdown = tk.OptionMenu(filter_top_row, self.filter_column, 
                                       "none", "account_number", "username", "name", "email", "type", "status")
        filter_dropdown.config(width=12, font=("Arial", 9))
        filter_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        
        # Search entry
        tk.Label(filter_top_row, text="Search:", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.filter_text = tk.StringVar()
        self.filter_text.trace("w", self.on_filter_change)
        filter_entry = tk.Entry(filter_top_row, textvariable=self.filter_text, width=25, font=("Arial", 9))
        filter_entry.pack(side=tk.LEFT, padx=(0, 15))
        
        # Clear button
        clear_btn = tk.Button(filter_top_row, text="Clear All", command=self.clear_filter, 
                             width=10, font=("Arial", 9))
        clear_btn.pack(side=tk.LEFT)
        
        # Bottom row - Sort options
        filter_bottom_row = tk.Frame(filter_frame)
        filter_bottom_row.pack(fill=tk.X)
        
        tk.Label(filter_bottom_row, text="Sort order:", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.sort_order = tk.StringVar(value="asc")
        sort_frame = tk.Frame(filter_bottom_row)
        sort_frame.pack(side=tk.LEFT)
        
        sort_asc_btn = tk.Radiobutton(sort_frame, text="Ascending (A-Z)", variable=self.sort_order, 
                                     value="asc", command=self.apply_filter, font=("Arial", 9))
        sort_asc_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        sort_desc_btn = tk.Radiobutton(sort_frame, text="Descending (Z-A)", variable=self.sort_order, 
                                      value="desc", command=self.apply_filter, font=("Arial", 9))
        sort_desc_btn.pack(side=tk.LEFT)
        
        # Bind filter column change
        self.filter_column.trace("w", self.on_filter_change)
        
        # User list frame
        list_frame = tk.LabelFrame(main_frame, text="User List", font=("Arial", 10, "bold"), padx=5, pady=5)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Column headers frame
        headers_frame = tk.Frame(list_frame)
        headers_frame.pack(fill=tk.X, pady=(0, 2))
        
        # Column headers - more Windows-like styling
        header_font = ("Arial", 9, "bold")
        header_bg = "#f0f0f0"
        
        # Create clickable header buttons with better styling
        self.header_buttons["account_number"] = tk.Button(headers_frame, text="Account #", font=header_font, width=10, 
                                                         relief=tk.RIDGE, bd=1, bg=header_bg,
                                                         command=lambda: self.set_filter_column("account_number"))
        self.header_buttons["account_number"].pack(side=tk.LEFT, padx=(0, 1))
        
        self.header_buttons["username"] = tk.Button(headers_frame, text="Username", font=header_font, width=12, 
                                                   relief=tk.RIDGE, bd=1, bg=header_bg,
                                                   command=lambda: self.set_filter_column("username"))
        self.header_buttons["username"].pack(side=tk.LEFT, padx=(0, 1))
        
        self.header_buttons["name"] = tk.Button(headers_frame, text="Name", font=header_font, width=18, 
                                               relief=tk.RIDGE, bd=1, bg=header_bg,
                                               command=lambda: self.set_filter_column("name"))
        self.header_buttons["name"].pack(side=tk.LEFT, padx=(0, 1))
        
        self.header_buttons["email"] = tk.Button(headers_frame, text="Email", font=header_font, width=20, 
                                                relief=tk.RIDGE, bd=1, bg=header_bg,
                                                command=lambda: self.set_filter_column("email"))
        self.header_buttons["email"].pack(side=tk.LEFT, padx=(0, 1))
        
        self.header_buttons["type"] = tk.Button(headers_frame, text="Type", font=header_font, width=8, 
                                               relief=tk.RIDGE, bd=1, bg=header_bg,
                                               command=lambda: self.set_filter_column("type"))
        self.header_buttons["type"].pack(side=tk.LEFT, padx=(0, 1))
        
        self.header_buttons["status"] = tk.Button(headers_frame, text="Status", font=header_font, width=12, 
                                                 relief=tk.RIDGE, bd=1, bg=header_bg,
                                                 command=lambda: self.set_filter_column("status"))
        self.header_buttons["status"].pack(side=tk.LEFT)
        
        # Update header appearance for default selection
        self.update_header_appearance()
        
        # User listbox with scrollbar
        listbox_frame = tk.Frame(list_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.user_listbox = tk.Listbox(listbox_frame, width=100, yscrollcommand=scrollbar.set, 
                                      font=("Consolas", 9), selectmode=tk.SINGLE)
        self.user_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.user_listbox.yview)
        
        # Actions frame
        actions_frame = tk.LabelFrame(main_frame, text="User Actions", font=("Arial", 10, "bold"), padx=10, pady=10)
        actions_frame.pack(fill=tk.X, pady=(0, 10))
        
        # First row of buttons
        btn_row1 = tk.Frame(actions_frame)
        btn_row1.pack(fill=tk.X, pady=(0, 5))
        
        tk.Button(btn_row1, text="Add User", command=self.add_user, width=15, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row1, text="Edit User", command=self.edit_user, width=15, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row1, text="Delete User", command=self.delete_user, width=15, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row1, text="Refresh List", command=self.refresh_user_list, width=15, font=("Arial", 9)).pack(side=tk.LEFT)
        
        # Second row of buttons
        btn_row2 = tk.Frame(actions_frame)
        btn_row2.pack(fill=tk.X)
        
        tk.Button(btn_row2, text="Reset Password", command=self.reset_password, width=15, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row2, text="Reset 2FA", command=self.reset_2fa, width=15, font=("Arial", 9)).pack(side=tk.LEFT)
        
        # Status frame
        self.status_label = tk.Label(main_frame, text="Ready", relief=tk.SUNKEN, anchor=tk.W, 
                                    font=("Arial", 9), bg="white")
        self.status_label.pack(fill=tk.X)

    def on_filter_change(self, *args):
        """Called when filter settings change"""
        self.apply_filter()

    def clear_filter(self):
        """Clear all filters and show all users"""
        self.filter_column.set("account_number")
        self.filter_text.set("")
        self.sort_order.set("asc")
        self.update_header_appearance()
        self.apply_filter()

    def get_user_display_data(self, user):
        """Extract display data from user object"""
        # Get user profile fields (now supported in the updated User model)
        first_name = getattr(user, "first_name", "") or ""
        last_name = getattr(user, "last_name", "") or ""
        display_name = getattr(user, "display_name", "") or ""
        # Generate a simple account number based on user ID
        account_number = f"USR{getattr(user, 'id', 0):05d}" if hasattr(user, 'id') else "N/A"
        
        full_name = f"{first_name} {last_name}".strip()
        name_display = display_name if display_name else full_name if full_name else user.username
        
        # User type
        user_type = "Admin" if user.is_admin else "User"
        
        # Status flags (excluding admin since it's now in type)
        twofa_flag = "2FA" if getattr(user, "two_factor_enabled", False) else ""
        active_flag = "Active" if getattr(user, "is_active", True) else "Inactive"
        
        status_parts = [active_flag]
        if twofa_flag:
            status_parts.append(twofa_flag)
        
        status_display = ", ".join(status_parts)
        
        return {
            "user_obj": user,
            "account_number": account_number,
            "username": user.username,
            "name": name_display,
            "email": user.email or "",
            "type": user_type,
            "status": status_display,
            "full_name": full_name,
            "display_name": display_name
        }

    def set_filter_column(self, column):
        """Set the filter column and toggle sort order if same column clicked"""
        current_column = self.filter_column.get()
        
        if current_column == column:
            # Same column clicked, toggle sort order
            current_sort = self.sort_order.get()
            new_sort = "desc" if current_sort == "asc" else "asc"
            self.sort_order.set(new_sort)
        else:
            # Different column clicked, set to ascending
            self.filter_column.set(column)
            self.sort_order.set("asc")
        
        # Clear search text when changing columns
        self.filter_text.set("")
        
        # Update header appearance and apply filter
        self.update_header_appearance()
        self.apply_filter()

    def update_header_appearance(self):
        """Update header button appearance to show selected column"""
        selected_column = self.filter_column.get()
        sort_order = self.sort_order.get()
        
        for column, button in self.header_buttons.items():
            if column == selected_column:
                # Highlight selected column
                button.config(relief=tk.SUNKEN, bg="#d0d0ff", font=("Arial", 9, "bold"))
                # Add sort indicator to button text
                base_text = button.cget("text").split(" ")[0]
                if base_text == "Account":
                    base_text = "Account #"
                sort_indicator = " ▲" if sort_order == "asc" else " ▼"
                button.config(text=base_text + sort_indicator)
            else:
                # Reset other columns
                button.config(relief=tk.RIDGE, bg="#f0f0f0", font=("Arial", 9, "bold"))
                base_text = button.cget("text").split(" ")[0]
                if base_text == "Account":
                    base_text = "Account #"
                button.config(text=base_text)

    def apply_filter(self):
        """Apply current filter and sort settings"""
        try:
            if not self.all_users:
                return
            
            filtered_users = []
            filter_col = self.filter_column.get()
            filter_text = self.filter_text.get().lower()
            
            for user_data in self.all_users:
                # Apply text filter
                if filter_col != "none" and filter_text:
                    if filter_col == "account_number":
                        search_value = user_data["account_number"].lower()
                    elif filter_col == "username":
                        search_value = user_data["username"].lower()
                    elif filter_col == "name":
                        search_value = user_data["name"].lower()
                    elif filter_col == "email":
                        search_value = user_data["email"].lower()
                    elif filter_col == "type":
                        search_value = user_data["type"].lower()
                    elif filter_col == "status":
                        search_value = user_data["status"].lower()
                    else:
                        search_value = ""
                    
                    if filter_text not in search_value:
                        continue
                
                filtered_users.append(user_data)
            
            # Sort users
            if filter_col != "none":
                sort_key = filter_col
            else:
                sort_key = "account_number"  # Default sort by account number
            
            reverse_order = (self.sort_order.get() == "desc")
            filtered_users.sort(key=lambda x: x[sort_key].lower(), reverse=reverse_order)
            
            # Update listbox
            self.user_listbox.delete(0, tk.END)
            for user_data in filtered_users:
                # Format display line with fixed-width columns
                account_num = user_data["account_number"][:9].ljust(9)
                username = user_data["username"][:11].ljust(11)
                name = user_data["name"][:17].ljust(17)
                email = user_data["email"][:19].ljust(19)
                user_type = user_data["type"][:7].ljust(7)
                status = user_data["status"][:11].ljust(11)
                
                display_line = f"{account_num} {username} {name} {email} {user_type} {status}"
                self.user_listbox.insert(tk.END, display_line)
            
            # Update status
            total_users = len(self.all_users)
            shown_users = len(filtered_users)
            if filter_col != "none" or filter_text:
                self.status_label.config(text=f"Showing {shown_users} of {total_users} users (filtered by {filter_col})")
            else:
                self.status_label.config(text=f"Loaded {total_users} users (sorted by {filter_col})")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply filter: {str(e)}")

    def refresh_user_list(self):
        try:
            users = self.user_manager.list_users()
            self.all_users = [self.get_user_display_data(user) for user in users]
            self.apply_filter()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh user list: {str(e)}")
            self.status_label.config(text="Error loading users")

    def get_selected_username(self):
        """Get username from selected listbox item"""
        selection = self.user_listbox.curselection()
        if not selection:
            return None
        
        # Get the display line and extract account number to find user
        display_line = self.user_listbox.get(selection[0])
        account_num = display_line[:9].strip()
        
        # Find user by account number
        for user_data in self.all_users:
            if user_data["account_number"] == account_num:
                return user_data["username"]
        
        return None

    def edit_user(self):
        try:
            username = self.get_selected_username()
            if not username:
                messagebox.showinfo("No Selection", "Please select a user to edit.")
                return
                
            user = self.user_manager.get_user(username)
            if not user:
                messagebox.showerror("Error", "User not found.")
                return
            
            # Create a custom dialog for editing user information
            edit_window = tk.Toplevel(self)
            edit_window.title(f"Edit User: {username}")
            edit_window.geometry("400x500")
            edit_window.transient(self)
            edit_window.grab_set()
            
            # Center the window
            edit_window.update_idletasks()
            x = (edit_window.winfo_screenwidth() // 2) - (400 // 2)
            y = (edit_window.winfo_screenheight() // 2) - (500 // 2)
            edit_window.geometry(f"400x500+{x}+{y}")
            
            # User info frame
            info_frame = tk.Frame(edit_window)
            info_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            # Account number (read-only) - generated from user ID
            tk.Label(info_frame, text="Account Number:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
            account_number = f"USR{getattr(user, 'id', 0):05d}" if hasattr(user, 'id') else "N/A"
            tk.Label(info_frame, text=account_number, bg="lightgray", relief="sunken", width=30).grid(row=0, column=1, pady=5, padx=(10, 0))
            
            # Email
            tk.Label(info_frame, text="Email:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky="w", pady=5)
            email_var = tk.StringVar(value=user.email or "")
            email_entry = tk.Entry(info_frame, textvariable=email_var, width=30)
            email_entry.grid(row=1, column=1, pady=5, padx=(10, 0))
            
            # First Name (now supported)
            tk.Label(info_frame, text="First Name:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky="w", pady=5)
            first_name_var = tk.StringVar(value=getattr(user, "first_name", "") or "")
            first_name_entry = tk.Entry(info_frame, textvariable=first_name_var, width=30)
            first_name_entry.grid(row=2, column=1, pady=5, padx=(10, 0))
            
            # Last Name (now supported)
            tk.Label(info_frame, text="Last Name:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky="w", pady=5)
            last_name_var = tk.StringVar(value=getattr(user, "last_name", "") or "")
            last_name_entry = tk.Entry(info_frame, textvariable=last_name_var, width=30)
            last_name_entry.grid(row=3, column=1, pady=5, padx=(10, 0))
            
            # Display Name (now supported)
            tk.Label(info_frame, text="Display Name:", font=("Arial", 10, "bold")).grid(row=4, column=0, sticky="w", pady=5)
            display_name_var = tk.StringVar(value=getattr(user, "display_name", "") or "")
            display_name_entry = tk.Entry(info_frame, textvariable=display_name_var, width=30)
            display_name_entry.grid(row=4, column=1, pady=5, padx=(10, 0))
            
            # Admin status
            tk.Label(info_frame, text="Admin:", font=("Arial", 10, "bold")).grid(row=5, column=0, sticky="w", pady=5)
            admin_var = tk.BooleanVar(value=user.is_admin)
            admin_check = tk.Checkbutton(info_frame, variable=admin_var)
            admin_check.grid(row=5, column=1, sticky="w", pady=5, padx=(10, 0))
            
            # 2FA status
            tk.Label(info_frame, text="2FA Enabled:", font=("Arial", 10, "bold")).grid(row=6, column=0, sticky="w", pady=5)
            current_2fa = getattr(user, "two_factor_enabled", False)
            twofa_var = tk.BooleanVar(value=current_2fa)
            twofa_check = tk.Checkbutton(info_frame, variable=twofa_var)
            twofa_check.grid(row=6, column=1, sticky="w", pady=5, padx=(10, 0))
            
            # Button frame
            btn_frame = tk.Frame(edit_window)
            btn_frame.pack(fill=tk.X, padx=20, pady=10)
            
            def save_changes():
                try:
                    two_factor_secret = getattr(user, "two_factor_secret", None)
                    enable_2fa = twofa_var.get()
                    
                    if enable_2fa and not current_2fa:
                        if PYOTP_AVAILABLE:
                            two_factor_secret = pyotp.random_base32()
                            messagebox.showinfo("2FA Secret", 
                                              f"New 2FA Secret for {username}:\n{two_factor_secret}\n\n"
                                              "Save this secret - it won't be shown again!")
                        else:
                            messagebox.showwarning("Warning", "pyotp not installed. 2FA will be disabled.")
                            enable_2fa = False
                            two_factor_secret = None
                    elif not enable_2fa:
                        two_factor_secret = None
                    
                    self.user_manager.update_user(
                        username,
                        email=email_var.get() if email_var.get().strip() else None,
                        first_name=first_name_var.get() if first_name_var.get().strip() else None,
                        last_name=last_name_var.get() if last_name_var.get().strip() else None,
                        display_name=display_name_var.get() if display_name_var.get().strip() else None,
                        is_admin=admin_var.get(),
                        two_factor_enabled=enable_2fa,
                        two_factor_secret=two_factor_secret
                    )
                    
                    edit_window.destroy()
                    self.refresh_user_list()
                    self.status_label.config(text=f"User '{username}' updated successfully")
                    
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save changes: {str(e)}")
            
            tk.Button(btn_frame, text="Save", command=save_changes, width=12).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="Cancel", command=edit_window.destroy, width=12).pack(side=tk.LEFT, padx=5)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to edit user: {str(e)}")

    def reset_2fa(self):
        try:
            username = self.get_selected_username()
            if not username:
                messagebox.showinfo("No Selection", "Please select a user to reset 2FA.")
                return
                
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
            username = self.get_selected_username()
            if not username:
                messagebox.showinfo("No Selection", "Please select a user to delete.")
                return
                
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

    def reset_password(self):
        try:
            username = self.get_selected_username()
            if not username:
                messagebox.showinfo("No Selection", "Please select a user to reset password.")
                return
                
            new_password = simpledialog.askstring("New Password", 
                                                f"Enter new password for user '{username}':", 
                                                show="*", parent=self)
            if not new_password:
                return
                
            confirm_password = simpledialog.askstring("Confirm Password", 
                                                     "Confirm new password:", 
                                                     show="*", parent=self)
            if confirm_password != new_password:
                messagebox.showerror("Error", "Passwords do not match.")
                return
            
            if self.user_manager.update_user(username, password=new_password):
                self.status_label.config(text=f"Password reset for user '{username}'")
                messagebox.showinfo("Password Reset", f"Password has been reset for user '{username}'.", parent=self)
            else:
                messagebox.showerror("Error", f"Failed to reset password for user '{username}'.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset password: {str(e)}")

    def add_user(self):
        """Add a new user"""
        try:
            # Create a custom dialog for adding user information
            add_window = tk.Toplevel(self)
            add_window.title("Add New User")
            add_window.geometry("400x450")
            add_window.transient(self)
            add_window.grab_set()
            
            # Center the window
            add_window.update_idletasks()
            x = (add_window.winfo_screenwidth() // 2) - (400 // 2)
            y = (add_window.winfo_screenheight() // 2) - (450 // 2)
            add_window.geometry(f"400x450+{x}+{y}")
            
            # User info frame
            info_frame = tk.Frame(add_window)
            info_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            
            # Username
            tk.Label(info_frame, text="Username:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
            username_var = tk.StringVar()
            username_entry = tk.Entry(info_frame, textvariable=username_var, width=30)
            username_entry.grid(row=0, column=1, pady=5, padx=(10, 0))
            username_entry.focus()
            
            # Password
            tk.Label(info_frame, text="Password:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky="w", pady=5)
            password_var = tk.StringVar()
            password_entry = tk.Entry(info_frame, textvariable=password_var, width=30, show="*")
            password_entry.grid(row=1, column=1, pady=5, padx=(10, 0))
            
            # Email
            tk.Label(info_frame, text="Email:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky="w", pady=5)
            email_var = tk.StringVar()
            email_entry = tk.Entry(info_frame, textvariable=email_var, width=30)
            email_entry.grid(row=2, column=1, pady=5, padx=(10, 0))
            
            # First Name (now supported)
            tk.Label(info_frame, text="First Name:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky="w", pady=5)
            first_name_var = tk.StringVar()
            first_name_entry = tk.Entry(info_frame, textvariable=first_name_var, width=30)
            first_name_entry.grid(row=3, column=1, pady=5, padx=(10, 0))
            
            # Last Name (now supported)
            tk.Label(info_frame, text="Last Name:", font=("Arial", 10, "bold")).grid(row=4, column=0, sticky="w", pady=5)
            last_name_var = tk.StringVar()
            last_name_entry = tk.Entry(info_frame, textvariable=last_name_var, width=30)
            last_name_entry.grid(row=4, column=1, pady=5, padx=(10, 0))
            
            # Display Name (now supported)
            tk.Label(info_frame, text="Display Name:", font=("Arial", 10, "bold")).grid(row=5, column=0, sticky="w", pady=5)
            display_name_var = tk.StringVar()
            display_name_entry = tk.Entry(info_frame, textvariable=display_name_var, width=30)
            display_name_entry.grid(row=5, column=1, pady=5, padx=(10, 0))
            
            # Admin status
            tk.Label(info_frame, text="Admin:", font=("Arial", 10, "bold")).grid(row=6, column=0, sticky="w", pady=5)
            admin_var = tk.BooleanVar(value=False)
            admin_check = tk.Checkbutton(info_frame, variable=admin_var)
            admin_check.grid(row=6, column=1, sticky="w", pady=5, padx=(10, 0))
            
            # 2FA status
            tk.Label(info_frame, text="Enable 2FA:", font=("Arial", 10, "bold")).grid(row=7, column=0, sticky="w", pady=5)
            twofa_var = tk.BooleanVar(value=False)
            twofa_check = tk.Checkbutton(info_frame, variable=twofa_var)
            twofa_check.grid(row=7, column=1, sticky="w", pady=5, padx=(10, 0))
            
            # Button frame
            btn_frame = tk.Frame(add_window)
            btn_frame.pack(fill=tk.X, padx=20, pady=10)
            
            def create_user():
                try:
                    username = username_var.get().strip()
                    password = password_var.get()
                    email = email_var.get().strip()
                    
                    if not username:
                        messagebox.showerror("Error", "Username is required.")
                        return
                    
                    if not password:
                        messagebox.showerror("Error", "Password is required.")
                        return
                    
                    # Check if user already exists
                    if self.user_manager.get_user(username):
                        messagebox.showerror("Error", f"User '{username}' already exists.")
                        return
                    
                    two_factor_secret = None
                    enable_2fa = twofa_var.get()
                    
                    if enable_2fa:
                        if PYOTP_AVAILABLE:
                            two_factor_secret = pyotp.random_base32()
                            messagebox.showinfo("2FA Secret", 
                                              f"2FA Secret for {username}:\n{two_factor_secret}\n\n"
                                              "Save this secret - it won't be shown again!")
                        else:
                            messagebox.showwarning("Warning", "pyotp not installed. 2FA will be disabled.")
                            enable_2fa = False
                    
                    # Create the user with basic parameters first
                    success = self.user_manager.add_user(
                        username=username,
                        password=password,
                        email=email if email else None,
                        is_admin=admin_var.get()
                    )
                    
                    if success:
                        # If user creation succeeded, try to update with additional fields
                        try:
                            additional_fields = {}
                            # Add profile fields (now supported in the User model)
                            if first_name_var.get().strip():
                                additional_fields['first_name'] = first_name_var.get().strip()
                            if last_name_var.get().strip():
                                additional_fields['last_name'] = last_name_var.get().strip()
                            if display_name_var.get().strip():
                                additional_fields['display_name'] = display_name_var.get().strip()
                            if enable_2fa:
                                additional_fields['two_factor_enabled'] = True
                                additional_fields['two_factor_secret'] = two_factor_secret
                                
                            # Update user with additional fields if needed
                            if additional_fields:
                                self.user_manager.update_user(username, **additional_fields)
                                
                            add_window.destroy()
                            self.refresh_user_list()
                            self.status_label.config(text=f"User '{username}' created successfully")
                            messagebox.showinfo("User Created", f"User '{username}' has been created successfully.", parent=self)
                            
                        except Exception as e:
                            # If updating additional fields fails, warn but don't fail completely
                            messagebox.showwarning("Warning", f"User created but some settings may not have been applied: {str(e)}")
                            add_window.destroy()
                            self.refresh_user_list()
                            self.status_label.config(text=f"User '{username}' created with warnings")
                    else:
                        messagebox.showerror("Error", f"Failed to create user '{username}'.")
                        
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to create user: {str(e)}")
            
            tk.Button(btn_frame, text="Create", command=create_user, width=12).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="Cancel", command=add_window.destroy, width=12).pack(side=tk.LEFT, padx=5)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open add user dialog: {str(e)}")


if __name__ == "__main__":
    main()
                            