# Script parameters for both installation and service management
param(
    [Parameter()]
    [ValidateSet("Install", "Uninstall", "Start", "Stop", "Restart", "Status")]
    [string]$ServiceAction,
    
    [Parameter()]
    [switch]$ServiceOnly,
    
    [Parameter()]
    [switch]$Help
)

# Set preferences to suppress all interactive prompts
$ConfirmPreference = "None"
$VerbosePreference = "SilentlyContinue"
$WarningPreference = "SilentlyContinue"

# Force all cmdlets to not prompt for confirmation
$PSDefaultParameterValues = @{
    '*:Confirm' = $false
    '*:Force' = $true
    'Remove-Item:Confirm' = $false
    'Remove-Item:Force' = $true
    'Move-Item:Confirm' = $false
    'Move-Item:Force' = $true
}

# Disable all progress bars and informational output
$ProgressPreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'
$DebugPreference = 'SilentlyContinue'

# Prevent Python from creating __pycache__ directories
$env:PYTHONDONTWRITEBYTECODE = "1"

# Load Windows Forms and Drawing assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Check if this is a service management call
if ($ServiceAction -or $ServiceOnly) {
    # Service management mode
    Invoke-ServiceManagement -Action $ServiceAction
    exit
}

# Log function
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    $global:logMemory += $logMessage
}

function Write-LogToFile {
    param (
        [string]$logFilePath
    )
    if (-not $logFilePath) { return }
    try {
        foreach ($logMessage in $global:logMemory) {
            Add-Content -Path $logFilePath -Value $logMessage
        }
    } catch {}
    $global:logMemory = @()
}

# Console window handling function
function Show-Console {
    param ([Switch]$Show, [Switch]$Hide)
    if (-not ("Console.Window" -as [type])) {
        Add-Type -Name Window -Namespace Console -MemberDefinition '
        [DllImport("Kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        '
    }
    $consolePtr = [Console.Window]::GetConsoleWindow()
    $nCmdShow = if ($Show) { 5 } elseif ($Hide) { 0 } else { return }
    [Console.Window]::ShowWindow($consolePtr, $nCmdShow) | Out-Null
    $script:DebugLoggingEnabled = $Show.IsPresent
    Write-Log -Message "Console visibility set to: $($Show.IsPresent)" -Level DEBUG
}

# Function to ensure no console prompts during GUI operations
function Set-NoConsolePrompts {
    # Set all preference variables to suppress prompts - MAXIMUM SUPPRESSION
    $Global:ConfirmPreference = "None"
    $Global:VerbosePreference = "SilentlyContinue" 
    $Global:WarningPreference = "SilentlyContinue"
    $Global:InformationPreference = "SilentlyContinue"
    $Global:DebugPreference = "SilentlyContinue"
    $Global:ProgressPreference = "SilentlyContinue"
    $Global:ErrorActionPreference = "SilentlyContinue"
    
    # Also set for current session
    $ConfirmPreference = "None"
    $VerbosePreference = "SilentlyContinue"
    $WarningPreference = "SilentlyContinue"
    $InformationPreference = "SilentlyContinue"
    $DebugPreference = "SilentlyContinue"
    $ProgressPreference = "SilentlyContinue"
    $ErrorActionPreference = "SilentlyContinue"
    
    # Force all cmdlets to default to non-interactive behavior
    $Global:PSDefaultParameterValues = @{
        '*:Confirm' = $false
        '*:Force' = $true
        'Remove-Item:Confirm' = $false
        'Remove-Item:Force' = $true
        'Remove-Item:Recurse' = $true
        'Move-Item:Confirm' = $false
        'Move-Item:Force' = $true
        'Copy-Item:Confirm' = $false
        'Copy-Item:Force' = $true
    }
    
    # Redirect standard error to null to prevent console output
    $Global:ErrorView = 'CategoryView'
    
    Write-Log "All console prompts have been maximally suppressed for GUI installation"
}

# Hide Console
Show-Console -Hide

# Service Management Functions
function Invoke-ServiceManagement {
    param([string]$Action)
    
    # Check for admin rights and self-elevate if needed
    if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "Administrator rights required. Attempting to restart with elevated privileges..."
        Start-Process PowerShell -Verb RunAs -ArgumentList ("-ExecutionPolicy Bypass -File `"{0}`" -ServiceAction {1} -ServiceOnly" -f $PSCommandPath, $Action)
        exit
    }

    # Get Server Manager directory from registry
    try {
        $regPath = "HKLM:\Software\SkywereIndustries\Servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $regPath -Name "ServerManagerPath").ServerManagerPath
        Write-Log "Server Manager directory: $serverManagerDir"
    } catch {
        Write-Log "Error: Server Manager installation not found in registry."
        [System.Windows.Forms.MessageBox]::Show("Error: Server Manager installation not found in registry. Please run the installer first.", "Service Manager Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        exit 1
    }

    # Check if service helper exists
    $serviceHelperPath = Join-Path $serverManagerDir "service_helper.py"
    if (-not (Test-Path $serviceHelperPath)) {
        Write-Log "Error: Service helper script not found at: $serviceHelperPath"
        [System.Windows.Forms.MessageBox]::Show("Error: Service helper script not found at: $serviceHelperPath", "Service Manager Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        exit 1
    }

    # Find Python executable
    $pythonPath = Find-PythonExecutable
    if (-not $pythonPath) {
        Write-Log "Error: Python executable not found."
        [System.Windows.Forms.MessageBox]::Show("Error: Python executable not found. Please ensure Python is installed and added to PATH.", "Service Manager Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        exit 1
    }

    Write-Log "Using Python: $pythonPath"

    # Execute the requested action
    try {
        Write-Log "Executing action: $Action"
        
        # Set environment variable to prevent Python cache creation
        $env:PYTHONDONTWRITEBYTECODE = "1"
        
        $result = & $pythonPath $serviceHelperPath $Action.ToLower() 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Action completed successfully!"
            Write-Log $result
            [System.Windows.Forms.MessageBox]::Show("Action completed successfully!`n`n$result", "Service Manager", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        } else {
            Write-Log "Action failed!"
            Write-Log $result
            [System.Windows.Forms.MessageBox]::Show("Action failed!`n`n$result", "Service Manager Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        }
    } catch {
        Write-Log "Error executing action: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show("Error executing action: $($_.Exception.Message)", "Service Manager Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
    }

    # Additional information based on action
    switch ($Action.ToLower()) {
        "install" {
            [System.Windows.Forms.MessageBox]::Show("If installation was successful:`n- The service is now installed and running`n- Server Manager will start automatically with Windows`n- You can access the web interface at http://localhost:8080", "Service Installation Complete", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        }
        "uninstall" {
            [System.Windows.Forms.MessageBox]::Show("If uninstallation was successful:`n- The service has been removed`n- Server Manager will no longer start automatically`n- You can still start it manually using Start-ServerManager.pyw", "Service Uninstallation Complete", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        }
        "status" {
            [System.Windows.Forms.MessageBox]::Show("Service management commands:`n- To start:   .\install.ps1 -ServiceAction Start`n- To stop:    .\install.ps1 -ServiceAction Stop`n- To restart: .\install.ps1 -ServiceAction Restart", "Service Status", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        }
    }
}

function Find-PythonExecutable {
    $pythonPaths = @(
        (Get-Command python -ErrorAction SilentlyContinue).Source,
        (Get-Command python3 -ErrorAction SilentlyContinue).Source,
        "C:\Python\python.exe",
        "C:\Python39\python.exe",
        "C:\Python310\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe"
    )

    foreach ($path in $pythonPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    return $null
}

# --- Main installer script ---
# Define global variables first
$global:logMemory = @()
$global:logFilePath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Install-Log.txt"

# Firewall Rules Management Functions
function Add-ServerManagerFirewallRules {
    param(
        [string]$HostType = "Host",
        [bool]$ClusterEnabled = $false
    )
    
    Write-Log "Configuring Windows Firewall rules for Server Manager..."
    
    try {
        # Remove any existing rules first (cleanup from previous installations)
        Remove-ServerManagerFirewallRules -Quiet
        
        # Rule 1: Main web interface (port 8080) - Inbound and Outbound
        $webRuleInbound = @{
            DisplayName = "ServerManager_WebInterface_In"
            Direction = "Inbound"
            Protocol = "TCP"
            LocalPort = "8080"
            Action = "Allow"
            Description = "Allow inbound access to Server Manager web interface on port 8080"
        }
        
        $webRuleOutbound = @{
            DisplayName = "ServerManager_WebInterface_Out"
            Direction = "Outbound"
            Protocol = "TCP"
            LocalPort = "8080"
            Action = "Allow"
            Description = "Allow outbound access from Server Manager web interface on port 8080"
        }
        
        $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($pythonPath) {
            $webRuleInbound.Program = $pythonPath
            $webRuleOutbound.Program = $pythonPath
        }
        
        New-NetFirewallRule @webRuleInbound -ErrorAction Stop | Out-Null
        New-NetFirewallRule @webRuleOutbound -ErrorAction Stop | Out-Null
        Write-Log "Added firewall rules for web interface (port 8080) - inbound and outbound"
        
        # Rule 2: Cluster API (port 8080) - Additional rules for cluster-enabled hosts
        if ($HostType -eq "Host" -or $ClusterEnabled) {
            $clusterRuleInbound = @{
                DisplayName = "ServerManager_ClusterAPI_In"
                Direction = "Inbound" 
                Protocol = "TCP"
                LocalPort = "8080"
                Action = "Allow"
                Description = "Allow inbound access to Server Manager cluster API on port 8080"
            }
            
            $clusterRuleOutbound = @{
                DisplayName = "ServerManager_ClusterAPI_Out"
                Direction = "Outbound"
                Protocol = "TCP" 
                LocalPort = "8080"
                Action = "Allow"
                Description = "Allow outbound access from Server Manager cluster API on port 8080"
            }
            
            if ($pythonPath) {
                $clusterRuleInbound.Program = $pythonPath
                $clusterRuleOutbound.Program = $pythonPath
            }
            
            New-NetFirewallRule @clusterRuleInbound -ErrorAction Stop | Out-Null
            New-NetFirewallRule @clusterRuleOutbound -ErrorAction Stop | Out-Null
            Write-Log "Added additional firewall rules for cluster API (port 8080) - inbound and outbound"
        }        # Rule 3: Game server ports range (7777-7800) - TCP Inbound and Outbound
        $gamePortsRuleInbound = @{
            DisplayName = "ServerManager_GameServers_In"
            Direction = "Inbound"
            Protocol = "TCP"
            LocalPort = "7777-7800"
            Action = "Allow"
            Description = "Allow inbound TCP access to game servers managed by Server Manager (ports 7777-7800)"
        }
        
        $gamePortsRuleOutbound = @{
            DisplayName = "ServerManager_GameServers_Out"
            Direction = "Outbound"
            Protocol = "TCP"
            LocalPort = "7777-7800"
            Action = "Allow"
            Description = "Allow outbound TCP access from game servers managed by Server Manager (ports 7777-7800)"
        }
        
        New-NetFirewallRule @gamePortsRuleInbound -ErrorAction Stop | Out-Null
        New-NetFirewallRule @gamePortsRuleOutbound -ErrorAction Stop | Out-Null
        Write-Log "Added firewall rules for game servers TCP (ports 7777-7800) - inbound and outbound"
        
        # Rule 4: Game server ports range (7777-7800) - UDP Inbound and Outbound
        $gamePortsUDPRuleInbound = @{
            DisplayName = "ServerManager_GameServers_UDP_In"
            Direction = "Inbound"
            Protocol = "UDP"
            LocalPort = "7777-7800"
            Action = "Allow"
            Description = "Allow inbound UDP access to game servers managed by Server Manager (ports 7777-7800)"
        }
        
        $gamePortsUDPRuleOutbound = @{
            DisplayName = "ServerManager_GameServers_UDP_Out"
            Direction = "Outbound"
            Protocol = "UDP"
            LocalPort = "7777-7800"
            Action = "Allow"
            Description = "Allow outbound UDP access from game servers managed by Server Manager (ports 7777-7800)"
        }
        
        New-NetFirewallRule @gamePortsUDPRuleInbound -ErrorAction Stop | Out-Null
        New-NetFirewallRule @gamePortsUDPRuleOutbound -ErrorAction Stop | Out-Null
        Write-Log "Added firewall rules for game servers UDP (ports 7777-7800) - inbound and outbound"
        
        # Rule 5: Steam query protocol (ports 27015-27030) - UDP Inbound and Outbound
        $steamQueryRuleInbound = @{
            DisplayName = "ServerManager_SteamQuery_In"
            Direction = "Inbound"
            Protocol = "UDP"
            LocalPort = "27015-27030"
            Action = "Allow"
            Description = "Allow inbound UDP for Steam query protocol (ports 27015-27030)"
        }
        
        $steamQueryRuleOutbound = @{
            DisplayName = "ServerManager_SteamQuery_Out"
            Direction = "Outbound"
            Protocol = "UDP"
            LocalPort = "27015-27030"
            Action = "Allow"
            Description = "Allow outbound UDP for Steam query protocol (ports 27015-27030)"
        }
        
        New-NetFirewallRule @steamQueryRuleInbound -ErrorAction Stop | Out-Null
        New-NetFirewallRule @steamQueryRuleOutbound -ErrorAction Stop | Out-Null
        Write-Log "Added firewall rules for Steam query protocol (ports 27015-27030) - inbound and outbound"
        
        Write-Log "All firewall rules configured successfully"
        
    } catch {
        Write-Log "Warning: Failed to configure firewall rules: $($_.Exception.Message)"
        Write-Log "You may need to manually configure Windows Firewall to allow:"
        Write-Log "  - Port 8080 (TCP) for web interface (inbound and outbound)"
        if ($HostType -eq "Host" -or $ClusterEnabled) {
            Write-Log "  - Port 8080 (TCP) for cluster API (inbound and outbound)"
        }
        Write-Log "  - Ports 7777-7800 (TCP/UDP) for game servers (inbound and outbound)"
        Write-Log "  - Ports 27015-27030 (UDP) for Steam query protocol (inbound and outbound)"
    }
}

function Remove-ServerManagerFirewallRules {
    param([switch]$Quiet)
    
    if (-not $Quiet) {
        Write-Log "Removing Server Manager firewall rules..."
    }
    
    try {
        $rulesToRemove = @(
            "ServerManager_WebInterface_In",
            "ServerManager_WebInterface_Out",
            "ServerManager_ClusterAPI_In",
            "ServerManager_ClusterAPI_Out",
            "ServerManager_GameServers_In",
            "ServerManager_GameServers_Out",
            "ServerManager_GameServers_UDP_In",
            "ServerManager_GameServers_UDP_Out",
            "ServerManager_SteamQuery_In",
            "ServerManager_SteamQuery_Out",
            # Legacy rule names for backward compatibility
            "ServerManager_WebInterface",
            "ServerManager_ClusterAPI",
            "ServerManager_GameServers",
            "ServerManager_GameServers_UDP",
            "ServerManager_SteamQuery"
        )
        
        $rulesRemoved = 0
        foreach ($ruleName in $rulesToRemove) {
            try {
                $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
                if ($existingRule) {
                    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction Stop
                    if (-not $Quiet) {
                        Write-Log "Removed firewall rule: $ruleName"
                    }
                    $rulesRemoved++
                }
            } catch {
                # Ignore errors for non-existent rules
            }
        }
        
        if (-not $Quiet) {
            if ($rulesRemoved -eq 0) {
                Write-Log "No ServerManager firewall rules found to remove"
            } else {
                Write-Log "Firewall rules cleanup completed ($rulesRemoved rules removed)"
            }
        }
        
    } catch {
        if (-not $Quiet) {
            Write-Log "Warning: Some firewall rules may not have been removed: $($_.Exception.Message)"
        }
    }
}

# Define global variables first
$global:logMemory = @()
$global:logFilePath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Install-Log.txt"
$CurrentVersion = "0.8"
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

# Add this function after global variable definitions
function Test-ExistingInstallation {
    param([string]$RegPath)
    return Test-Path $RegPath
}

function Request-Reinstall {
    $result = [System.Windows.Forms.MessageBox]::Show(
        "An existing Server Manager installation was detected. Do you want to reinstall (this will overwrite previous settings)?",
        "Reinstall Server Manager",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

# Add all missing functions from original script
function Get-InstalledSQLServers {
    $detected = @()
    # Always add SQLite (Python built-in)
    $detected += @{
        Type = "SQLite"
        Version = "3"
        Location = ""
        Display = "SQLite (local file, recommended for most users)"
    }

    # Detect MSSQL (Express or full)
    try {
        $mssqlRegPaths = @(
            "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL"
        )
        foreach ($regPath in $mssqlRegPaths) {
            if (Test-Path $regPath) {
                $props = Get-ItemProperty -Path $regPath
                $instanceNames = @()
                foreach ($prop in $props.PSObject.Properties) {
                    if ($prop.Name -notlike "PS*") {
                        $instanceNames += $prop.Name
                    }
                }
                foreach ($instance in $instanceNames) {
                    $ver = ""
                    try {
                        $verKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$($instance)\MSSQLServer\CurrentVersion"
                        if (Test-Path $verKey) {
                            $ver = (Get-ItemProperty -Path $verKey).CurrentVersion
                        }
                    } catch {}
                    $loc = ".\$instance"
                    $detected += @{
                        Type = $instance
                        Version = $ver
                        Location = $loc
                        Display = "$instance $ver"
                    }
                }
            }
        }
    } catch {}

    # Detect MySQL/MariaDB (look for service)
    try {
        $mysqlService = Get-Service | Where-Object { $_.Name -like "mysql*" -or $_.Name -like "mariadb*" }
        foreach ($svc in $mysqlService) {
            $type = if ($svc.Name -like "mariadb*") { "MariaDB" } else { "MySQL" }
            $ver = ""
            try {
                $exe = (Get-WmiObject Win32_Service -Filter "Name='$($svc.Name)'").PathName
                if ($exe -and (Test-Path $exe)) {
                    $ver = (& "$exe" --version 2>&1 | Select-String -Pattern "\d+\.\d+\.\d+" | Select-Object -First 1).Matches.Value
                }
            } catch {}
            $detected += @{
                Type = $type
                Version = $ver
                Location = "localhost"
                Display = "$type ($svc.Name) $ver"
            }
        }
    } catch {}

    return $detected
}

function Initialize-SQLDatabase {
    param(
        [string]$SQLType,
        [string]$SQLVersion,
        [string]$SQLLocation,
        [string]$DataFolder
    )
    Write-Log "Setting up SQL databases..."

    if ($SQLType -eq "SQLite" -or [string]::IsNullOrEmpty($SQLType)) {
        # Create separate user and Steam databases in db folder
        $dbFolder = $DataFolder -replace "data$", "db"
        if (-not (Test-Path $dbFolder)) {
            New-Item -ItemType Directory -Force -Path $dbFolder | Out-Null
        }
        $userDbFile = Join-Path $dbFolder "servermanager_users.db"
        $steamDbFile = Join-Path $dbFolder "steam_ID.db"
        $global:SQLDatabaseFile = $userDbFile
        $global:SteamDatabaseFile = $steamDbFile
        
        if (-not (Test-Path $userDbFile)) {
            Write-Log "Creating SQLite user database at $userDbFile"
            try {
                $pythonScript = @"
import sqlite3
import sys
dbfile = sys.argv[1]
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
print('SUCCESS: User database created')
"@
                $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempPy -Value $pythonScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $dbResult = python $tempPy $userDbFile 2>&1
                Remove-Item $tempPy -Force -Confirm:$false
                Write-Log "Database creation result: $dbResult"
                
                if (-not (Test-Path $userDbFile)) {
                    throw "User database file was not created successfully"
                }
            } catch {
                throw "Failed to create user database: $($_.Exception.Message)"
            }
            
            # The admin user will be created via GUI after database setup
        }
        
        if (-not (Test-Path $steamDbFile)) {
            Write-Log "Creating SQLite Steam database at $steamDbFile"
            try {
                $steamPythonScript = @"
import sqlite3
import sys
dbfile = sys.argv[1]
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
print('SUCCESS: Steam database created')
"@
                $tempSteamPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempSteamPy -Value $steamPythonScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $steamDbResult = python $tempSteamPy $steamDbFile 2>&1
                Remove-Item $tempSteamPy -Force -Confirm:$false
                Write-Log "Steam database creation result: $steamDbResult"
                
                if (-not (Test-Path $steamDbFile)) {
                    throw "Steam database file was not created successfully"
                }
            } catch {
                Write-Log "Warning: Failed to create Steam database: $($_.Exception.Message)"
            }
        }
        
        # Create cluster management database
        $clusterDbFile = Join-Path $dbFolder "servermanager.db"
        if (-not (Test-Path $clusterDbFile)) {
            Write-Log "Creating SQLite cluster database at $clusterDbFile"
            try {
                $clusterPythonScript = @"
import sqlite3
import sys
from datetime import datetime
dbfile = sys.argv[1]
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
print('SUCCESS: Cluster database created')
"@
                $tempClusterPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempClusterPy -Value $clusterPythonScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $clusterDbResult = python $tempClusterPy $clusterDbFile 2>&1
                Remove-Item $tempClusterPy -Force -Confirm:$false
                Write-Log "Cluster database creation result: $clusterDbResult"
                
                if (-not (Test-Path $clusterDbFile)) {
                    throw "Cluster database file was not created successfully"
                }
            } catch {
                Write-Log "Warning: Failed to create cluster database: $($_.Exception.Message)"
            }
        }
        return $userDbFile
    }
    # Add other SQL types handling here if needed
    return $SQLLocation
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adminRole = (New-Object Security.Principal.WindowsPrincipal $currentUser).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    return $adminRole
}

function Test-AdminPrivileges {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "Administrative privileges required. Automatically elevating..."
        
        try {
            # Get the current script path
            $scriptPath = $MyInvocation.MyCommand.Path
            if (-not $scriptPath) {
                $scriptPath = $PSCommandPath
            }
            
            # Create elevated process
            $processInfo = New-Object System.Diagnostics.ProcessStartInfo
            $processInfo.FileName = "powershell.exe"
            $processInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
            $processInfo.UseShellExecute = $true
            $processInfo.Verb = "runas"
            $processInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            
            Write-Log "Starting elevated process: $($processInfo.FileName) $($processInfo.Arguments)"
            
            $process = [System.Diagnostics.Process]::Start($processInfo)
            
            if ($process) {
                Write-Log "Elevated process started successfully. Exiting current instance."
                exit 0
            } else {
                throw "Failed to start elevated process"
            }
        }
        catch {
            Write-Log "Failed to restart with administrator privileges: $($_.Exception.Message)"
            
            # Show message box only if automatic elevation failed
            [System.Windows.Forms.MessageBox]::Show(
                "This installer requires administrative privileges to install Server Manager.`n`nAutomatic elevation failed. Please run this installer as an administrator manually.`n`nError: $($_.Exception.Message)",
                "Administrator Rights Required",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            )
            exit 1
        }
    } else {
        Write-Log "Running with administrative privileges confirmed."
    }
}

function New-Servermanager {
    param ([string]$dir)
    if (-Not (Test-Path -Path $dir)) {
        try {
            Write-Log "Directory does not exist, creating: $dir"
            New-Item -ItemType Directory -Force -Path $dir
            Write-Log "Successfully created directory: $dir"
        } catch {
            Write-Log "Failed to create directory: $($_.Exception.Message)"
            throw
        }
    } else {
        Write-Log "Directory already exists: $dir"
    }
}

function Install-Git {
    if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Log "Git is not installed. Installing Git..."
        try {
            $installerUrl = "https://api.github.com/repos/git-for-windows/git/releases/latest"
            $latestRelease = Invoke-RestMethod -Uri $installerUrl
            $installerUrl = ($latestRelease.assets | Where-Object { $_.name -like "*64-bit.exe" }).browser_download_url
            $installerPath = Join-Path $env:TEMP "git-installer.exe"

            Write-Log "Downloading Git installer..."
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Log "Running Git installer..."
            Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART" -Wait

            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
                throw "Git installation failed verification"
            }

            Write-Log "Git installation completed."
            Remove-Item -Path $installerPath -Force -Confirm:$false
        } catch {
            Write-Log "Failed to install Git: $($_.Exception.Message)"
            exit 1
        }
    } else {
        Write-Log "Git is already installed."
    }
}

function Update-SteamCmd {
    param ([string]$steamCmdPath)
    Write-Log "Running SteamCMD update..."
    try {
        if (Test-Path $steamCmdPath) {
            Write-Log "SteamCMD executable found at $steamCmdPath"
            Start-Process -FilePath $steamCmdPath -ArgumentList "+login anonymous +quit" -NoNewWindow -Wait
            Write-Log "SteamCMD updated successfully."
        } else {
            Write-Log "SteamCMD executable not found. Cannot run update."
            exit
        }
    } catch {
        Write-Log "Failed to update SteamCMD: $($_.Exception.Message)"
    }
}

function Stop-RunningServerManager {
    Write-Log "Checking for and stopping any running Server Manager instances..."
    
    try {
        # Check for the Server Manager service
        $service = Get-Service -Name "ServerManager" -ErrorAction SilentlyContinue
        if ($service -and $service.Status -eq 'Running') {
            Write-Log "Stopping Server Manager service..."
            Stop-Service -Name "ServerManager" -Force -ErrorAction Stop
            Start-Sleep -Seconds 3
            Write-Log "Server Manager service stopped"
        }
        
        # Check for any python processes that might be running Server Manager
        $pythonProcesses = Get-Process -Name "python*" -ErrorAction SilentlyContinue
        foreach ($proc in $pythonProcesses) {
            try {
                $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)").CommandLine
                if ($cmdLine -and ($cmdLine -like "*servermanager*" -or $cmdLine -like "*Start-ServerManager*")) {
                    Write-Log "Stopping Server Manager Python process (PID: $($proc.Id))"
                    $proc.CloseMainWindow()
                    Start-Sleep -Seconds 2
                    if (-not $proc.HasExited) {
                        $proc.Kill()
                        Start-Sleep -Seconds 1
                    }
                    Write-Log "Server Manager process stopped"
                }
            } catch {
                Write-Log "Warning: Could not stop process $($proc.ProcessName): $($_.Exception.Message)"
            }
        }
        
        # Check for any pythonw.exe processes (windowless Python)
        $pythonwProcesses = Get-Process -Name "pythonw*" -ErrorAction SilentlyContinue
        foreach ($proc in $pythonwProcesses) {
            try {
                $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)").CommandLine
                if ($cmdLine -and ($cmdLine -like "*servermanager*" -or $cmdLine -like "*Start-ServerManager*")) {
                    Write-Log "Stopping Server Manager Python windowless process (PID: $($proc.Id))"
                    $proc.Kill()
                    Start-Sleep -Seconds 1
                    Write-Log "Server Manager windowless process stopped"
                }
            } catch {
                Write-Log "Warning: Could not stop process $($proc.ProcessName): $($_.Exception.Message)"
            }
        }
        
        return $true
    } catch {
        Write-Log "Warning: Error while stopping Server Manager instances: $($_.Exception.Message)"
        return $false
    }
}

# Function to force delete directories using .NET methods (bypasses PowerShell confirmation system)
function Remove-DirectoryForce {
    param([string]$Path)
    
    if (-not (Test-Path $Path)) {
        return $true
    }
    
    try {
        Write-Log "Using .NET Directory.Delete to force remove: $Path"
        
        # First try to remove all read-only attributes
        if (Test-Path $Path) {
            Get-ChildItem -Path $Path -Recurse -Force | ForEach-Object {
                try {
                    $_.Attributes = [System.IO.FileAttributes]::Normal
                } catch {
                    # Ignore errors
                }
            }
        }
        
        # Use .NET method which is more forceful than PowerShell cmdlets
        [System.IO.Directory]::Delete($Path, $true)
        Write-Log "Successfully removed directory using .NET method"
        return $true
        
    } catch {
        Write-Log "NET Directory.Delete failed: $($_.Exception.Message)"
        return $false
    }
}

function Remove-ExistingInstallation {
    param([string]$destination)
    
    Write-Log "Attempting to clean up existing installation at: $destination"
    
    if (-not (Test-Path $destination)) {
        Write-Log "No existing installation found at destination"
        return $true
    }
    
    try {
        # First attempt: Try the .NET method directly (most reliable)
        if (Force-DeleteDirectory -Path $destination) {
            Write-Log "Successfully removed directory using .NET method"
            return $true
        }
        
        # Second attempt: Use robocopy method to force delete the directory - this bypasses most Windows file locking issues
        Write-Log "Using robocopy method to force remove directory..."
        
        # Create empty temp directory
        $emptyDir = Join-Path $env:TEMP "empty_$(Get-Date -Format 'yyyyMMddHHmmss')"
        New-Item -ItemType Directory -Path $emptyDir -Force | Out-Null
        
        # Use robocopy to "mirror" empty directory over the target (effectively deleting everything)
        Write-Log "Running robocopy to clear directory contents..."
        Start-Process -FilePath "robocopy.exe" -ArgumentList "`"$emptyDir`"", "`"$destination`"", "/MIR", "/R:0", "/W:0", "/NFL", "/NDL", "/NJH", "/NJS" -Wait -WindowStyle Hidden | Out-Null
        
        # Clean up empty temp directory
        Remove-Item -Path $emptyDir -Force -Confirm:$false -ErrorAction SilentlyContinue
        
        # Try to remove the now-empty destination directory
        if (Test-Path $destination) {
            try {
                [System.IO.Directory]::Delete($destination, $true)
                Write-Log "Successfully removed directory using System.IO.Directory.Delete"
            } catch {
                # Fallback to PowerShell cmdlet with all suppression flags
                try {
                    $null = Remove-Item -Path $destination -Recurse -Force -Confirm:$false -ErrorAction Stop 2>$null
                    Write-Log "Successfully removed directory using Remove-Item"
                } catch {
                    Write-Log "Standard removal failed, trying alternative method..."
                    
                    # Ultimate fallback: Use cmd.exe rmdir
                    Write-Log "Using cmd.exe rmdir as final removal method..."
                    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "rmdir", "/s", "/q", "`"$destination`"" -Wait -WindowStyle Hidden | Out-Null
                    
                    if (Test-Path $destination) {
                        # Last resort: rename the directory
                        try {
                            $backupName = "$destination.old.$(Get-Date -Format 'yyyyMMddHHmmss')"
                            [System.IO.Directory]::Move($destination, $backupName)
                            Write-Log "Renamed problematic directory to: $backupName"
                            Write-Log "Installation will continue. Please manually remove $backupName later."
                        } catch {
                            throw "Could not remove or rename existing installation directory. Please manually delete '$destination' and run the installer again."
                        }
                    } else {
                        Write-Log "Successfully removed directory using cmd rmdir"
                    }
                }
            }
        }
        
        return $true
        
    } catch {
        Write-Log "Error during cleanup: $($_.Exception.Message)"
        
        # Final attempt: try to create the installation in a different location
        $alternativeDir = "$destination.new.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Write-Log "All cleanup attempts failed. Installation will use alternative directory: $alternativeDir"
        throw "ALTERNATIVE_PATH:$alternativeDir"
    }
}

function Initialize-GitRepo {
    param ([string]$repoUrl, [string]$destination, [System.Windows.Forms.Label]$StatusLabel = $null, [System.Windows.Forms.Form]$Form = $null)
    
    Write-Log "Attempting to download Server Manager from Git repository..."
    $actualDestination = $destination  # Track the actual destination in case it changes
    
    try {
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            Write-Log "Git not found, skipping to website download..."
            throw "Git not available, using website fallback"
        }
        
        # Use the new removal function
        if (Test-Path $actualDestination) {
            Write-Log "Removing existing directory..."
            try {
                if (-not (Remove-ExistingInstallation -destination $actualDestination)) {
                    throw "Failed to remove existing installation"
                }
            } catch {
                if ($_.Exception.Message -like "ALTERNATIVE_PATH:*") {
                    $actualDestination = $_.Exception.Message.Split(':')[1]
                    Write-Log "Using alternative installation path: $actualDestination"
                } else {
                    throw
                }
            }
        }
        
        Write-Log "Testing repository access before full clone..."
        
        # Update status label if provided
        if ($StatusLabel -and $Form) {
            $StatusLabel.Text = "Testing repository access..."
            $Form.Refresh()
        }
        
        # First, test if we can access the repository without credentials by doing a lightweight operation
        Write-Log "Checking if repository is publicly accessible..."
        $testProcess = Start-Process -FilePath "git" -ArgumentList "ls-remote", "--exit-code", $repoUrl, "HEAD" -NoNewWindow -PassThru -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
        
        # Give it 10 seconds max to respond
        $testCompleted = $testProcess.WaitForExit(10000)
        
        if (-not $testCompleted) {
            Write-Log "Repository access test timed out - likely requires authentication"
            try {
                $testProcess.Kill()
                $testProcess.WaitForExit(2000)
            } catch {
                # Ignore kill errors
            }
            throw "Repository requires authentication, using website fallback"
        }
        
        if ($testProcess.ExitCode -ne 0) {
            Write-Log "Repository access test failed with exit code $($testProcess.ExitCode) - likely private or requires authentication"
            throw "Repository not publicly accessible, using website fallback"
        }
        
        Write-Log "Repository is publicly accessible, proceeding with clone..."
        
        # Update status for actual clone
        if ($StatusLabel -and $Form) {
            $StatusLabel.Text = "Cloning repository..."
            $Form.Refresh()
        }
        
        # Now do the actual clone with a timeout
        $gitProcess = Start-Process -FilePath "git" -ArgumentList "clone", "--depth", "1", "--single-branch", $repoUrl, $actualDestination -NoNewWindow -PassThru -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
        
        # Wait for the process to complete with timeout (30 seconds for the actual clone)
        $timeoutReached = $false
        if (-not $gitProcess.WaitForExit(30000)) {
            Write-Log "Git clone timed out after 30 seconds"
            try {
                $gitProcess.Kill()
                $gitProcess.WaitForExit(2000)
            } catch {
                Write-Log "Failed to kill git process: $($_.Exception.Message)"
            }
            $timeoutReached = $true
        }
        
        if ($timeoutReached) {
            throw "Git clone operation timed out, using website fallback"
        }
        
        if ($gitProcess.ExitCode -ne 0) {
            throw "Git clone failed with exit code: $($gitProcess.ExitCode), using website fallback"
        }
        
        # Verify the clone was successful
        if (Test-Path $actualDestination) {
            Write-Log "Git repository successfully cloned."
            # Update the original destination variable if it changed
            if ($actualDestination -ne $destination) {
                Write-Log "Installation completed in alternative directory: $actualDestination"
            }
            return
        } else {
            throw "Repository directory not created after clone, using website fallback"
        }
        
    } catch {
        Write-Log "Git download failed: $($_.Exception.Message)"
        Write-Log "Falling back to website download..."
        
        # Clean up any partial clone
        if (Test-Path $actualDestination) {
            try {
                Force-DeleteDirectory -Path $actualDestination
            } catch {
                # Ignore cleanup errors
            }
        }
        
        # Update status for website fallback
        if ($StatusLabel -and $Form) {
            $StatusLabel.Text = "Git failed, downloading from website..."
            $Form.Refresh()
        }
        
        try {
            Download-FromWebsite -destination $destination -StatusLabel $StatusLabel -Form $Form
            Write-Log "Successfully downloaded Server Manager from website"
            return
        } catch {
            Write-Log "Website download also failed: $($_.Exception.Message)"
            
            # Final error message
            $errorMessage = @"
Both Git repository and website download failed.

This could be because:
1. The Git repository requires authentication (private repository)
2. The website is temporarily unavailable  
3. Network connectivity issues

Please contact the developer for assistance or try again later.

Technical Details:
- Git Error: Repository access failed or timed out
- Website Error: $($_.Exception.Message)
"@
            throw $errorMessage
        }
    }
}

function Get-FromWebsite {
    param ([string]$destination, [System.Windows.Forms.Label]$StatusLabel = $null, [System.Windows.Forms.Form]$Form = $null)
    
    Write-Log "Attempting to download Server Manager from website..."
    $websiteUrl = "https://www.skywereindustries.com/servermanager/releases/latest.zip"
    $tempZip = Join-Path $env:TEMP "servermanager-latest.zip"
    $maxAttempts = 3
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            # Clean up destination if it exists using the improved method
            if (Test-Path $destination) {
                if (-not (Remove-ExistingInstallation -destination $destination)) {
                    throw "Failed to remove existing installation"
                }
            }
            
            Write-Log "Website download attempt $attempt of $maxAttempts..."
            
            # Update status label if provided
            if ($StatusLabel -and $Form) {
                $StatusLabel.Text = "Website download attempt $attempt of $maxAttempts..."
                $Form.Refresh()
            }
            
            # Use Invoke-WebRequest with timeout instead of WebClient
            Write-Log "Downloading from $websiteUrl..."
            Invoke-WebRequest -Uri $websiteUrl -OutFile $tempZip -TimeoutSec 120 -UseBasicParsing
            
            if (-not (Test-Path $tempZip)) {
                throw "Download file was not created"
            }
            
            $fileSize = (Get-Item $tempZip).Length
            if ($fileSize -lt 1024) {
                throw "Downloaded file is too small ($fileSize bytes), probably an error page"
            }
            
            Write-Log "Downloaded $fileSize bytes successfully"
            
            # Update status for extraction
            if ($StatusLabel -and $Form) {
                $StatusLabel.Text = "Extracting downloaded files..."
                $Form.Refresh()
            }
            
            Write-Log "Extracting files..."
            
            # Create destination directory
            New-Item -ItemType Directory -Force -Path $destination | Out-Null
            
            # Extract with error handling using Add-Type for System.IO.Compression
            try {
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                [System.IO.Compression.ZipFile]::ExtractToDirectory($tempZip, $destination)
            } catch {
                # Fallback to Expand-Archive if ZipFile fails
                Write-Log "ZipFile extraction failed, trying Expand-Archive..."
                Expand-Archive -Path $tempZip -DestinationPath $destination -Force
            }
            
            # Check if files were extracted to a subdirectory and move them up if needed
            $extractedItems = Get-ChildItem -Path $destination -ErrorAction SilentlyContinue
            if ($extractedItems.Count -eq 1 -and $extractedItems[0].PSIsContainer) {
                $subDir = $extractedItems[0].FullName
                $tempDir = "$destination-temp"
                
                Write-Log "Moving files from subdirectory to main directory..."
                
                # Move subdirectory contents to temp location
                Move-Item -Path $subDir -Destination $tempDir -Force -Confirm:$false
                
                # Remove original destination and move temp to destination
                Remove-Item -Path $destination -Recurse -Force -Confirm:$false
                Move-Item -Path $tempDir -Destination $destination -Force -Confirm:$false
            }
            
            # Verify extraction
            $finalItems = Get-ChildItem -Path $destination -ErrorAction SilentlyContinue
            if ($finalItems.Count -eq 0) {
                throw "No files were extracted from the archive"
            }
            
            Write-Log "Successfully downloaded and extracted Server Manager files from website ($($finalItems.Count) items)"
            
            # Clean up
            if (Test-Path $tempZip) {
                Remove-Item -Path $tempZip -Force -Confirm:$false
            }
            
            return
            
        } catch {
            Write-Log "Website download attempt $attempt failed: $($_.Exception.Message)"
            
            # Clean up on failure
            if (Test-Path $tempZip) {
                Remove-Item -Path $tempZip -Force -Confirm:$false -ErrorAction SilentlyContinue
            }
            if (Test-Path $destination) {
                Remove-Item -Path $destination -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
            }
            
            if ($attempt -eq $maxAttempts) {
                throw "Website download failed after $maxAttempts attempts: $($_.Exception.Message)"
            } else {
                Write-Log "Retrying website download in 2 seconds..."
                
                # Update status for retry
                if ($StatusLabel -and $Form) {
                    $StatusLabel.Text = "Website attempt $attempt failed, retrying in 2 seconds..."
                    $Form.Refresh()
                }
                
                Start-Sleep -Seconds 2
            }
        }
    }
}

# --- Main installer script (continued) ---

# Unified installer form
function Show-InstallerWizard {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Server Manager Installer v$CurrentVersion"
    $form.Size = New-Object System.Drawing.Size(650, 550)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon("$env:SystemRoot\System32\msiexec.exe")

    # Header panel
    $headerPanel = New-Object System.Windows.Forms.Panel
    $headerPanel.Location = New-Object System.Drawing.Point(0, 0)
    $headerPanel.Size = New-Object System.Drawing.Size(650, 60)
    $headerPanel.BackColor = [System.Drawing.Color]::White
    $form.Controls.Add($headerPanel)

    # Header title
    $headerTitle = New-Object System.Windows.Forms.Label
    $headerTitle.Text = "Server Manager Setup Wizard"
    $headerTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $headerTitle.Location = New-Object System.Drawing.Point(20, 10)
    $headerTitle.Size = New-Object System.Drawing.Size(400, 25)
    $headerPanel.Controls.Add($headerTitle)

    # Header subtitle
    $headerSubtitle = New-Object System.Windows.Forms.Label
    $headerSubtitle.Text = "This wizard will guide you through the installation of Server Manager"
    $headerSubtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $headerSubtitle.Location = New-Object System.Drawing.Point(20, 35)
    $headerSubtitle.Size = New-Object System.Drawing.Size(500, 20)
    $headerPanel.Controls.Add($headerSubtitle)

    # Main content panel
    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(0, 60)
    $contentPanel.Size = New-Object System.Drawing.Size(650, 380)
    $contentPanel.BackColor = [System.Drawing.Color]::White
    $form.Controls.Add($contentPanel)

    # Bottom panel for buttons and progress
    $bottomPanel = New-Object System.Windows.Forms.Panel
    $bottomPanel.Location = New-Object System.Drawing.Point(0, 440)
    $bottomPanel.Size = New-Object System.Drawing.Size(650, 80)
    $bottomPanel.BackColor = [System.Drawing.SystemColors]::Control
    $form.Controls.Add($bottomPanel)

    # Separator line
    $separator = New-Object System.Windows.Forms.Label
    $separator.BorderStyle = [System.Windows.Forms.BorderStyle]::Fixed3D
    $separator.Location = New-Object System.Drawing.Point(0, 0)
    $separator.Size = New-Object System.Drawing.Size(650, 2)
    $bottomPanel.Controls.Add($separator)

    # Progress bar
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(20, 15)
    $progressBar.Size = New-Object System.Drawing.Size(610, 20)
    $progressBar.Style = 'Continuous'
    $progressBar.Visible = $false
    $bottomPanel.Controls.Add($progressBar)

    # Status label
    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Text = ""
    $statusLabel.Location = New-Object System.Drawing.Point(20, 40)
    $statusLabel.Size = New-Object System.Drawing.Size(500, 20)
    $statusLabel.Visible = $false
    $bottomPanel.Controls.Add($statusLabel)

    # Navigation buttons
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.Location = New-Object System.Drawing.Point(365, 35)
    $cancelButton.Size = New-Object System.Drawing.Size(85, 30)
    $bottomPanel.Controls.Add($cancelButton)

    $backButton = New-Object System.Windows.Forms.Button
    $backButton.Text = "< Back"
    $backButton.Location = New-Object System.Drawing.Point(450, 35)
    $backButton.Size = New-Object System.Drawing.Size(85, 30)
    $backButton.Enabled = $false
    $bottomPanel.Controls.Add($backButton)

    $nextButton = New-Object System.Windows.Forms.Button
    $nextButton.Text = "Next >"
    $nextButton.Location = New-Object System.Drawing.Point(545, 35)
    $nextButton.Size = New-Object System.Drawing.Size(85, 30)
    $bottomPanel.Controls.Add($nextButton)

    # Create wizard pages
    $pages = @()
    $currentPageIndex = 0

    # Page 1: Welcome
    $welcomePage = New-Object System.Windows.Forms.Panel
    $welcomePage.Location = New-Object System.Drawing.Point(20, 20)
    $welcomePage.Size = New-Object System.Drawing.Size(610, 340)
    $welcomePage.Visible = $true
    $contentPanel.Controls.Add($welcomePage)

    $welcomeTitle = New-Object System.Windows.Forms.Label
    $welcomeTitle.Text = "Welcome to Server Manager Setup"
    $welcomeTitle.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
    $welcomeTitle.Location = New-Object System.Drawing.Point(20, 20)
    $welcomeTitle.Size = New-Object System.Drawing.Size(400, 30)
    $welcomePage.Controls.Add($welcomeTitle)

    $welcomeText = New-Object System.Windows.Forms.Label
    $welcomeText.Text = @"
This wizard will install Server Manager on your computer.

Server Manager is a comprehensive tool for managing game servers, providing an easy-to-use web interface for server administration, user management, and automated server deployment.

Click Next to continue, or Cancel to exit Setup.
"@
    $welcomeText.Location = New-Object System.Drawing.Point(20, 70)
    $welcomeText.Size = New-Object System.Drawing.Size(550, 150)
    $welcomePage.Controls.Add($welcomeText)

    $pages += $welcomePage

    # Page 2: Installation Options
    $optionsPage = New-Object System.Windows.Forms.Panel
    $optionsPage.Location = New-Object System.Drawing.Point(20, 20)
    $optionsPage.Size = New-Object System.Drawing.Size(610, 340)
    $optionsPage.Visible = $false
    $contentPanel.Controls.Add($optionsPage)

    $optionsTitle = New-Object System.Windows.Forms.Label
    $optionsTitle.Text = "Installation Options"
    $optionsTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $optionsTitle.Location = New-Object System.Drawing.Point(20, 20)
    $optionsTitle.Size = New-Object System.Drawing.Size(300, 25)
    $optionsPage.Controls.Add($optionsTitle)

    # SteamCMD Path
    $steamCmdLabel = New-Object System.Windows.Forms.Label
    $steamCmdLabel.Text = "SteamCMD Installation Directory:"
    $steamCmdLabel.Location = New-Object System.Drawing.Point(20, 60)
    $steamCmdLabel.Size = New-Object System.Drawing.Size(220, 20)
    $optionsPage.Controls.Add($steamCmdLabel)

    $steamCmdBox = New-Object System.Windows.Forms.TextBox
    $steamCmdBox.Location = New-Object System.Drawing.Point(20, 85)
    $steamCmdBox.Size = New-Object System.Drawing.Size(450, 20)
    $steamCmdBox.Text = "C:\SteamCMD"
    $optionsPage.Controls.Add($steamCmdBox)

    $steamCmdBrowse = New-Object System.Windows.Forms.Button
    $steamCmdBrowse.Text = "Browse..."
    $steamCmdBrowse.Location = New-Object System.Drawing.Point(480, 85)
    $steamCmdBrowse.Size = New-Object System.Drawing.Size(85, 28)
    $optionsPage.Controls.Add($steamCmdBrowse)

    # User Workspace Path
    $workspaceLabel = New-Object System.Windows.Forms.Label
    $workspaceLabel.Text = "User Workspace Directory:"
    $workspaceLabel.Location = New-Object System.Drawing.Point(20, 120)
    $workspaceLabel.Size = New-Object System.Drawing.Size(220, 20)
    $optionsPage.Controls.Add($workspaceLabel)

    $workspaceBox = New-Object System.Windows.Forms.TextBox
    $workspaceBox.Location = New-Object System.Drawing.Point(20, 145)
    $workspaceBox.Size = New-Object System.Drawing.Size(450, 20)
    $workspaceBox.Text = Join-Path $steamCmdBox.Text "user_workspace"
    $workspaceBox.ReadOnly = $true
    $optionsPage.Controls.Add($workspaceBox)

    $workspaceBrowse = New-Object System.Windows.Forms.Button
    $workspaceBrowse.Text = "Browse..."
    $workspaceBrowse.Location = New-Object System.Drawing.Point(480, 145)
    $workspaceBrowse.Size = New-Object System.Drawing.Size(85, 28)
    $optionsPage.Controls.Add($workspaceBrowse)

    # Custom workspace checkbox
    $customWorkspaceCheckbox = New-Object System.Windows.Forms.CheckBox
    $customWorkspaceCheckbox.Text = "Use custom workspace directory"
    $customWorkspaceCheckbox.Location = New-Object System.Drawing.Point(20, 175)
    $customWorkspaceCheckbox.Size = New-Object System.Drawing.Size(250, 20)
    $optionsPage.Controls.Add($customWorkspaceCheckbox)

    # Service installation
    $serviceCheckbox = New-Object System.Windows.Forms.CheckBox
    $serviceCheckbox.Text = "Install as Windows Service (recommended - starts automatically with Windows)"
    $serviceCheckbox.Location = New-Object System.Drawing.Point(20, 210)
    $serviceCheckbox.Size = New-Object System.Drawing.Size(500, 20)
    $optionsPage.Controls.Add($serviceCheckbox)

    # Host type group - Simple cluster configuration
    $hostGroupBox = New-Object System.Windows.Forms.GroupBox
    $hostGroupBox.Text = "Cluster Type"
    $hostGroupBox.Location = New-Object System.Drawing.Point(20, 240)
    $hostGroupBox.Size = New-Object System.Drawing.Size(540, 100)
    $optionsPage.Controls.Add($hostGroupBox)

    $hostRadio = New-Object System.Windows.Forms.RadioButton
    $hostRadio.Text = "Master Host - Manage other servers in the cluster"
    $hostRadio.Location = New-Object System.Drawing.Point(15, 25)
    $hostRadio.Size = New-Object System.Drawing.Size(350, 20)
    $hostRadio.Checked = $true
    $hostGroupBox.Controls.Add($hostRadio)

    $subhostRadio = New-Object System.Windows.Forms.RadioButton
    $subhostRadio.Text = "Cluster Node - Managed by another Master Host"
    $subhostRadio.Location = New-Object System.Drawing.Point(15, 50)
    $subhostRadio.Size = New-Object System.Drawing.Size(300, 20)
    $hostGroupBox.Controls.Add($subhostRadio)

    # Master Host IP for cluster nodes
    $hostAddrLabel = New-Object System.Windows.Forms.Label
    $hostAddrLabel.Text = "Master Host IP Address:"
    $hostAddrLabel.Location = New-Object System.Drawing.Point(300, 50)
    $hostAddrLabel.Size = New-Object System.Drawing.Size(150, 20)
    $hostAddrLabel.Visible = $false
    $hostGroupBox.Controls.Add($hostAddrLabel)

    $hostAddrBox = New-Object System.Windows.Forms.TextBox
    $hostAddrBox.Location = New-Object System.Drawing.Point(450, 48)
    $hostAddrBox.Size = New-Object System.Drawing.Size(100, 20)
    $hostAddrBox.Visible = $false
    $hostAddrBox.Text = ""
    $hostAddrBox.ForeColor = [System.Drawing.Color]::Black
    
    $hostGroupBox.Controls.Add($hostAddrBox)

    $pages += $optionsPage

    # Page 3: Database Configuration
    $dbPage = New-Object System.Windows.Forms.Panel
    $dbPage.Location = New-Object System.Drawing.Point(20, 20)
    $dbPage.Size = New-Object System.Drawing.Size(610, 340)
    $dbPage.Visible = $false
    $contentPanel.Controls.Add($dbPage)

    $dbTitle = New-Object System.Windows.Forms.Label
    $dbTitle.Text = "Database Configuration"
    $dbTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $dbTitle.Location = New-Object System.Drawing.Point(20, 20)
    $dbTitle.Size = New-Object System.Drawing.Size(300, 25)
    $dbPage.Controls.Add($dbTitle)

    $dbDesc = New-Object System.Windows.Forms.Label
    $dbDesc.Text = "Select the database type for storing user accounts and server configurations."
    $dbDesc.Location = New-Object System.Drawing.Point(20, 50)
    $dbDesc.Size = New-Object System.Drawing.Size(500, 20)
    $dbPage.Controls.Add($dbDesc)

    $sqlTypeLabel = New-Object System.Windows.Forms.Label
    $sqlTypeLabel.Text = "Database Type:"
    $sqlTypeLabel.Location = New-Object System.Drawing.Point(20, 90)
    $sqlTypeLabel.Size = New-Object System.Drawing.Size(100, 20)
    $dbPage.Controls.Add($sqlTypeLabel)

    $sqlTypeCombo = New-Object System.Windows.Forms.ComboBox
    $sqlTypeCombo.Location = New-Object System.Drawing.Point(130, 90)
    $sqlTypeCombo.Size = New-Object System.Drawing.Size(300, 20)
    $sqlTypeCombo.DropDownStyle = 'DropDownList'
    $dbPage.Controls.Add($sqlTypeCombo)

    # Populate SQL types
    $detected = Get-InstalledSQLServers
    foreach ($item in $detected) {
        $sqlTypeCombo.Items.Add($item.Display)
    }
    if ($sqlTypeCombo.Items.Count -gt 0) {
        $sqlTypeCombo.SelectedIndex = 0
    }

    $sqlLocationLabel = New-Object System.Windows.Forms.Label
    $sqlLocationLabel.Text = "Connection String:"
    $sqlLocationLabel.Location = New-Object System.Drawing.Point(20, 130)
    $sqlLocationLabel.Size = New-Object System.Drawing.Size(120, 20)
    $dbPage.Controls.Add($sqlLocationLabel)

    $sqlLocationBox = New-Object System.Windows.Forms.TextBox
    $sqlLocationBox.Location = New-Object System.Drawing.Point(20, 155)
    $sqlLocationBox.Size = New-Object System.Drawing.Size(540, 20)
    if ($detected.Count -gt 0) {
        $sqlLocationBox.Text = if ($detected[0].Type -eq "SQLite") { "(no connection string required)" } else { $detected[0].Location }
        $sqlLocationBox.ReadOnly = ($detected[0].Type -eq "SQLite")
    }
    $dbPage.Controls.Add($sqlLocationBox)

    $sqlNote = New-Object System.Windows.Forms.Label
    $sqlNote.Text = "Note: SQLite is recommended for most installations as it requires no additional setup."
    $sqlNote.Font = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Italic)
    $sqlNote.Location = New-Object System.Drawing.Point(20, 185)
    $sqlNote.Size = New-Object System.Drawing.Size(500, 30)
    $dbPage.Controls.Add($sqlNote)

    $pages += $dbPage

    # Page 4: Installation Progress
    $installPage = New-Object System.Windows.Forms.Panel
    $installPage.Location = New-Object System.Drawing.Point(20, 20)
    $installPage.Size = New-Object System.Drawing.Size(610, 340)
    $installPage.Visible = $false
    $contentPanel.Controls.Add($installPage)

    $installTitle = New-Object System.Windows.Forms.Label
    $installTitle.Text = "Installing Server Manager"
    $installTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $installTitle.Location = New-Object System.Drawing.Point(20, 20)
    $installTitle.Size = New-Object System.Drawing.Size(300, 25)
    $installPage.Controls.Add($installTitle)

    $installDesc = New-Object System.Windows.Forms.Label
    $installDesc.Text = "Please wait while Server Manager is being installed..."
    $installDesc.Location = New-Object System.Drawing.Point(20, 50)
    $installDesc.Size = New-Object System.Drawing.Size(400, 20)
    $installPage.Controls.Add($installDesc)

    $installProgressBar = New-Object System.Windows.Forms.ProgressBar
    $installProgressBar.Location = New-Object System.Drawing.Point(20, 100)
    $installProgressBar.Size = New-Object System.Drawing.Size(570, 25)
    $installProgressBar.Style = 'Continuous'
    $installPage.Controls.Add($installProgressBar)

    $installStatusLabel = New-Object System.Windows.Forms.Label
    $installStatusLabel.Text = "Preparing installation..."
    $installStatusLabel.Location = New-Object System.Drawing.Point(20, 140)
    $installStatusLabel.Size = New-Object System.Drawing.Size(570, 20)
    $installPage.Controls.Add($installStatusLabel)

    $pages += $installPage

    # Page 5: Completion
    $completePage = New-Object System.Windows.Forms.Panel
    $completePage.Location = New-Object System.Drawing.Point(20, 20)
    $completePage.Size = New-Object System.Drawing.Size(610, 340)
    $completePage.Visible = $false
    $contentPanel.Controls.Add($completePage)

    $completeTitle = New-Object System.Windows.Forms.Label
    $completeTitle.Text = "Installation Complete"
    $completeTitle.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
    $completeTitle.Location = New-Object System.Drawing.Point(20, 20)
    $completeTitle.Size = New-Object System.Drawing.Size(400, 30)
    $completePage.Controls.Add($completeTitle)

    $completeText = New-Object System.Windows.Forms.Label
    $completeText.Text = @"
Server Manager has been successfully installed on your computer.

You can now:
Access the web interface at http://localhost:8080
Log in with username: admin, password: admin
Start managing your game servers

Click Finish to complete the setup.
"@
    $completeText.Location = New-Object System.Drawing.Point(20, 70)
    $completeText.Size = New-Object System.Drawing.Size(550, 150)
    $completePage.Controls.Add($completeText)

    $pages += $completePage

    # Event handlers
    $steamCmdBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select SteamCMD installation directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $steamCmdBox.Text = $dialog.SelectedPath
            # Update workspace path if not using custom
            if (-not $customWorkspaceCheckbox.Checked) {
                $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
            }
        }
    })

    $workspaceBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select user workspace parent directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
        }
    })

    $customWorkspaceCheckbox.Add_CheckedChanged({
        if ($customWorkspaceCheckbox.Checked) {
            $workspaceBox.ReadOnly = $false
            $workspaceBrowse.Enabled = $true
            $workspaceBox.Text = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "user_workspace"
        } else {
            $workspaceBox.ReadOnly = $true
            $workspaceBrowse.Enabled = $false
            $workspaceBox.Text = Join-Path $steamCmdBox.Text "user_workspace"
        }
    })

    $subhostRadio.Add_CheckedChanged({
        $hostAddrLabel.Visible = $subhostRadio.Checked
        $hostAddrBox.Visible = $subhostRadio.Checked
    })

    $sqlTypeCombo.Add_SelectedIndexChanged({
        if ($sqlTypeCombo.SelectedIndex -ge 0) {
            $selectedItem = $detected[$sqlTypeCombo.SelectedIndex]
            if ($selectedItem.Type -eq "SQLite") {
                $sqlLocationBox.Text = "(no connection string required)"
                $sqlLocationBox.ReadOnly = $true
            } else {
                $sqlLocationBox.Text = $selectedItem.Location
                $sqlLocationBox.ReadOnly = $false
            }
        }
    })

    function Show-Page($index) {
        for ($i = 0; $i -lt $pages.Count; $i++) {
            $pages[$i].Visible = ($i -eq $index)
        }
        
        # Update header subtitle based on current page
        switch ($index) {
            0 { $headerSubtitle.Text = "Welcome to the Server Manager Setup Wizard" }
            1 { $headerSubtitle.Text = "Choose installation options and directories" }
            2 { $headerSubtitle.Text = "Configure the database for user accounts" }
            3 { $headerSubtitle.Text = "Installing Server Manager components..." }
            4 { $headerSubtitle.Text = "Setup completed successfully" }
        }
        
        # Update button states
        $backButton.Enabled = ($index -gt 0 -and $index -ne 3 -and $index -ne 4)
        $nextButton.Enabled = ($index -ne 3)  # Enable for all pages except installation progress
        $cancelButton.Enabled = ($index -ne 3 -and $index -ne 4)
        
        if ($index -eq 2) {
            $nextButton.Text = "Install"
            $nextButton.Enabled = $true  # Explicitly enable Install button
        } elseif ($index -eq 4) {
            $nextButton.Text = "Finish"
            $nextButton.Enabled = $true
        } else {
            $nextButton.Text = "Next >"
        }
        
        $script:currentPageIndex = $index
    }

    $nextButton.Add_Click({
        switch ($script:currentPageIndex) {
            0 { Show-Page 1 }
            1 { Show-Page 2 }
            2 { 
                # Simple validation for cluster nodes
                if ($subhostRadio.Checked) {
                    $hostAddress = $hostAddrBox.Text.Trim()
                    
                    # Validate Master Host IP Address is required
                    if ([string]::IsNullOrWhiteSpace($hostAddress)) {
                        [System.Windows.Forms.MessageBox]::Show(
                            "Master Host IP Address is required for cluster nodes.", 
                            "Validation Error", 
                            [System.Windows.Forms.MessageBoxButtons]::OK, 
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        return
                    }
                    
                    # Basic IP format validation
                    if (-not ($hostAddress -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')) {
                        [System.Windows.Forms.MessageBox]::Show(
                            "Please enter a valid IP address format (e.g., 192.168.1.50).", 
                            "Validation Error", 
                            [System.Windows.Forms.MessageBoxButtons]::OK, 
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        return
                    }
                }
                
                # Start installation
                Show-Page 3
                $cancelButton.Enabled = $false
                $backButton.Enabled = $false
                $nextButton.Enabled = $false
                
                # Collect settings and start installation
                $hostAddressValue = if ($subhostRadio.Checked) { 
                    $addr = $hostAddrBox.Text.Trim()
                    if ([string]::IsNullOrWhiteSpace($addr)) { $null } else { $addr }
                } else { 
                    $null 
                }
                
                $settings = @{
                    SteamCMDPath = $steamCmdBox.Text
                    UserWorkspacePath = $workspaceBox.Text
                    InstallService = $serviceCheckbox.Checked
                    HostType = if ($hostRadio.Checked) { "Host" } else { "Subhost" }
                    HostAddress = $hostAddressValue
                    SQLType = if ($sqlTypeCombo.SelectedIndex -ge 0) { $detected[$sqlTypeCombo.SelectedIndex].Type } else { "SQLite" }
                    SQLLocation = if ($sqlTypeCombo.SelectedIndex -ge 0 -and $detected[$sqlTypeCombo.SelectedIndex].Type -eq "SQLite") { "" } else { $sqlLocationBox.Text }
                    SQLVersion = if ($sqlTypeCombo.SelectedIndex -ge 0) { $detected[$sqlTypeCombo.SelectedIndex].Version } else { "3" }
                    SubhostID = if ($subhostRadio.Checked) { "$env:COMPUTERNAME-$(Get-Random -Minimum 1000 -Maximum 9999)" } else { $null }
                }
                
                Start-Installation -Settings $settings -ProgressBar $installProgressBar -StatusLabel $installStatusLabel -Form $form -OnComplete {
                    # Handle cluster approval workflow for subhosts
                    if ($settings.HostType -eq "Subhost" -and $settings.HostAddress) {
                        Show-ClusterApprovalDialog -Settings $settings -Form $form -OnApproved {
                            Show-Page 4
                        }
                    } else {
                        Show-Page 4
                    }
                }
            }
            4 { 
                $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
                $form.Close()
            }
        }
    })

    $backButton.Add_Click({
        if ($script:currentPageIndex -gt 0) {
            Show-Page ($script:currentPageIndex - 1)
        }
    })

    $cancelButton.Add_Click({
        $form.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $form.Close()
    })

    # Initialize first page
    Show-Page 0

    return $form.ShowDialog()
}

function Start-Installation {
    param(
        [hashtable]$Settings,
        [System.Windows.Forms.ProgressBar]$ProgressBar,
        [System.Windows.Forms.Label]$StatusLabel,
        [System.Windows.Forms.Form]$Form,
        [scriptblock]$OnComplete
    )

    try {
        # IMMEDIATELY ensure no console prompts during installation - MAXIMUM SUPPRESSION
        Set-NoConsolePrompts
        
        # Also hide the console window completely during GUI operations
        Show-Console -Hide
        
        $totalSteps = 12
        $currentStep = 0

        function Update-Progress([string]$Message) {
            $script:currentStep++
            $StatusLabel.Text = $Message
            $ProgressBar.Value = [math]::Min(100, ($script:currentStep / $totalSteps) * 100)
            $Form.Refresh()
            Write-Log $Message
            Start-Sleep -Milliseconds 200  # Brief pause to show progress
        }

        function Show-StepError([string]$StepName, [string]$ErrorMessage) {
            Write-Log "[ERROR] $StepName failed: $ErrorMessage"
            $result = [System.Windows.Forms.MessageBox]::Show(
                "$StepName failed with the following error:`n`n$ErrorMessage`n`nWould you like to continue with the installation? (Some features may not work properly)",
                "Installation Step Failed",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )
            return $result -eq [System.Windows.Forms.DialogResult]::Yes
        }

        Update-Progress "Checking prerequisites..."
        try {
            Test-AdminPrivileges
        } catch {
            if (-not (Show-StepError "Admin Privilege Check" $_.Exception.Message)) {
                throw "Installation cancelled by user after admin privilege check failed"
            }
        }

        Update-Progress "Stopping any running Server Manager instances..."
        try {
            Stop-RunningServerManager
        } catch {
            Write-Log "Warning: Error stopping running instances: $($_.Exception.Message)"
        }

        Update-Progress "Checking Python 3.10+ installation..."
        try {
            if (-not (Test-Python310)) {
                Update-Progress "Installing Python 3.10..."
                Install-Python310
                if (-not (Test-Python310)) {
                    throw "Python 3.10 (64-bit) installation verification failed"
                }
            }
        } catch {
            if (-not (Show-StepError "Python Installation" "Failed to install or verify Python 3.10 (64-bit): $($_.Exception.Message)")) {
                throw "Installation cancelled by user after Python installation failed"
            }
        }

        Update-Progress "Creating directories..."
        try {
            New-Servermanager -dir $Settings.SteamCMDPath
            $ServerManagerDir = Join-Path $Settings.SteamCMDPath "Servermanager"
            New-Item -ItemType Directory -Force -Path $ServerManagerDir | Out-Null
            
            if (-not (Test-Path $Settings.UserWorkspacePath)) {
                New-Item -ItemType Directory -Force -Path $Settings.UserWorkspacePath | Out-Null
            }
        } catch {
            if (-not (Show-StepError "Directory Creation" "Failed to create installation directories: $($_.Exception.Message)")) {
                throw "Installation cancelled by user after directory creation failed"
            }
        }

        Update-Progress "Setting up logging..."
        try {
            $global:logFilePath = Join-Path $ServerManagerDir "Install-Log.txt"
        } catch {
            Write-Log "Warning: Failed to set up logging path: $($_.Exception.Message)"
        }

        Update-Progress "Creating registry entries..."
        try {
            $registryValues = @{
                'CurrentVersion' = $CurrentVersion
                'SteamCMDPath' = $Settings.SteamCMDPath
                'Servermanagerdir' = $ServerManagerDir
                'UserWorkspace' = $Settings.UserWorkspacePath
                'InstallDate' = (Get-Date).ToString('o')
                'LastUpdate' = (Get-Date).ToString('o')
                'WebPort' = '8080'
                'ModulePath' = "$ServerManagerDir\Modules"
                'LogPath' = "$ServerManagerDir\logs"
                'HostType' = $Settings.HostType
                'SQLType' = $Settings.SQLType
            }
            
            # Add database paths (always set these for SQLite compatibility) - using db directory
            $registryValues['UsersSQLDatabasePath'] = "$ServerManagerDir\db\servermanager_users.db"
            $registryValues['SteamSQLDatabasePath'] = "$ServerManagerDir\db\steam_ID.db"
            
            if ($Settings.SQLType -eq "SQLite" -or [string]::IsNullOrEmpty($Settings.SQLType)) {
                # SQLite is the default, database paths already set above
                $registryValues['SQLType'] = "SQLite"
            } else {
                # For other SQL types, also set database names
                $registryValues['UsersSQLDatabase'] = "servermanager_users"
                $registryValues['SteamSQLDatabase'] = "steam_apps"
                if ($Settings.SQLHost) { $registryValues['SQLHost'] = $Settings.SQLHost }
                if ($Settings.SQLPort) { $registryValues['SQLPort'] = $Settings.SQLPort }
                if ($Settings.SQLUsername) { $registryValues['SQLUsername'] = $Settings.SQLUsername }
                if ($Settings.SQLPassword) { $registryValues['SQLPassword'] = $Settings.SQLPassword }
            }
            
            # Add cluster configuration
            if ($Settings.HostType -eq "Subhost" -and $Settings.HostAddress) {
                $registryValues['HostAddress'] = $Settings.HostAddress
                # Store master IP for cluster nodes
                $registryValues['MasterHostIP'] = $Settings.HostAddress
                # Use the SubhostID generated during settings creation
                $registryValues['SubhostID'] = $Settings.SubhostID
                Write-Log "Master Host IP and SubhostID configured for cluster node: $($Settings.SubhostID)"
            } elseif ($Settings.HostType -eq "Host") {
                # Generate a new cluster secret for Master Host
                $ClusterSecret = -join ((1..32) | ForEach-Object {Get-Random -Input ([char[]]([char]'A'..[char]'Z' + [char]'a'..[char]'z' + [char]'0'..[char]'9'))})
                $registryValues['ClusterSecret'] = $ClusterSecret
                Write-Log "Generated new cluster secret for Master Host"
                
                # Also save to a secure file for reference
                $tokenFile = Join-Path $ServerManagerDir "cluster-security-token.txt"
                try {
                    $tokenContent = @"
Server Manager Cluster Security Token
Generated: $(Get-Date -Format 'o')
Master Host: $ServerManagerDir

SECURITY TOKEN:
$ClusterSecret

IMPORTANT NOTES:
- This token provides full access to your Server Manager cluster
- Store it securely and share only with trusted subhost administrators  
- This token cannot be recovered if lost - you'll need to generate a new one
- All existing subhosts will need to update their tokens if regenerated

Provide this token to subhost administrators during their installation process.
"@
                    Set-Content -Path $tokenFile -Value $tokenContent -Encoding UTF8
                    Write-Log "Cluster security token saved to: $tokenFile"
                } catch {
                    Write-Log "Warning: Could not save token to file: $($_.Exception.Message)"
                }
            }

            New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
            New-Item -Path $registryPath -Force | Out-Null
            foreach ($key in $registryValues.Keys) {
                Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
            }
            
            # Configure Windows Firewall rules
            Write-Log "Configuring Windows Firewall rules..."
            try {
                $clusterEnabled = ($Settings.HostType -eq "Host" -or ($Settings.HostType -eq "Subhost" -and $Settings.HostAddress))
                Add-ServerManagerFirewallRules -HostType $Settings.HostType -ClusterEnabled $clusterEnabled
            } catch {
                Write-Log "Warning: Firewall configuration failed: $($_.Exception.Message)"
                # Don't fail installation if firewall rules fail
            }
            
            # Migrate any existing databases to the new db directory
            Write-Log "Setting up database directory and migrating existing databases..."
            $migrationScript = Join-Path $ServerManagerDir "setup-db-directory.ps1"
            if (Test-Path $migrationScript) {
                try {
                    & $migrationScript -ServerManagerDir $ServerManagerDir
                } catch {
                    Write-Log "Warning: Database migration script encountered an issue: $($_.Exception.Message)"
                }
            }
        } catch {
            if (-not (Show-StepError "Registry Configuration" "Failed to create registry entries: $($_.Exception.Message)")) {
                throw "Installation cancelled by user after registry configuration failed"
            }
        }

        Update-Progress "Installing Git..."
        try {
            Install-Git
        } catch {
            if (-not (Show-StepError "Git Installation" "Failed to install Git: $($_.Exception.Message)`n`nThis may prevent downloading the latest Server Manager files.")) {
                throw "Installation cancelled by user after Git installation failed"
            }
        }

        Update-Progress "Downloading Server Manager files..."
        try {
            # Add a bit more detail to show progress
            $StatusLabel.Text = "Downloading Server Manager files (this may take a moment)..."
            $Form.Refresh()
            
            Initialize-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir -StatusLabel $StatusLabel -Form $Form
            
        } catch {
            $errorMsg = $_.Exception.Message
            if ($errorMsg -match "timeout|timed out") {
                $errorMsg = "Download operation timed out. This could be due to:`n• Slow internet connection`n• Repository server issues`n• Firewall blocking the connection`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "fatal: could not read Username" -or $errorMsg -match "Authentication failed" -or $errorMsg -match "repository not found") {
                $errorMsg = "Repository access denied. This may be because:`n• The repository is private and requires authentication`n• The repository URL is incorrect`n• Network connectivity issues`n`nAttempted fallback download from website but that also failed.`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "Both Git clone and website download failed") {
                $errorMsg = "Failed to download Server Manager files from both Git repository and website backup.`n`nThis could be due to:`n• Network connectivity issues`n• Repository access restrictions`n• Website availability problems`n• Firewall blocking connections`n`nOriginal error: $errorMsg"
            }
            if (-not (Show-StepError "Repository Download" $errorMsg)) {
                throw "Installation cancelled by user after repository download failed"
            }
        }

        Update-Progress "Installing Python requirements..."
        try {
            $requirementsPath = Join-Path $ServerManagerDir "requirements.txt"
            if (Test-Path $requirementsPath) {
                if (-not (Install-PythonRequirements -RequirementsPath $requirementsPath)) {
                    throw "Failed to install required Python packages"
                }
            } else {
                Write-Log "Warning: requirements.txt not found, skipping Python package installation"
            }
        } catch {
            if (-not (Show-StepError "Python Requirements" "Failed to install Python requirements: $($_.Exception.Message)`n`nSome Python modules may not be available.")) {
                throw "Installation cancelled by user after Python requirements installation failed"
            }
        }

        Update-Progress "Installing SteamCMD..."
        try {
            $steamCmdExe = Join-Path $Settings.SteamCMDPath "steamcmd.exe"
            if (-Not (Test-Path $steamCmdExe)) {
                $steamCmdZip = Join-Path $Settings.SteamCMDPath "steamcmd.zip"
                Write-Log "Downloading SteamCMD from $steamCmdUrl"
                Invoke-WebRequest -Uri $steamCmdUrl -OutFile $steamCmdZip -TimeoutSec 30
                Expand-Archive -Path $steamCmdZip -DestinationPath $Settings.SteamCMDPath -Force
            Remove-Item -Path $steamCmdZip -Force -Confirm:$false
            }
        } catch {
            if (-not (Show-StepError "SteamCMD Installation" "Failed to download or extract SteamCMD: $($_.Exception.Message)`n`nYou may need to install SteamCMD manually.")) {
                throw "Installation cancelled by user after SteamCMD installation failed"
            }
        }

        Update-Progress "Updating SteamCMD..."
        try {
            $steamCmdExe = Join-Path $Settings.SteamCMDPath "steamcmd.exe"
            if (Test-Path $steamCmdExe) {
                Update-SteamCmd -steamCmdPath $steamCmdExe
            }
        } catch {
            Write-Log "Warning: SteamCMD update failed: $($_.Exception.Message)"
        }

        Update-Progress "Setting up database..."
        try {
            $DataFolder = Join-Path $ServerManagerDir "data"
            if (-not (Test-Path $DataFolder)) {
                New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
            }
            # Initialize database and store path for potential future use
            $null = Initialize-SQLDatabase -SQLType $Settings.SQLType -SQLVersion $Settings.SQLVersion -SQLLocation $Settings.SQLLocation -DataFolder $DataFolder
        } catch {
            if (-not (Show-StepError "Database Setup" "Failed to initialize database: $($_.Exception.Message)`n`nUser authentication may not work properly.")) {
                throw "Installation cancelled by user after database setup failed"
            }
        }

        Update-Progress "Configuring cluster database..."
        try {
            # Initialize cluster configuration in database
            $clusterDbPath = "$ServerManagerDir\db\servermanager.db"
            if (Test-Path $clusterDbPath) {
                $initClusterScript = @"
import sys
sys.path.insert(0, r'$ServerManagerDir')
from Modules.Database.cluster_database import ClusterDatabase

try:
    cluster_db = ClusterDatabase(r'$clusterDbPath')
    
    # Set initial cluster configuration based on installation type
    host_type = '$($Settings.HostType)'
    master_ip = '$($Settings.HostAddress)' if '$($Settings.HostAddress)' else None
    cluster_name = 'ServerManager-Cluster'
    
    # Generate cluster secret for master hosts
    cluster_secret = None
    if host_type == 'Host':
        import secrets
        cluster_secret = secrets.token_urlsafe(32)
    
    success = cluster_db.set_cluster_config(host_type, cluster_name, cluster_secret, master_ip)
    if success:
        print(f'SUCCESS: Cluster database configured as {host_type}')
        if cluster_secret:
            print(f'CLUSTER_SECRET: {cluster_secret}')
    else:
        print('ERROR: Failed to configure cluster database')
        
except Exception as e:
    print(f'ERROR: {e}')
"@
                $tempClusterInitPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempClusterInitPy -Value $initClusterScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $clusterInitResult = python $tempClusterInitPy 2>&1
                Remove-Item $tempClusterInitPy -Force -Confirm:$false
                Write-Log "Cluster database initialization result: $clusterInitResult"
                
                # Extract cluster secret if generated
                if ($clusterInitResult -match "CLUSTER_SECRET: (.+)") {
                    $GeneratedClusterSecret = $matches[1]
                    $registryValues['ClusterSecret'] = $GeneratedClusterSecret
                    Write-Log "Cluster secret stored in database and registry"
                }
            }
        } catch {
            Write-Log "Warning: Failed to initialize cluster database configuration: $($_.Exception.Message)"
        }

        Update-Progress "Creating configuration files..."
        try {
            # Environment file creation removed - using registry-based configuration only
        } catch {
            if (-not (Show-StepError "Configuration Files" "Failed to create configuration files: $($_.Exception.Message)`n`nYou may need to configure the application manually.")) {
                throw "Installation cancelled by user after configuration file creation failed"
            }
        }

        Update-Progress "Setting up authentication..."
        try {
            Set-InitialAuthConfig -ServerManagerDir $ServerManagerDir
        } catch {
            Write-Log "Warning: Authentication setup failed: $($_.Exception.Message)"
        }

        if ($Settings.InstallService) {
            Update-Progress "Installing Windows Service..."
            try {
                Write-Log "Installing Server Manager as Windows Service..."
                
                # Path to the service wrapper script
                $serviceWrapperPath = Join-Path $ServerManagerDir "Modules\service_wrapper.py"
                
                # Check if service wrapper exists
                if (-not (Test-Path $serviceWrapperPath)) {
                    throw "Service wrapper script not found at: $serviceWrapperPath"
                }
                
                # Install pywin32 if not already installed
                Write-Log "Ensuring pywin32 is installed for service functionality..."
                & $PythonPath -m pip install pywin32 2>&1 | Out-Null
                
                # Install the service
                Write-Log "Installing Windows service..."
                $installResult = & $PythonPath $serviceWrapperPath install 2>&1
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "Service installed successfully"
                    
                    # Start the service
                    Write-Log "Starting Server Manager service..."
                    $startResult = & $PythonPath $serviceWrapperPath start 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Log "Service started successfully"
                        
                        # Set the service to automatically start with Windows
                        try {
                            Set-Service -Name "ServerManagerService" -StartupType Automatic
                            Write-Log "Service configured to start automatically with Windows"
                        } catch {
                            Write-Log "Warning: Could not set service startup type: $($_.Exception.Message)"
                        }
                    } else {
                        Write-Log "Warning: Service installed but failed to start: $startResult"
                    }
                } else {
                    throw "Service installation failed: $installResult"
                }
                
            } catch {
                Write-Log "Warning: Windows Service installation failed: $($_.Exception.Message)"
                Write-Log "Server Manager can still be started manually using Start-ServerManager.pyw"
            }
        }

        Update-Progress "Finalizing installation..."
        $ProgressBar.Value = 100
        
        Write-LogToFile -logFilePath $global:logFilePath
        
        # Call completion callback
        if ($OnComplete) {
            & $OnComplete
        }
    }
    catch {
        Write-Log "[ERROR] Installation failed: $($_.Exception.Message)"
        Write-LogToFile -logFilePath $global:logFilePath
        
        # Re-enable buttons for user to potentially retry or cancel
        $cancelButton.Enabled = $true
        $backButton.Enabled = $true
        
        [System.Windows.Forms.MessageBox]::Show(
            "Installation failed: $($_.Exception.Message)`n`nPlease check the installation log for more details. You can try going back and changing settings, or cancel the installation.",
            "Installation Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
        
        # Don't automatically close, let user decide
    }
}

# Cluster approval dialog for subhosts
function Show-ClusterApprovalDialog {
    param(
        [PSCustomObject]$Settings,
        [System.Windows.Forms.Form]$Form,
        [scriptblock]$OnApproved
    )
    
    # Create approval request form
    $approvalForm = New-Object System.Windows.Forms.Form
    $approvalForm.Text = "Cluster Join Request - Waiting for Approval"
    $approvalForm.Size = New-Object System.Drawing.Size(500, 300)
    $approvalForm.StartPosition = "CenterParent"
    $approvalForm.FormBorderStyle = "FixedDialog"
    $approvalForm.MaximizeBox = $false
    $approvalForm.MinimizeBox = $false
    $approvalForm.ShowIcon = $false
    $approvalForm.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 48)
    $approvalForm.ForeColor = [System.Drawing.Color]::White
    
    # Title label
    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = "Requesting to Join Cluster"
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $titleLabel.Location = New-Object System.Drawing.Point(20, 20)
    $titleLabel.Size = New-Object System.Drawing.Size(450, 25)
    $titleLabel.ForeColor = [System.Drawing.Color]::White
    $approvalForm.Controls.Add($titleLabel)
    
    # Status label
    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Text = "Sending join request to master host...`nPlease wait for approval from the administrator."
    $statusLabel.Location = New-Object System.Drawing.Point(20, 60)
    $statusLabel.Size = New-Object System.Drawing.Size(450, 60)
    $statusLabel.ForeColor = [System.Drawing.Color]::LightGray
    $statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $approvalForm.Controls.Add($statusLabel)
    
    # Progress indicator
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(20, 130)
    $progressBar.Size = New-Object System.Drawing.Size(450, 20)
    $progressBar.Style = "Marquee"
    $progressBar.MarqueeAnimationSpeed = 30
    $approvalForm.Controls.Add($progressBar)
    
    # Details label  
    $detailsLabel = New-Object System.Windows.Forms.Label
    $detailsLabel.Text = "Master Host: $($Settings.HostAddress)`nHost Name: $env:COMPUTERNAME`nSubhost ID: $($Settings.SubhostID)`n`nTimeout: 5 minutes maximum"
    $detailsLabel.Location = New-Object System.Drawing.Point(20, 160)
    $detailsLabel.Size = New-Object System.Drawing.Size(450, 80)
    $detailsLabel.ForeColor = [System.Drawing.Color]::LightGray
    $detailsLabel.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $approvalForm.Controls.Add($detailsLabel)
    
    # Cancel button
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel Installation"
    $cancelButton.Location = New-Object System.Drawing.Point(350, 250)
    $cancelButton.Size = New-Object System.Drawing.Size(120, 25)
    $cancelButton.BackColor = [System.Drawing.Color]::FromArgb(80, 80, 80)
    $cancelButton.ForeColor = [System.Drawing.Color]::White
    $cancelButton.FlatStyle = "Flat"
    $cancelButton.Add_Click({
        $approvalForm.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $approvalForm.Close()
    })
    $approvalForm.Controls.Add($cancelButton)
    
    # Show the approval form
    $approvalForm.Show()
    $approvalForm.BringToFront()
    
    # Start approval request process
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 5000 # Check every 5 seconds
    $approvalRequestId = $null
    $requestSent = $false
    $attemptCount = 0
    $maxAttempts = 60  # 5 minutes total (60 * 5 seconds)
    $lastErrorMessage = ""
    
    $timer.Add_Tick({
        try {
            $script:attemptCount++
            
            # Check for timeout
            if ($script:attemptCount -gt $script:maxAttempts) {
                $timer.Stop()
                $statusLabel.Text = "Timeout waiting for approval. Installation will continue without cluster membership."
                $progressBar.Style = "Continuous"
                $progressBar.Value = 0
                
                Write-Log "[WARNING] Cluster join request timed out after $($script:maxAttempts * 5) seconds"
                
                [System.Windows.Forms.MessageBox]::Show(
                    "The request to join the cluster has timed out.`n`nPossible causes:`n- Master host is offline`n- Network connectivity issues`n- Administrator has not approved the request`n`nThe installation will complete without cluster membership.",
                    "Cluster Join Timeout",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                
                $approvalForm.Hide()
                if ($OnApproved) {
                    & $OnApproved
                }
                $approvalForm.Close()
                return
            }
            
            if (-not $requestSent) {
                # First check if host is online and available
                try {
                    $statusLabel.Text = "Checking host availability..."
                    $hostStatus = Invoke-RestMethod -Uri "http://$($Settings.HostAddress):8080/api/cluster/status" -Method GET -TimeoutSec 10
                    
                    if ($hostStatus.host_status -eq "offline" -or $hostStatus.dashboard_active -eq $false) {
                        $statusLabel.Text = "Host is currently offline or dashboard is not active. Retrying..."
                        Write-Log "[WARNING] Host is offline or dashboard inactive. Status: $($hostStatus.host_status), Dashboard Active: $($hostStatus.dashboard_active)"
                        return  # Wait for next timer tick
                    }
                    
                    if ($hostStatus.maintenance_mode -eq $true) {
                        $statusLabel.Text = "Host is in maintenance mode. Waiting for maintenance to complete..."
                        Write-Log "[WARNING] Host is in maintenance mode. Waiting for completion."
                        return  # Wait for next timer tick
                    }
                    
                    Write-Log "[INFO] Host is online and available. Dashboard active: $($hostStatus.dashboard_active)"
                    $statusLabel.Text = "Host is online. Sending join request..."
                    
                } catch {
                    $statusLabel.Text = "Unable to connect to host. Retrying in 5 seconds...`nError: $($_.Exception.Message)"
                    Write-Log "[WARNING] Host status check failed: $($_.Exception.Message). Will retry."
                    return  # Wait for next timer tick
                }
                
                # Send the join request (host is confirmed online and available)
                $requestBody = @{
                    subhost_id = $Settings.SubhostID
                    info = @{
                        machine_name = $env:COMPUTERNAME
                        os = (Get-ComputerInfo).WindowsProductName
                        install_time = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                        ip_address = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" } | Select-Object -First 1).IPAddress
                    }
                } | ConvertTo-Json -Depth 3
                
                $response = Invoke-RestMethod -Uri "http://$($Settings.HostAddress):8080/api/cluster/request-join" -Method POST -Body $requestBody -ContentType "application/json" -TimeoutSec 15
                
                if ($response.request_id) {
                    $script:approvalRequestId = $response.request_id
                    $requestSent = $true
                    $statusLabel.Text = "Request sent! Waiting for administrator approval...`nRequest ID: $($response.request_id)"
                    Write-Log "[INFO] Cluster join request sent with ID: $($response.request_id)"
                } else {
                    throw "Invalid response from master host"
                }
            } else {
                # Check host status first before checking approval
                try {
                    $hostStatus = Invoke-RestMethod -Uri "http://$($Settings.HostAddress):8080/api/cluster/status" -Method GET -TimeoutSec 10
                    
                    if ($hostStatus.host_status -eq "offline" -or $hostStatus.dashboard_active -eq $false) {
                        $statusLabel.Text = "Host appears to be offline. Your request is still pending...`nRequest ID: $script:approvalRequestId`n`nWaiting for host to come back online..."
                        Write-Log "[WARNING] Host is offline during approval check. Status: $($hostStatus.host_status)"
                        return  # Wait for next timer tick
                    }
                } catch {
                    $statusLabel.Text = "Unable to contact host. Your request is still pending...`nRequest ID: $script:approvalRequestId`n`nWaiting for host connection..."
                    Write-Log "[WARNING] Cannot contact host during approval check: $($_.Exception.Message)"
                    return  # Wait for next timer tick
                }
                
                # Check if our request was approved by getting all pending requests
                try {
                    $pendingResponse = Invoke-RestMethod -Uri "http://$($Settings.HostAddress):8080/api/cluster/pending" -Method GET -TimeoutSec 10
                    
                    # Check if our request is still pending
                    $ourRequest = $null
                    foreach ($requestId in $pendingResponse.pending_requests.PSObject.Properties.Name) {
                        $request = $pendingResponse.pending_requests.$requestId
                        if ($request.id -eq $Settings.SubhostID -or $request.request_id -eq $script:approvalRequestId) {
                            $ourRequest = $request
                            break
                        }
                    }
                    
                    if ($ourRequest) {
                        # Request is still pending
                        $statusLabel.Text = "Still waiting for approval...`nRequest ID: $script:approvalRequestId`n`nRequest Status: $($ourRequest.status)"
                        Write-Log "[INFO] Request still pending approval. Status: $($ourRequest.status)"
                    } else {
                        # Request no longer in pending list - check if we got approved by checking cluster nodes
                        try {
                            $nodesResponse = Invoke-RestMethod -Uri "http://$($Settings.HostAddress):8080/api/cluster/nodes" -Method GET -TimeoutSec 10
                            
                            $approved = $false
                            foreach ($node in $nodesResponse) {
                                if ($node.subhost_id -eq $Settings.SubhostID -or $node.id -eq $Settings.SubhostID) {
                                    $approved = $true
                                    break
                                }
                            }
                            
                            if ($approved) {
                                $timer.Stop()
                                $statusLabel.Text = "Approved! Completing installation..."
                                $progressBar.Style = "Continuous"
                                $progressBar.Value = 100
                                
                                Write-Log "[INFO] Cluster join request approved - found in nodes list"
                                
                                # Close approval dialog and continue
                                $approvalForm.Hide()
                                if ($OnApproved) {
                                    & $OnApproved
                                }
                                $approvalForm.Close()
                            } else {
                                # Request was rejected
                                $timer.Stop()
                                $statusLabel.Text = "Request rejected by administrator"
                                $progressBar.Style = "Continuous"
                                $progressBar.Value = 0
                                
                                Write-Log "[WARNING] Cluster join request rejected - not found in nodes list"
                                
                                [System.Windows.Forms.MessageBox]::Show(
                                    "Your request to join the cluster was rejected by the administrator.`n`nThe installation is complete but this host will not be part of the cluster.",
                                    "Cluster Join Rejected",
                                    [System.Windows.Forms.MessageBoxButtons]::OK,
                                    [System.Windows.Forms.MessageBoxIcon]::Warning
                                )
                                
                                $approvalForm.Hide()
                                if ($OnApproved) {
                                    & $OnApproved
                                }
                                $approvalForm.Close()
                            }
                        } catch {
                            Write-Log "[ERROR] Error checking cluster nodes: $($_.Exception.Message)"
                            $statusLabel.Text = "Error checking approval status. Retrying..."
                        }
                    }
                } catch {
                    Write-Log "[ERROR] Error checking pending requests: $($_.Exception.Message)"
                    $statusLabel.Text = "Error checking approval status. Retrying..."
                }
            }
            # If pending, continue waiting
        }
        catch {
            $script:lastErrorMessage = $_.Exception.Message
            Write-Log "[ERROR] Cluster approval request failed (attempt $script:attemptCount/$script:maxAttempts): $($_.Exception.Message)"
            
            if ($script:attemptCount -lt 3) {
                $statusLabel.Text = "Connection error. Retrying... (attempt $script:attemptCount)"
            } else {
                $statusLabel.Text = "Connection issues. Still trying... (attempt $script:attemptCount)`nLast error: $($script:lastErrorMessage)"
            }
        }
    })
    
    $timer.Start()
    
    # Handle form closing
    $approvalForm.Add_FormClosing({
        param($formSender, $closeEventArgs)
        if ($timer) {
            $timer.Stop()
            $timer.Dispose()
        }
        if ($closeEventArgs.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing -and $approvalForm.DialogResult -eq [System.Windows.Forms.DialogResult]::Cancel) {
            # User cancelled - close main form too
            $Form.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
            $Form.Close()
        }
    })
}

function Test-Python310 {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $ver = & python -c "import sys; print(sys.version_info.major, sys.version_info.minor, sys.maxsize > 2**32)"
        $parts = $ver -split " "
        if ($parts.Length -eq 3) {
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            $is64 = $parts[2] -eq "True"
            if ($major -eq 3 -and $minor -ge 10 -and $is64) {
                return $true
            }
        }
    }
    return $false
}

function Install-Python310 {
    Write-Log "Python 3.10 (64-bit) not found. Downloading and installing Python 3.10 (64-bit)..."
    $pythonInstallerUrl = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri $pythonInstallerUrl -OutFile $installerPath
    Write-Log "Running Python installer..."
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    Remove-Item $installerPath -Force -Confirm:$false
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

function Install-PythonRequirements {
    param([string]$RequirementsPath)
    Write-Log "Installing Python requirements using pip..." -ForegroundColor Cyan
    if (-not (Test-Path $RequirementsPath)) {
        Write-Log "Python requirements.txt not found at: $RequirementsPath" -ForegroundColor Yellow
        return $false
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Log "Python not found in PATH after install. Please restart your shell and try again." -ForegroundColor Red
        return $false
    }
    Write-Log "Upgrading pip..."
    & python -m pip install --upgrade pip | Out-Null
    Write-Log "Installing requirements from $RequirementsPath..."
    & python -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to install Python requirements." -ForegroundColor Red
        return $false
    }
    Write-Log "Python requirements installed successfully." -ForegroundColor Green
    return $true
}

function New-Salt {
    param([int]$Length = 32)
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes)
    return ([BitConverter]::ToString($bytes) -replace '-', '').Substring(0, $Length)
}

function Protect-ConfigFile {
    param([Parameter(Mandatory=$true)][string]$FilePath)
    if (-not (Test-Path $FilePath)) {
        Write-Log "File not found: $FilePath" -ForegroundColor Yellow
        return $false
    }
    try {
        $acl = Get-Acl $FilePath
        $acl.SetAccessRuleProtection($true, $false)

        foreach ($rule in $acl.Access) {
            $acl.RemoveAccessRule($rule)
        }

        $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "FullControl", "Allow"
        )
        $acl.AddAccessRule($systemRule)

        $adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "Administrators", "FullControl", "Allow"
        )
        $acl.AddAccessRule($adminRule)

        Set-Acl -Path $FilePath -AclObject $acl
        Write-Log "Protected config file: $FilePath" -ForegroundColor Green
        return $true
    } catch {
        Write-Log "Failed to protect config file: $FilePath - $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Set-InitialAuthConfig {
    param([string]$ServerManagerDir)
    
    Write-Log "Starting authentication configuration setup"
    
    try {
        # Check if user database exists - using db directory
        $dbFolder = Join-Path $ServerManagerDir "db"
        $dbFile = Join-Path $dbFolder "servermanager_users.db"
        
        if (Test-Path $dbFile) {
            # Show GUI for admin user setup
            Write-Log "Setting up administrator user via GUI"
            
            $adminForm = New-Object System.Windows.Forms.Form
            $adminForm.Text = "Administrator Account Setup"
            $adminForm.Size = New-Object System.Drawing.Size(450, 350)
            $adminForm.StartPosition = "CenterScreen"
            $adminForm.FormBorderStyle = "FixedDialog"
            $adminForm.MaximizeBox = $false
            $adminForm.MinimizeBox = $false
            
            # Title
            $titleLabel = New-Object System.Windows.Forms.Label
            $titleLabel.Text = "Create Administrator Account"
            $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
            $titleLabel.Location = New-Object System.Drawing.Point(20, 20)
            $titleLabel.Size = New-Object System.Drawing.Size(400, 30)
            $adminForm.Controls.Add($titleLabel)
            
            # Description
            $descLabel = New-Object System.Windows.Forms.Label
            $descLabel.Text = "Please create an administrator account for Server Manager:"
            $descLabel.Location = New-Object System.Drawing.Point(20, 60)
            $descLabel.Size = New-Object System.Drawing.Size(400, 20)
            $adminForm.Controls.Add($descLabel)
            
            # Username field
            $usernameLabel = New-Object System.Windows.Forms.Label
            $usernameLabel.Text = "Username:"
            $usernameLabel.Location = New-Object System.Drawing.Point(20, 100)
            $usernameLabel.Size = New-Object System.Drawing.Size(100, 20)
            $adminForm.Controls.Add($usernameLabel)
            
            $usernameBox = New-Object System.Windows.Forms.TextBox
            $usernameBox.Text = "admin"
            $usernameBox.Location = New-Object System.Drawing.Point(130, 98)
            $usernameBox.Size = New-Object System.Drawing.Size(280, 22)
            $adminForm.Controls.Add($usernameBox)
            
            # Password field
            $passwordLabel = New-Object System.Windows.Forms.Label
            $passwordLabel.Text = "Password:"
            $passwordLabel.Location = New-Object System.Drawing.Point(20, 140)
            $passwordLabel.Size = New-Object System.Drawing.Size(100, 20)
            $adminForm.Controls.Add($passwordLabel)
            
            $passwordBox = New-Object System.Windows.Forms.TextBox
            $passwordBox.UseSystemPasswordChar = $true
            $passwordBox.Location = New-Object System.Drawing.Point(130, 138)
            $passwordBox.Size = New-Object System.Drawing.Size(280, 22)
            $adminForm.Controls.Add($passwordBox)
            
            # Confirm Password field
            $confirmLabel = New-Object System.Windows.Forms.Label
            $confirmLabel.Text = "Confirm Password:"
            $confirmLabel.Location = New-Object System.Drawing.Point(20, 180)
            $confirmLabel.Size = New-Object System.Drawing.Size(100, 20)
            $adminForm.Controls.Add($confirmLabel)
            
            $confirmBox = New-Object System.Windows.Forms.TextBox
            $confirmBox.UseSystemPasswordChar = $true
            $confirmBox.Location = New-Object System.Drawing.Point(130, 178)
            $confirmBox.Size = New-Object System.Drawing.Size(280, 22)
            $adminForm.Controls.Add($confirmBox)
            
            # Email field (optional)
            $emailLabel = New-Object System.Windows.Forms.Label
            $emailLabel.Text = "Email (optional):"
            $emailLabel.Location = New-Object System.Drawing.Point(20, 220)
            $emailLabel.Size = New-Object System.Drawing.Size(100, 20)
            $adminForm.Controls.Add($emailLabel)
            
            $emailBox = New-Object System.Windows.Forms.TextBox
            $emailBox.Text = "admin@localhost"
            $emailBox.Location = New-Object System.Drawing.Point(130, 218)
            $emailBox.Size = New-Object System.Drawing.Size(280, 22)
            $adminForm.Controls.Add($emailBox)
            
            # Buttons
            $okButton = New-Object System.Windows.Forms.Button
            $okButton.Text = "Create Account"
            $okButton.Location = New-Object System.Drawing.Point(230, 270)
            $okButton.Size = New-Object System.Drawing.Size(120, 35)
            $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $adminForm.Controls.Add($okButton)
            
            $cancelButton = New-Object System.Windows.Forms.Button
            $cancelButton.Text = "Skip"
            $cancelButton.Location = New-Object System.Drawing.Point(360, 270)
            $cancelButton.Size = New-Object System.Drawing.Size(80, 35)
            $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
            $adminForm.Controls.Add($cancelButton)
            
            # Form validation using FormClosing event
            $adminForm.Add_FormClosing({
                param($formSender, $closeEventArgs)
                
                # Only validate if OK was clicked (DialogResult is OK)
                if ($adminForm.DialogResult -eq [System.Windows.Forms.DialogResult]::OK) {
                    $isValid = $true
                    
                    if ([string]::IsNullOrWhiteSpace($usernameBox.Text)) {
                        [System.Windows.Forms.MessageBox]::Show("Username is required.", "Validation Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
                        $usernameBox.Focus()
                        $isValid = $false
                    }
                    elseif ([string]::IsNullOrWhiteSpace($passwordBox.Text)) {
                        [System.Windows.Forms.MessageBox]::Show("Password is required.", "Validation Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
                        $passwordBox.Focus()
                        $isValid = $false
                    }
                    elseif ($passwordBox.Text -ne $confirmBox.Text) {
                        [System.Windows.Forms.MessageBox]::Show("Passwords do not match.", "Validation Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
                        # Clear password fields to force re-entry
                        $passwordBox.Text = ""
                        $confirmBox.Text = ""
                        $passwordBox.Focus()
                        $isValid = $false
                    }
                    
                    # If validation failed, cancel the form closing
                    if (-not $isValid) {
                        $closeEventArgs.Cancel = $true
                    }
                }
            })
            
            $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $adminForm.CancelButton = $cancelButton
            
            # Show the form
            $result = $adminForm.ShowDialog()
            
            if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
                # Create the admin user
                $username = $usernameBox.Text.Trim()
                $password = $passwordBox.Text
                $email = $emailBox.Text.Trim()
                
                $createAdminScript = @"
import sqlite3
import hashlib
import uuid
from datetime import datetime

username = '$username'
password = '$password'
email = '$email'
dbfile = r'$dbFile'

try:
    conn = sqlite3.connect(dbfile)
    cursor = conn.cursor()
    
    # Check if user already exists
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        print(f'ERROR: User {username} already exists')
    else:
        # Create admin user
        admin_password = hashlib.sha256(password.encode()).hexdigest()
        account_number = str(uuid.uuid4())[:8].upper()
        created_at = datetime.utcnow().isoformat()
        
        cursor.execute('''
            INSERT INTO users (username, password, email, first_name, last_name, display_name, account_number, is_admin, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (username, admin_password, email, 'System', 'Administrator', username.title(), account_number, 1, 1, created_at))
        
        conn.commit()
        print(f'SUCCESS: Administrator user {username} created')
        
    conn.close()
except Exception as e:
    print(f'ERROR: {e}')
"@
                
                $tempAdminPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempAdminPy -Value $createAdminScript
                
                try {
                    $env:PYTHONDONTWRITEBYTECODE = "1"
                    $adminResult = python $tempAdminPy 2>&1
                    Write-Log "Admin user creation result: $adminResult"
                    
                    if ($adminResult -match "SUCCESS") {
                        Write-Log "Administrator user created successfully"
                    } else {
                        Write-Log "Warning: Admin user creation may have failed: $adminResult"
                    }
                } finally {
                    Remove-Item $tempAdminPy -Force -Confirm:$false -ErrorAction SilentlyContinue
                }
            } else {
                Write-Log "Admin user setup skipped by user"
                # Create a default admin user
                $defaultAdminScript = @"
import sqlite3
import hashlib
import uuid
from datetime import datetime

try:
    conn = sqlite3.connect(r'$dbFile')
    cursor = conn.cursor()
    
    # Check if any admin user exists
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_admin = 1')
    admin_count = cursor.fetchone()[0]
    
    if admin_count == 0:
        # Create default admin user
        admin_password = hashlib.sha256('admin'.encode()).hexdigest()
        account_number = str(uuid.uuid4())[:8].upper()
        created_at = datetime.utcnow().isoformat()
        
        cursor.execute('''
            INSERT INTO users (username, password, email, first_name, last_name, display_name, account_number, is_admin, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('admin', admin_password, 'admin@localhost', 'System', 'Administrator', 'Admin', account_number, 1, 1, created_at))
        
        conn.commit()
        print('SUCCESS: Default admin user created (username: admin, password: admin)')
    
    conn.close()
except Exception as e:
    print(f'ERROR: {e}')
"@
                
                $tempDefaultPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempDefaultPy -Value $defaultAdminScript
                
                try {
                    $env:PYTHONDONTWRITEBYTECODE = "1"
                    $defaultResult = python $tempDefaultPy 2>&1
                    Write-Log "Default admin creation result: $defaultResult"
                } finally {
                    Remove-Item $tempDefaultPy -Force -Confirm:$false -ErrorAction SilentlyContinue
                }
            }
            
            $adminForm.Dispose()
        } else {
            Write-Log "Database file not found, authentication setup will be handled by application startup"
        }
        
        return $true
    }
    catch {
        Write-Log "Error during authentication setup: $($_.Exception.Message)"
        return $false
    }
    finally {
        Write-Log "Authentication configuration setup completed"
    }
}

# MAIN SCRIPT FLOW
try {
    # Check admin privileges first, before showing any UI
    Test-AdminPrivileges

    # Check for existing installation and prompt for reinstall
    if (Test-ExistingInstallation -RegPath $registryPath) {
        if (-not (Prompt-Reinstall)) {
            Write-Log "Installation cancelled by user." -ForegroundColor Yellow
            exit 0
        }
        else {
            Write-Log "Proceeding with reinstall. Existing settings will be overwritten." -ForegroundColor Yellow
        }
    }

    # Show the unified installer wizard
    $result = Show-InstallerWizard
    
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Log "Installation cancelled by user." -ForegroundColor Yellow
        exit 0
    }
}
catch {
    Write-Log "[ERROR] Installation failed: $($_.Exception.Message)"
    if (Test-Path (Split-Path $global:logFilePath -Parent)) {
        Write-LogToFile -logFilePath $global:logFilePath
    }
    [System.Windows.Forms.MessageBox]::Show(
        "Installation failed: $($_.Exception.Message)",
        "Installation Error",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

exit 0