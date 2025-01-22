Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

param(
    [switch]$AsService
)

# Set title and clear screen
$host.ui.RawUI.WindowTitle = "Server Manager"
Clear-Host

# Add early in the script
$script:IsService = $AsService -or ([System.Environment]::UserInteractive -eq $false)

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

# Create a script-level variable for the log file stream
$script:logStream = $null

# Initialize log file with proper sharing
try {
    # Delete existing log if it exists
    if (Test-Path $logPaths.Main) {
        Remove-Item $logPaths.Main -Force -ErrorAction Stop
    }
    
    # Create new log file with FileShare.ReadWrite
    $script:logStream = [System.IO.File]::Open(
        $logPaths.Main,
        [System.IO.FileMode]::Create,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite
    )
    $script:logWriter = New-Object System.IO.StreamWriter($script:logStream)
    $script:logWriter.AutoFlush = $true
} catch {
    Write-Warning "Failed to initialize log file: $_"
}

# Store process IDs for cleanup
$Global:ProcessTracker = @{
    WebServer = $null
    TrayIcon = $null
}

# Modified Write-StatusMessage function
function Write-StatusMessage {
    param(
        [string]$Message,
        [string]$Color = 'White',
        [switch]$Verbose
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    
    try {
        if ($script:logWriter) {
            $script:logWriter.WriteLine($logMessage)
        }
    } catch {
        Write-Warning "Log write failed: $_"
    }
    
    if (-not $Verbose) {
        Write-Host $Message -ForegroundColor $Color
    }
}

# Function to cleanup processes
function Stop-AllComponents {
    Write-StatusMessage "Stopping all components..." "Yellow"
    
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
    
    Write-StatusMessage "Cleanup complete." "Green"
}

# Replace the trap handler with a Ctrl+C handler
$null = [Console]::TreatControlCAsInput = $true

# Add cleanup on PowerShell exit
$exitScript = {
    Write-StatusMessage "Cleaning up processes..." "Yellow"
    Stop-AllComponents
}
Register-EngineEvent PowerShell.Exiting -Action $exitScript | Out-Null

# Check for admin privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-StatusMessage "Please run this script as Administrator" "Red"
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
    
    Write-StatusMessage "Server Directory: $serverDir" "Cyan"
    
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
    Write-StatusMessage "Error accessing Server Manager installation: $($_.Exception.Message)" "Red"
    Write-StatusMessage "Registry Path: $registryPath" "Yellow"
    Write-StatusMessage "Server Directory: $serverDir" "Yellow"
    Write-StatusMessage "Please ensure Server Manager is properly installed by running install.ps1"
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
            Write-StatusMessage "No required functions specified for $ModulePath" "Yellow"
            return $true
        }

        Write-StatusMessage "Testing module: $ModulePath" "Cyan"
        Write-StatusMessage "Required functions: $($RequiredFunctions -join ', ')" "Cyan"
        
        $moduleInfo = Import-Module -Name $ModulePath -Force -PassThru -ErrorAction Stop
        if (-not $moduleInfo) {
            throw "Failed to import module for validation"
        }

        $exportedFunctions = $moduleInfo.ExportedFunctions.Keys
        Write-StatusMessage "Exported functions: $($exportedFunctions -join ', ')" "Gray"
        
        $missingFunctions = $RequiredFunctions | Where-Object { $_ -notin $exportedFunctions }
        
        if ($missingFunctions) {
            throw "Missing required functions: $($missingFunctions -join ', ')"
        }
        
        return $true
    }
    catch {
        Write-StatusMessage "Module validation failed for $ModulePath : $($_.Exception.Message)" "Red"
        return $false
    }
}

# Clear any existing modules first
Get-Module | Where-Object { $_.Path -like "*$modulesPath*" } | Remove-Module -Force

# Add before module loading
Write-StatusMessage "Module path: $modulesPath" "Cyan"

# Add before module loading section
Write-StatusMessage "Clearing module cache..." "Cyan"
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
    Write-StatusMessage "Loading module: $module" -Color Cyan
    Write-StatusMessage "Module path: $modulePath" -Color Gray -Verbose
    
    if (Test-Path $modulePath) {
        try {
            # First try to import without -Verbose to check for errors
            $moduleInfo = Import-Module -Name $modulePath -Global -Force -PassThru -ErrorAction Stop -DisableNameChecking
            
            if ($null -eq $moduleInfo) {
                Write-StatusMessage "Module failed to load. Attempting verbose import for debugging..." -Color Yellow
                
                # Try again with verbose output for debugging
                $verbosePreference = 'Continue'
                $moduleInfo = Import-Module -Name $modulePath -Global -Force -PassThru -Verbose -ErrorAction Stop -DisableNameChecking
                $verbosePreference = 'SilentlyContinue'
                
                if ($null -eq $moduleInfo) {
                    throw "Module import returned null after verbose attempt"
                }
            }
            
            # Verify module was loaded
            $loadedModule = Get-Module $module.Replace('.psm1', '') -ErrorAction SilentlyContinue
            if ($null -eq $loadedModule) {
                throw "Module appears to be loaded but Get-Module returns null"
            }
            
            Write-StatusMessage "Module $module loaded successfully ($($loadedModule.ExportedFunctions.Count) functions)" -Color Green
            # Log functions to file only
            Write-StatusMessage "Exported functions: $($loadedModule.ExportedFunctions.Keys -join ', ')" -Color Gray -Verbose
            
        } catch {
            $moduleLoadingSuccess = $false
            Write-StatusMessage "Error loading module $module" -Color Red
            Write-StatusMessage "Error details: $($_.Exception.Message)" -Color Red
            Write-StatusMessage "Stack trace: $($_.ScriptStackTrace)" -Color Red -Verbose
            break
        }
    } else {
        $moduleLoadingSuccess = $false
        Write-StatusMessage "Core module not found: $modulePath" -Color Red
        break
    }
}

# Simplified verification output
if ($moduleLoadingSuccess) {
    Write-StatusMessage "All modules loaded successfully" -Color Green
} else {
    throw "Module loading failed. Check logs for details."
}

# Modified verification section - only write function details to log
Write-StatusMessage "`nVerifying loaded modules:" "Cyan"
$loadedModules = Get-Module | Where-Object { $_.Path -like "*$modulesPath*" }
foreach ($module in $loadedModules) {
    Write-StatusMessage "Module $($module.Name) verified" "Green"
    # Log functions to file only
    $module.ExportedFunctions.Keys | ForEach-Object {
        Write-StatusMessage "  - $_" "Gray" -Verbose
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

Write-StatusMessage "`nAll required modules and functions verified. Continuing with launch...`n" "Green"

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

# Modify process creation for child scripts
function Start-HiddenProcess {
    param(
        [string]$FilePath,
        [string]$ArgumentList,
        [switch]$NoWindow
    )
    
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "powershell.exe"
    $startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$FilePath`" $ArgumentList"
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    
    return $process
}

# Add service support detection
$script:ServiceName = "ServerManagerService"

# Move Start-TrayIcon function definition before Initialize-ServerManager
function Start-TrayIcon {
    $trayIconPath = Join-Path $PSScriptRoot "trayicon.ps1"
    $process = Start-HiddenProcess -FilePath $trayIconPath -ArgumentList "-LogPath `"$($logPaths.TrayIcon)`"" -NoWindow
    
    Write-StatusMessage "Starting tray icon..." -Color Cyan
    
    # Give the process time to start and initialize
    Start-Sleep -Seconds 3
    
    if ($process.HasExited) {
        $log = Get-Content -Path $logPaths.TrayIcon -ErrorAction SilentlyContinue
        throw "Tray icon process failed to start.`nLog:`n$($log -join "`n")"
    }
    
    $Global:ProcessTracker.TrayIcon = $process.Id
    return $process
}

# Add new launcher initialization function
function Initialize-ServerManager {
    param (
        [switch]$AsService
    )
    
    Write-StatusMessage "Initializing Server Manager..." "Cyan"
    
    # Get server manager directory from registry first
    try {
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
        
        if ([string]::IsNullOrWhiteSpace($serverManagerDir)) {
            throw "Server Manager directory path is empty in registry"
        }
        
        # Clean up path
        $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
        Write-StatusMessage "Server Manager Directory: $serverManagerDir" "Cyan"
        
        if (-not (Test-Path $serverManagerDir)) {
            throw "Server Manager directory not found: $serverManagerDir"
        }
    }
    catch {
        throw "Failed to get Server Manager directory: $($_.Exception.Message)"
    }
    
    # Ensure directories exist
    $dirs = @(
        (Join-Path $serverManagerDir "logs"),
        (Join-Path $serverManagerDir "config"),
        (Join-Path $serverManagerDir "temp")
    )
    
    foreach ($dir in $dirs) {
        if (-not (Test-Path $dir)) {
            New-Item -Path $dir -ItemType Directory -Force | Out-Null
        }
    }

    # Kill any existing instances
    Get-Process -Name "powershell" | 
        Where-Object { $_.CommandLine -like "*webserver.ps1*" -or $_.CommandLine -like "*dashboard.ps1*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    # Clear any stale ready flags
    Remove-Item -Path "$env:TEMP\websocket_ready.flag" -ErrorAction SilentlyContinue
    Remove-Item -Path "$env:TEMP\webserver_ready.flag" -ErrorAction SilentlyContinue

    # Start web server with proper verification
    try {
        Write-StatusMessage "Starting web server component..." "Cyan"
        $webServerProcess = Start-WebServer
        Write-StatusMessage "Waiting for web server initialization..." "Cyan"
        
        # Wait for both HTTP and WebSocket servers
        $maxWait = 30
        $waited = 0
        $ready = $false
        
        while (-not $ready -and $waited -lt $maxWait) {
            Start-Sleep -Seconds 1
            $waited++
            
            # Check if process is still running
            if ($webServerProcess.HasExited) {
                throw "Web server process terminated unexpectedly"
            }
            
            # Check ready flags
            $wsReadyFile = Join-Path $env:TEMP "websocket_ready.flag"
            $httpReadyFile = Join-Path $env:TEMP "webserver_ready.flag"
            
            Write-StatusMessage "Checking ready flags... (attempt $waited/$maxWait)" "Cyan" -Verbose
            Write-StatusMessage "WebSocket flag: $(Test-Path $wsReadyFile), HTTP flag: $(Test-Path $httpReadyFile)" "Gray" -Verbose
            
            if ((Test-Path $wsReadyFile) -and (Test-Path $httpReadyFile)) {
                try {
                    $wsConfig = Get-Content $wsReadyFile -Raw | ConvertFrom-Json
                    Write-StatusMessage "WebSocket config loaded: $($wsConfig | ConvertTo-Json)" "Gray" -Verbose
                    
                    if ($wsConfig.status -eq "ready") {
                        # Test actual connection
                        $tcpClient = New-Object System.Net.Sockets.TcpClient
                        try {
                            Write-StatusMessage "Testing connection to port $($wsConfig.port)..." "Gray" -Verbose
                            if ($tcpClient.ConnectAsync("localhost", $wsConfig.port).Wait(2000)) {
                                $ready = $true
                                Write-StatusMessage "Web server initialization complete" "Green"
                                break
                            }
                        }
                        catch {
                            Write-StatusMessage "Connection test failed: $_" "Yellow" -Verbose
                        }
                        finally {
                            $tcpClient.Dispose()
                        }
                    }
                }
                catch {
                    Write-StatusMessage "Error verifying WebSocket: $_" "Yellow" -Verbose
                }
            }
            Write-StatusMessage "Waiting for server initialization... ($waited/$maxWait)" "Cyan"
        }
        
        if (-not $ready) {
            # Collect diagnostic information
            $diagnostics = @{
                ProcessRunning = -not $webServerProcess.HasExited
                ProcessExitCode = if ($webServerProcess.HasExited) { $webServerProcess.ExitCode } else { "N/A" }
                WsReadyExists = Test-Path $wsReadyFile
                HttpReadyExists = Test-Path $httpReadyFile
                WsReadyContent = if (Test-Path $wsReadyFile) { Get-Content $wsReadyFile -Raw } else { "N/A" }
                HttpReadyContent = if (Test-Path $httpReadyFile) { Get-Content $httpReadyFile -Raw } else { "N/A" }
            }
            
            Write-StatusMessage "Initialization diagnostic data: $($diagnostics | ConvertTo-Json)" "Yellow" -Verbose
            throw "Server initialization timed out after $maxWait seconds"
        }

        if ($ready) {
            # Start tray icon first
            $trayProcess = Start-TrayIcon
            Write-StatusMessage "Tray icon started successfully" "Green"
            
            # Show dashboard selection if not running as service
            if (-not $AsService) {
                $dashboardChoice = Show-DashboardDialog
                switch ($dashboardChoice) {
                    "Web" {
                        Start-Process "http://localhost:8080"
                    }
                    "PowerShell" {
                        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\dashboard.ps1`""
                    }
                }
            }
        }

        return $true
    }
    catch {
        Write-StatusMessage "Failed to initialize Server Manager: $_" "Red"
        throw
    }
}

# Add dashboard selection dialog
function Show-DashboardDialog {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Select Dashboard Type"
    $form.Size = New-Object System.Drawing.Size(300,150)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $webButton = New-Object System.Windows.Forms.Button
    $webButton.Location = New-Object System.Drawing.Point(50,20)
    $webButton.Size = New-Object System.Drawing.Size(200,30)
    $webButton.Text = "Web Dashboard"
    $webButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $webButton.Add_Click({ $form.Tag = "Web"; $form.Close() })
    $form.Controls.Add($webButton)

    $psButton = New-Object System.Windows.Forms.Button
    $psButton.Location = New-Object System.Drawing.Point(50,60)
    $psButton.Size = New-Object System.Drawing.Size(200,30)
    $psButton.Text = "PowerShell Dashboard"
    $psButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $psButton.Add_Click({ $form.Tag = "PowerShell"; $form.Close() })
    $form.Controls.Add($psButton)

    $form.ShowDialog() | Out-Null
    return $form.Tag
}

# Add service installation support
function Install-ServerManagerService {
    $servicePath = Join-Path $serverManagerDir "service.ps1"
    $serviceContent = @"
`$PSScriptRoot = Split-Path -Parent `$MyInvocation.MyCommand.Path
`$launcherPath = Join-Path `$PSScriptRoot 'Scripts\launcher.ps1'
& `$launcherPath -AsService
"@
    
    $serviceContent | Set-Content -Path $servicePath -Force
    
    $params = @{
        Name = $script:ServiceName
        BinaryPathName = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$servicePath`""
        DisplayName = "Server Manager Service"
        StartupType = "Automatic"
        Description = "Manages game servers and provides web interface"
    }
    
    New-Service @params
}

# Modify Start-WebServer to be more robust
function Start-WebServer {
    $webserverPath = Join-Path $PSScriptRoot "webserver.ps1"
    
    # Create process with proper configuration
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "powershell.exe"
    $pinfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$webserverPath`""
    $pinfo.UseShellExecute = $false
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
    $pinfo.CreateNoWindow = $false  # Changed to show window for debugging
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $pinfo
    
    # Add enhanced output handling
    $stdoutEvent = Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action {
        param($sender, $eventArgs)
        if ($eventArgs.Data) {
            Write-StatusMessage "WebServer: $($eventArgs.Data)" "Gray"
            # Log to specific file for debugging
            Add-Content -Path (Join-Path $logDir "webserver_debug.log") -Value "OUTPUT: $($eventArgs.Data)"
        }
    }
    
    $stderrEvent = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action {
        param($sender, $eventArgs)
        if ($eventArgs.Data) {
            Write-StatusMessage "WebServer Error: $($eventArgs.Data)" "Red"
            # Log to specific file for debugging
            Add-Content -Path (Join-Path $logDir "webserver_debug.log") -Value "ERROR: $($eventArgs.Data)"
        }
    }
    
    Write-StatusMessage "Starting web server process..." "Cyan"
    
    # Start process with error handling
    try {
        $process.Start() | Out-Null
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        
        Write-StatusMessage "Web server process started with PID: $($process.Id)" "Green"
        
        # Wait a moment for initial startup
        Start-Sleep -Seconds 2
        
        if ($process.HasExited) {
            throw "Web server process terminated immediately"
        }
        
        $Global:ProcessTracker.WebServer = $process.Id
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start web server: $($_.Exception.Message)" "Red"
        throw
    }
}

# Main execution block
try {
    if ($script:IsService) {
        Initialize-ServerManager -AsService
    } else {
        Initialize-ServerManager
    }
    
    # Monitor loop
    while ($true) {
        Start-Sleep -Seconds 5
        
        # Check process health - Change $pid to $processId
        $processes = @($Global:ProcessTracker.WebServer)
        foreach ($processId in $processes) {
            if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                Write-StatusMessage "Process $processId stopped unexpectedly" "Red"
                if ($script:IsService) {
                    Restart-Service -Name $script:ServiceName
                } else {
                    Stop-AllComponents
                    throw "Critical process stopped"
                }
            }
        }
    }
}
catch {
    Write-StatusMessage "Fatal error: $_" "Red"
    Stop-AllComponents
    if (-not $script:IsService) {
        Read-Host "Press Enter to exit"
    }
    exit 1
}

# Modify the launch sequence
try {
    Write-StatusMessage "Initializing Server Manager..." -Color Cyan
    
    # Start web server first and wait for ready state
    $webServerProcess = Start-WebServer
    
    # Only start tray icon after web server is confirmed running
    Start-Sleep -Seconds 2
    $trayProcess = Start-TrayIcon
    
    # Final status message
    Write-StatusMessage "`nServer Manager is running!" -Color Green
    Write-StatusMessage "Web Interface: http://localhost:8080/" -Color Cyan
    Write-StatusMessage "Use the tray icon for management" -Color Cyan
    Write-StatusMessage "Check logs at: $logDir" -Color Gray

    # Silent monitoring loop
    while ($true) {
        Start-Sleep -Milliseconds 500
        try {
            $null = Get-Process -Id $webServerProcess.Id, $trayProcess.Id -ErrorAction Stop
        }
        catch {
            Write-StatusMessage "Component stopped unexpectedly" -Color Red
            Stop-AllComponents
            break
        }
    }
}
catch {
    Write-StatusMessage "Error: $($_.Exception.Message)" -Color Red
    Stop-AllComponents
}
finally {
    if ($script:logWriter) {
        $script:logWriter.Dispose()
    }
    if ($script:logStream) {
        $script:logStream.Dispose()
    }
}

