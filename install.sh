#!/bin/bash
set -e  # Exit on any error

# Configuration
CURRENT_VERSION="0.9"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/Install-Log.txt"
SERVER_MANAGER_DIR=""
STEAMCMD_DIR="$HOME/SteamCMD"
WORKSPACE_DIR="$STEAMCMD_DIR/user_workspace"
PYTHON_CMD=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    echo "[$level] $message"
}

log_info() {
    log "INFO" "$1"
}

log_error() {
    log "ERROR" "$1"
    echo -e "${RED}ERROR: $1${NC}" >&2
}

log_success() {
    log "SUCCESS" "$1"
    echo -e "${GREEN}SUCCESS: $1${NC}"
}

log_warning() {
    log "WARNING" "$1"
    echo -e "${YELLOW}WARNING: $1${NC}"
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "This script should not be run as root. Please run as a regular user."
        exit 1
    fi
}

# Detect package manager
detect_package_manager() {
    if command -v apt-get &> /dev/null; then
        echo "apt"
    elif command -v yum &> /dev/null; then
        echo "yum"
    elif command -v dnf &> /dev/null; then
        echo "dnf"
    elif command -v pacman &> /dev/null; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

# Install package using detected package manager
install_package() {
    local package="$1"
    local pm=$(detect_package_manager)

    case $pm in
        apt)
            sudo apt-get update && sudo apt-get install -y "$package"
            ;;
        yum)
            sudo yum install -y "$package"
            ;;
        dnf)
            sudo dnf install -y "$package"
            ;;
        pacman)
            sudo pacman -S --noconfirm "$package"
            ;;
        *)
            log_error "Unsupported package manager. Please install $package manually."
            return 1
            ;;
    esac
}

# Find Python executable
find_python() {
    local python_cmds=("python3" "python" "python3.10" "python3.9" "python3.8")

    for cmd in "${python_cmds[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            # Check version
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
                PYTHON_CMD="$cmd"
                log_info "Found suitable Python: $PYTHON_CMD"
                return 0
            fi
        fi
    done

    log_error "Python 3.8+ not found. Please install Python 3.8 or higher."
    return 1
}

# Install Python if not found
install_python() {
    local pm=$(detect_package_manager)

    log_info "Installing Python..."

    case $pm in
        apt)
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip python3-venv
            ;;
        yum)
            sudo yum install -y python3 python3-pip
            ;;
        dnf)
            sudo dnf install -y python3 python3-pip
            ;;
        pacman)
            sudo pacman -S --noconfirm python python-pip
            ;;
        *)
            log_error "Please install Python 3.8+ manually."
            return 1
            ;;
    esac

    find_python
}

# Install Python requirements
install_requirements() {
    local requirements_file="$SCRIPT_DIR/requirements.txt"

    if [[ ! -f "$requirements_file" ]]; then
        log_error "Requirements file not found: $requirements_file"
        return 1
    fi

    log_info "Installing Python requirements..."
    "$PYTHON_CMD" -m pip install --user -r "$requirements_file"
}

# Setup directories
setup_directories() {
    log_info "Setting up directories..."

    # Create SteamCMD directory
    mkdir -p "$STEAMCMD_DIR"
    mkdir -p "$WORKSPACE_DIR"

    # Create server manager directory (assume current directory for now)
    SERVER_MANAGER_DIR="$SCRIPT_DIR"

    log_info "Directories created successfully"
}

# Initialize databases
initialize_databases() {
    log_info "Initializing databases..."

    local db_dir="$SCRIPT_DIR/db"
    mkdir -p "$db_dir"

    # Create user database
    local user_db="$db_dir/user_database.db"
    if [[ ! -f "$user_db" ]]; then
        log_info "Creating user database..."
        "$PYTHON_CMD" -c "
import sqlite3
import sys
dbfile = '$user_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    email TEXT,
    first_name TEXT,
    last_name TEXT,
    display_name TEXT,
    account_number TEXT UNIQUE,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME,
    two_factor_enabled INTEGER DEFAULT 0,
    two_factor_secret TEXT
)
''')
conn.commit()
conn.close()
print('User database created successfully')
"
    fi

    # Create Steam database
    local steam_db="$db_dir/steam_ID.db"
    if [[ ! -f "$steam_db" ]]; then
        log_info "Creating Steam database..."
        "$PYTHON_CMD" -c "
import sqlite3
import sys
dbfile = '$steam_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS steam_apps (
    appid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,
    is_server INTEGER DEFAULT 0,
    is_dedicated_server INTEGER DEFAULT 0,
    requires_subscription INTEGER DEFAULT 0,
    anonymous_install INTEGER DEFAULT 1,
    publisher TEXT,
    release_date TEXT,
    description TEXT,
    tags TEXT,
    price TEXT,
    platforms TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'steamdb'
)
''')
conn.commit()
conn.close()
print('Steam database created successfully')
"
    fi

    # Create cluster database
    local cluster_db="$db_dir/servermanager.db"
    if [[ ! -f "$cluster_db" ]]; then
        log_info "Creating cluster database..."
        "$PYTHON_CMD" -c "
import sqlite3
import sys
from datetime import datetime
dbfile = '$cluster_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

# Cluster configuration table
c.execute('''
CREATE TABLE IF NOT EXISTS cluster_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_type TEXT NOT NULL DEFAULT 'Host',
    cluster_name TEXT,
    cluster_secret TEXT,
    master_ip TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Cluster nodes table
c.execute('''
CREATE TABLE IF NOT EXISTS cluster_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    ip_address TEXT NOT NULL,
    port INTEGER DEFAULT 8080,
    node_type TEXT DEFAULT 'node',
    status TEXT DEFAULT 'unknown',
    last_ping DATETIME,
    cluster_token TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Cluster authentication tokens table
c.execute('''
CREATE TABLE IF NOT EXISTS cluster_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    node_name TEXT,
    node_ip TEXT,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    revoked INTEGER DEFAULT 0
)
''')

# Cluster communication log
c.execute('''
CREATE TABLE IF NOT EXISTS cluster_communication_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ip TEXT NOT NULL,
    target_ip TEXT,
    action TEXT NOT NULL,
    status TEXT DEFAULT 'success',
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()
print('Cluster database created successfully')
"
    fi
}

# Setup firewall rules (basic)
setup_firewall() {
    log_info "Setting up firewall rules..."

    # Check if ufw is available
    if command -v ufw &> /dev/null; then
        log_info "Using UFW firewall"
        sudo ufw allow 8080/tcp
        sudo ufw allow 80/tcp
        sudo ufw allow 443/tcp
    # Check if firewalld is available
    elif command -v firewall-cmd &> /dev/null; then
        log_info "Using firewalld"
        sudo firewall-cmd --permanent --add-port=8080/tcp
        sudo firewall-cmd --permanent --add-port=80/tcp
        sudo firewall-cmd --permanent --add-port=443/tcp
        sudo firewall-cmd --reload
    else
        log_warning "No supported firewall manager found. Please manually open ports 80, 443, and 8080."
    fi
}

# Create desktop shortcut/menu entry
create_shortcut() {
    log_info "Creating application shortcuts..."

    # Create desktop entry for Linux desktop environments
    local desktop_file="$HOME/.local/share/applications/servermanager.desktop"

    mkdir -p "$(dirname "$desktop_file")"

    cat > "$desktop_file" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Server Manager
Comment=Game Server Management Tool
Exec=$PYTHON_CMD $SCRIPT_DIR/Start-ServerManager.pyw
Icon=$SCRIPT_DIR/icons/servermanager.ico
Terminal=false
Categories=Utility;System;
EOF

    chmod +x "$desktop_file"
    log_info "Desktop shortcut created"
}

# Setup auto-start (basic systemd user service)
setup_autostart() {
    log_info "Setting up auto-start service..."

    local service_file="$HOME/.config/systemd/user/servermanager.service"

    mkdir -p "$(dirname "$service_file")"

    cat > "$service_file" << EOF
[Unit]
Description=Server Manager
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_CMD $SCRIPT_DIR/Start-ServerManager.pyw
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

    # Enable and start the service
    systemctl --user daemon-reload
    systemctl --user enable servermanager.service

    log_info "Auto-start service configured"
}

# Main installation function
main_install() {
    log_info "Starting Server Manager installation..."

    # Check prerequisites
    check_root

    # Find Python
    if ! find_python; then
        echo "Python 3.8+ is required. Attempting to install..."
        if ! install_python; then
            log_error "Failed to install Python. Please install Python 3.8+ manually."
            exit 1
        fi
    fi

    # Setup directories
    setup_directories

    # Install requirements
    install_requirements

    # Initialize databases
    initialize_databases

    # Setup firewall
    setup_firewall

    # Create shortcuts
    create_shortcut

    # Setup auto-start
    setup_autostart

    log_success "Server Manager installation completed!"
    echo
    echo "You can now:"
    echo "1. Start Server Manager: $PYTHON_CMD $SCRIPT_DIR/Start-ServerManager.pyw"
    echo "2. Access the web interface at: http://localhost:8080"
    echo "3. Default login: admin / admin"
    echo
    echo "The service will start automatically on system boot."
}

# Service management functions
service_start() {
    log_info "Starting Server Manager service..."
    systemctl --user start servermanager.service
    log_success "Service started"
}

service_stop() {
    log_info "Stopping Server Manager service..."
    systemctl --user stop servermanager.service
    log_success "Service stopped"
}

service_restart() {
    log_info "Restarting Server Manager service..."
    systemctl --user restart servermanager.service
    log_success "Service restarted"
}

service_status() {
    systemctl --user status servermanager.service
}

service_install() {
    log_info "Installing Server Manager service..."
    setup_autostart
    service_start
    log_success "Service installed and started"
}

service_uninstall() {
    log_info "Uninstalling Server Manager service..."
    systemctl --user stop servermanager.service 2>/dev/null || true
    systemctl --user disable servermanager.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/servermanager.service"
    systemctl --user daemon-reload
    log_success "Service uninstalled"
}

# Show usage
show_usage() {
    cat << EOF
Server Manager Linux Installer v$CURRENT_VERSION

Usage: $0 [OPTIONS] [ACTION]

Actions:
    install     Install Server Manager (default)
    uninstall   Uninstall Server Manager
    start       Start the Server Manager service
    stop        Stop the Server Manager service
    restart     Restart the Server Manager service
    status      Show service status

Options:
    --help, -h  Show this help message

Examples:
    $0                    # Install Server Manager
    $0 install           # Same as above
    $0 start             # Start the service
    $0 status            # Check service status

EOF
}

# Parse command line arguments
ACTION="install"

while [[ $# -gt 0 ]]; do
    case $1 in
        install|uninstall|start|stop|restart|status)
            ACTION="$1"
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Initialize log file
echo "=== Server Manager Installation Log $(date) ===" > "$LOG_FILE"

# Execute action
case $ACTION in
    install)
        main_install
        ;;
    uninstall)
        service_uninstall
        log_success "Server Manager uninstalled"
        ;;
    start)
        service_start
        ;;
    stop)
        service_stop
        ;;
    restart)
        service_restart
        ;;
    status)
        service_status
        ;;
    *)
        log_error "Unknown action: $ACTION"
        show_usage
        exit 1
        ;;
esac
