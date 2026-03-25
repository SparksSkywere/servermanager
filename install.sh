#!/bin/bash
# Server Manager Linux Installer
# Installs Server Manager with cluster support for Linux systems

set -e

# Configuration
CURRENT_VERSION="1.4"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/Install-Log.txt"
SERVER_MANAGER_DIR=""
STEAMCMD_DIR="$HOME/SteamCMD"
WORKSPACE_DIR="$STEAMCMD_DIR/user_workspace"
PYTHON_CMD=""
GIT_REPO_URL="https://github.com/SparksSkywere/servermanager.git"

# Installation options (set during interactive setup)
INSTALL_SERVICE=true
HOST_TYPE="Host"
HOST_ADDRESS=""
SUBHOST_ID=""
SSL_ENABLED=true

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
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
    local python_cmds=("python3" "python" "python3.12" "python3.11" "python3.10" "python3.9" "python3.8")

    for cmd in "${python_cmds[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            # Check version is at least 3.8
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
            sudo apt-get install -y python3 python3-pip python3-venv python3-dev
            ;;
        yum)
            sudo yum install -y python3 python3-pip python3-devel
            ;;
        dnf)
            sudo dnf install -y python3 python3-pip python3-devel
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

# Install Git if not found
install_git() {
    if command -v git &> /dev/null; then
        log_info "Git is already installed"
        return 0
    fi
    
    log_info "Installing Git..."
    local pm=$(detect_package_manager)
    
    case $pm in
        apt)
            sudo apt-get update && sudo apt-get install -y git
            ;;
        yum)
            sudo yum install -y git
            ;;
        dnf)
            sudo dnf install -y git
            ;;
        pacman)
            sudo pacman -S --noconfirm git
            ;;
        *)
            log_error "Please install Git manually."
            return 1
            ;;
    esac
    
    log_success "Git installed successfully"
}

# Install Python requirements
install_requirements() {
    local requirements_file="$SCRIPT_DIR/requirements.txt"

    if [[ ! -f "$requirements_file" ]]; then
        log_warning "Requirements file not found: $requirements_file"
        return 0
    fi

    log_info "Installing Python requirements..."
    
    # Upgrade pip first
    "$PYTHON_CMD" -m pip install --upgrade pip --user 2>/dev/null || true
    
    # Install requirements
    "$PYTHON_CMD" -m pip install --user -r "$requirements_file"
    
    log_success "Python requirements installed"
}

# Setup directories
setup_directories() {
    log_info "Setting up directories..."

    # Create SteamCMD directory
    mkdir -p "$STEAMCMD_DIR"
    mkdir -p "$WORKSPACE_DIR"

    # Set server manager directory
    SERVER_MANAGER_DIR="$SCRIPT_DIR"
    
    # Create required subdirectories
    mkdir -p "$SERVER_MANAGER_DIR/db"
    mkdir -p "$SERVER_MANAGER_DIR/logs"
    mkdir -p "$SERVER_MANAGER_DIR/temp"
    mkdir -p "$SERVER_MANAGER_DIR/servers"
    mkdir -p "$SERVER_MANAGER_DIR/ssl"

    log_info "Directories created successfully"
}

# Initialise databases
initialise_databases() {
    log_info "Initialising databases..."

    local db_dir="$SERVER_MANAGER_DIR/db"
    mkdir -p "$db_dir"

    # Create user database
    local user_db="$db_dir/servermanager_users.db"
    if [[ ! -f "$user_db" ]]; then
        log_info "Creating user database..."
        "$PYTHON_CMD" << EOF
import sqlite3
import hashlib
import uuid
from datetime import datetime

dbfile = '$user_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

# Create users table
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
    two_factor_secret TEXT,
    avatar TEXT,
    bio TEXT,
    timezone TEXT DEFAULT 'UTC',
    theme_preference TEXT DEFAULT 'dark'
)
''')

# Create default admin user
admin_password = hashlib.sha256('admin'.encode()).hexdigest()
account_number = str(uuid.uuid4())[:8].upper()
created_at = datetime.utcnow().isoformat()

c.execute('''
    INSERT OR IGNORE INTO users (username, password, email, first_name, last_name, display_name, account_number, is_admin, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''', ('admin', admin_password, 'admin@localhost', 'System', 'Administrator', 'Admin', account_number, 1, 1, created_at))

conn.commit()
conn.close()
print('User database created successfully')
EOF
    fi

    # Create Steam database
    local steam_db="$db_dir/steam_ID.db"
    if [[ ! -f "$steam_db" ]]; then
        log_info "Creating Steam database..."
        "$PYTHON_CMD" << EOF
import sqlite3

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
EOF
    fi

    # Create cluster database
    local cluster_db="$db_dir/servermanager.db"
    if [[ ! -f "$cluster_db" ]]; then
        log_info "Creating cluster database..."
        "$PYTHON_CMD" << EOF
import sqlite3
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
    hostname TEXT,
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

# Pending cluster requests table
c.execute('''
CREATE TABLE IF NOT EXISTS pending_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_name TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    port INTEGER DEFAULT 8080,
    machine_name TEXT,
    os_info TEXT,
    request_data TEXT,
    status TEXT DEFAULT 'pending',
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at DATETIME,
    approved_by TEXT,
    approval_token TEXT,
    rejected_at DATETIME,
    rejected_by TEXT
)
''')

# Host status table
c.execute('''
CREATE TABLE IF NOT EXISTS host_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'online',
    dashboard_active INTEGER DEFAULT 1,
    maintenance_mode INTEGER DEFAULT 0,
    status_message TEXT,
    last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Main configuration table
c.execute('''
CREATE TABLE IF NOT EXISTS main_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT,
    config_type TEXT DEFAULT 'string',
    category TEXT DEFAULT 'system',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Insert default host status
c.execute('INSERT OR IGNORE INTO host_status (id, status, dashboard_active) VALUES (1, "online", 1)')

# Insert cluster configuration
c.execute('INSERT OR IGNORE INTO cluster_config (id, host_type, cluster_name) VALUES (1, "$HOST_TYPE", "ServerManager-Cluster")')

# Insert default theme preference
c.execute('''
INSERT OR IGNORE INTO main_config (config_key, config_value, config_type, category)
VALUES ('theme', 'light', 'string', 'settings')
''')

conn.commit()
conn.close()
print('Cluster database created successfully')
EOF
    fi
    
    log_success "Databases initialised"
}

# Setup firewall rules
setup_firewall() {
    log_info "Setting up firewall rules..."

    # Check if ufw is available
    if command -v ufw &> /dev/null; then
        log_info "Using UFW firewall"
        sudo ufw allow 8080/tcp comment "Server Manager Web Interface" 2>/dev/null || true
        sudo ufw allow 80/tcp comment "Server Manager HTTP" 2>/dev/null || true
        
        # SSL/HTTPS ports
        if [[ "$SSL_ENABLED" == true ]]; then
            sudo ufw allow 443/tcp comment "Server Manager HTTPS" 2>/dev/null || true
            sudo ufw allow 8081/tcp comment "Server Manager HTTP to HTTPS Redirect" 2>/dev/null || true
        fi
        
        # Cluster API port
        if [[ "$HOST_TYPE" == "Host" ]] || [[ "$HOST_TYPE" == "Subhost" ]]; then
            sudo ufw allow 5001/tcp comment "Server Manager Cluster API" 2>/dev/null || true
        fi
        
        # Game server ports range
        sudo ufw allow 27015:27050/tcp comment "Steam Game Servers TCP" 2>/dev/null || true
        sudo ufw allow 27015:27050/udp comment "Steam Game Servers UDP" 2>/dev/null || true
        
        log_success "UFW rules configured"
        
    # Check if firewalld is available
    elif command -v firewall-cmd &> /dev/null; then
        log_info "Using firewalld"
        sudo firewall-cmd --permanent --add-port=8080/tcp 2>/dev/null || true
        sudo firewall-cmd --permanent --add-port=80/tcp 2>/dev/null || true
        
        # SSL/HTTPS ports
        if [[ "$SSL_ENABLED" == true ]]; then
            sudo firewall-cmd --permanent --add-port=443/tcp 2>/dev/null || true
            sudo firewall-cmd --permanent --add-port=8081/tcp 2>/dev/null || true
        fi
        
        # Cluster API port
        if [[ "$HOST_TYPE" == "Host" ]] || [[ "$HOST_TYPE" == "Subhost" ]]; then
            sudo firewall-cmd --permanent --add-port=5001/tcp 2>/dev/null || true
        fi
        
        sudo firewall-cmd --permanent --add-port=27015-27050/tcp 2>/dev/null || true
        sudo firewall-cmd --permanent --add-port=27015-27050/udp 2>/dev/null || true
        sudo firewall-cmd --reload 2>/dev/null || true
        
        log_success "firewalld rules configured"
    else
        log_warning "No supported firewall manager found. Please manually open required ports."
        log_warning "Required ports: 8080 (web)"
        if [[ "$SSL_ENABLED" == true ]]; then
            log_warning "SSL ports: 443 (HTTPS), 8081 (HTTP redirect)"
        fi
        log_warning "Cluster: 5001, Game servers: 27015-27050"
    fi
}

# Setup SSL/HTTPS certificates
setup_ssl() {
    if [[ "$SSL_ENABLED" != true ]]; then
        log_info "SSL/HTTPS is disabled, skipping certificate generation"
        return 0
    fi
    
    log_info "Setting up SSL/HTTPS certificates..."
    
    local ssl_dir="$SERVER_MANAGER_DIR/ssl"
    local cert_file="$ssl_dir/server.crt"
    local key_file="$ssl_dir/server.key"
    
    mkdir -p "$ssl_dir"
    
    # Generate self-signed certificate using Python cryptography library
    "$PYTHON_CMD" << EOF
import sys
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime
    import ipaddress
    import socket

    # Generate RSA key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    
    hostname = socket.gethostname()
    
    # Build subject
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Server Manager"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Self-Signed"),
    ])
    
    # SANs
    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName(hostname),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    try:
        san_list.append(x509.IPAddress(ipaddress.IPv6Address("::1")))
    except Exception:
        pass
    
    # Build certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    
    # Write key file
    with open("$key_file", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Write certificate file
    with open("$cert_file", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print("SUCCESS: SSL certificates generated")
except ImportError:
    print("FALLBACK: cryptography library not available, using openssl")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
EOF
    
    if [[ $? -ne 0 ]]; then
        # Fallback to openssl command line
        log_info "Falling back to openssl for certificate generation..."
        if command -v openssl &> /dev/null; then
            local hostname=$(hostname)
            openssl req -x509 -newkey rsa:2048 -keyout "$key_file" -out "$cert_file" \
                -days 3650 -nodes -subj "/CN=$hostname/O=Server Manager/OU=Self-Signed" \
                -addext "subjectAltName=DNS:localhost,DNS:$hostname,IP:127.0.0.1" 2>/dev/null
            
            if [[ $? -eq 0 ]]; then
                log_success "SSL certificates generated using openssl"
            else
                log_error "Failed to generate SSL certificates"
                SSL_ENABLED=false
                return 1
            fi
        else
            log_error "Neither Python cryptography nor openssl available. Disabling SSL."
            SSL_ENABLED=false
            return 1
        fi
    else
        log_success "SSL certificates generated using Python cryptography"
    fi
    
    # Set secure permissions on certificate files
    chmod 600 "$key_file"
    chmod 644 "$cert_file"
    
    # Verify certificate
    if [[ -f "$cert_file" ]] && [[ -f "$key_file" ]]; then
        local cert_size=$(stat -c %s "$cert_file" 2>/dev/null || stat -f %z "$cert_file" 2>/dev/null)
        local key_size=$(stat -c %s "$key_file" 2>/dev/null || stat -f %z "$key_file" 2>/dev/null)
        
        if [[ "$cert_size" -gt 0 ]] && [[ "$key_size" -gt 0 ]]; then
            log_success "SSL certificate verified: $cert_file ($cert_size bytes)"
            log_success "SSL private key verified: $key_file ($key_size bytes)"
        else
            log_error "SSL certificate files are empty. Disabling SSL."
            SSL_ENABLED=false
            return 1
        fi
    else
        log_error "SSL certificate files not found. Disabling SSL."
        SSL_ENABLED=false
        return 1
    fi
    
    # Save SSL configuration to a config file for the application
    local ssl_config="$SERVER_MANAGER_DIR/ssl/ssl_config.json"
    cat > "$ssl_config" << SSLEOF
{
    "ssl_enabled": true,
    "ssl_cert_path": "$cert_file",
    "ssl_key_path": "$key_file",
    "ssl_auto_generate": true
}
SSLEOF
    chmod 600 "$ssl_config"
    log_info "SSL configuration saved to: $ssl_config"
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
Categories=Utility;System;Game;
Keywords=server;game;steam;manager;
EOF

    chmod +x "$desktop_file"
    
    # Update desktop database
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    
    log_info "Desktop shortcut created"
}

# Setup auto-start systemd user service
setup_autostart() {
    if [[ "$INSTALL_SERVICE" != true ]]; then
        log_info "Skipping service installation (not requested)"
        return 0
    fi
    
    log_info "Setting up auto-start service..."

    local service_dir="$HOME/.config/systemd/user"
    local service_file="$service_dir/servermanager.service"

    mkdir -p "$service_dir"

    cat > "$service_file" << EOF
[Unit]
Description=Server Manager - Game Server Management
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_CMD $SCRIPT_DIR/Start-ServerManager.pyw
Restart=always
RestartSec=10
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
Environment=SSL_ENABLED=$SSL_ENABLED
Environment=SSL_CERT_PATH=$SCRIPT_DIR/ssl/server.crt
Environment=SSL_KEY_PATH=$SCRIPT_DIR/ssl/server.key

[Install]
WantedBy=default.target
EOF

    # Enable lingering for user services to run without login
    loginctl enable-linger "$USER" 2>/dev/null || true

    # Reload and enable service
    systemctl --user daemon-reload
    systemctl --user enable servermanager.service

    log_success "Auto-start service configured"
}

# Configure cluster settings
configure_cluster() {
    log_info "Configuring cluster settings..."
    
    local cluster_db="$SERVER_MANAGER_DIR/db/servermanager.db"
    
    if [[ ! -f "$cluster_db" ]]; then
        log_warning "Cluster database not found at $cluster_db - will be created on first launch"
        return 0
    fi
    
    if [[ "$HOST_TYPE" == "Host" ]]; then
        # Generate cluster secret for master host using Python secrets module
        "$PYTHON_CMD" << EOF
import sqlite3
import secrets
from datetime import datetime

dbfile = '$cluster_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

cluster_secret = secrets.token_urlsafe(32)

# Update or insert cluster config
c.execute('SELECT COUNT(*) FROM cluster_config')
count = c.fetchone()[0]
if count == 0:
    c.execute('''INSERT INTO cluster_config (host_type, cluster_name, cluster_secret, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?)''',
              ('Host', 'ServerManager-Cluster', cluster_secret, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
else:
    c.execute('UPDATE cluster_config SET host_type = ?, cluster_secret = ?, updated_at = ? WHERE id = 1',
              ('Host', cluster_secret, datetime.utcnow().isoformat()))

# Ensure host_status has a default row
c.execute('SELECT COUNT(*) FROM host_status')
if c.fetchone()[0] == 0:
    c.execute('INSERT INTO host_status (id, status, dashboard_active) VALUES (1, "online", 1)')

# Ensure theme preference exists
c.execute('''
INSERT OR IGNORE INTO main_config (config_key, config_value, config_type, category)
VALUES ('theme', 'light', 'string', 'settings')
''')

conn.commit()
conn.close()
print(f'CLUSTER_SECRET:{cluster_secret}')
print('Cluster configured as Master Host')
EOF
        
        # Extract the generated secret
        local cluster_secret
        cluster_secret=$("$PYTHON_CMD" -c "
import sqlite3
conn = sqlite3.connect('$cluster_db')
c = conn.cursor()
c.execute('SELECT cluster_secret FROM cluster_config WHERE id = 1')
row = c.fetchone()
conn.close()
print(row[0] if row else '')
" 2>/dev/null)
        
        # Save cluster token to file
        if [[ -n "$cluster_secret" ]]; then
            local token_file="$SERVER_MANAGER_DIR/cluster-security-token.txt"
            cat > "$token_file" << TOKENEOF
Server Manager Cluster Security Token
Generated: $(date -Iseconds)
Master Host: $SERVER_MANAGER_DIR

SECURITY TOKEN:
$cluster_secret

IMPORTANT NOTES:
- This token provides full access to your Server Manager cluster
- Store it securely and share only with trusted subhost administrators
- This token cannot be recovered if lost - you will need to generate a new one
- All existing subhosts will need to update their tokens if regenerated

Provide this token to subhost administrators during their installation process.
TOKENEOF
            chmod 600 "$token_file"
            log_info "Cluster security token saved to: $token_file"
        fi
        
    elif [[ "$HOST_TYPE" == "Subhost" ]] && [[ -n "$HOST_ADDRESS" ]]; then
        # Configure as subhost
        "$PYTHON_CMD" << EOF
import sqlite3
from datetime import datetime

dbfile = '$cluster_db'
conn = sqlite3.connect(dbfile)
c = conn.cursor()

# Update or insert cluster config
c.execute('SELECT COUNT(*) FROM cluster_config')
count = c.fetchone()[0]
if count == 0:
    c.execute('''INSERT INTO cluster_config (host_type, cluster_name, master_ip, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?)''',
              ('Subhost', 'ServerManager-Cluster', '$HOST_ADDRESS', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
else:
    c.execute('UPDATE cluster_config SET host_type = ?, master_ip = ?, updated_at = ? WHERE id = 1',
              ('Subhost', '$HOST_ADDRESS', datetime.utcnow().isoformat()))

# Ensure host_status has a default row
c.execute('SELECT COUNT(*) FROM host_status')
if c.fetchone()[0] == 0:
    c.execute('INSERT INTO host_status (id, status, dashboard_active) VALUES (1, "online", 1)')

# Ensure theme preference exists
c.execute('''
INSERT OR IGNORE INTO main_config (config_key, config_value, config_type, category)
VALUES ('theme', 'light', 'string', 'settings')
''')

conn.commit()
conn.close()
print('Cluster configured as Subhost')
EOF
        log_info "Configured as cluster subhost, master host: $HOST_ADDRESS"
    fi
    
    log_success "Cluster configuration complete"
}

# Request to join cluster (for subhosts)
request_cluster_join() {
    if [[ "$HOST_TYPE" != "Subhost" ]] || [[ -z "$HOST_ADDRESS" ]]; then
        return 0
    fi
    
    log_info "Requesting to join cluster at $HOST_ADDRESS..."
    
    # Generate subhost ID
    SUBHOST_ID="${HOSTNAME:-$(hostname)}-$(date +%s | tail -c 5)"
    
    # Get local IP
    local local_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown")
    
    # Try to send join request
    local response
    response=$("$PYTHON_CMD" << EOF
import urllib.request
import urllib.error
import json
import sys

host = '$HOST_ADDRESS'
subhost_id = '$SUBHOST_ID'
local_ip = '$local_ip'
ssl_enabled = '$SSL_ENABLED'

# Use HTTPS when SSL is enabled, HTTP as fallback
if ssl_enabled.lower() == 'true':
    protocol = 'https'
    port = 443
else:
    protocol = 'http'
    port = 8080

request_data = {
    "subhost_id": subhost_id,
    "info": {
        "machine_name": "$(hostname)",
        "os": "$(uname -s) $(uname -r)",
        "install_time": "$(date -Iseconds)",
        "ip_address": local_ip
    }
}

try:
    # First check if host is available
    status_url = f"{protocol}://{host}:{port}/api/cluster/status"
    try:
        status_req = urllib.request.Request(status_url, method='GET')
        status_resp = urllib.request.urlopen(status_req, timeout=10)
        status_data = json.loads(status_resp.read().decode())
        print(f"Host status: {status_data.get('host_status', 'unknown')}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Could not check host status: {e}", file=sys.stderr)
    
    # Send join request
    url = f"{protocol}://{host}:{port}/api/cluster/request-join"
    data = json.dumps(request_data).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read().decode())
    
    if result.get('status') == 'pending_approval':
        print(f"SUCCESS: Join request submitted. Request ID: {result.get('request_id')}")
        print("Please wait for the cluster administrator to approve your request.")
    else:
        print(f"Response: {result}")
        
except urllib.error.URLError as e:
    print(f"ERROR: Could not connect to host at {host}:8080 - {e}")
    print("Make sure the master host is running and accessible.")
except Exception as e:
    print(f"ERROR: {e}")
EOF
)
    
    echo "$response"
    log_info "$response"
}

# Interactive installation prompts
interactive_setup() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}   Server Manager Installer v$CURRENT_VERSION${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    
    # SteamCMD directory
    echo -e "${YELLOW}SteamCMD Installation Directory${NC}"
    echo "Default: $STEAMCMD_DIR"
    read -p "Enter directory (or press Enter for default): " input_steamcmd
    if [[ -n "$input_steamcmd" ]]; then
        STEAMCMD_DIR="$input_steamcmd"
        WORKSPACE_DIR="$STEAMCMD_DIR/user_workspace"
    fi
    echo ""
    
    # Install as service
    echo -e "${YELLOW}Install as System Service${NC}"
    echo "This will start Server Manager automatically on boot."
    read -p "Install as service? (Y/n): " input_service
    if [[ "$input_service" =~ ^[Nn]$ ]]; then
        INSTALL_SERVICE=false
    else
        INSTALL_SERVICE=true
    fi
    echo ""
    
    # Cluster type
    echo -e "${YELLOW}Cluster Configuration${NC}"
    echo "1) Master Host - Manage other servers in the cluster"
    echo "2) Cluster Node - Managed by another Master Host"
    read -p "Select cluster type (1/2) [1]: " input_cluster
    
    if [[ "$input_cluster" == "2" ]]; then
        HOST_TYPE="Subhost"
        echo ""
        read -p "Enter Master Host IP Address: " input_host_addr
        if [[ -z "$input_host_addr" ]]; then
            log_error "Master Host IP Address is required for cluster nodes"
            exit 1
        fi
        # Validate IP or hostname format
        if [[ ! "$input_host_addr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] && [[ ! "$input_host_addr" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            log_error "Invalid IP address or hostname format"
            exit 1
        fi
        HOST_ADDRESS="$input_host_addr"
    else
        HOST_TYPE="Host"
    fi
    echo ""
    
    # HTTPS/SSL Configuration
    echo -e "${YELLOW}Web Server Protocol${NC}"
    echo ""
    echo "1) HTTPS (Recommended) - Encrypted connections using SSL/TLS"
    echo "   A self-signed certificate will be generated automatically."
    echo ""
    echo -e "2) HTTP - ${RED}WARNING: Unencrypted connections${NC}"
    echo -e "   ${RED}Passwords and data will be transmitted in plain text.${NC}"
    echo -e "   ${RED}Not recommended for production or network-accessible deployments.${NC}"
    echo ""
    read -p "Select protocol (1/2) [1]: " input_ssl
    
    if [[ "$input_ssl" == "2" ]]; then
        SSL_ENABLED=false
        echo ""
        echo -e "${RED}WARNING: You have chosen HTTP (unencrypted).${NC}"
        echo -e "${RED}All data including passwords will be sent in plain text.${NC}"
        echo -e "${RED}This is only suitable for localhost-only or trusted network access.${NC}"
        read -p "Are you sure you want to continue without HTTPS? (y/N): " confirm_http
        if [[ ! "$confirm_http" =~ ^[Yy]$ ]]; then
            SSL_ENABLED=true
            echo "HTTPS will be used."
        fi
    else
        SSL_ENABLED=true
    fi
    echo ""
    
    # Confirm settings
    echo -e "${YELLOW}Installation Summary${NC}"
    echo "SteamCMD Directory: $STEAMCMD_DIR"
    echo "Workspace Directory: $WORKSPACE_DIR"
    echo "Install Service: $INSTALL_SERVICE"
    echo "Cluster Type: $HOST_TYPE"
    if [[ -n "$HOST_ADDRESS" ]]; then
        echo "Master Host: $HOST_ADDRESS"
    fi
    if [[ "$SSL_ENABLED" == true ]]; then
        echo -e "Protocol: ${GREEN}HTTPS (SSL/TLS)${NC}"
    else
        echo -e "Protocol: ${RED}HTTP (Unencrypted)${NC}"
    fi
    echo ""
    
    read -p "Proceed with installation? (Y/n): " confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        log_info "Installation cancelled by user"
        exit 0
    fi
    echo ""
}

# Main installation function
main_install() {
    log_info "Starting Server Manager installation..."

    # Check prerequisites
    check_root

    # Run interactive setup if not in quiet mode
    if [[ "$QUIET_MODE" != true ]]; then
        interactive_setup
    fi

    # Find or install Python
    if ! find_python; then
        echo "Python 3.8+ is required. Attempting to install..."
        if ! install_python; then
            log_error "Failed to install Python. Please install Python 3.8+ manually."
            exit 1
        fi
    fi

    # Install Git
    install_git

    # Setup directories
    setup_directories

    # Install requirements
    install_requirements

    # Initialise databases
    initialise_databases

    # Configure cluster
    configure_cluster

    # Setup SSL/HTTPS
    setup_ssl

    # Setup firewall
    setup_firewall

    # Create shortcuts
    create_shortcut

    # Setup auto-start
    setup_autostart

    # Request cluster join for subhosts
    request_cluster_join

    log_success "Server Manager installation completed!"
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   Installation Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "You can now:"
    echo "1. Start Server Manager: $PYTHON_CMD $SCRIPT_DIR/Start-ServerManager.pyw"
    if [[ "$SSL_ENABLED" == true ]]; then
        echo -e "2. Access the web interface at: ${GREEN}https://localhost:443${NC}"
        echo "   (Your browser may warn about the self-signed certificate - this is expected)"
    else
        echo -e "2. Access the web interface at: ${YELLOW}http://localhost:8080${NC}"
        echo -e "   ${RED}WARNING: Running without HTTPS - data is not encrypted${NC}"
    fi
    echo "3. Default login: admin / admin"
    echo ""
    
    if [[ "$INSTALL_SERVICE" == true ]]; then
        echo "The service will start automatically on system boot."
        echo "Start now with: systemctl --user start servermanager.service"
    fi
    
    if [[ "$HOST_TYPE" == "Host" ]]; then
        echo ""
        echo -e "${YELLOW}Cluster Security Token saved to:${NC}"
        echo "$SERVER_MANAGER_DIR/cluster-security-token.txt"
    fi
    
    echo ""
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
    INSTALL_SERVICE=true
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
    uninstall   Uninstall Server Manager service
    start       Start the Server Manager service
    stop        Stop the Server Manager service
    restart     Restart the Server Manager service
    status      Show service status

Options:
    --quiet, -q         Run without interactive prompts (use defaults)
    --steamcmd PATH     Set SteamCMD installation directory
    --host-type TYPE    Set cluster type: Host or Subhost
    --host-addr IP      Set Master Host IP address (for Subhost type)
    --no-service        Do not install as system service
    --ssl               Enable HTTPS with self-signed certificate (default)
    --no-ssl            Disable HTTPS, use plain HTTP
    --help, -h          Show this help message

Examples:
    $0                              # Interactive installation
    $0 install                      # Same as above
    $0 -q --host-type Host          # Quiet install as master host
    $0 -q --host-type Subhost --host-addr 192.168.1.50
    $0 start                        # Start the service
    $0 status                       # Check service status

EOF
}

# Parse command line arguments
ACTION="install"
QUIET_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        install|uninstall|start|stop|restart|status)
            ACTION="$1"
            shift
            ;;
        --quiet|-q)
            QUIET_MODE=true
            shift
            ;;
        --steamcmd)
            STEAMCMD_DIR="$2"
            WORKSPACE_DIR="$STEAMCMD_DIR/user_workspace"
            shift 2
            ;;
        --host-type)
            HOST_TYPE="$2"
            shift 2
            ;;
        --host-addr)
            HOST_ADDRESS="$2"
            shift 2
            ;;
        --no-service)
            INSTALL_SERVICE=false
            shift
            ;;
        --ssl)
            SSL_ENABLED=true
            shift
            ;;
        --no-ssl)
            SSL_ENABLED=false
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

# Initialise log file
echo "=== Server Manager Installation Log $(date) ===" > "$LOG_FILE"

# Execute action
case $ACTION in
    install)
        main_install
        ;;
    uninstall)
        service_uninstall
        log_success "Server Manager service uninstalled"
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
