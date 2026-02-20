# -*- coding: utf-8 -*-
# Dashboard UI components - Tkinter UI creation and dialog management
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Modules.common import setup_module_path
setup_module_path()

from Modules.server_logging import get_dashboard_logger
from Host.dashboard_functions import get_current_server_list

logger: logging.Logger = get_dashboard_logger()


def setup_ui(dashboard):
    # Create and configure the main dashboard user interface
    # Setup the menu bar first
    setup_menu_bar(dashboard)
    
    # Create loading overlay that covers the entire window during initialisation
    dashboard.loading_frame = ttk.Frame(dashboard.root)
    dashboard.loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
    dashboard.loading_frame.lift()  # Ensure it's on top
    
    # Centre the loading content
    loading_content = ttk.Frame(dashboard.loading_frame)
    loading_content.place(relx=0.5, rely=0.5, anchor="center")
    
    # Loading label with icon
    ttk.Label(loading_content, text="⏳", font=("Segoe UI", 32)).pack(pady=(0, 10))
    ttk.Label(loading_content, text="Loading Dashboard...", font=("Segoe UI", 14, "bold")).pack()
    dashboard.loading_status_label = ttk.Label(loading_content, text="Initialising...", font=("Segoe UI", 10), foreground="gray")
    dashboard.loading_status_label.pack(pady=(5, 10))
    
    # Progress bar for visual feedback
    dashboard.loading_progress = ttk.Progressbar(loading_content, mode='determinate', length=250, maximum=100)
    dashboard.loading_progress.pack(pady=(0, 10))
    dashboard.loading_progress['value'] = 0
    
    # Progress percentage label
    dashboard.loading_percentage_label = ttk.Label(loading_content, text="0%", font=("Segoe UI", 9), foreground="gray")
    dashboard.loading_percentage_label.pack(pady=(0, 10))
    
    # Create top frame for action buttons
    dashboard.top_frame = ttk.Frame(dashboard.root)
    dashboard.top_frame.pack(fill=tk.X, padx=10, pady=(8, 5))
    
    # Use DPI-aware button sizing for proper scaling
    button_width = dashboard.scale_value(14)
    button_spacing = dashboard.scale_value(4)
    
    # Action buttons on the left: Add Server, Stop Server, Import Server, Update All, Schedules, Consoles, Cluster
    dashboard.add_server_btn = ttk.Button(dashboard.top_frame, text="Add Server", 
                                    command=dashboard.add_server, width=button_width)
    dashboard.add_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.stop_server_btn = ttk.Button(dashboard.top_frame, text="Stop Server", 
                                     command=dashboard.stop_server, width=button_width)
    dashboard.stop_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.import_server_btn = ttk.Button(dashboard.top_frame, text="Import Server", 
                                       command=dashboard.import_server, width=button_width)
    dashboard.import_server_btn.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.update_all_button = ttk.Button(dashboard.top_frame, text="Update All", 
                                      command=dashboard.update_all_servers, width=button_width)
    dashboard.update_all_button.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.schedules_button = ttk.Button(dashboard.top_frame, text="Schedules", 
                                     command=dashboard.show_schedule_manager, width=button_width)
    dashboard.schedules_button.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.console_button = ttk.Button(dashboard.top_frame, text="Consoles", 
                                   command=dashboard.show_console_manager, width=button_width)
    dashboard.console_button.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.cluster_button = ttk.Button(dashboard.top_frame, text="Cluster", 
                                    command=dashboard.add_agent, width=button_width)
    dashboard.cluster_button.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    dashboard.automation_button = ttk.Button(dashboard.top_frame, text="Automation", 
                                      command=dashboard.open_automation_settings, width=button_width)
    dashboard.automation_button.pack(side=tk.LEFT, padx=(0, button_spacing))
    
    # Main container - reduced padding for tighter layout
    dashboard.container_frame = ttk.Frame(dashboard.root, padding=(10, 5, 10, 10))
    dashboard.container_frame.pack(fill=tk.BOTH, expand=True)
    
    # Configure container frame for proper resizing with grid
    dashboard.container_frame.columnconfigure(0, weight=1)
    dashboard.container_frame.rowconfigure(0, weight=1)  # Main pane takes all available space
    
    # Main layout - servers list and system info
    dashboard.main_pane = ttk.PanedWindow(dashboard.container_frame, orient=tk.HORIZONTAL)
    dashboard.main_pane.grid(row=0, column=0, sticky="nsew")
    
    # Server tabs frame (left side) - Tabbed interface for subhosts
    dashboard.servers_frame = ttk.LabelFrame(dashboard.main_pane, text="Host Servers", padding=10)
    
    # Adjust pane weights based on screen size for better responsiveness
    screen_width = dashboard.root.winfo_screenwidth()
    if screen_width < 1366:  # Smaller screens
        server_weight = 75  # Give more space to servers on small screens
        system_weight = 25
    else:  # Larger screens
        server_weight = 70
        system_weight = 30
    
    dashboard.main_pane.add(dashboard.servers_frame, weight=server_weight)
    
    # Configure servers frame for proper resizing
    dashboard.servers_frame.columnconfigure(0, weight=1)
    dashboard.servers_frame.rowconfigure(0, weight=0)
    dashboard.servers_frame.rowconfigure(1, weight=1)
    
    # Create tab navigation frame
    dashboard.tab_nav_frame = ttk.Frame(dashboard.servers_frame)
    dashboard.tab_nav_frame.pack(fill=tk.X, pady=(0, 5))
    
    # Left arrow button for tab navigation
    dashboard.left_arrow = ttk.Button(dashboard.tab_nav_frame, text="◀", width=3, command=lambda: scroll_tabs_left(dashboard))
    dashboard.left_arrow.pack(side=tk.LEFT, padx=(0, 2))
    dashboard.left_arrow.config(state=tk.DISABLED)
    
    # Right arrow button for tab navigation
    dashboard.right_arrow = ttk.Button(dashboard.tab_nav_frame, text="▶", width=3, command=lambda: scroll_tabs_right(dashboard))
    dashboard.right_arrow.pack(side=tk.RIGHT, padx=(2, 0))
    dashboard.right_arrow.config(state=tk.DISABLED)
    
    # Category control buttons
    dashboard.category_frame = ttk.Frame(dashboard.tab_nav_frame)
    dashboard.category_frame.pack(side=tk.RIGHT, padx=(10, 0))
    
    dashboard.expand_all_btn = ttk.Button(dashboard.category_frame, text="Expand All", width=10, command=lambda: expand_all_categories(dashboard))
    dashboard.expand_all_btn.pack(side=tk.LEFT, padx=(0, 2))
    
    dashboard.collapse_all_btn = ttk.Button(dashboard.category_frame, text="Collapse All", width=10, command=lambda: collapse_all_categories(dashboard))
    dashboard.collapse_all_btn.pack(side=tk.LEFT)
    
    # Tab notebook
    dashboard.server_notebook = ttk.Notebook(dashboard.servers_frame)
    dashboard.server_notebook.pack(fill=tk.BOTH, expand=True)
    
    # Dictionary to store server lists for each tab
    dashboard.server_lists = {}
    dashboard.tab_frames = {}
    
    # Initialise with local host tab
    add_subhost_tab(dashboard, "Local Host", is_local=True)
    
    # Load cluster nodes and create tabs for subhosts
    load_subhost_tabs(dashboard)
    
    # Setup right-click context menu for server lists (will be bound to each tab's treeview)
    dashboard.server_context_menu = tk.Menu(dashboard.root, tearoff=0)
    dashboard.server_context_menu.add_command(label="Add Server", command=dashboard.add_server)
    dashboard.server_context_menu.add_command(label="Refresh", command=dashboard.refresh_all)
    dashboard.server_context_menu.add_separator()
    dashboard.server_context_menu.add_command(label="Create Category", command=dashboard.create_category)
    dashboard.server_context_menu.add_command(label="Rename Category", command=dashboard.rename_category)
    dashboard.server_context_menu.add_command(label="Delete Category", command=dashboard.delete_category)
    dashboard.server_context_menu.add_separator()
    dashboard.server_context_menu.add_command(label="Start Server", command=dashboard.start_server)
    dashboard.server_context_menu.add_command(label="Stop Server", command=dashboard.stop_server)
    dashboard.server_context_menu.add_command(label="Kill Process", command=dashboard.kill_server_process)
    dashboard.server_context_menu.add_command(label="Restart Server", command=dashboard.restart_server)
    dashboard.server_context_menu.add_command(label="View Process Details", command=dashboard.view_process_details)
    dashboard.server_context_menu.add_command(label="Show Console", command=dashboard.show_server_console)
    dashboard.server_context_menu.add_command(label="Configure Server", command=dashboard.configure_server)
    dashboard.server_context_menu.add_separator()
    dashboard.server_context_menu.add_command(label="Check for Updates", command=dashboard.check_server_updates)
    dashboard.server_context_menu.add_command(label="Update Server", command=dashboard.update_server)
    dashboard.server_context_menu.add_command(label="Schedule", command=dashboard.show_server_schedule)
    dashboard.server_context_menu.add_command(label="Console Manager", command=dashboard.show_console_manager)
    dashboard.server_context_menu.add_separator()
    dashboard.server_context_menu.add_command(label="Export Server", command=dashboard.export_server)
    dashboard.server_context_menu.add_command(label="Open Folder Directory", command=dashboard.open_server_directory)
    dashboard.server_context_menu.add_command(label="Remove Server", command=dashboard.remove_server)
    
    # Collapse toggle frame (vertical bar between panes with centred arrow)
    dashboard.system_info_visible = dashboard.variables.get("systemInfoVisible", True)
    dashboard.collapse_frame = ttk.Frame(dashboard.main_pane, width=20)
    dashboard.main_pane.add(dashboard.collapse_frame, weight=0)
    
    # Configure collapse frame to centre the button vertically
    dashboard.collapse_frame.columnconfigure(0, weight=1)
    dashboard.collapse_frame.rowconfigure(0, weight=1)
    dashboard.collapse_frame.rowconfigure(1, weight=0)
    dashboard.collapse_frame.rowconfigure(2, weight=1)
    
    # Collapse/Expand toggle button (centred vertically with horizontal arrows)
    dashboard.system_toggle_btn = ttk.Button(
        dashboard.collapse_frame,
        text="◀" if dashboard.system_info_visible else "▶",
        width=2,
        command=dashboard.toggle_system_info
    )
    dashboard.system_toggle_btn.grid(row=1, column=0, pady=5)
    
    # System info frame (right side)
    dashboard.system_frame = ttk.LabelFrame(dashboard.main_pane, text="System Information", padding=10)
    if dashboard.system_info_visible:
        dashboard.main_pane.add(dashboard.system_frame, weight=system_weight)
    
    # Configure system frame for proper resizing
    dashboard.system_frame.columnconfigure(0, weight=1)
    dashboard.system_frame.rowconfigure(0, weight=0)  # Header
    dashboard.system_frame.rowconfigure(1, weight=1)  # Metrics
    
    # System info header
    dashboard.system_header = ttk.Frame(dashboard.system_frame)
    dashboard.system_header.pack(fill=tk.X, pady=(0, 15))
    
    dashboard.system_name = ttk.Label(dashboard.system_header, text="Loading system info...", font=("Segoe UI", 14, "bold"))
    dashboard.system_name.pack(anchor=tk.W, pady=(0, 5))
    
    dashboard.os_info = ttk.Label(dashboard.system_header, text="Loading OS info...", foreground="gray")
    dashboard.os_info.pack(anchor=tk.W, pady=(0, 5))
    
    # Show installation info from registry
    if hasattr(dashboard, 'registry_values'):
        install_info = ttk.Label(dashboard.system_header, 
            text=f"Version: {dashboard.registry_values.get('CurrentVersion', 'Unknown')} | "
                 f"Host Type: {dashboard.registry_values.get('HostType', 'Unknown')}", 
            foreground="gray")
        install_info.pack(anchor=tk.W, pady=(0, 8))
    
    # Web server status
    dashboard.webserver_frame = ttk.Frame(dashboard.system_header)
    dashboard.webserver_frame.pack(anchor=tk.W, pady=(0, 10))
    
    ttk.Label(dashboard.webserver_frame, text="Web Server: ").pack(side=tk.LEFT)
    dashboard.webserver_status = ttk.Label(dashboard.webserver_frame, text="Checking...", foreground="gray")
    dashboard.webserver_status.pack(side=tk.LEFT)
    
    # Offline mode toggle
    dashboard.offline_var = tk.BooleanVar(value=dashboard.variables["offlineMode"])
    dashboard.offline_check = ttk.Checkbutton(
        dashboard.webserver_frame,
        text="Offline Mode",
        variable=dashboard.offline_var,
        command=dashboard.toggle_offline_mode
    )
    dashboard.offline_check.pack(side=tk.LEFT, padx=(15, 0))
    
    # System metrics grid
    dashboard.metrics_frame = ttk.Frame(dashboard.system_frame, padding=(0, 10, 0, 0))
    dashboard.metrics_frame.pack(fill=tk.BOTH, expand=True)
    
    # Configure grid layout with proper weights for uniform sizing
    for i in range(2):
        dashboard.metrics_frame.columnconfigure(i, weight=1, uniform="metric_col")
    for i in range(3):
        dashboard.metrics_frame.rowconfigure(i, weight=1, uniform="metric_row")
    
    # Create metric panels with uniform sizing
    dashboard.metric_labels = {}
    
    metrics = [
        {"row": 0, "col": 0, "title": "CPU", "name": "cpu", "icon": ""},
        {"row": 0, "col": 1, "title": "Memory", "name": "memory", "icon": ""},
        {"row": 1, "col": 0, "title": "Disk Space", "name": "disk", "icon": ""},
        {"row": 1, "col": 1, "title": "Network", "name": "network", "icon": ""},
        {"row": 2, "col": 0, "title": "GPU", "name": "gpu", "icon": ""},
        {"row": 2, "col": 1, "title": "System Uptime", "name": "uptime", "icon": ""}
    ]
    
    for metric in metrics:
        # Create frame with responsive sizing - use DPI-aware padding
        scaled_padding = dashboard.scale_value(8)
        frame = ttk.LabelFrame(dashboard.metrics_frame, text=f"{metric['icon']} {metric['title']}", padding=scaled_padding)
        frame.grid(row=metric["row"], column=metric["col"], padx=3, pady=3, sticky="nsew")
        
        # Let the frame size naturally based on content
        # Don't use fixed heights - this was causing the button bar to be pushed off screen
        # The grid with uniform sizing will handle proportional sizing
        
        # Create value label with DPI-aware wrapping
        # Calculate wrap width based on screen size and DPI
        screen_width = dashboard.root.winfo_screenwidth()
        base_wrap = 150 if metric["name"] == "gpu" else 120
        
        # Scale the wrap width based on screen size ratio and DPI
        screen_scale = screen_width / 1920.0  # Normalise to 1080p base
        wrap_width = int(base_wrap * max(0.7, min(1.5, screen_scale)) * dashboard.dpi_scale)
        
        # Use DPI-aware font size
        font_size = dashboard.scale_value(9)
        value = ttk.Label(frame, text="Loading...", font=("Segoe UI", font_size), wraplength=wrap_width, justify=tk.LEFT)
        value.pack(anchor=tk.W, fill=tk.BOTH, expand=True)
        
        dashboard.metric_labels[metric["name"]] = value


def setup_menu_bar(dashboard):
    # Setup the menu bar
    dashboard.menubar = tk.Menu(dashboard.root)
    dashboard.root.config(menu=dashboard.menubar)
    
    # File Menu
    file_menu = tk.Menu(dashboard.menubar, tearoff=0)
    dashboard.menubar.add_cascade(label="File", menu=file_menu)
    file_menu.add_command(label="Settings", command=dashboard.show_settings_dialog)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=dashboard.on_close)
    
    # Tools Menu
    tools_menu = tk.Menu(dashboard.menubar, tearoff=0)
    dashboard.menubar.add_cascade(label="Tools", menu=tools_menu)
    tools_menu.add_command(label="Find Broken Servers", command=dashboard.find_broken_servers)
    tools_menu.add_command(label="Verify Server Information", command=dashboard.verify_servers)
    tools_menu.add_separator()
    tools_menu.add_command(label="Update Databases", command=dashboard.update_databases)
    tools_menu.add_command(label="Verify Databases", command=dashboard.verify_databases)
    
    # Help Menu
    help_menu = tk.Menu(dashboard.menubar, tearoff=0)
    dashboard.menubar.add_cascade(label="Help", menu=help_menu)
    help_menu.add_command(label="About", command=dashboard.show_about)
    help_menu.add_command(label="Help", command=dashboard.show_help)


def add_subhost_tab(dashboard, subhost_name, is_local=False):
    # Add a new tab for a subhost
    # Create tab frame
    tab_frame = ttk.Frame(dashboard.server_notebook)
    dashboard.tab_frames[subhost_name] = tab_frame
    
    # Configure tab frame for proper resizing
    tab_frame.columnconfigure(0, weight=1)
    tab_frame.rowconfigure(0, weight=1)
    
    # Create server list for this tab
    columns = ("name", "status", "pid", "cpu", "memory", "uptime")
    server_list = ttk.Treeview(tab_frame, columns=columns, show="tree headings")
    
    # Column headings
    server_list.heading("#0", text="Categories")
    server_list.heading("name", text="Server Name")
    server_list.heading("status", text="Status")
    server_list.heading("pid", text="PID")
    server_list.heading("cpu", text="CPU Usage")
    server_list.heading("memory", text="Memory Usage")
    server_list.heading("uptime", text="Uptime")

    # Column widths - adjust based on screen size
    screen_width = dashboard.root.winfo_screenwidth()
    if screen_width < 1366:  # Smaller screens
        name_width, name_min = 150, 120
        status_width, status_min = 80, 60
        pid_width, pid_min = 60, 50
        cpu_width, cpu_min = 80, 60
        memory_width, memory_min = 100, 80
        uptime_width, uptime_min = 120, 100
    else:  # Larger screens
        name_width, name_min = 200, 150
        status_width, status_min = 100, 80
        pid_width, pid_min = 80, 60
        cpu_width, cpu_min = 100, 80
        memory_width, memory_min = 120, 100
        uptime_width, uptime_min = 160, 120
    
    server_list.column("#0", width=200, minwidth=150, anchor=tk.W)
    server_list.column("name", width=name_width, minwidth=name_min, anchor=tk.W)
    server_list.column("status", width=status_width, minwidth=status_min, anchor=tk.CENTER)
    server_list.column("pid", width=pid_width, minwidth=pid_min, anchor=tk.CENTER)
    server_list.column("cpu", width=cpu_width, minwidth=cpu_min, anchor=tk.CENTER)
    server_list.column("memory", width=memory_width, minwidth=memory_min, anchor=tk.CENTER)
    server_list.column("uptime", width=uptime_width, minwidth=uptime_min, anchor=tk.CENTER)
    
    # Add scrollbar
    server_scroll = ttk.Scrollbar(tab_frame, orient=tk.VERTICAL, command=server_list.yview)
    server_list.configure(yscrollcommand=server_scroll.set)
    
    server_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
    server_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
    # Bind events
    server_list.bind("<Button-3>", lambda e: show_server_context_menu(dashboard, e))
    server_list.bind("<Button-1>", lambda e: on_server_list_click(dashboard, e))
    server_list.bind("<Double-1>", lambda e: on_server_double_click(dashboard, e))
    
    # Bind drag-and-drop events for category management
    server_list.bind("<ButtonPress-1>", lambda e: on_drag_start(dashboard, e))
    server_list.bind("<B1-Motion>", lambda e: on_drag_motion(dashboard, e))
    server_list.bind("<ButtonRelease-1>", lambda e: on_drag_release(dashboard, e))
    
    # Store reference
    dashboard.server_lists[subhost_name] = server_list
    
    # Add tab to notebook
    display_name = subhost_name if is_local else f"Remote {subhost_name}"
    dashboard.server_notebook.add(tab_frame, text=display_name)
    
    # Update navigation arrows
    update_tab_navigation(dashboard)
    
    logger.info(f"Added tab for subhost: {subhost_name}")


def remove_subhost_tab(dashboard, subhost_name):
    # Remove a tab for a subhost
    if subhost_name in dashboard.tab_frames:
        # Remove from notebook
        tab_index = dashboard.server_notebook.index(dashboard.tab_frames[subhost_name])
        dashboard.server_notebook.forget(tab_index)
        
        # Clean up references
        del dashboard.server_lists[subhost_name]
        del dashboard.tab_frames[subhost_name]
        
        # Update navigation arrows
        update_tab_navigation(dashboard)
        
        logger.info(f"Removed tab for subhost: {subhost_name}")


def load_subhost_tabs(dashboard):
    # Load tabs for all available subhosts
    try:
        # Import agent manager
        from Modules.agents import AgentManager
        agent_manager = AgentManager()
        
        # Add tabs for each cluster node
        for node_name, node in agent_manager.nodes.items():
            if node_name.lower() != "local host":
                add_subhost_tab(dashboard, node_name, is_local=False)
        
        logger.info(f"Loaded {len(agent_manager.nodes)} subhost tabs")
        
    except Exception as e:
        logger.warning(f"Could not load subhost tabs: {e}")


def update_tab_navigation(dashboard):
    # Update the state of navigation arrows based on tab count and visibility
    tab_count = len(dashboard.server_notebook.tabs())
    
    if tab_count <= 5:  # If 5 or fewer tabs, no need for navigation
        dashboard.left_arrow.config(state=tk.DISABLED)
        dashboard.right_arrow.config(state=tk.DISABLED)
    else:
        # Enable navigation arrows
        dashboard.left_arrow.config(state=tk.NORMAL)
        dashboard.right_arrow.config(state=tk.NORMAL)


def scroll_tabs_left(dashboard):
    # Scroll tabs to the left
    current_tab = dashboard.server_notebook.index(dashboard.server_notebook.select())
    if current_tab > 0:
        dashboard.server_notebook.select(current_tab - 1)


def scroll_tabs_right(dashboard):
    # Scroll tabs to the right
    current_tab = dashboard.server_notebook.index(dashboard.server_notebook.select())
    if current_tab < len(dashboard.server_notebook.tabs()) - 1:
        dashboard.server_notebook.select(current_tab + 1)


def expand_all_categories(dashboard):
    # Expand all categories in the current server list
    # Debounce check to prevent rapid clicking issues
    if hasattr(dashboard, '_expanding_categories') and dashboard._expanding_categories:
        return
    dashboard._expanding_categories = True
    
    try:
        current_list = get_current_server_list(dashboard)
        if not current_list:
            return
        
        # Disable button during operation to prevent rapid clicks
        if hasattr(dashboard, 'expand_all_btn'):
            dashboard.expand_all_btn.config(state=tk.DISABLED)
        
        # Find all category items (items with no server name)
        for item in current_list.get_children():
            try:
                if current_list.exists(item):
                    item_values = current_list.item(item)['values']
                    if item_values and not item_values[1]:  # No server name = category
                        current_list.item(item, open=True)
            except tk.TclError:
                # Item may have been deleted during iteration
                continue
                
    except Exception as e:
        logger.error(f"Error expanding categories: {str(e)}")
    finally:
        dashboard._expanding_categories = False
        # Re-enable button after a short delay
        if hasattr(dashboard, 'expand_all_btn'):
            dashboard.root.after(100, lambda: dashboard.expand_all_btn.config(state=tk.NORMAL))


def collapse_all_categories(dashboard):
    # Collapse all categories in the current server list
    # Debounce check to prevent rapid clicking issues
    if hasattr(dashboard, '_collapsing_categories') and dashboard._collapsing_categories:
        return
    dashboard._collapsing_categories = True
    
    try:
        current_list = get_current_server_list(dashboard)
        if not current_list:
            return
        
        # Disable button during operation to prevent rapid clicks
        if hasattr(dashboard, 'collapse_all_btn'):
            dashboard.collapse_all_btn.config(state=tk.DISABLED)
        
        # Find all category items (items with no server name)
        for item in current_list.get_children():
            try:
                if current_list.exists(item):
                    item_values = current_list.item(item)['values']
                    if item_values and not item_values[1]:  # No server name = category
                        current_list.item(item, open=False)
            except tk.TclError:
                # Item may have been deleted during iteration
                continue
                
    except Exception as e:
        logger.error(f"Error collapsing categories: {str(e)}")
    finally:
        dashboard._collapsing_categories = False
        # Re-enable button after a short delay
        if hasattr(dashboard, 'collapse_all_btn'):
            dashboard.root.after(100, lambda: dashboard.collapse_all_btn.config(state=tk.NORMAL))


def show_server_context_menu(dashboard, event):
    # Show context menu on right-click in server list
    current_list = get_current_server_list(dashboard)
    if not current_list:
        return
        
    item = current_list.identify_row(event.y)
    
    if item:
        current_list.selection_set(item)
        # Enable server-specific options
        dashboard.server_context_menu.entryconfigure("Open Folder Directory", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Remove Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Start Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Stop Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Restart Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("View Process Details", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Show Console", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Configure Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Export Server", state=tk.NORMAL)
        dashboard.server_context_menu.entryconfigure("Kill Process", state=tk.NORMAL)
    else:
        # Disable server-specific options
        dashboard.server_context_menu.entryconfigure("Open Folder Directory", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Remove Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Start Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Stop Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Restart Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("View Process Details", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Show Console", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Configure Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Export Server", state=tk.DISABLED)
        dashboard.server_context_menu.entryconfigure("Kill Process", state=tk.DISABLED)
        
    # Show context menu
    dashboard.server_context_menu.tk_popup(event.x_root, event.y_root)


def on_server_list_click(dashboard, event):
    # Handle left-click on server list - deselect all if clicking on empty space
    current_list = get_current_server_list(dashboard)
    if not current_list:
        return
        
    item = current_list.identify_row(event.y)
    
    if not item:
        # Clicked on empty space - clear all selections (like Windows Explorer)
        # Only clear if there are actually items in the list and not during refresh
        if current_list.get_children() and not getattr(dashboard, '_refreshing_server_list', False):
            current_list.selection_remove(current_list.selection())
            logger.debug("Cleared server list selection due to empty space click")


def on_server_double_click(dashboard, event):
    # Handle double-click on server list - open configuration dialog
    current_list = get_current_server_list(dashboard)
    if not current_list:
        return
        
    item = current_list.identify_row(event.y)
    
    if item:
        # Double-clicked on a server - open configuration
        current_list.selection_set(item)
        dashboard.configure_server()


def on_drag_start(dashboard, event):
    # Handle drag start for server/category movement
    current_list = get_current_server_list(dashboard)
    if not current_list:
        return
        
    # Get the region where the click occurred
    region = current_list.identify_region(event.x, event.y)
    
    # Only allow dragging from data cells, not tree column
    if region != "cell":
        return
        
    item = current_list.identify_row(event.y)
    if not item:
        return
    
    # Get item values
    item_values = current_list.item(item)['values']
    
    # Only allow dragging servers, not categories
    if not item_values or not item_values[1]:  # No server name = category
        return
        
    # Store drag information
    dashboard._drag_item = item
    dashboard._drag_start_y = event.y
    dashboard._drag_data = item_values
    dashboard._drag_active = False  # Will be set to True when drag threshold is exceeded
    dashboard._highlighted_category = None
    
    # Highlight the dragged item
    current_list.selection_set(item)


def on_drag_motion(dashboard, event):
    # Handle drag motion - provide visual feedback
    if not hasattr(dashboard, '_drag_item') or not dashboard._drag_item:
        return
        
    current_list = get_current_server_list(dashboard)
    if not current_list:
        return
    
    # Check if we've moved enough to start the drag
    if not getattr(dashboard, '_drag_active', False):
        if abs(event.y - dashboard._drag_start_y) > 5:  # 5 pixel threshold
            dashboard._drag_active = True
            # Create floating drag indicator
            _create_drag_indicator(dashboard, current_list, dashboard._drag_data[0] if dashboard._drag_data else "")
        else:
            return
    
    # Update drag indicator position
    if hasattr(dashboard, '_drag_indicator') and dashboard._drag_indicator:
        try:
            # Position indicator near cursor
            x = current_list.winfo_rootx() + event.x + 15
            y = current_list.winfo_rooty() + event.y + 10
            dashboard._drag_indicator.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        
    # Get the region where the mouse is
    region = current_list.identify_region(event.x, event.y)
    
    # Clear previous highlight
    _clear_category_highlight(dashboard, current_list)
    
    # Only provide feedback for cell regions
    if region != "cell":
        current_list.config(cursor="no")
        _update_drag_indicator(dashboard, False, "")
        return
        
    # Get current position
    current_item = current_list.identify_row(event.y)
    
    # Provide visual feedback
    if current_item and current_item != dashboard._drag_item:
        # Check if this is a valid drop target (category or item under category)
        target_values = current_list.item(current_item)['values']
        
        # Find the parent category for the target
        parent = current_list.parent(current_item)
        if not target_values[1]:  # No server name = this IS a category
            category_item = current_item
            category_name = target_values[0]
        elif parent:  # Server under a category
            category_item = parent
            category_name = current_list.item(parent)['values'][0]
        else:
            category_item = None
            category_name = ""
        
        if category_item:
            current_list.config(cursor="hand2")  # Hand cursor for valid drop
            _highlight_category(dashboard, current_list, category_item)
            _update_drag_indicator(dashboard, True, category_name)
        else:
            current_list.config(cursor="no")  # No cursor for invalid drop
            _update_drag_indicator(dashboard, False, "")
    else:
        current_list.config(cursor="")
        _update_drag_indicator(dashboard, False, "")


def _create_drag_indicator(dashboard, parent, server_name):
    # Create a floating drag indicator window
    try:
        # Destroy existing indicator if any
        if hasattr(dashboard, '_drag_indicator') and dashboard._drag_indicator:
            try:
                dashboard._drag_indicator.destroy()
            except tk.TclError:
                pass
        
        # Create toplevel window for drag indicator
        dashboard._drag_indicator = tk.Toplevel(dashboard.root)
        dashboard._drag_indicator.overrideredirect(True)  # No window decorations
        dashboard._drag_indicator.attributes('-alpha', 0.85)  # Slightly transparent
        dashboard._drag_indicator.attributes('-topmost', True)
        
        # Create frame with border
        frame = tk.Frame(dashboard._drag_indicator, bg='#4a90d9', padx=2, pady=2)
        frame.pack(fill=tk.BOTH, expand=True)
        
        inner_frame = tk.Frame(frame, bg='#f0f0f0', padx=8, pady=4)
        inner_frame.pack(fill=tk.BOTH, expand=True)
        
        # Server name label
        dashboard._drag_label = tk.Label(inner_frame, text=f"📦 {server_name}", 
                                        bg='#f0f0f0', fg='#333333',
                                        font=('Segoe UI', 9, 'bold'))
        dashboard._drag_label.pack(side=tk.LEFT)
        
        # Target category label
        dashboard._drag_target_label = tk.Label(inner_frame, text="", 
                                               bg='#f0f0f0', fg='#666666',
                                               font=('Segoe UI', 8))
        dashboard._drag_target_label.pack(side=tk.LEFT, padx=(10, 0))
        
    except Exception as e:
        logger.debug(f"Error creating drag indicator: {e}")


def _update_drag_indicator(dashboard, valid, category_name):
    # Update the drag indicator to show target status
    try:
        if hasattr(dashboard, '_drag_target_label') and dashboard._drag_target_label:
            if valid and category_name:
                dashboard._drag_target_label.config(text=f'→ {category_name}', fg='#2e7d32')  # Green
            elif not valid:
                dashboard._drag_target_label.config(text='✗ Invalid target', fg='#c62828')  # Red
            else:
                dashboard._drag_target_label.config(text='')
    except (tk.TclError, AttributeError):
        pass


def _destroy_drag_indicator(dashboard):
    # Destroy the drag indicator window
    try:
        if hasattr(dashboard, '_drag_indicator') and dashboard._drag_indicator:
            dashboard._drag_indicator.destroy()
            dashboard._drag_indicator = None
    except tk.TclError:
        pass


def _highlight_category(dashboard, treeview, category_item):
    # Highlight a category row to show it's a valid drop target
    try:
        # Store the highlighted category
        dashboard._highlighted_category = category_item
        
        # Add highlight tag
        current_tags = list(treeview.item(category_item, 'tags'))
        if 'drop_target' not in current_tags:
            current_tags.append('drop_target')
            treeview.item(category_item, tags=current_tags)
        
        # Configure the drop_target tag style
        treeview.tag_configure('drop_target', background='#c8e6c9')  # Light green
        
    except Exception as e:
        logger.debug(f'Error highlighting category: {e}')


def _clear_category_highlight(dashboard, treeview):
    # Clear any category highlighting
    try:
        if hasattr(dashboard, '_highlighted_category') and dashboard._highlighted_category:
            try:
                current_tags = list(treeview.item(dashboard._highlighted_category, 'tags'))
                if 'drop_target' in current_tags:
                    current_tags.remove('drop_target')
                    treeview.item(dashboard._highlighted_category, tags=current_tags)
            except tk.TclError:
                pass
        dashboard._highlighted_category = None
    except (tk.TclError, AttributeError):
        pass


def on_drag_release(dashboard, event):
    # Handle drag release - move server to new category
    current_list = get_current_server_list(dashboard)
    
    try:
        # Clean up visual elements first
        if current_list:
            current_list.config(cursor="")
            _clear_category_highlight(dashboard, current_list)
        _destroy_drag_indicator(dashboard)
        
        # Check if we were actually dragging
        if not hasattr(dashboard, '_drag_item') or not dashboard._drag_item:
            return
        
        if not getattr(dashboard, '_drag_active', False):
            # Was just a click, not a drag
            dashboard._drag_item = None
            dashboard._drag_data = None
            dashboard._drag_active = False
            return
            
        if not current_list:
            return
        
        # Check if we're releasing over a valid drop region
        region = current_list.identify_region(event.x, event.y)
        
        # Get drop target
        drop_item = current_list.identify_row(event.y)
        if not drop_item or drop_item == dashboard._drag_item:
            return
        
        # Find the target category
        drop_values = current_list.item(drop_item)['values']
        parent = current_list.parent(drop_item)
        
        if not drop_values[1]:  # No server name = this IS a category
            target_category = drop_values[0]
        elif parent:  # Server under a category - use parent category
            parent_values = current_list.item(parent)['values']
            target_category = parent_values[0]
        else:
            messagebox.showinfo("Invalid Target", "Please drop onto a category.")
            return
            
        # Get source data
        source_values = dashboard._drag_data
        if not source_values or not source_values[1]:  # Not a server
            return
            
        server_name = source_values[0]
        
        # Get current category from parent of dragged item
        drag_parent = current_list.parent(dashboard._drag_item)
        if drag_parent:
            current_category = current_list.item(drag_parent)['values'][0]
        else:
            current_category = "Uncategorized"
        
        # Don't move if already in target category
        if current_category == target_category:
            return
            
        # Move server to new category
        dashboard._move_server_to_category(server_name, target_category)
        
        # Refresh categories immediately for instant visual feedback
        dashboard.refresh_categories()
        
        logger.info(f"Moved server '{server_name}' from '{current_category}' to category '{target_category}'")
            
    except Exception as e:
        logger.error(f"Error during drag-and-drop: {str(e)}")
        messagebox.showerror("Error", f"Failed to move item: {str(e)}")
        
    finally:
        # Always clear drag state
        dashboard._drag_item = None
        dashboard._drag_data = None
        dashboard._drag_active = False
        dashboard._highlighted_category = None
