# Set title and clear screen
$host.ui.RawUI.WindowTitle = "Server Manager Launcher"
Clear-Host

# Set error action preference and initialize
$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $rootDir "logs"

# Create structured log directories
$logPaths = @{
    Main = Join-Path $logDir "main.log"
    WebServer = Join-Path $logDir "webserver.log"
    TrayIcon = Join-Path $logDir "trayicon.log"
    Updates = Join-Path $logDir "updates.log"
}

# Ensure log directory exists
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Start transcript for main logging
Start-Transcript -Path $logPaths.Main -Append

# Store process IDs for cleanup
$Global:ProcessTracker = @{
    WebServer = $null
    TrayIcon = $null
}

# Function to cleanup processes
function Stop-AllComponents {
    Write-Host "Stopping all components..." -ForegroundColor Cyan
    
    $processes = @($Global:ProcessTracker.WebServer, $Global:ProcessTracker.TrayIcon)
    foreach ($processToStop in $processes) {
        if ($processToStop) {
            try {
                $process = Get-Process -Id $processToStop -ErrorAction Stop
                if (-not $process.HasExited) {
                    Stop-Process -Id $processToStop -Force
                    Wait-Process -Id $processToStop -Timeout 5 -ErrorAction SilentlyContinue
                }
            } catch { }
        }
    }
    
    # Ensure ports are released
    try {
        netsh http delete urlacl url=http://localhost:8080/ | Out-Null
    } catch { }
    
    # Kill any remaining processes using port 8080
    Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
        ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
}

# Replace the trap handler with a Ctrl+C handler
$null = [Console]::TreatControlCAsInput = $true

# Add cleanup on PowerShell exit
$exitScript = {
    Write-Host "Cleaning up processes..." -ForegroundColor Yellow
    Stop-AllComponents
}
Register-EngineEvent PowerShell.Exiting -Action $exitScript | Out-Null

# Check for admin privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Get script directory and parent directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

# Get registry paths
try {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $steamCmdDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).SteamCmdPath
    
    # Validate server directory
    if ([string]::IsNullOrWhiteSpace($serverDir)) {
        throw "Server directory path is empty in registry"
    }
    
    # Clean up path (remove any trailing slashes and quotes)
    $serverDir = $serverDir.Trim('"', ' ', '\')
    
    Write-Host "Server Directory: $serverDir" -ForegroundColor Cyan
    
    if (-not (Test-Path $serverDir)) {
        throw "Server directory not found: $serverDir"
    }

    # Validate required subdirectories
    $requiredPaths = @(
        (Join-Path $rootDir "Modules"),
        (Join-Path $scriptDir "webserver.ps1")
    )

    foreach ($path in $requiredPaths) {
        if (-not (Test-Path $path)) {
            throw "Required path not found: $path"
        }
    }

} catch {
    Write-Host "Error accessing Server Manager installation: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Registry Path: $registryPath" -ForegroundColor Yellow
    Write-Host "Server Directory: $serverDir" -ForegroundColor Yellow
    Write-Host "Please ensure Server Manager is properly installed by running install.ps1"
    Read-Host "Press Enter to exit"
    exit 1
}

# Remove any private path references in module loading
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$modulesPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "Modules"

# Modified module loading section
$modulesPath = Join-Path $serverDir "Modules"
if (-not (Test-Path $modulesPath)) {
    throw "Modules directory not found: $modulesPath"
}

# Load core modules first in specific order
$coreModules = @(
    "Network.psm1",
    "WebSocketServer.psm1",
    "ServerManager.psm1"
)

# Define required functions for each module
$Global:requiredFunctions = @{
    "Network.psm1" = @(
        "New-ServerNetwork",
        "Remove-ServerNetwork"
    )
    "WebSocketServer.psm1" = @(
        "New-WebSocketServer",
        "New-WebSocketClient"
    )
    "ServerManager.psm1" = @(
        "New-GameServer",
        "Start-GameServer",
        "Stop-GameServer",
        "New-ServerInstance",
        "Start-ServerInstance",
        "Stop-ServerInstance",
        "Get-ServerInstances",
        "Get-ServerStatus"
    )
}

# Improved module validation function
function Test-ModuleExports {
    param (
        [string]$ModulePath,
        [string[]]$RequiredFunctions
    )
    
    try {
        if (-not $RequiredFunctions) {
            Write-Host "No required functions specified for $ModulePath" -ForegroundColor Yellow
            return $true
        }

        Write-Host "Testing module: $ModulePath" -ForegroundColor Cyan
        Write-Host "Required functions: $($RequiredFunctions -join ', ')" -ForegroundColor Cyan
        
        $moduleInfo = Import-Module -Name $ModulePath -Force -PassThru -ErrorAction Stop
        if (-not $moduleInfo) {
            throw "Failed to import module for validation"
        }

        $exportedFunctions = $moduleInfo.ExportedFunctions.Keys
        Write-Host "Exported functions: $($exportedFunctions -join ', ')" -ForegroundColor Gray
        
        $missingFunctions = $RequiredFunctions | Where-Object { $_ -notin $exportedFunctions }
        
        if ($missingFunctions) {
            throw "Missing required functions: $($missingFunctions -join ', ')"
        }
        
        return $true
    }
    catch {
        Write-Host "Module validation failed for $ModulePath : $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Clear any existing modules first
Get-Module | Where-Object { $_.Path -like "*$modulesPath*" } | Remove-Module -Force

# Add before module loading
Write-Host "Module path: $modulesPath" -ForegroundColor Cyan

# Add before module loading section
Write-Host "Clearing module cache..." -ForegroundColor Cyan
Get-Module | Where-Object { $_.Path -like "*$modulesPath*" } | Remove-Module -Force
Remove-Module Network, WebSocketServer, ServerManager -ErrorAction SilentlyContinue

# Define required functions as array, not hashtable
[string[]]$requiredFunctions = @(
    "New-ServerNetwork",
    "New-WebSocketServer",
    "New-GameServer"
)

# Modified module loading section
$moduleLoadingSuccess = $true
foreach ($module in $coreModules) {
    $modulePath = Join-Path $modulesPath $module
    Write-Host "Attempting to load module: $modulePath" -ForegroundColor Cyan
    
    if (Test-Path $modulePath) {
        try {
            Write-Host "`nValidating core module: $module" -ForegroundColor Cyan
            
            # Import module with scope options
            $moduleInfo = Import-Module -Name $modulePath -Global -Force -PassThru -Verbose -ErrorAction Stop -DisableNameChecking
            
            if ($moduleInfo) {
                Write-Host "Module imported: $($moduleInfo.Name)" -ForegroundColor Green
                Write-Host "Exported functions: $($moduleInfo.ExportedFunctions.Keys -join ', ')" -ForegroundColor Gray
                
                # Force functions into global scope
                $moduleInfo.ExportedFunctions.Keys | ForEach-Object {
                    $null = New-Item -Path Function::Global:$_ -Value (Get-Content Function::$_) -Force
                }
                
                Write-Host "Successfully loaded $module" -ForegroundColor Green
            } else {
                throw "Module import returned null"
            }
        }
        catch {
            $moduleLoadingSuccess = $false
            Write-Host "Error loading module $module : $($_.Exception.Message)" -ForegroundColor Red
            Write-Host $_.ScriptStackTrace -ForegroundColor Red
            break
        }
    }
    else {
        $moduleLoadingSuccess = $false
        Write-Host "Core module not found: $modulePath" -ForegroundColor Red
        break
    }
}

# Modified verification step
Write-Host "`nVerifying function availability:" -ForegroundColor Cyan
foreach ($funcName in $requiredFunctions) {
    $cmd = Get-Command -Name $funcName -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host "Function $funcName : Available" -ForegroundColor Green
    } else {
        Write-Host "Function $funcName : Missing" -ForegroundColor Red
        $moduleLoadingSuccess = $false
    }
}

# Verify modules are loaded before continuing
Write-Host "`nVerifying loaded modules:" -ForegroundColor Cyan
$loadedModules = Get-Module | Where-Object { $_.Path -like "*$modulesPath*" }
foreach ($module in $loadedModules) {
    Write-Host "Loaded $($module.Name) with functions:" -ForegroundColor Green
    $module.ExportedFunctions.Keys | ForEach-Object {
        Write-Host "  - $_" -ForegroundColor Gray
    }
}

if (-not $moduleLoadingSuccess) {
    throw "Critical module loading failed. Cannot continue."
}

# Verify required functions are available
$requiredFunctions = @(
    "New-ServerNetwork",
    "New-WebSocketServer",
    "New-GameServer"
)

$missingFunctions = $requiredFunctions | Where-Object {
    -not (Get-Command $_ -ErrorAction SilentlyContinue)
}

if ($missingFunctions) {
    throw "Missing required functions: $($missingFunctions -join ', ')"
}

Write-Host "`nAll required modules and functions verified. Continuing with launch...`n" -ForegroundColor Green

# Add error action preference to catch more errors
$ErrorActionPreference = 'Stop'

# Create log directory if it doesn't exist
$logDir = Join-Path $rootDir "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Define log files
$webServerLog = Join-Path $logDir "webserver.log"
$trayIconLog = Join-Path $logDir "trayicon.log"

# Launch web server
function Start-WebServer {
    $webserverPath = Join-Path $PSScriptRoot "webserver.ps1"
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "powershell.exe"
    $startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$webserverPath`" -LogPath `"$($logPaths.WebServer)`""
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.WindowStyle = 'Hidden'
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    
    $Global:ProcessTracker.WebServer = $process.Id
    return $process
}

# Launch tray icon
function Start-TrayIcon {
    $trayIconPath = Join-Path $PSScriptRoot "trayicon.ps1"
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "powershell.exe"
    $startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -Sta -WindowStyle Hidden -File `"$trayIconPath`" -LogPath `"$($logPaths.TrayIcon)`""
    $startInfo.UseShellExecute = $true
    $startInfo.WindowStyle = 'Hidden'
    
    Write-Host "Starting tray icon with arguments: $($startInfo.Arguments)"
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    
    # Give the process time to start and initialize
    Start-Sleep -Seconds 3
    
    if ($process.HasExited) {
        $log = Get-Content -Path $logPaths.TrayIcon -ErrorAction SilentlyContinue
        throw "Tray icon process failed to start.`nLog:`n$($log -join "`n")"
    }
    
    $Global:ProcessTracker.TrayIcon = $process.Id
    return $process
}

try {
    # Launch components with validation
    Write-Host "Starting Web Server..." -ForegroundColor Cyan
    $webServerProcess = Start-WebServer
    
    # Validate web server started
    Start-Sleep -Seconds 2
    if ($webServerProcess.HasExited) {
        throw "Web server failed to start. Check logs at: $($logPaths.WebServer)"
    }
    
    # Test web server connection
    $maxAttempts = 30
    $attempts = 0
    $serverReady = $false
    
    while (-not $serverReady -and $attempts -lt $maxAttempts) {
        try {
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            $tcpClient.Connect("localhost", 8080)
            $tcpClient.Close()
            $serverReady = $true
            Write-Host "Web server is responding!" -ForegroundColor Green
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
            $attempts++
            Write-Host "Waiting for web server... Attempt $attempts of $maxAttempts" -ForegroundColor Yellow
        }
    }
    
    if (-not $serverReady) {
        throw "Web server failed to respond after $maxAttempts attempts"
    }
    
    Write-Host "Starting Tray Icon..." -ForegroundColor Cyan
    $trayProcess = Start-TrayIcon
    
    # Validate tray icon started
    Start-Sleep -Seconds 2
    if ($trayProcess.HasExited) {
        throw "Tray icon failed to start. Check logs at: $($logPaths.TrayIcon)"
    }
    
    Write-Host "`nServer Manager components started successfully!" -ForegroundColor Green
    Write-Host "Access web interface at: http://localhost:8080/" -ForegroundColor Cyan
    Write-Host "Use the tray icon for quick access" -ForegroundColor Cyan
    Write-Host "Logs directory: $logDir" -ForegroundColor Gray
    
    # Monitor processes with improved error handling
    while ($true) {
        Start-Sleep -Milliseconds 500
        
        try {
            # Check web server
            if (-not (Get-Process -Id $webServerProcess.Id -ErrorAction Stop)) {
                throw "Web server process terminated unexpectedly"
            }
            
            # Check tray icon
            if (-not (Get-Process -Id $trayProcess.Id -ErrorAction Stop)) {
                throw "Tray icon process terminated unexpectedly"
            }
            
            # Check for Ctrl+C
            if ([Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq "C" -and $key.Modifiers -eq "Control") {
                    Write-Host "`nShutting down..." -ForegroundColor Yellow
                    Stop-AllComponents
                    break
                }
            }
        }
        catch {
            if ($_.Exception.Message -match "Cannot find a process") {
                Write-Host "Process monitoring error: $($_.Exception.Message)" -ForegroundColor Red
                Stop-AllComponents
                break
            }
            throw
        }
    }
}
catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    Stop-AllComponents
}
finally {
    Stop-Transcript
}

