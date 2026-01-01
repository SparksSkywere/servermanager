#!/bin/bash
# Server Manager Linux Uninstaller
# Removes Server Manager installation, services, and related files

set -e

# Configuration
CURRENT_VERSION="1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/Uninstall-Log.txt"
STEAMCMD_DIR="$HOME/SteamCMD"
SERVER_MANAGER_DIR="$SCRIPT_DIR"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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
check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "This script should not be run as root. Please run as a regular user."
        exit 1
    fi
}

# Find Python executable
find_python() {
    local python_cmds=("python3" "python" "python3.10" "python3.9" "python3.8")
    
    for cmd in "${python_cmds[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    
    echo ""
    return 1
}

# Stop Server Manager service
stop_service() {
    log_info "Stopping Server Manager service..."
    
    # Try systemd user service
    if systemctl --user is-active servermanager.service &>/dev/null; then
        systemctl --user stop servermanager.service 2>/dev/null || true
        log_info "Stopped systemd user service"
    fi
    
    # Try stopping via Python script
    if [[ -f "$SERVER_MANAGER_DIR/Modules/stop_servermanager.py" ]]; then
        local python_cmd=$(find_python)
        if [[ -n "$python_cmd" ]]; then
            "$python_cmd" "$SERVER_MANAGER_DIR/Modules/stop_servermanager.py" 2>/dev/null || true
            log_info "Executed stop script"
        fi
    fi
    
    # Kill any remaining processes
    pkill -f "Start-ServerManager" 2>/dev/null || true
    pkill -f "servermanager" 2>/dev/null || true
    
    # Wait for processes to terminate
    sleep 2
    
    log_info "Server Manager processes stopped"
}

# Disable and remove systemd service
remove_service() {
    log_info "Removing systemd service..."
    
    local service_file="$HOME/.config/systemd/user/servermanager.service"
    
    # Disable service
    systemctl --user disable servermanager.service 2>/dev/null || true
    
    # Remove service file
    if [[ -f "$service_file" ]]; then
        rm -f "$service_file"
        log_info "Removed service file: $service_file"
    fi
    
    # Reload systemd
    systemctl --user daemon-reload 2>/dev/null || true
    
    log_info "Systemd service removed"
}

# Remove desktop shortcut
remove_desktop_shortcut() {
    log_info "Removing desktop shortcuts..."
    
    local desktop_file="$HOME/.local/share/applications/servermanager.desktop"
    
    if [[ -f "$desktop_file" ]]; then
        rm -f "$desktop_file"
        log_info "Removed desktop shortcut: $desktop_file"
    fi
    
    # Update desktop database
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    
    log_info "Desktop shortcuts removed"
}

# Remove firewall rules
remove_firewall_rules() {
    log_info "Removing firewall rules..."
    
    # UFW
    if command -v ufw &>/dev/null; then
        sudo ufw delete allow 8080/tcp 2>/dev/null || true
        sudo ufw delete allow 80/tcp 2>/dev/null || true
        sudo ufw delete allow 443/tcp 2>/dev/null || true
        log_info "Removed UFW rules"
    fi
    
    # firewalld
    if command -v firewall-cmd &>/dev/null; then
        sudo firewall-cmd --permanent --remove-port=8080/tcp 2>/dev/null || true
        sudo firewall-cmd --permanent --remove-port=80/tcp 2>/dev/null || true
        sudo firewall-cmd --permanent --remove-port=443/tcp 2>/dev/null || true
        sudo firewall-cmd --reload 2>/dev/null || true
        log_info "Removed firewalld rules"
    fi
    
    log_info "Firewall rules removed"
}

# Remove Server Manager files
remove_server_manager_files() {
    log_info "Removing Server Manager files..."
    
    # Remove db directory
    if [[ -d "$SERVER_MANAGER_DIR/db" ]]; then
        rm -rf "$SERVER_MANAGER_DIR/db"
        log_info "Removed database directory"
    fi
    
    # Remove logs directory
    if [[ -d "$SERVER_MANAGER_DIR/logs" ]]; then
        rm -rf "$SERVER_MANAGER_DIR/logs"
        log_info "Removed logs directory"
    fi
    
    # Remove temp directory
    if [[ -d "$SERVER_MANAGER_DIR/temp" ]]; then
        rm -rf "$SERVER_MANAGER_DIR/temp"
        log_info "Removed temp directory"
    fi
    
    # Remove __pycache__ directories
    find "$SERVER_MANAGER_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    log_info "Removed Python cache directories"
    
    # Remove .pyc files
    find "$SERVER_MANAGER_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    log_info "Removed compiled Python files"
    
    log_info "Server Manager files removed"
}

# Remove SteamCMD (optional)
remove_steamcmd() {
    log_info "Removing SteamCMD directory..."
    
    if [[ -d "$STEAMCMD_DIR" ]]; then
        rm -rf "$STEAMCMD_DIR"
        log_info "Removed SteamCMD directory: $STEAMCMD_DIR"
    fi
    
    log_info "SteamCMD removed"
}

# Remove entire Server Manager installation
remove_full_installation() {
    log_info "Removing full Server Manager installation..."
    
    # Remove the entire Server Manager directory
    if [[ -d "$SERVER_MANAGER_DIR" ]]; then
        cd "$HOME"
        rm -rf "$SERVER_MANAGER_DIR"
        log_info "Removed Server Manager directory: $SERVER_MANAGER_DIR"
    fi
    
    log_info "Full installation removed"
}

# Confirm uninstallation
confirm_uninstall() {
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}   Server Manager Uninstaller v$CURRENT_VERSION${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "This will uninstall Server Manager from your system."
    echo ""
    echo "Server Manager directory: $SERVER_MANAGER_DIR"
    echo "SteamCMD directory: $STEAMCMD_DIR"
    echo ""
    
    read -p "Do you want to proceed with uninstallation? (y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        log_info "Uninstallation cancelled by user"
        exit 0
    fi
    
    echo ""
    read -p "Do you also want to remove SteamCMD and all game servers? (y/N): " remove_steam
    
    echo ""
    read -p "Remove all Server Manager files including databases and logs? (y/N): " remove_all
    
    echo ""
    
    REMOVE_STEAMCMD=false
    REMOVE_ALL_FILES=false
    
    if [[ "$remove_steam" =~ ^[Yy]$ ]]; then
        REMOVE_STEAMCMD=true
    fi
    
    if [[ "$remove_all" =~ ^[Yy]$ ]]; then
        REMOVE_ALL_FILES=true
    fi
}

# Show usage
show_usage() {
    cat << EOF
Server Manager Linux Uninstaller v$CURRENT_VERSION

Usage: $0 [OPTIONS]

Options:
    --yes, -y           Skip confirmation prompts
    --remove-steamcmd   Also remove SteamCMD directory
    --remove-all        Remove all files including databases
    --help, -h          Show this help message

Examples:
    $0                          # Interactive uninstallation
    $0 -y                       # Uninstall without prompts
    $0 -y --remove-all          # Complete removal without prompts

EOF
}

# Parse command line arguments
SKIP_CONFIRM=false
REMOVE_STEAMCMD=false
REMOVE_ALL_FILES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --yes|-y)
            SKIP_CONFIRM=true
            shift
            ;;
        --remove-steamcmd)
            REMOVE_STEAMCMD=true
            shift
            ;;
        --remove-all)
            REMOVE_ALL_FILES=true
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

# Main uninstallation function
main_uninstall() {
    # Initialise log file
    echo "=== Server Manager Uninstallation Log $(date) ===" > "$LOG_FILE"
    
    log_info "Starting Server Manager uninstallation..."
    
    # Check not running as root
    check_not_root
    
    # Confirm uninstallation unless skipped
    if [[ "$SKIP_CONFIRM" != true ]]; then
        confirm_uninstall
    fi
    
    # Stop services
    stop_service
    
    # Remove systemd service
    remove_service
    
    # Remove desktop shortcut
    remove_desktop_shortcut
    
    # Remove firewall rules
    remove_firewall_rules
    
    # Remove Server Manager files
    if [[ "$REMOVE_ALL_FILES" == true ]]; then
        remove_full_installation
    else
        remove_server_manager_files
    fi
    
    # Remove SteamCMD if requested
    if [[ "$REMOVE_STEAMCMD" == true ]]; then
        remove_steamcmd
    fi
    
    echo ""
    log_success "Server Manager uninstallation completed!"
    echo ""
    
    if [[ "$REMOVE_STEAMCMD" != true ]]; then
        echo -e "${YELLOW}SteamCMD remains at: $STEAMCMD_DIR${NC}"
    fi
    
    if [[ "$REMOVE_ALL_FILES" != true ]]; then
        echo -e "${YELLOW}Some Server Manager files may remain at: $SERVER_MANAGER_DIR${NC}"
    fi
    
    echo ""
}

# Run main function
main_uninstall
