# Documentation dialogs
import os
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import centre_window, REGISTRY_PATH

def _open_project_wiki(logger=None):
    # Open the local technical wiki file.
    try:
        wiki_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'WIKI.md'))
        if not os.path.exists(wiki_path):
            messagebox.showerror("Wiki Not Found", f"WIKI.md was not found:\n{wiki_path}")
            return

        if os.name == 'nt':
            os.startfile(wiki_path)
        else:
            import webbrowser
            webbrowser.open(f"file://{wiki_path}")
    except Exception as e:
        if logger:
            logger.error(f"Failed to open WIKI.md: {e}")
        messagebox.showerror("Error", f"Failed to open WIKI.md: {e}")

def show_help_dialog(parent_window, logger=None):
    # Display help dialog with organised tabs
    try:
        help_dialog = tk.Toplevel(parent_window)
        help_dialog.title("Server Manager Dashboard - Help")
        help_dialog.transient(parent_window)
        help_dialog.grab_set()

        main_frame = ttk.Frame(help_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="Server Manager Dashboard Help",
                              font=("Segoe UI", 16, "bold"))
        title_label.pack(anchor=tk.W, pady=(0, 20))

        top_links_frame = ttk.Frame(main_frame)
        top_links_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(top_links_frame,
              text="Need full technical details? Open the project wiki:").pack(side=tk.LEFT)
        ttk.Button(top_links_frame, text="Open WIKI.md",
               command=lambda: _open_project_wiki(logger)).pack(side=tk.RIGHT)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        _add_overview_tab(notebook)
        _add_controls_tab(notebook)
        _add_server_management_tab(notebook)
        _add_troubleshooting_tab(notebook)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Close", command=help_dialog.destroy, width=15).pack(side=tk.RIGHT)

        centre_window(help_dialog, 800, 700, parent_window)

    except Exception as e:
        error_msg = f"Help dialog error: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Help failed: {str(e)}")

def _add_overview_tab(notebook):
    # Overview tab content
    overview_frame = ttk.Frame(notebook)
    notebook.add(overview_frame, text="Overview")

    overview_text = scrolledtext.ScrolledText(overview_frame, wrap=tk.WORD,
                                            width=70, height=20, font=("Segoe UI", 10))
    overview_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    overview_content = """Server Manager Dashboard

Overview

Server Manager provides desktop and web management for dedicated game servers.
The desktop dashboard focuses on day-to-day operations you can see directly in the UI:

- Add and import servers
- Start, stop, and restart servers
- Open live consoles
- Configure automation and schedules
- Monitor CPU, memory, disk, network, and uptime
- Manage updates and database tools

Supported server types shown in the app:

- Steam
- Minecraft
- Other

Quick start

1. Open the dashboard and sign in.
2. Use Add Server or Import Server to register a server.
3. Use the server list and context menu for operations.
4. Open Consoles for live output and command input.
5. Use Settings -> Updates for ServerManager update checks.

For full architecture and internals, use the Open WIKI.md button at the top."""

    overview_text.insert(tk.END, overview_content)
    overview_text.config(state=tk.DISABLED)

def _add_controls_tab(notebook):
    # Add the Controls & Shortcuts tab to the help notebook
    controls_frame = ttk.Frame(notebook)
    notebook.add(controls_frame, text="Controls & Shortcuts")

    controls_text = scrolledtext.ScrolledText(controls_frame, wrap=tk.WORD,
                                            width=70, height=20, font=("Segoe UI", 10))
    controls_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    controls_content = """Interface Controls

Main toolbar buttons

- Add Server
- Stop Server
- Import Server
- Update All
- Schedules
- Consoles
- Cluster
- Automation

Menus

- Tools menu: automation settings, verification, database update/verify, and other admin tools.
- Settings menu: dashboard/system settings, Steam credentials, and ServerManager update checks.
- Help menu: Help and About dialogs.

Server list actions

- Left-click selects a server.
- Right-click opens the server action menu.
- Double-click opens server configuration/details.

System panel

The dashboard shows live CPU, memory, disk, network, GPU (when available), and uptime values.

Web and tray access

You can also use tray actions and the web dashboard for remote management.
If something in this tab does not match your current build, check WIKI.md for the latest reference."""

    controls_text.insert(tk.END, controls_content)
    controls_text.config(state=tk.DISABLED)

def _add_server_management_tab(notebook):
    # Add the Server Management tab to the help notebook
    servers_frame = ttk.Frame(notebook)
    notebook.add(servers_frame, text="Server Management")

    servers_text = scrolledtext.ScrolledText(servers_frame, wrap=tk.WORD,
                                           width=70, height=20, font=("Segoe UI", 10))
    servers_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    servers_content = """Server Management

Adding and importing

Use Add Server for guided setup, or Import Server for existing directories/configurations.
Server types visible in UI are Steam, Minecraft, and Other.

Daily operations

From the server list and context menu you can:

- Start, stop, and restart servers
- Open server console windows
- View process details
- Open server directory
- Configure server settings
- Remove server entries (when appropriate)

Automation and scheduling

Use Automation and Schedules to configure:

- MOTD command/message and intervals
- Restart warnings and intervals
- Save/stop/start command behavior

Monitoring

Track per-server state, PID, CPU, memory, and uptime directly in dashboard views.

Data and maintenance tools

Use Tools and Settings for:

- Verify server information
- Update databases
- Verify databases
- ServerManager update checks (stable and development branch)

For implementation details and architecture, open WIKI.md."""

    servers_text.insert(tk.END, servers_content)
    servers_text.config(state=tk.DISABLED)

def _add_troubleshooting_tab(notebook):
    # Add the Troubleshooting tab to the help notebook
    troubleshooting_frame = ttk.Frame(notebook)
    notebook.add(troubleshooting_frame, text="Troubleshooting")

    troubleshooting_text = scrolledtext.ScrolledText(troubleshooting_frame, wrap=tk.WORD,
                                                   width=70, height=20, font=("Segoe UI", 10))
    troubleshooting_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    troubleshooting_content = """Troubleshooting

Common checks

- Run ServerManager with administrator privileges.
- Verify registry paths and install paths are valid.
- Confirm SteamCMD path and server executable paths are correct.
- Ensure enough free disk space and memory are available.

Server does not start

- Check server executable path and startup arguments in Configure Server.
- Open Process Details and server logs to inspect errors.
- Confirm required ports are not blocked or already in use.

Commands do not reach server

- Open server console and test a simple command.
- If needed, restart the server to rebuild stdin relay/queue paths.
- Verify the server process is still running and not stale.

Web dashboard issues

- Check web service status in dashboard/tray.
- Verify configured web port and firewall rules.
- Confirm Offline Mode is not blocking expected web actions.

Database and tools issues

- Use Update Databases to refresh Steam/Minecraft metadata.
- Use Verify Databases for integrity checks.
- If update checks fail, confirm internet access and GitHub availability.

Logs and diagnostics

- Review logs in logs/components and logs/services.
- Use Debug/diagnostics tools for deeper inspection.

Need full technical guidance?

Use the Open WIKI.md button for complete architecture, API, and operations documentation."""

    troubleshooting_text.insert(tk.END, troubleshooting_content)
    troubleshooting_text.config(state=tk.DISABLED)

def get_version_from_registry():
    # Get the current version from Windows registry
    from Modules.core.common import get_registry_value
    return get_registry_value(REGISTRY_PATH, "CurrentVersion", "Unknown")

def get_application_info():
    # Get comprehensive application information for display
    return {
        "name": "Server Manager Dashboard",
        "description": "A comprehensive game server management application for Windows systems",
        "version": get_version_from_registry(),
        "author": "Skywere Industries",
        "copyright": "© 2023-2026 Skywere Industries. All rights reserved.",
        "supported_servers": ["Steam Servers", "Minecraft Servers", "Custom Servers"],
        "features": [
            "Automated server installation and deployment",
            "Real-time system and server monitoring",
            "Process management and control",
            "Web-based remote dashboard interface",
            "Automated agent management",
            "Configuration import and export",
            "Multi-user access control",
            "Comprehensive logging and diagnostics"
        ],
        "contact": "For support and documentation, visit the project repository."
    }

def show_about_dialog(parent_window, logger=None):
    # Display a professional about dialog with comprehensive application information
    try:
        app_info = get_application_info()

        about_dialog = tk.Toplevel(parent_window)
        about_dialog.title("About Server Manager Dashboard")
        about_dialog.transient(parent_window)
        about_dialog.grab_set()
        about_dialog.resizable(True, True)
        about_dialog.minsize(420, 440)

        # Main frame with padding
        main_frame = ttk.Frame(about_dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Application name and version
        ttk.Label(main_frame, text=app_info["name"],
                 font=("Segoe UI", 16, "bold")).pack(pady=(0, 5))
        ttk.Label(main_frame, text=f"Version {app_info['version']}",
                 font=("Segoe UI", 12)).pack(pady=(0, 15))

        # Description
        desc_frame = ttk.LabelFrame(main_frame, text="Description", padding=10)
        desc_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(desc_frame, text=app_info["description"],
                 font=("Segoe UI", 10), wraplength=350).pack(anchor=tk.W)

        # Supported Server Types
        servers_frame = ttk.LabelFrame(main_frame, text="Supported Server Types", padding=10)
        servers_frame.pack(fill=tk.X, pady=(0, 10))
        servers_text = "\n".join(f"• {server}" for server in app_info["supported_servers"])
        ttk.Label(servers_frame, text=servers_text, font=("Segoe UI", 9),
                 justify=tk.LEFT).pack(anchor=tk.W)

        # Copyright and author
        ttk.Label(main_frame, text=app_info["copyright"],
                 font=("Segoe UI", 9)).pack(pady=(10, 5))
        ttk.Label(main_frame, text=app_info["contact"],
                 font=("Segoe UI", 9)).pack(pady=(0, 15))

        # Close button
        ttk.Button(main_frame, text="Close", command=about_dialog.destroy,
                  width=15).pack()

        # Centre dialog relative to parent
        centre_window(about_dialog, 400, 420, parent_window)

    except Exception as e:
        error_msg = f"Error showing about dialog: {str(e)}"
        if logger:
            logger.error(error_msg)
        messagebox.showerror("Error", f"Failed to show about dialog: {str(e)}")

# Test function for standalone testing
def test_documentation():
    # Test function to run the documentation dialogs standalone (DEBUG!)
    root = tk.Tk()
    root.title("Documentation Test")

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Documentation Module Test",
             font=("Segoe UI", 14, "bold")).pack(pady=10)

    ttk.Button(frame, text="Show Help",
              command=lambda: show_help_dialog(root)).pack(pady=5)

    ttk.Button(frame, text="Show About",
              command=lambda: show_about_dialog(root)).pack(pady=5)

    ttk.Button(frame, text="Exit", command=root.destroy).pack(pady=10)

    # Centre the test window
    centre_window(root, 400, 200)

    root.mainloop()

if __name__ == "__main__":
    test_documentation()


