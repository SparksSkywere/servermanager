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

# Define global variables
$global:logMemory = @()
$global:logFilePath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Install-Log.txt"
$CurrentVersion = "1.4.1"
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

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
    
    # Force all cmdlets to default to non-interactive behaviour
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
            # Detect SSL setting from registry
            $sslFlag = $false
            try { $sslFlag = (Get-ItemProperty -Path "HKLM:\Software\SkywereIndustries\Servermanager" -Name "SSLEnabled" -ErrorAction SilentlyContinue).SSLEnabled -eq "True" } catch {}
            $webUrl = if ($sslFlag) { "https://localhost:443" } else { "http://localhost:8080" }
            [System.Windows.Forms.MessageBox]::Show("If installation was successful:`n- The service is now installed and running`n- Server Manager will start automatically with Windows`n- You can access the web interface at $webUrl", "Service Installation Complete", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
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
        [bool]$ClusterEnabled = $false,
        [bool]$SSLEnabled = $false
    )
    
    Write-Log "Configuring Windows Firewall rules for Server Manager..."
    
    try {
        # Remove any existing rules first (cleanup from previous installations)
        Remove-ServerManagerFirewallRules -Quiet
        
        $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
        
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
        
        if ($pythonPath) {
            $webRuleInbound.Program = $pythonPath
            $webRuleOutbound.Program = $pythonPath
        }
        
        New-NetFirewallRule @webRuleInbound -ErrorAction Stop | Out-Null
        New-NetFirewallRule @webRuleOutbound -ErrorAction Stop | Out-Null
        Write-Log "Added firewall rules for web interface (port 8080) - inbound and outbound"
        
        # Rule 2: HTTPS port (443) - Inbound and Outbound
        if ($SSLEnabled) {
            $httpsRuleInbound = @{
                DisplayName = "ServerManager_HTTPS_In"
                Direction = "Inbound"
                Protocol = "TCP"
                LocalPort = "443"
                Action = "Allow"
                Description = "Allow inbound HTTPS access to Server Manager on port 443"
            }
            $httpsRuleOutbound = @{
                DisplayName = "ServerManager_HTTPS_Out"
                Direction = "Outbound"
                Protocol = "TCP"
                LocalPort = "443"
                Action = "Allow"
                Description = "Allow outbound HTTPS access from Server Manager on port 443"
            }
            if ($pythonPath) {
                $httpsRuleInbound.Program = $pythonPath
                $httpsRuleOutbound.Program = $pythonPath
            }
            New-NetFirewallRule @httpsRuleInbound -ErrorAction Stop | Out-Null
            New-NetFirewallRule @httpsRuleOutbound -ErrorAction Stop | Out-Null
            Write-Log "Added firewall rules for HTTPS (port 443) - inbound and outbound"
            
            # Rule 2b: HTTP redirect port (8081) when SSL enabled
            $redirectRuleInbound = @{
                DisplayName = "ServerManager_HTTPRedirect_In"
                Direction = "Inbound"
                Protocol = "TCP"
                LocalPort = "8081"
                Action = "Allow"
                Description = "Allow inbound HTTP-to-HTTPS redirect on port 8081"
            }
            if ($pythonPath) { $redirectRuleInbound.Program = $pythonPath }
            New-NetFirewallRule @redirectRuleInbound -ErrorAction Stop | Out-Null
            Write-Log "Added firewall rule for HTTP redirect (port 8081) - inbound"
        }
        
        # Rule 3: Cluster API (port 5001) - for cluster-enabled hosts
        if ($HostType -eq "Host" -or $ClusterEnabled) {
            $clusterRuleInbound = @{
                DisplayName = "ServerManager_ClusterAPI_In"
                Direction = "Inbound" 
                Protocol = "TCP"
                LocalPort = "5001"
                Action = "Allow"
                Description = "Allow inbound access to Server Manager cluster API on port 5001"
            }
            
            $clusterRuleOutbound = @{
                DisplayName = "ServerManager_ClusterAPI_Out"
                Direction = "Outbound"
                Protocol = "TCP" 
                LocalPort = "5001"
                Action = "Allow"
                Description = "Allow outbound access from Server Manager cluster API on port 5001"
            }
            
            if ($pythonPath) {
                $clusterRuleInbound.Program = $pythonPath
                $clusterRuleOutbound.Program = $pythonPath
            }
            
            New-NetFirewallRule @clusterRuleInbound -ErrorAction Stop | Out-Null
            New-NetFirewallRule @clusterRuleOutbound -ErrorAction Stop | Out-Null
            Write-Log "Added firewall rules for cluster API (port 5001) - inbound and outbound"
        }
        
        # Rule 4: Game server ports range (7777-7800) - TCP Inbound and Outbound
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
        if ($SSLEnabled) {
            Write-Log "  - Port 443 (TCP) for HTTPS (inbound and outbound)"
            Write-Log "  - Port 8081 (TCP) for HTTP redirect (inbound)"
        }
        if ($HostType -eq "Host" -or $ClusterEnabled) {
            Write-Log "  - Port 5001 (TCP) for cluster API (inbound and outbound)"
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
            "ServerManager_HTTPS_In",
            "ServerManager_HTTPS_Out",
            "ServerManager_HTTPRedirect_In",
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

# Add this function after global variable definitions
function Request-ReinstallConfirmation {
    $result = [System.Windows.Forms.MessageBox]::Show(
        "An existing Server Manager installation was detected. Do you want to reinstall (this will overwrite previous settings)?",
        "Reinstall Server Manager",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

# Add this function after global variable definitions
function Test-ExistingInstallation {
    param([string]$RegPath)
    return Test-Path $RegPath
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
        # Validate DataFolder parameter
        if ([string]::IsNullOrWhiteSpace($DataFolder)) {
            throw "DataFolder parameter is required but was not provided"
        }
        
        # Use the DataFolder directly as the db folder
        $dbFolder = $DataFolder
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

# Insert default host status
c.execute('INSERT OR IGNORE INTO host_status (id, status, dashboard_active) VALUES (1, "online", 1)')

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

            # Refresh PATH environment variable safely
            $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            $newPath = @($machinePath, $userPath) | Where-Object { $_ } | ForEach-Object { $_.TrimEnd(';') }
            $env:Path = ($newPath -join ';')
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
        if (Remove-DirectoryForce -Path $destination) {
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
                    # Use Substring to extract path after "ALTERNATIVE_PATH:" prefix (handles Windows paths with drive letter colons)
                    $actualDestination = $_.Exception.Message.Substring(17)
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
                Remove-DirectoryForce -Path $actualDestination
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
            Get-FromWebsite -destination $destination -StatusLabel $StatusLabel -Form $Form
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

# Classic Windows XP-style installer colours
$script:ThemeColors = @{
    # Classic Windows colours
    FormBackground = [System.Drawing.Color]::FromArgb(236, 233, 216)   # Classic dialog background
    HeaderBlue = [System.Drawing.Color]::FromArgb(0, 78, 152)          # Classic blue header
    HeaderLight = [System.Drawing.Color]::FromArgb(90, 135, 190)       # Lighter blue gradient
    PanelBackground = [System.Drawing.Color]::FromArgb(255, 255, 255)  # White content area
    ButtonFace = [System.Drawing.Color]::FromArgb(236, 233, 216)       # Standard button
    TextBlack = [System.Drawing.Color]::Black                          # Primary text
    TextGray = [System.Drawing.Color]::FromArgb(100, 100, 100)         # Secondary text
    LinkBlue = [System.Drawing.Color]::FromArgb(0, 102, 204)           # Link colour
    BorderGray = [System.Drawing.Color]::FromArgb(172, 168, 153)       # Border colour
    Success = [System.Drawing.Color]::FromArgb(0, 128, 0)              # Green for success
    Warning = [System.Drawing.Color]::FromArgb(255, 140, 0)            # Orange for warning
    Danger = [System.Drawing.Color]::FromArgb(178, 34, 34)             # Red for errors
}

# Unified installer form - Classic Windows XP Style
function Show-InstallerWizard {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Server Manager Setup"
    $form.Size = New-Object System.Drawing.Size(500, 400)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $true
    $form.BackColor = $script:ThemeColors.FormBackground
    $form.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $form.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon("$env:SystemRoot\System32\msiexec.exe")

    # Left side banner panel (classic wizard style)
    $bannerPanel = New-Object System.Windows.Forms.Panel
    $bannerPanel.Location = New-Object System.Drawing.Point(0, 0)
    $bannerPanel.Size = New-Object System.Drawing.Size(165, 315)
    $bannerPanel.BackColor = $script:ThemeColors.HeaderBlue
    $form.Controls.Add($bannerPanel)

    # Banner title
    $bannerTitle = New-Object System.Windows.Forms.Label
    $bannerTitle.Text = "Server`nManager`nSetup"
    $bannerTitle.Font = New-Object System.Drawing.Font("Tahoma", 14, [System.Drawing.FontStyle]::Bold)
    $bannerTitle.Location = New-Object System.Drawing.Point(15, 20)
    $bannerTitle.Size = New-Object System.Drawing.Size(135, 80)
    $bannerTitle.ForeColor = [System.Drawing.Color]::White
    $bannerPanel.Controls.Add($bannerTitle)

    # Version label
    $versionLabel = New-Object System.Windows.Forms.Label
    $versionLabel.Text = "Version $CurrentVersion"
    $versionLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $versionLabel.Location = New-Object System.Drawing.Point(15, 280)
    $versionLabel.Size = New-Object System.Drawing.Size(135, 20)
    $versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(180, 200, 220)
    $bannerPanel.Controls.Add($versionLabel)

    # Main content panel (white area)
    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(165, 0)
    $contentPanel.Size = New-Object System.Drawing.Size(325, 315)
    $contentPanel.BackColor = $script:ThemeColors.PanelBackground
    $form.Controls.Add($contentPanel)

    # Bottom button panel (gray area with buttons)
    $bottomPanel = New-Object System.Windows.Forms.Panel
    $bottomPanel.Location = New-Object System.Drawing.Point(0, 315)
    $bottomPanel.Size = New-Object System.Drawing.Size(500, 55)
    $bottomPanel.BackColor = $script:ThemeColors.FormBackground
    $form.Controls.Add($bottomPanel)

    # Horizontal separator line
    $separator = New-Object System.Windows.Forms.Label
    $separator.BackColor = $script:ThemeColors.BorderGray
    $separator.Location = New-Object System.Drawing.Point(0, 0)
    $separator.Size = New-Object System.Drawing.Size(500, 2)
    $bottomPanel.Controls.Add($separator)

    # Navigation buttons - Classic Windows style
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.Location = New-Object System.Drawing.Point(395, 15)
    $cancelButton.Size = New-Object System.Drawing.Size(75, 25)
    $cancelButton.UseVisualStyleBackColor = $true
    $bottomPanel.Controls.Add($cancelButton)

    $nextButton = New-Object System.Windows.Forms.Button
    $nextButton.Text = "Next >"
    $nextButton.Location = New-Object System.Drawing.Point(310, 15)
    $nextButton.Size = New-Object System.Drawing.Size(75, 25)
    $nextButton.UseVisualStyleBackColor = $true
    $bottomPanel.Controls.Add($nextButton)

    $backButton = New-Object System.Windows.Forms.Button
    $backButton.Text = "< Back"
    $backButton.Location = New-Object System.Drawing.Point(230, 15)
    $backButton.Size = New-Object System.Drawing.Size(75, 25)
    $backButton.Enabled = $false
    $backButton.UseVisualStyleBackColor = $true
    $bottomPanel.Controls.Add($backButton)

    # Create wizard pages
    $pages = @()
    $currentPageIndex = 0

    # Page 1: Welcome
    $welcomePage = New-Object System.Windows.Forms.Panel
    $welcomePage.Location = New-Object System.Drawing.Point(10, 10)
    $welcomePage.Size = New-Object System.Drawing.Size(305, 295)
    $welcomePage.Visible = $true
    $welcomePage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($welcomePage)

    $welcomeTitle = New-Object System.Windows.Forms.Label
    $welcomeTitle.Text = "Welcome to the Server Manager Setup Wizard"
    $welcomeTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $welcomeTitle.Location = New-Object System.Drawing.Point(0, 5)
    $welcomeTitle.Size = New-Object System.Drawing.Size(300, 40)
    $welcomeTitle.ForeColor = $script:ThemeColors.TextBlack
    $welcomePage.Controls.Add($welcomeTitle)

    $welcomeText = New-Object System.Windows.Forms.Label
    $welcomeText.Text = @"
This wizard will install Server Manager on your computer.

Server Manager provides an easy-to-use web interface for managing game servers, user accounts, and automated deployment.

Click Next to continue, or Cancel to exit Setup.
"@
    $welcomeText.Location = New-Object System.Drawing.Point(0, 55)
    $welcomeText.Size = New-Object System.Drawing.Size(295, 200)
    $welcomeText.ForeColor = $script:ThemeColors.TextBlack
    $welcomeText.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $welcomePage.Controls.Add($welcomeText)

    $pages += $welcomePage

    # Page 2: Installation Options
    $optionsPage = New-Object System.Windows.Forms.Panel
    $optionsPage.Location = New-Object System.Drawing.Point(10, 10)
    $optionsPage.Size = New-Object System.Drawing.Size(305, 295)
    $optionsPage.Visible = $false
    $optionsPage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($optionsPage)

    $optionsTitle = New-Object System.Windows.Forms.Label
    $optionsTitle.Text = "Installation Options"
    $optionsTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $optionsTitle.Location = New-Object System.Drawing.Point(0, 5)
    $optionsTitle.Size = New-Object System.Drawing.Size(295, 25)
    $optionsTitle.ForeColor = $script:ThemeColors.TextBlack
    $optionsPage.Controls.Add($optionsTitle)

    # SteamCMD Path
    $steamCmdLabel = New-Object System.Windows.Forms.Label
    $steamCmdLabel.Text = "SteamCMD Directory:"
    $steamCmdLabel.Location = New-Object System.Drawing.Point(0, 35)
    $steamCmdLabel.Size = New-Object System.Drawing.Size(150, 16)
    $steamCmdLabel.ForeColor = $script:ThemeColors.TextBlack
    $steamCmdLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($steamCmdLabel)

    $steamCmdBox = New-Object System.Windows.Forms.TextBox
    $steamCmdBox.Location = New-Object System.Drawing.Point(0, 52)
    $steamCmdBox.Size = New-Object System.Drawing.Size(220, 20)
    $steamCmdBox.Text = "C:\SteamCMD"
    $steamCmdBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($steamCmdBox)

    $steamCmdBrowse = New-Object System.Windows.Forms.Button
    $steamCmdBrowse.Text = "Browse..."
    $steamCmdBrowse.Location = New-Object System.Drawing.Point(225, 51)
    $steamCmdBrowse.Size = New-Object System.Drawing.Size(70, 22)
    $steamCmdBrowse.UseVisualStyleBackColor = $true
    $steamCmdBrowse.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($steamCmdBrowse)

    # User Workspace Path
    $workspaceLabel = New-Object System.Windows.Forms.Label
    $workspaceLabel.Text = "Workspace Directory:"
    $workspaceLabel.Location = New-Object System.Drawing.Point(0, 78)
    $workspaceLabel.Size = New-Object System.Drawing.Size(150, 16)
    $workspaceLabel.ForeColor = $script:ThemeColors.TextBlack
    $workspaceLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($workspaceLabel)

    $workspaceBox = New-Object System.Windows.Forms.TextBox
    $workspaceBox.Location = New-Object System.Drawing.Point(0, 95)
    $workspaceBox.Size = New-Object System.Drawing.Size(220, 20)
    $workspaceBox.Text = Join-Path $steamCmdBox.Text "user_workspace"
    $workspaceBox.ReadOnly = $true
    $workspaceBox.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
    $workspaceBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($workspaceBox)

    $workspaceBrowse = New-Object System.Windows.Forms.Button
    $workspaceBrowse.Text = "Browse..."
    $workspaceBrowse.Location = New-Object System.Drawing.Point(225, 94)
    $workspaceBrowse.Size = New-Object System.Drawing.Size(70, 22)
    $workspaceBrowse.Enabled = $false
    $workspaceBrowse.UseVisualStyleBackColor = $true
    $workspaceBrowse.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($workspaceBrowse)

    # Custom workspace checkbox
    $customWorkspaceCheckbox = New-Object System.Windows.Forms.CheckBox
    $customWorkspaceCheckbox.Text = "Use custom workspace directory"
    $customWorkspaceCheckbox.Location = New-Object System.Drawing.Point(0, 120)
    $customWorkspaceCheckbox.Size = New-Object System.Drawing.Size(200, 18)
    $customWorkspaceCheckbox.ForeColor = $script:ThemeColors.TextBlack
    $customWorkspaceCheckbox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($customWorkspaceCheckbox)

    # Service installation
    $serviceCheckbox = New-Object System.Windows.Forms.CheckBox
    $serviceCheckbox.Text = "Install as Windows Service"
    $serviceCheckbox.Location = New-Object System.Drawing.Point(0, 142)
    $serviceCheckbox.Size = New-Object System.Drawing.Size(200, 18)
    $serviceCheckbox.ForeColor = $script:ThemeColors.TextBlack
    $serviceCheckbox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($serviceCheckbox)

    # Host type group - Cluster configuration
    $hostGroupBox = New-Object System.Windows.Forms.GroupBox
    $hostGroupBox.Text = "Cluster Configuration"
    $hostGroupBox.Location = New-Object System.Drawing.Point(0, 168)
    $hostGroupBox.Size = New-Object System.Drawing.Size(295, 100)
    $hostGroupBox.ForeColor = $script:ThemeColors.TextBlack
    $hostGroupBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $optionsPage.Controls.Add($hostGroupBox)

    $hostRadio = New-Object System.Windows.Forms.RadioButton
    $hostRadio.Text = "Master Host"
    $hostRadio.Location = New-Object System.Drawing.Point(10, 18)
    $hostRadio.Size = New-Object System.Drawing.Size(120, 18)
    $hostRadio.Checked = $true
    $hostRadio.ForeColor = $script:ThemeColors.TextBlack
    $hostRadio.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $hostGroupBox.Controls.Add($hostRadio)

    $subhostRadio = New-Object System.Windows.Forms.RadioButton
    $subhostRadio.Text = "Cluster Node"
    $subhostRadio.Location = New-Object System.Drawing.Point(10, 40)
    $subhostRadio.Size = New-Object System.Drawing.Size(120, 18)
    $subhostRadio.ForeColor = $script:ThemeColors.TextBlack
    $subhostRadio.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $hostGroupBox.Controls.Add($subhostRadio)

    # Master Host IP for cluster nodes
    $hostAddrLabel = New-Object System.Windows.Forms.Label
    $hostAddrLabel.Text = "Host IP:"
    $hostAddrLabel.Location = New-Object System.Drawing.Point(10, 65)
    $hostAddrLabel.Size = New-Object System.Drawing.Size(50, 16)
    $hostAddrLabel.Visible = $false
    $hostAddrLabel.ForeColor = $script:ThemeColors.TextBlack
    $hostAddrLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $hostGroupBox.Controls.Add($hostAddrLabel)

    $hostAddrBox = New-Object System.Windows.Forms.TextBox
    $hostAddrBox.Location = New-Object System.Drawing.Point(65, 62)
    $hostAddrBox.Size = New-Object System.Drawing.Size(150, 20)
    $hostAddrBox.Visible = $false
    $hostAddrBox.Text = ""
    $hostAddrBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $hostGroupBox.Controls.Add($hostAddrBox)

    $pages += $optionsPage

    # Page 3: Database Configuration
    $dbPage = New-Object System.Windows.Forms.Panel
    $dbPage.Location = New-Object System.Drawing.Point(10, 10)
    $dbPage.Size = New-Object System.Drawing.Size(305, 295)
    $dbPage.Visible = $false
    $dbPage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($dbPage)

    $dbTitle = New-Object System.Windows.Forms.Label
    $dbTitle.Text = "Database Configuration"
    $dbTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $dbTitle.Location = New-Object System.Drawing.Point(0, 5)
    $dbTitle.Size = New-Object System.Drawing.Size(295, 25)
    $dbTitle.ForeColor = $script:ThemeColors.TextBlack
    $dbPage.Controls.Add($dbTitle)

    $dbDesc = New-Object System.Windows.Forms.Label
    $dbDesc.Text = "Select the database type for storing user accounts and configurations."
    $dbDesc.Location = New-Object System.Drawing.Point(0, 35)
    $dbDesc.Size = New-Object System.Drawing.Size(295, 30)
    $dbDesc.ForeColor = $script:ThemeColors.TextBlack
    $dbDesc.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $dbPage.Controls.Add($dbDesc)

    $sqlTypeLabel = New-Object System.Windows.Forms.Label
    $sqlTypeLabel.Text = "Database Type:"
    $sqlTypeLabel.Location = New-Object System.Drawing.Point(0, 75)
    $sqlTypeLabel.ForeColor = $script:ThemeColors.TextBlack
    $sqlTypeLabel.Size = New-Object System.Drawing.Size(90, 16)
    $sqlTypeLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $dbPage.Controls.Add($sqlTypeLabel)

    $sqlTypeCombo = New-Object System.Windows.Forms.ComboBox
    $sqlTypeCombo.Location = New-Object System.Drawing.Point(95, 72)
    $sqlTypeCombo.Size = New-Object System.Drawing.Size(200, 21)
    $sqlTypeCombo.DropDownStyle = 'DropDownList'
    $sqlTypeCombo.Font = New-Object System.Drawing.Font("Tahoma", 8)
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
    $sqlLocationLabel.Location = New-Object System.Drawing.Point(0, 105)
    $sqlLocationLabel.Size = New-Object System.Drawing.Size(120, 16)
    $sqlLocationLabel.ForeColor = $script:ThemeColors.TextBlack
    $sqlLocationLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $dbPage.Controls.Add($sqlLocationLabel)

    $sqlLocationBox = New-Object System.Windows.Forms.TextBox
    $sqlLocationBox.Location = New-Object System.Drawing.Point(0, 122)
    $sqlLocationBox.Size = New-Object System.Drawing.Size(295, 20)
    $sqlLocationBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    if ($detected.Count -gt 0) {
        $sqlLocationBox.Text = if ($detected[0].Type -eq "SQLite") { "(not required)" } else { $detected[0].Location }
        $sqlLocationBox.ReadOnly = ($detected[0].Type -eq "SQLite")
        if ($detected[0].Type -eq "SQLite") {
            $sqlLocationBox.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
        }
    }
    $dbPage.Controls.Add($sqlLocationBox)

    $sqlNote = New-Object System.Windows.Forms.Label
    $sqlNote.Text = "Note: SQLite is recommended for most installations."
    $sqlNote.Font = New-Object System.Drawing.Font("Tahoma", 8, [System.Drawing.FontStyle]::Italic)
    $sqlNote.Location = New-Object System.Drawing.Point(0, 150)
    $sqlNote.Size = New-Object System.Drawing.Size(295, 30)
    $sqlNote.ForeColor = $script:ThemeColors.TextGray
    $dbPage.Controls.Add($sqlNote)

    $pages += $dbPage

    # Page 4: SSL/HTTPS Configuration
    $sslPage = New-Object System.Windows.Forms.Panel
    $sslPage.Location = New-Object System.Drawing.Point(10, 10)
    $sslPage.Size = New-Object System.Drawing.Size(305, 295)
    $sslPage.Visible = $false
    $sslPage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($sslPage)

    $sslTitle = New-Object System.Windows.Forms.Label
    $sslTitle.Text = "Web Server Security (HTTPS)"
    $sslTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $sslTitle.Location = New-Object System.Drawing.Point(0, 5)
    $sslTitle.Size = New-Object System.Drawing.Size(295, 25)
    $sslTitle.ForeColor = $script:ThemeColors.TextBlack
    $sslPage.Controls.Add($sslTitle)

    $sslDesc = New-Object System.Windows.Forms.Label
    $sslDesc.Text = "Choose whether to enable HTTPS for secure communication. HTTPS encrypts all traffic between the browser and Server Manager."
    $sslDesc.Location = New-Object System.Drawing.Point(0, 35)
    $sslDesc.Size = New-Object System.Drawing.Size(295, 40)
    $sslDesc.ForeColor = $script:ThemeColors.TextBlack
    $sslDesc.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $sslPage.Controls.Add($sslDesc)

    $sslGroupBox = New-Object System.Windows.Forms.GroupBox
    $sslGroupBox.Text = "Protocol"
    $sslGroupBox.Location = New-Object System.Drawing.Point(0, 80)
    $sslGroupBox.Size = New-Object System.Drawing.Size(295, 70)
    $sslGroupBox.ForeColor = $script:ThemeColors.TextBlack
    $sslGroupBox.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $sslPage.Controls.Add($sslGroupBox)

    $httpsRadio = New-Object System.Windows.Forms.RadioButton
    $httpsRadio.Text = "HTTPS (Recommended - Secure)"
    $httpsRadio.Location = New-Object System.Drawing.Point(10, 18)
    $httpsRadio.Size = New-Object System.Drawing.Size(270, 18)
    $httpsRadio.Checked = $true
    $httpsRadio.ForeColor = $script:ThemeColors.TextBlack
    $httpsRadio.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $sslGroupBox.Controls.Add($httpsRadio)

    $httpRadio = New-Object System.Windows.Forms.RadioButton
    $httpRadio.Text = "HTTP (Not secure - for local/testing only)"
    $httpRadio.Location = New-Object System.Drawing.Point(10, 42)
    $httpRadio.Size = New-Object System.Drawing.Size(270, 18)
    $httpRadio.ForeColor = $script:ThemeColors.TextBlack
    $httpRadio.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $sslGroupBox.Controls.Add($httpRadio)

    $sslWarningLabel = New-Object System.Windows.Forms.Label
    $sslWarningLabel.Text = ""
    $sslWarningLabel.Location = New-Object System.Drawing.Point(0, 155)
    $sslWarningLabel.Size = New-Object System.Drawing.Size(295, 60)
    $sslWarningLabel.ForeColor = $script:ThemeColors.Danger
    $sslWarningLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $sslPage.Controls.Add($sslWarningLabel)

    $sslInfoLabel = New-Object System.Windows.Forms.Label
    $sslInfoLabel.Text = "A self-signed SSL certificate will be generated automatically. You can replace it with your own certificate later in the ssl/ directory."
    $sslInfoLabel.Location = New-Object System.Drawing.Point(0, 220)
    $sslInfoLabel.Size = New-Object System.Drawing.Size(295, 60)
    $sslInfoLabel.ForeColor = $script:ThemeColors.TextGray
    $sslInfoLabel.Font = New-Object System.Drawing.Font("Tahoma", 8, [System.Drawing.FontStyle]::Italic)
    $sslPage.Controls.Add($sslInfoLabel)

    # SSL radio button events
    $httpRadio.Add_CheckedChanged({
        if ($httpRadio.Checked) {
            $sslWarningLabel.Text = "WARNING: HTTP sends all data including passwords in plain text. This is only acceptable for local/isolated network use and poses a significant security risk on public networks."
            $sslInfoLabel.Visible = $false
        }
    })

    $httpsRadio.Add_CheckedChanged({
        if ($httpsRadio.Checked) {
            $sslWarningLabel.Text = ""
            $sslInfoLabel.Visible = $true
        }
    })

    $pages += $sslPage

    # Page 5: Installation Progress
    $installPage = New-Object System.Windows.Forms.Panel
    $installPage.Location = New-Object System.Drawing.Point(10, 10)
    $installPage.Size = New-Object System.Drawing.Size(305, 295)
    $installPage.Visible = $false
    $installPage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($installPage)

    $installTitle = New-Object System.Windows.Forms.Label
    $installTitle.Text = "Installing..."
    $installTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $installTitle.Location = New-Object System.Drawing.Point(0, 5)
    $installTitle.Size = New-Object System.Drawing.Size(295, 25)
    $installTitle.ForeColor = $script:ThemeColors.TextBlack
    $installPage.Controls.Add($installTitle)

    $installDesc = New-Object System.Windows.Forms.Label
    $installDesc.Text = "Please wait while Server Manager is being installed on your computer."
    $installDesc.Location = New-Object System.Drawing.Point(0, 35)
    $installDesc.Size = New-Object System.Drawing.Size(295, 35)
    $installDesc.ForeColor = $script:ThemeColors.TextBlack
    $installDesc.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $installPage.Controls.Add($installDesc)

    $installProgressBar = New-Object System.Windows.Forms.ProgressBar
    $installProgressBar.Location = New-Object System.Drawing.Point(0, 80)
    $installProgressBar.Size = New-Object System.Drawing.Size(295, 20)
    $installProgressBar.Style = 'Continuous'
    $installPage.Controls.Add($installProgressBar)

    $installStatusLabel = New-Object System.Windows.Forms.Label
    $installStatusLabel.Text = "Preparing installation..."
    $installStatusLabel.Location = New-Object System.Drawing.Point(0, 108)
    $installStatusLabel.Size = New-Object System.Drawing.Size(295, 50)
    $installStatusLabel.ForeColor = $script:ThemeColors.TextGray
    $installStatusLabel.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $installPage.Controls.Add($installStatusLabel)

    $pages += $installPage

    # Page 5: Completion
    $completePage = New-Object System.Windows.Forms.Panel
    $completePage.Location = New-Object System.Drawing.Point(10, 10)
    $completePage.Size = New-Object System.Drawing.Size(305, 295)
    $completePage.Visible = $false
    $completePage.BackColor = $script:ThemeColors.PanelBackground
    $contentPanel.Controls.Add($completePage)

    $completeTitle = New-Object System.Windows.Forms.Label
    $completeTitle.Text = "Setup Complete"
    $completeTitle.Font = New-Object System.Drawing.Font("Tahoma", 10, [System.Drawing.FontStyle]::Bold)
    $completeTitle.Location = New-Object System.Drawing.Point(0, 5)
    $completeTitle.Size = New-Object System.Drawing.Size(295, 25)
    $completeTitle.ForeColor = $script:ThemeColors.Success
    $completePage.Controls.Add($completeTitle)

    $completeText = New-Object System.Windows.Forms.Label
    $completeText.Text = @"
Server Manager has been installed successfully.

You can now:
- Access the web interface at:
  https://localhost:8080
- Log in with the credentials you created
- Start managing your game servers

Click Finish to close this wizard.
"@
    $completeText.Location = New-Object System.Drawing.Point(0, 40)
    $completeText.Size = New-Object System.Drawing.Size(295, 200)
    $completeText.ForeColor = $script:ThemeColors.TextBlack
    $completeText.Font = New-Object System.Drawing.Font("Tahoma", 8)
    $completePage.Controls.Add($completeText)

    $pages += $completePage

    # Event handlers
    $steamCmdBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select SteamCMD directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $steamCmdBox.Text = $dialog.SelectedPath
            if (-not $customWorkspaceCheckbox.Checked) {
                $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
            }
        }
    })

    $workspaceBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select workspace directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
        }
    })

    $customWorkspaceCheckbox.Add_CheckedChanged({
        if ($customWorkspaceCheckbox.Checked) {
            $workspaceBox.ReadOnly = $false
            $workspaceBox.BackColor = [System.Drawing.Color]::White
            $workspaceBrowse.Enabled = $true
            $workspaceBox.Text = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "user_workspace"
        } else {
            $workspaceBox.ReadOnly = $true
            $workspaceBox.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
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
                $sqlLocationBox.Text = "(not required)"
                $sqlLocationBox.ReadOnly = $true
                $sqlLocationBox.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
            } else {
                $sqlLocationBox.Text = $selectedItem.Location
                $sqlLocationBox.ReadOnly = $false
                $sqlLocationBox.BackColor = [System.Drawing.Color]::White
            }
        }
    })

    function Show-Page($index) {
        for ($i = 0; $i -lt $pages.Count; $i++) {
            $pages[$i].Visible = ($i -eq $index)
        }
        
        # Update button states (pages 4=install progress, 5=complete are non-navigable back)
        $backButton.Enabled = ($index -gt 0 -and $index -ne 4 -and $index -ne 5)
        $nextButton.Enabled = ($index -ne 4)
        $cancelButton.Enabled = ($index -ne 4 -and $index -ne 5)
        
        if ($index -eq 3) {
            $nextButton.Text = "Install"
            $nextButton.Enabled = $true
        } elseif ($index -eq 5) {
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
            1 { 
                # Validate SteamCMD path before moving to next page
                $steamPath = $steamCmdBox.Text.Trim()
                if ([string]::IsNullOrWhiteSpace($steamPath)) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "SteamCMD Installation Directory is required.", 
                        "Validation Error", 
                        [System.Windows.Forms.MessageBoxButtons]::OK, 
                        [System.Windows.Forms.MessageBoxIcon]::Warning
                    )
                    return
                }
                
                # Check for invalid path characters
                $invalidChars = [System.IO.Path]::GetInvalidPathChars()
                if ($steamPath.IndexOfAny($invalidChars) -ge 0) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "The path contains invalid characters. Please enter a valid directory path.", 
                        "Validation Error", 
                        [System.Windows.Forms.MessageBoxButtons]::OK, 
                        [System.Windows.Forms.MessageBoxIcon]::Warning
                    )
                    return
                }
                
                Show-Page 2 
            }
            2 { Show-Page 3 }
            3 { 
                # Validate cluster node settings on the SSL page (which triggers install)
                if ($subhostRadio.Checked) {
                    $hostAddress = $hostAddrBox.Text.Trim()
                    
                    # Validate Master Host IP Address is required
                    if ([string]::IsNullOrWhiteSpace($hostAddress)) {
                        [System.Windows.Forms.MessageBox]::Show(
                            "Master Host IP Address is required for cluster nodes. Go back to Installation Options to set it.", 
                            "Validation Error", 
                            [System.Windows.Forms.MessageBoxButtons]::OK, 
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        return
                    }
                    
                    # Basic IP format validation
                    if (-not ($hostAddress -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')) {
                        [System.Windows.Forms.MessageBox]::Show(
                            "Please enter a valid IP address format (e.g., 192.168.1.50). Go back to Installation Options to fix it.", 
                            "Validation Error", 
                            [System.Windows.Forms.MessageBoxButtons]::OK, 
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        return
                    }
                }
                
                # Start installation
                Show-Page 4
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
                
                $sslEnabled = $httpsRadio.Checked
                
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
                    SSLEnabled = $sslEnabled
                }
                
                Start-Installation -Settings $settings -ProgressBar $installProgressBar -StatusLabel $installStatusLabel -Form $form -OnComplete {
                    # Update completion page text based on SSL choice
                    $protocol = if ($settings.SSLEnabled) { "https" } else { "http" }
                    $sslNote = if ($settings.SSLEnabled) { "`n- HTTPS is enabled with a self-signed certificate`n- Your browser may show a security warning for the self-signed certificate - this is normal" } else { "`n- WARNING: HTTP mode is active - traffic is not encrypted" }
                    $completeText.Text = @"
Server Manager has been installed successfully.

You can now:
- Access the web interface at:
  ${protocol}://localhost:8080
- Log in with the credentials you created
- Start managing your game servers$sslNote

Click Finish to close this wizard.
"@
                    
                    # Handle cluster approval workflow for subhosts
                    if ($settings.HostType -eq "Subhost" -and $settings.HostAddress) {
                        Show-ClusterApprovalDialog -Settings $settings -Form $form -OnApproved {
                            Show-Page 5
                        }
                    } else {
                        Show-Page 5
                    }
                }
            }
            5 { 
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

    # Initialise first page
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
        # Validate settings first
        if ([string]::IsNullOrWhiteSpace($Settings.SteamCMDPath)) {
            throw "SteamCMD installation path is empty. Please specify a valid directory."
        }
        
        # IMMEDIATELY ensure no console prompts during installation - MAXIMUM SUPPRESSION
        Set-NoConsolePrompts
        
        # Also hide the console window completely during GUI operations
        Show-Console -Hide
        
        $totalSteps = 14
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
                'Theme' = 'light'
                'ModulePath' = "$ServerManagerDir\Modules"
                'LogPath' = "$ServerManagerDir\logs"
                'HostType' = $Settings.HostType
                'SQLType' = $Settings.SQLType
                'SSLEnabled' = if ($Settings.SSLEnabled) { "true" } else { "false" }
                'SSLAutoGenerate' = if ($Settings.SSLEnabled) { "true" } else { "false" }
                'ClusterEnabled' = if ($Settings.HostType -ne "standalone") { "true" } else { "false" }
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
            }
            # Note: Cluster secret generation and token file creation for Master Hosts
            # is handled in the "Configuring cluster database..." step below

            New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
            New-Item -Path $registryPath -Force | Out-Null
            foreach ($key in $registryValues.Keys) {
                Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
            }
            
            # Configure Windows Firewall rules
            Write-Log "Configuring Windows Firewall rules..."
            try {
                $clusterEnabled = ($Settings.HostType -eq "Host" -or ($Settings.HostType -eq "Subhost" -and $Settings.HostAddress))
                Add-ServerManagerFirewallRules -HostType $Settings.HostType -ClusterEnabled $clusterEnabled -SSLEnabled $Settings.SSLEnabled
            } catch {
                Write-Log "Warning: Firewall configuration failed: $($_.Exception.Message)"
                # Don't fail installation if firewall rules fail
            }
            
            # Add Windows Defender exclusions to prevent scanning interruptions
            Write-Log "Adding Windows Defender exclusions..."
            try {
                $serversPath = Join-Path $ServerManagerDir "servers"
                $serverManagerPath = $ServerManagerDir
                
                # Add exclusion for servers folder
                Add-MpPreference -ExclusionPath $serversPath -ErrorAction SilentlyContinue
                Write-Log "Added Windows Defender exclusion for servers folder: $serversPath"
                
                # Add exclusion for entire Server Manager directory
                Add-MpPreference -ExclusionPath $serverManagerPath -ErrorAction SilentlyContinue
                Write-Log "Added Windows Defender exclusion for Server Manager directory: $serverManagerPath"
            } catch {
                Write-Log "Warning: Windows Defender exclusion setup failed: $($_.Exception.Message)"
                # Don't fail installation if Defender exclusions fail
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
                $errorMsg = "Download operation timed out. This could be due to:`n- Slow internet connection`n- Repository server issues`n- Firewall blocking the connection`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "fatal: could not read Username" -or $errorMsg -match "Authentication failed" -or $errorMsg -match "repository not found") {
                $errorMsg = "Repository access denied. This may be because:`n- The repository is private and requires authentication`n- The repository URL is incorrect`n- Network connectivity issues`n`nAttempted fallback download from website but that also failed.`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "Both Git clone and website download failed") {
                $errorMsg = "Failed to download Server Manager files from both Git repository and website backup.`n`nThis could be due to:`n- Network connectivity issues`n- Repository access restrictions`n- Website availability problems`n- Firewall blocking connections`n`nOriginal error: $errorMsg"
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

        Update-Progress "Configuring SSL/HTTPS..."
        try {
            # Create ssl directory
            $sslDir = Join-Path $ServerManagerDir "ssl"
            if (-not (Test-Path $sslDir)) {
                New-Item -ItemType Directory -Force -Path $sslDir | Out-Null
                Write-Log "Created SSL directory: $sslDir"
            }
            
            if ($Settings.SSLEnabled) {
                Write-Log "SSL/HTTPS is enabled - generating self-signed certificate..."
                
                # Generate self-signed certificate using Python ssl_utils module
                $sslGenScript = @"
import sys
import os
sys.path.insert(0, r'$ServerManagerDir')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

try:
    from Modules.security.ssl_utils import generate_self_signed_certificate, verify_certificate
    
    ssl_dir = r'$sslDir'
    cert_path = os.path.join(ssl_dir, 'server.crt')
    key_path = os.path.join(ssl_dir, 'server.key')
    
    # Generate the certificate
    result = generate_self_signed_certificate(ssl_dir)
    if result:
        print('SUCCESS: Self-signed SSL certificate generated')
        print(f'Certificate: {cert_path}')
        print(f'Private key: {key_path}')
        
        # Verify the generated certificate
        verify_result = verify_certificate(cert_path, key_path)
        if verify_result and verify_result.get('valid'):
            print(f'Certificate verified - expires: {verify_result.get("not_after", "unknown")}')
            print('SSL_VERIFIED: true')
        else:
            print('WARNING: Certificate generated but verification returned unexpected result')
            print('SSL_VERIFIED: partial')
    else:
        print('ERROR: Certificate generation returned no result')
        print('SSL_VERIFIED: false')
except ImportError as e:
    # Fallback: generate certificate using cryptography library directly
    print(f'ssl_utils import failed ({e}), using direct generation...')
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        import datetime
        import socket
        
        ssl_dir = r'$sslDir'
        cert_path = os.path.join(ssl_dir, 'server.crt')
        key_path = os.path.join(ssl_dir, 'server.key')
        
        # Generate key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        
        # Build certificate
        hostname = socket.gethostname()
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Server Manager'),
        ])
        
        san_list = [x509.DNSName('localhost'), x509.DNSName(hostname), x509.IPAddress(ipaddress.IPv4Address('127.0.0.1'))]
        try:
            import ipaddress
            local_ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
            for _, _, _, _, sockaddr in local_ips:
                try:
                    san_list.append(x509.IPAddress(ipaddress.IPv4Address(sockaddr[0])))
                except: pass
        except: pass
        
        cert = (x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256(), default_backend()))
        
        # Write files
        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        print('SUCCESS: Self-signed SSL certificate generated (direct method)')
        print('SSL_VERIFIED: true')
    except Exception as e2:
        print(f'ERROR: Failed to generate certificate: {e2}')
        print('SSL_VERIFIED: false')
except Exception as e:
    print(f'ERROR: {e}')
    print('SSL_VERIFIED: false')
"@
                $tempSslPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempSslPy -Value $sslGenScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $sslResult = python $tempSslPy 2>&1
                Remove-Item $tempSslPy -Force -Confirm:$false
                Write-Log "SSL setup result: $sslResult"
                
                # Update registry with SSL paths
                $certPath = Join-Path $sslDir "server.crt"
                $keyPath = Join-Path $sslDir "server.key"
                if (Test-Path $certPath) {
                    Set-ItemProperty -Path $registryPath -Name 'SSLCertPath' -Value $certPath -Force
                    Set-ItemProperty -Path $registryPath -Name 'SSLKeyPath' -Value $keyPath -Force
                    Write-Log "SSL certificate paths saved to registry"
                    
                    if ($sslResult -match "SSL_VERIFIED: true") {
                        Write-Log "SSL certificate generated and verified successfully"
                    } elseif ($sslResult -match "SSL_VERIFIED: partial") {
                        Write-Log "SSL certificate generated but needs manual verification"
                    } else {
                        Write-Log "Warning: SSL certificate generation may have failed - check logs"
                    }
                } else {
                    Write-Log "Warning: SSL certificate file not found after generation attempt"
                    # Disable SSL if cert generation failed
                    Set-ItemProperty -Path $registryPath -Name 'SSLEnabled' -Value "false" -Force
                    Write-Log "SSL has been disabled due to certificate generation failure"
                }
            } else {
                Write-Log "SSL/HTTPS is disabled - skipping certificate generation"
                Write-Log "You can enable HTTPS later via the dashboard settings or by running: python Modules/security/ssl_utils.py --enable"
            }
        } catch {
            Write-Log "Warning: SSL configuration failed: $($_.Exception.Message)"
            Write-Log "HTTPS may not be available. You can configure it later."
            # Don't fail installation if SSL setup fails
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
            # Initialise database and store path for potential future use
            # DataFolder should be the db directory path
            $dataFolder = Join-Path $ServerManagerDir "db"
            $null = Initialize-SQLDatabase -SQLType $Settings.SQLType -SQLVersion $Settings.SQLVersion -SQLLocation $Settings.SQLLocation -DataFolder $dataFolder
        } catch {
            if (-not (Show-StepError "Database Setup" "Failed to initialise database: $($_.Exception.Message)`n`nUser authentication may not work properly.")) {
                throw "Installation cancelled by user after database setup failed"
            }
        }

        Update-Progress "Configuring cluster database..."
        try {
            # Initialise cluster configuration in database using direct SQLite
            $clusterDbPath = "$ServerManagerDir\db\servermanager.db"
            if (Test-Path $clusterDbPath) {
                $initClusterScript = @"
import sqlite3
import secrets
import sys
from datetime import datetime

try:
    db_path = r'$clusterDbPath'
    host_type = '$($Settings.HostType)'
    host_address = '$($Settings.HostAddress)' if '$($Settings.HostAddress)' else None
    cluster_name = 'ServerManager-Cluster'
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Generate cluster secret for master hosts
    cluster_secret = None
    if host_type == 'Host':
        cluster_secret = secrets.token_urlsafe(32)
    
    # Check if cluster_config already has a row
    c.execute('SELECT COUNT(*) FROM cluster_config')
    count = c.fetchone()[0]
    
    if count == 0:
        c.execute('''
            INSERT INTO cluster_config (host_type, cluster_name, cluster_secret, master_ip, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (host_type, cluster_name, cluster_secret, host_address, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    else:
        c.execute('''
            UPDATE cluster_config SET host_type = ?, cluster_name = ?, cluster_secret = ?, master_ip = ?, updated_at = ? WHERE id = 1
        ''', (host_type, cluster_name, cluster_secret, host_address, datetime.utcnow().isoformat()))
    
    # Ensure host_status has a default row
    c.execute('SELECT COUNT(*) FROM host_status')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO host_status (id, status, dashboard_active) VALUES (1, "online", 1)')
    
    conn.commit()
    conn.close()
    
    print(f'SUCCESS: Cluster database configured as {host_type}')
    if cluster_secret:
        print(f'CLUSTER_SECRET: {cluster_secret}')

except Exception as e:
    print(f'ERROR: {e}')
"@
                $tempClusterInitPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempClusterInitPy -Value $initClusterScript
                $env:PYTHONDONTWRITEBYTECODE = "1"
                $clusterInitResult = python $tempClusterInitPy 2>&1
                Remove-Item $tempClusterInitPy -Force -Confirm:$false
                Write-Log "Cluster database initialisation result: $clusterInitResult"
                
                # Extract and save cluster secret to registry
                if ($clusterInitResult -match "CLUSTER_SECRET: (.+)") {
                    $GeneratedClusterSecret = $matches[1].Trim()
                    Set-ItemProperty -Path $registryPath -Name 'ClusterSecret' -Value $GeneratedClusterSecret -Force
                    Write-Log "Cluster secret stored in registry"
                    
                    # Save token file for master host
                    if ($Settings.HostType -eq "Host") {
                        $tokenFile = Join-Path $ServerManagerDir "cluster-security-token.txt"
                        try {
                            $tokenContent = @"
Server Manager Cluster Security Token
Generated: $(Get-Date -Format 'o')
Master Host: $ServerManagerDir

SECURITY TOKEN:
$GeneratedClusterSecret

IMPORTANT NOTES:
- This token provides full access to your Server Manager cluster
- Store it securely and share only with trusted subhost administrators  
- This token cannot be recovered if lost - you'll need to generate a new one
- All existing subhosts will need to update their tokens if regenerated

Provide this token to subhost administrators during their installation process.
"@
                            Set-Content -Path $tokenFile -Value $tokenContent -Encoding UTF8
                            # Protect the token file
                            Protect-ConfigFile -FilePath $tokenFile
                            Write-Log "Cluster security token saved to: $tokenFile"
                        } catch {
                            Write-Log "Warning: Could not save token to file: $($_.Exception.Message)"
                        }
                    }
                }
            } else {
                Write-Log "Warning: Cluster database not found at $clusterDbPath - will be created on first launch"
            }
        } catch {
            Write-Log "Warning: Failed to initialise cluster database configuration: $($_.Exception.Message)"
        }

        Update-Progress "Creating configuration files..."
        try {
            # Environment file creation removed - using registry-based configuration only
        } catch {
            if (-not (Show-StepError "Configuration Files" "Failed to create configuration files: $($_.Exception.Message)")) {
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
                $serviceWrapperPath = Join-Path $ServerManagerDir "Modules\services\service_wrapper.py"
                
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

# Cluster approval dialog for subhosts - Classic Windows Style
function Show-ClusterApprovalDialog {
    param(
        [PSCustomObject]$Settings,
        [System.Windows.Forms.Form]$Form,
        [scriptblock]$OnApproved
    )
    
    # Create approval request form - Classic Windows style
    $script:clusterApprovalForm = New-Object System.Windows.Forms.Form
    $script:clusterApprovalForm.Text = "Cluster Join Request"
    $script:clusterApprovalForm.Size = New-Object System.Drawing.Size(400, 280)
    $script:clusterApprovalForm.StartPosition = "CenterParent"
    $script:clusterApprovalForm.FormBorderStyle = "FixedDialog"
    $script:clusterApprovalForm.MaximizeBox = $false
    $script:clusterApprovalForm.MinimizeBox = $false
    $script:clusterApprovalForm.ShowIcon = $false
    $script:clusterApprovalForm.BackColor = [System.Drawing.Color]::FromArgb(236, 233, 216)
    $script:clusterApprovalForm.Font = New-Object System.Drawing.Font("Tahoma", 8)
    
    # Status label - script scope for timer access
    $script:clusterStatusLabel = New-Object System.Windows.Forms.Label
    $script:clusterStatusLabel.Text = "Connecting to master host..."
    $script:clusterStatusLabel.Location = New-Object System.Drawing.Point(20, 20)
    $script:clusterStatusLabel.Size = New-Object System.Drawing.Size(350, 20)
    $script:clusterStatusLabel.Font = New-Object System.Drawing.Font("Tahoma", 8, [System.Drawing.FontStyle]::Bold)
    $script:clusterApprovalForm.Controls.Add($script:clusterStatusLabel)
    
    # Detail label - script scope for timer access
    $script:clusterDetailLabel = New-Object System.Windows.Forms.Label
    $script:clusterDetailLabel.Text = "Please wait..."
    $script:clusterDetailLabel.Location = New-Object System.Drawing.Point(20, 45)
    $script:clusterDetailLabel.Size = New-Object System.Drawing.Size(350, 35)
    $script:clusterApprovalForm.Controls.Add($script:clusterDetailLabel)
    
    # Progress bar - script scope for timer access
    $script:clusterProgressBar = New-Object System.Windows.Forms.ProgressBar
    $script:clusterProgressBar.Location = New-Object System.Drawing.Point(20, 90)
    $script:clusterProgressBar.Size = New-Object System.Drawing.Size(350, 18)
    $script:clusterProgressBar.Style = "Marquee"
    $script:clusterProgressBar.MarqueeAnimationSpeed = 30
    $script:clusterApprovalForm.Controls.Add($script:clusterProgressBar)
    
    # Info group
    $infoGroup = New-Object System.Windows.Forms.GroupBox
    $infoGroup.Text = "Connection Details"
    $infoGroup.Location = New-Object System.Drawing.Point(20, 115)
    $infoGroup.Size = New-Object System.Drawing.Size(350, 75)
    $script:clusterApprovalForm.Controls.Add($infoGroup)
    
    $infoText = New-Object System.Windows.Forms.Label
    $infoText.Text = "Master Host: $($Settings.HostAddress)`nLocal Machine: $env:COMPUTERNAME`nTimeout: 5 minutes"
    $infoText.Location = New-Object System.Drawing.Point(10, 18)
    $infoText.Size = New-Object System.Drawing.Size(330, 50)
    $infoGroup.Controls.Add($infoText)
    
    # Buttons - script scope for timer access
    $script:clusterRetryButton = New-Object System.Windows.Forms.Button
    $script:clusterRetryButton.Text = "Retry"
    $script:clusterRetryButton.Location = New-Object System.Drawing.Point(130, 205)
    $script:clusterRetryButton.Size = New-Object System.Drawing.Size(75, 25)
    $script:clusterRetryButton.Visible = $false
    $script:clusterRetryButton.UseVisualStyleBackColor = $true
    $script:clusterApprovalForm.Controls.Add($script:clusterRetryButton)
    
    $script:clusterSkipButton = New-Object System.Windows.Forms.Button
    $script:clusterSkipButton.Text = "Skip"
    $script:clusterSkipButton.Location = New-Object System.Drawing.Point(215, 205)
    $script:clusterSkipButton.Size = New-Object System.Drawing.Size(75, 25)
    $script:clusterSkipButton.Visible = $false
    $script:clusterSkipButton.UseVisualStyleBackColor = $true
    $script:clusterApprovalForm.Controls.Add($script:clusterSkipButton)
    
    $script:clusterCancelButton = New-Object System.Windows.Forms.Button
    $script:clusterCancelButton.Text = "Cancel"
    $script:clusterCancelButton.Location = New-Object System.Drawing.Point(300, 205)
    $script:clusterCancelButton.Size = New-Object System.Drawing.Size(75, 25)
    $script:clusterCancelButton.UseVisualStyleBackColor = $true
    $script:clusterApprovalForm.Controls.Add($script:clusterCancelButton)
    
    # State variables
    $script:approvalRequestId = $null
    $script:requestSent = $false
    $script:attemptCount = 0
    $script:maxAttempts = 60
    $script:consecutiveErrors = 0
    $script:isPaused = $false
    $script:lastErrorMessage = ""
    $script:clusterHostAddress = $Settings.HostAddress
    $script:clusterSubhostID = $Settings.SubhostID
    $script:clusterSettings = $Settings
    $script:clusterOnApproved = $OnApproved
    $script:clusterParentForm = $Form
    
    # Timer - script scope
    $script:clusterTimer = New-Object System.Windows.Forms.Timer
    $script:clusterTimer.Interval = 5000
    
    # Cancel click
    $script:clusterCancelButton.Add_Click({
        $script:clusterTimer.Stop()
        $script:clusterApprovalForm.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $script:clusterApprovalForm.Close()
    })
    
    # Skip click
    $script:clusterSkipButton.Add_Click({
        $script:clusterTimer.Stop()
        Write-Log "User chose to skip cluster join"
        $script:clusterApprovalForm.Hide()
        if ($script:clusterOnApproved) { & $script:clusterOnApproved }
        $script:clusterApprovalForm.Close()
    })
    
    # Retry click
    $script:clusterRetryButton.Add_Click({
        Write-Log "User initiated retry"
        $script:consecutiveErrors = 0
        $script:isPaused = $false
        $script:requestSent = $false
        $script:clusterStatusLabel.Text = "Retrying connection..."
        $script:clusterDetailLabel.Text = "Attempting to connect to master host..."
        $script:clusterProgressBar.Style = "Marquee"
        $script:clusterRetryButton.Visible = $false
        $script:clusterSkipButton.Visible = $false
        $script:clusterTimer.Start()
    })
    
    # Timer tick - main logic
    $script:clusterTimer.Add_Tick({
        if ($script:isPaused) { return }
        
        $script:attemptCount++
        $remaining = ($script:maxAttempts - $script:attemptCount) * 5
        $mins = [math]::Floor($remaining / 60)
        $secs = $remaining % 60
        
        # Timeout check
        if ($script:attemptCount -gt $script:maxAttempts) {
            $script:clusterTimer.Stop()
            $script:clusterStatusLabel.Text = "Request Timed Out"
            $script:clusterDetailLabel.Text = "Administrator did not respond within 5 minutes."
            $script:clusterProgressBar.Style = "Continuous"
            $script:clusterProgressBar.Value = 0
            $script:clusterRetryButton.Visible = $true
            $script:clusterSkipButton.Visible = $true
            $script:isPaused = $true
            Write-Log "Cluster join request timed out"
            return
        }
        
        if (-not $script:requestSent) {
            # Check host availability
            try {
                $script:clusterStatusLabel.Text = "Checking host... (${mins}:$($secs.ToString('00')) remaining)"
                $script:clusterDetailLabel.Text = "Connecting to $($script:clusterHostAddress)..."
                
                $hostStatus = Invoke-RestMethod -Uri "http://$($script:clusterHostAddress):8080/api/cluster/status" -Method GET -TimeoutSec 10
                
                if ($hostStatus.host_status -eq "offline" -or $hostStatus.dashboard_active -eq $false) {
                    $script:consecutiveErrors++
                    $script:clusterDetailLabel.Text = "Host is offline. Waiting... (attempt $script:attemptCount)"
                    if ($script:consecutiveErrors -ge 3) {
                        $script:clusterRetryButton.Visible = $true
                        $script:clusterSkipButton.Visible = $true
                    }
                    return
                }
                
                $script:consecutiveErrors = 0
                $script:clusterStatusLabel.Text = "Sending join request..."
                
                # Get local IP
                $localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
                if (-not $localIP) {
                    $localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" } | Select-Object -First 1).IPAddress
                }
                
                $hostname = $env:COMPUTERNAME
                try { $hostname = [System.Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName } catch {}
                
                $requestBody = @{
                    subhost_id = $script:clusterSubhostID
                    info = @{
                        machine_name = $env:COMPUTERNAME
                        hostname = $hostname
                        os = (Get-ComputerInfo).WindowsProductName
                        install_time = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                        ip_address = $localIP
                    }
                } | ConvertTo-Json -Depth 3
                
                Write-Log "Sending join request with IP: $localIP"
                $response = Invoke-RestMethod -Uri "http://$($script:clusterHostAddress):8080/api/cluster/request-join" -Method POST -Body $requestBody -ContentType "application/json" -TimeoutSec 15
                
                if ($response.request_id) {
                    $script:approvalRequestId = $response.request_id
                    $script:requestSent = $true
                    $script:consecutiveErrors = 0
                    $script:clusterStatusLabel.Text = "Waiting for Approval..."
                    $script:clusterDetailLabel.Text = "Request sent. Awaiting administrator response."
                    Write-Log "Join request sent with ID: $($response.request_id)"
                } else {
                    throw "No request_id in response"
                }
                
            } catch {
                $script:consecutiveErrors++
                $script:lastErrorMessage = $_.Exception.Message
                $script:clusterDetailLabel.Text = "Error: $script:lastErrorMessage"
                Write-Log "Connection error: $script:lastErrorMessage"
                
                if ($script:consecutiveErrors -ge 3) {
                    $script:clusterTimer.Stop()
                    $script:clusterStatusLabel.Text = "Connection Failed"
                    $script:clusterProgressBar.Style = "Continuous"
                    $script:clusterProgressBar.Value = 0
                    $script:clusterRetryButton.Visible = $true
                    $script:clusterSkipButton.Visible = $true
                    $script:isPaused = $true
                }
            }
        } else {
            # Check approval status
            try {
                $script:clusterStatusLabel.Text = "Waiting for Approval... (${mins}:$($secs.ToString('00')) remaining)"
                $approvalResponse = Invoke-RestMethod -Uri "http://$($script:clusterHostAddress):8080/api/cluster/check-approval/$($script:clusterSubhostID)" -Method GET -TimeoutSec 10
                
                if ($approvalResponse.status -eq "approved") {
                    $script:clusterTimer.Stop()
                    $script:clusterStatusLabel.Text = "Approved!"
                    $script:clusterDetailLabel.Text = "Join request accepted."
                    $script:clusterProgressBar.Style = "Continuous"
                    $script:clusterProgressBar.Value = 100
                    $script:clusterSettings.ClusterToken = $approvalResponse.approval_token
                    Write-Log "Cluster join approved! Token: $($approvalResponse.approval_token)"
                    Start-Sleep -Milliseconds 500
                    $script:clusterApprovalForm.Hide()
                    if ($script:clusterOnApproved) { & $script:clusterOnApproved }
                    $script:clusterApprovalForm.Close()
                    
                } elseif ($approvalResponse.status -eq "rejected") {
                    $script:clusterTimer.Stop()
                    $script:clusterStatusLabel.Text = "Request Rejected"
                    $script:clusterDetailLabel.Text = "Administrator declined the request."
                    $script:clusterProgressBar.Style = "Continuous"
                    $script:clusterProgressBar.Value = 0
                    $script:clusterSkipButton.Visible = $true
                    $script:isPaused = $true
                    Write-Log "Cluster join rejected"
                    
                } elseif ($approvalResponse.status -eq "pending") {
                    $script:clusterDetailLabel.Text = "Request pending administrator review..."
                }
                
                $script:consecutiveErrors = 0
                
            } catch {
                $script:consecutiveErrors++
                $script:lastErrorMessage = $_.Exception.Message
                $script:clusterDetailLabel.Text = "Status check error (attempt $script:consecutiveErrors/3)"
                Write-Log "Status check error: $script:lastErrorMessage"
                
                if ($script:consecutiveErrors -ge 3) {
                    $script:clusterTimer.Stop()
                    $script:clusterStatusLabel.Text = "Connection Lost"
                    $script:clusterProgressBar.Style = "Continuous"
                    $script:clusterProgressBar.Value = 0
                    $script:clusterRetryButton.Visible = $true
                    $script:clusterSkipButton.Visible = $true
                    $script:isPaused = $true
                }
            }
        }
    })
    
    # Form closing
    $script:clusterApprovalForm.Add_FormClosing({
        param($formSender, $closeEventArgs)
        if ($script:clusterTimer) { $script:clusterTimer.Stop(); $script:clusterTimer.Dispose() }
        if ($closeEventArgs.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing -and $script:clusterApprovalForm.DialogResult -eq [System.Windows.Forms.DialogResult]::Cancel) {
            $script:clusterParentForm.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
            $script:clusterParentForm.Close()
        }
    })
    
    $script:clusterApprovalForm.Show()
    $script:clusterApprovalForm.BringToFront()
    $script:clusterTimer.Start()
}

function Test-Python310 {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $ver = & python -c 'import sys; print(sys.version_info.major, sys.version_info.minor, sys.maxsize > 2**32)'
        $parts = $ver -split ' '
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
    Write-Log 'Python 3.10 64-bit not found. Downloading and installing Python 3.10 64-bit...'
    $pythonInstallerUrl = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri $pythonInstallerUrl -OutFile $installerPath
    Write-Log "Running Python installer..."
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    Remove-Item $installerPath -Force -Confirm:$false
    
    # Refresh PATH environment variable safely
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $newPath = @($machinePath, $userPath) | Where-Object { $_ } | ForEach-Object { $_.TrimEnd(';') }
    $env:Path = ($newPath -join ';')
    
    Write-Log "PATH refreshed after Python installation"
}

function Install-PythonRequirements {
    param([string]$RequirementsPath)
    Write-Log "Installing Python requirements using pip..."
    if (-not (Test-Path $RequirementsPath)) {
        Write-Log "Python requirements.txt not found at: $RequirementsPath"
        return $false
    }
    
    # Try to find Python in common locations if not in PATH
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Log "Python not found in PATH, searching common locations..."
        
        # Check common Python installation paths
        $commonPaths = @(
            "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
            "C:\Python310\python.exe",
            "C:\Python311\python.exe",
            "C:\Python312\python.exe",
            "C:\Program Files\Python310\python.exe",
            "C:\Program Files\Python311\python.exe",
            "C:\Program Files\Python312\python.exe"
        )
        
        foreach ($path in $commonPaths) {
            if (Test-Path $path) {
                Write-Log "Found Python at: $path"
                $pythonExe = $path
                break
            }
        }
        
        if (-not $pythonExe) {
            Write-Log "Python not found in PATH or common locations. Current PATH: $env:Path"
            return $false
        }
    } else {
        $pythonExe = "python"
    }
    
    Write-Log "Using Python: $pythonExe"
    Write-Log "Upgrading pip..."
    & $pythonExe -m pip install --upgrade pip 2>&1 | Out-Null
    Write-Log "Installing requirements from $RequirementsPath..."
    & $pythonExe -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to install Python requirements."
        return $false
    }
    Write-Log "Python requirements installed successfully."
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
            $adminForm.Controls.Add($okButton)
            
            $cancelButton = New-Object System.Windows.Forms.Button
            $cancelButton.Text = "Skip"
            $cancelButton.Location = New-Object System.Drawing.Point(360, 270)
            $cancelButton.Size = New-Object System.Drawing.Size(80, 35)
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
        if (-not (Request-ReinstallConfirmation)) {
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