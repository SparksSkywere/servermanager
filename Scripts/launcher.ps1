param(
    [switch]$AsService
)

# Set strict error handling
$ErrorActionPreference = 'Stop'

# Initial script-scope variable declarations
$script:Paths = $null
$script:ReadyFiles = $null 
$script:Ports = $null
$script:IsService = $AsService -or ([System.Environment]::UserInteractive -eq $false)
$script:ServiceName = "ServerManagerService"

# Global process tracker - add at the top of the script after initial variable declarations
$Global:ProcessTracker = @{
    WebServer = $null
    TrayIcon = $null
    StartTime = $null
    IsRunning = $false
}

# Initialize base paths first - this should only happen once
function Initialize-Configuration {
    try {
        Write-StatusMessage "Initializing configuration..." "Cyan" -LogOnly
        
        # Get base paths from registry
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
        $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
        
        $script:Paths = @{
            Root = $serverManagerDir
            Logs = Join-Path $serverManagerDir "logs"
            Config = Join-Path $serverManagerDir "config"
            Temp = Join-Path $serverManagerDir "temp"
            Scripts = Join-Path $serverManagerDir "Scripts"
            Modules = Join-Path $serverManagerDir "Modules"
        }

        # Create directories if needed
        foreach ($dir in $script:Paths.Values) {
            if (-not (Test-Path $dir)) {
                New-Item -Path $dir -ItemType Directory -Force | Out-Null
            }
        }
        
        $script:ReadyFiles = @{
            WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
            WebServer = Join-Path $script:Paths.Temp "webserver.ready"
        }
        
        $script:Ports = @{
            WebServer = 8080
            WebSocket = 8081
        }

        # Clean any existing ready files
        Get-ChildItem $script:Paths.Temp -Filter "*.ready" | Remove-Item -Force
        
        Write-StatusMessage "Configuration initialized successfully" "Green" -LogOnly
        return $true
    }
    catch {
        Write-StatusMessage "Failed to initialize configuration: $_" "Red"
        return $false
    }
}

# Consolidated process start function
function Start-ManagedProcess {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type,
        [string]$FilePath,
        [string]$ArgumentList,
        [switch]$NoWindow
    )
    
    # Check if process is already running
    if ($Global:ProcessTracker.$Type) {
        $existingProcess = Get-Process -Id $Global:ProcessTracker.$Type -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-StatusMessage "$Type process already running (PID: $($existingProcess.Id))" "Yellow"
            return $existingProcess
        }
    }
    
    Write-StatusMessage "Starting $Type process..." "Cyan"
    
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "powershell.exe"
    $pinfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$FilePath`" $ArgumentList"
    $pinfo.UseShellExecute = $false
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
    $pinfo.CreateNoWindow = $NoWindow
    $pinfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $pinfo
    
    try {
        $null = $process.Start()
        $Global:ProcessTracker.$Type = $process.Id
        Write-PidFile -Type $Type -ProcessId $process.Id
        
        # Register output handlers
        $null = Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action {
            param($sender, $e)
            if ($e.Data) { Write-StatusMessage "${Type}: $($e.Data)" "Gray" -LogOnly }
        }
        
        $null = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action {
            param($sender, $e)
            if ($e.Data) { Write-StatusMessage "$Type Error: $($e.Data)" "Red" -LogOnly }
        }
        
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        
        Write-StatusMessage "$Type process started (PID: $($process.Id))" "Green"
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start $Type process: $_" "Red"
        throw
    }
}

# Replace existing Start-WebServer function with this simplified version
function Start-WebServer {
    try {
        # Remove any existing ready files
        Remove-Item -Path $script:ReadyFiles.WebServer -Force -ErrorAction SilentlyContinue
        
        # Start the web server process
        $webserverPath = Join-Path $script:Paths.Scripts "webserver.ps1"
        $process = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$webserverPath`"" -PassThru -WindowStyle Hidden
        
        Write-StatusMessage "Started web server process (PID: $($process.Id))" "Cyan"
        $Global:ProcessTracker.WebServer = $process.Id
        
        # Wait for initialization
        Wait-WebServerReady
        
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start web server: $_" "Red"
        throw
    }
}

# Replace existing Start-TrayIcon function with this simplified version
function Start-TrayIcon {
    if (-not $Global:ProcessTracker.TrayIcon) {
        $trayIconPath = Join-Path $script:Paths.Scripts "trayicon.ps1"
        return Start-ManagedProcess -Type "TrayIcon" -FilePath $trayIconPath -ArgumentList "-LogPath `"$($logPaths.TrayIcon)`""
    }
    else {
        Write-StatusMessage "Tray icon is already running" "Yellow"
        return Get-Process -Id $Global:ProcessTracker.TrayIcon -ErrorAction SilentlyContinue
    }
}

# Modified Stop-AllComponents to use process tracker
function Stop-AllComponents {
    Write-StatusMessage "Stopping all components..." "Yellow"
    
    # Create a copy of keys to avoid enumeration issues
    $components = @() + $Global:ProcessTracker.Keys
    
    foreach ($component in $components) {
        try {
            $processId = $Global:ProcessTracker[$component]
            if ($processId) {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    Write-StatusMessage "Stopping $component (PID: $processId)" "Yellow"
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                }
            }
            $Global:ProcessTracker[$component] = $null
        }
        catch {
            Write-StatusMessage "Error stopping $component ${_}" "Red"
        }
    }
    
    $Global:ProcessTracker.IsRunning = $false
    Write-StatusMessage "All components stopped" "Green"
}

# New unified ready check function
function Wait-ServerReady {
    param(
        [int]$TimeoutSeconds = 30,
        [switch]$Quiet
    )
    
    $startTime = Get-Date
    $lastMessage = ""
    
    while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($TimeoutSeconds)) {
        if (-not $Quiet) {
            Write-StatusMessage "Checking server status..." "Gray" -Verbose
        }
        
        try {
            if ((Test-ReadyFile -Type "WebServer") -and (Test-ReadyFile -Type "WebSocket")) {
                Write-StatusMessage "Server ready" "Green"
                return $true
            }
            
            # Test actual connection to web server
            $webClient = New-Object System.Net.WebClient
            try {
                $null = $webClient.DownloadString("http://localhost:$($script:Ports.WebServer)/")
                Write-StatusMessage "Web server responding" "Green"
                return $true
            }
            catch {
                if (-not $Quiet) {
                    $message = "Waiting for server... $([int]([TimeSpan]((Get-Date) - $startTime)).TotalSeconds)s"
                    if ($message -ne $lastMessage) {
                        Write-StatusMessage $message "Cyan"
                        $lastMessage = $message
                    }
                }
            }
            finally {
                $webClient.Dispose()
            }
        }
        catch {
            if (-not $Quiet) {
                Write-StatusMessage "Error checking status: $_" "Red" -Verbose
            }
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    return $false
}

# Modified Initialize-ServerManager 
function Initialize-ServerManager {
    param([switch]$AsService)
    
    try {
        Write-StatusMessage "Initializing Server Manager..." "Cyan"
        
        if (-not (Initialize-Configuration)) {
            throw "Failed to initialize configuration"
        }
        
        Write-StatusMessage "Starting web server component..." "Cyan" -LogOnly
        $webServerProcess = Start-WebServer -Wait
        
        if (-not $webServerProcess) {
            throw "Failed to start web server"
        }
        
        Write-StatusMessage "Starting tray icon..." "Cyan" -LogOnly
        $trayProcess = Start-TrayIcon
        
        Write-StatusMessage "`nServer Manager initialized successfully!" "Green"
        Write-StatusMessage "Web Interface available at: http://localhost:$($script:Ports.WebServer)/" "Cyan"
        Write-StatusMessage "System tray icon active for management" "Cyan"
        
        if (-not $AsService) {
            Write-StatusMessage "Console window will be hidden in 3 seconds..." "Yellow"
            Start-Sleep -Seconds 3
            Set-ProcessProperties -HideConsole
        }
        
        return $true
    }
    catch {
        Write-StatusMessage "Failed to initialize Server Manager: $_" "Red"
        throw
    }
}

# Initialize paths before any module calls
try {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
    
    # Define paths structure first
    $script:Paths = @{
        Root = $serverManagerDir
        Logs = Join-Path $serverManagerDir "logs"
        Config = Join-Path $serverManagerDir "config"
        Temp = Join-Path $serverManagerDir "temp"
        Scripts = Join-Path $serverManagerDir "Scripts"
        Modules = Join-Path $serverManagerDir "Modules"
    }

    # Create directories if they don't exist
    foreach($path in $script:Paths.Values) {
        if(-not (Test-Path $path)) {
            New-Item -Path $path -ItemType Directory -Force | Out-Null
        }
    }

    # Initialize ready file paths to match WebSocketServer module
    $script:ReadyFiles = @{
        WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
        WebServer = Join-Path $script:Paths.Temp "webserver.ready"
    }

    # Clear any existing ready files at startup
    Remove-Item -Path $script:ReadyFiles.WebSocket -ErrorAction SilentlyContinue
    Remove-Item -Path $script:ReadyFiles.WebServer -ErrorAction SilentlyContinue
}
catch {
    Write-StatusMessage "Failed to initialize paths from registry: $_" "Red"
    exit 1
}

# Define ports structure
$script:Ports = @{
    WebServer = 8080  # Default web server port
    WebSocket = 8081  # Default WebSocket port
}

$script:IsService = $AsService -or ([System.Environment]::UserInteractive -eq $false)
$ErrorActionPreference = 'Stop'

# Now the log paths will work correctly
$logPaths = @{
    Main = Join-Path $script:Paths.Logs "launcher.log"
    WebServer = Join-Path $script:Paths.Logs "webserver.log"
    TrayIcon = Join-Path $script:Paths.Logs "trayicon.log"
    Updates = Join-Path $script:Paths.Logs "updates.log"
}

# Ensure log directory exists
if (-not (Test-Path $script:Paths.Logs)) {
    New-Item -ItemType Directory -Path $script:Paths.Logs -Force | Out-Null
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
        [switch]$Verbose,
        [switch]$LogOnly
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
    
    # Only write to console if not LogOnly and either not Verbose or $VerbosePreference is Continue
    if (-not $LogOnly -and (-not $Verbose -or $VerbosePreference -eq 'Continue')) {
        Write-Host $Message -ForegroundColor $Color
    }
}

# Replace the trap handler with a Ctrl+C handler
$null = [Console]::TreatControlCAsInput = $true

# Add cleanup on PowerShell exit
$exitScript = {
    Write-StatusMessage "Cleaning up processes..." "Yellow"
    Stop-AllComponents
    Write-StatusMessage "Cleaning up PID files..." "Yellow"
    foreach ($pidFile in $script:PidFiles.Values) {
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    }
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
    "Common.psm1",
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

# Initialize module loading success flag at the start
$moduleLoadingSuccess = $true

# Modify module loading section to ensure WebSocketServer is loaded first
Write-StatusMessage "Loading core modules..." "Cyan" -LogOnly

try {
    # First load WebSocketServer
    $webSocketModule = Join-Path $modulesPath "WebSocketServer.psm1"
    Import-Module $webSocketModule -Force -Global -DisableNameChecking
    $module = Get-Module WebSocketServer -ErrorAction Stop
    Write-StatusMessage "Module info: $($module | ConvertTo-Json)" "Gray" -Verbose
    
    if (-not $module) {
        $moduleLoadingSuccess = $false
        throw "WebSocketServer module failed to load"
    }
    
    # Verify required functions are available
    $requiredWebSocketFunctions = @(
        'Get-WebSocketPaths',
        'Test-WebSocketReady',
        'Set-WebSocketReady'
    )
    
    $missingFunctions = $requiredWebSocketFunctions | Where-Object {
        $fn = $_
        Write-StatusMessage "Checking for function: $fn" "Gray" -Verbose
        -not (Get-Command $fn -ErrorAction SilentlyContinue)
    }
    
    if ($missingFunctions) {
        throw "Missing required WebSocket functions: $($missingFunctions -join ', ')"
    }
    
    Write-StatusMessage "WebSocketServer module loaded successfully" "Green" -LogOnly
    
    # Load remaining modules
    foreach ($module in $coreModules | Where-Object { $_ -ne "WebSocketServer.psm1" }) {
        $modulePath = Join-Path $modulesPath $module
        Write-StatusMessage "Loading module: $module" -Color Cyan -LogOnly
        
        if (Test-Path $modulePath) {
            try {
                $moduleInfo = Import-Module -Name $modulePath -Force -Global -PassThru -ErrorAction Stop -DisableNameChecking -Verbose:$true
                Write-StatusMessage "Module $module loaded successfully" -Color Green -LogOnly
            }
            catch {
                $moduleLoadingSuccess = $false
                Write-StatusMessage "Failed to load module $module : $($_.Exception.Message)" -Color Red
                Write-StatusMessage $_.ScriptStackTrace -Color Red -Verbose
                throw
            }
        }
        else {
            $moduleLoadingSuccess = $false
            Write-StatusMessage "Module not found: $modulePath" -Color Red
            throw
        }
    }

    Write-StatusMessage "All core modules loaded successfully" -Color Green -LogOnly
}
catch {
    $moduleLoadingSuccess = $false
    Write-StatusMessage "Module loading failed: $($_.Exception.Message)" -Color Red
    throw
}

# Verify modules if loading succeeded
if (-not $moduleLoadingSuccess) {
    Write-StatusMessage "Failed to load one or more modules. Check previous messages for details." -Color Red
    throw "Module loading failed. Check previous messages for details."
}

# Initialize WebSocket paths
$webSocketPaths = Get-WebSocketPaths
$script:WebSocketReadyFile = $webSocketPaths.WebSocketReadyFile
$script:WebServerReadyFile = $webSocketPaths.WebServerReadyFile
$script:DefaultWebSocketPort = $webSocketPaths.DefaultWebSocketPort
$script:DefaultWebPort = $webSocketPaths.DefaultWebPort

Write-StatusMessage "All core modules loaded successfully" -Color Green -LogOnly

# Continue with the rest of launcher.ps1

# Simplified verification output
if ($moduleLoadingSuccess) {
    Write-StatusMessage "All modules loaded successfully" -Color Green
} else {
    throw "Module loading failed. Check logs for details."
}

# Modified verification section - only write function details to log
Write-StatusMessage "`nVerifying loaded modules:" "Cyan" -LogOnly
$loadedModules = Get-Module | Where-Object { $_.Path -like "*$modulesPath*" }
foreach ($module in $loadedModules) {
    Write-StatusMessage "Module $($module.Name) verified" "Green" -LogOnly
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
if (-not (Test-Path $script:Paths.Logs)) {
    New-Item -ItemType Directory -Path $script:Paths.Logs -Force | Out-Null
}

# Define log files
$webServerLog = Join-Path $script:Paths.Logs "webserver.log"
$trayIconLog = Join-Path $script:Paths.Logs "trayicon.log"

# Modified Start-HiddenProcess function
function Start-HiddenProcess {
    param(
        [string]$FilePath,
        [string]$ArgumentList,
        [switch]$NoWindow
    )
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = "powershell.exe"
    $process.StartInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$FilePath`" $ArgumentList"
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    
    try {
        $null = $process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        
        # Register event handlers for output
        $null = Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action {
            param($source, $e)
            if ($e.Data) {
                Write-StatusMessage $e.Data "Gray" -Verbose
            }
        }
        
        $null = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action {
            param($source, $e)
            if ($e.Data) {
                Write-StatusMessage "ERROR: $($e.Data)" "Red" -Verbose
            }
        }
        
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start process: $_" "Red"
        throw
    }
}

# Add service support detection
$script:ServiceName = "ServerManagerService"

# Move Start-TrayIcon function definition before Initialize-ServerManager
function Start-TrayIcon {
    $trayIconPath = Join-Path $PSScriptRoot "trayicon.ps1"
    $process = Start-HiddenProcess -FilePath $trayIconPath -ArgumentList "-LogPath `"$($logPaths.TrayIcon)`"" -NoWindow
    Write-PidFile -Type "TrayIcon" -ProcessId $process.Id
    
    Write-StatusMessage "Starting tray icon..." -Color Cyan -LogOnly
    
    # Give the process time to start and initialize
    Start-Sleep -Seconds 3
    
    if ($process.HasExited) {
        $log = Get-Content -Path $logPaths.TrayIcon -ErrorAction SilentlyContinue
        throw "Tray icon process failed to start.`nLog:`n$($log -join "`n")"
    }
    
    $Global:ProcessTracker.TrayIcon = $process.Id
    return $process
}

# Add process name setting and window hiding function
function Set-ProcessProperties {
    param(
        [switch]$HideConsole
    )
    
    if ($HideConsole) {
        Write-StatusMessage "Hiding console window..." "Gray"
        Add-Type -Name Window -Namespace Console -MemberDefinition '
            [DllImport("Kernel32.dll")]
            public static extern IntPtr GetConsoleWindow();
            [DllImport("user32.dll")]
            public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        '
        $consolePtr = [Console.Window]::GetConsoleWindow()
        [void][Console.Window]::ShowWindow($consolePtr, 0)
    }
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
    Remove-Item -Path "$script:ReadyFiles.WebSocket" -ErrorAction SilentlyContinue
    Remove-Item -Path "$script:ReadyFiles.WebServer" -ErrorAction SilentlyContinue

    # Start web server with proper verification
    try {
        Write-StatusMessage "Starting web server component..." "Cyan" -LogOnly
        $webServerProcess = Start-WebServer
        Write-StatusMessage "Waiting for web server initialization..." "Cyan" -LogOnly
        
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
            $wsReadyFile = $script:ReadyFiles.WebSocket
            $httpReadyFile = $script:ReadyFiles.WebServer
            
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
            Write-StatusMessage "Starting components..." "Cyan" -LogOnly
            
            # Start tray icon first
            $trayProcess = Start-TrayIcon
            Write-StatusMessage "Tray icon started successfully" "Green" -LogOnly
            
            # Final initialization messages
            Write-StatusMessage "`nServer Manager initialized successfully!" "Green"
            Write-StatusMessage "Web Interface available at: http://localhost:$script:Ports.WebServer/" "Cyan"
            Write-StatusMessage "System tray icon active for management" "Cyan"
            Write-StatusMessage "Logs directory: $script:Paths.Logs" "Gray"
            
            # Give user time to read messages if not in service mode
            if (-not $AsService) {
                Start-Sleep -Seconds 3
                Write-StatusMessage "Console window will be hidden in 3 seconds..." "Yellow"
                Start-Sleep -Seconds 3
            }
            
            # Hide console window after initialization
            Set-ProcessProperties -HideConsole
            
            return $true
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

# Add after module imports
$webSocketPaths = Get-WebSocketPaths
$script:WebSocketReadyFile = $webSocketPaths.WebSocketReadyFile
$script:WebServerReadyFile = $webSocketPaths.WebServerReadyFile
$script:DefaultWebSocketPort = $webSocketPaths.DefaultWebSocketPort
$script:DefaultWebPort = $webSocketPaths.DefaultWebPort

# Modify Start-WebServer to be more robust
function Start-WebServer {
    $webserverPath = Join-Path $script:Paths.Scripts "webserver.ps1"
    Write-StatusMessage "Starting web server from: $webserverPath" "Cyan" -LogOnly
    
    if (-not (Test-Path $webserverPath)) {
        throw "Web server script not found at: $webserverPath"
    }

    try {
        # Clear any existing ready files
        Remove-Item -Path $script:ReadyFiles.WebSocket -ErrorAction SilentlyContinue
        Remove-Item -Path $script:ReadyFiles.WebServer -ErrorAction SilentlyContinue
        
        $process = Start-Process powershell.exe -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$webserverPath`""
        ) -WindowStyle Hidden -PassThru

        if (-not $process -or $process.HasExited) {
            throw "Failed to start web server process"
        }

        $Global:ProcessTracker.WebServer = $process.Id
        Write-PidFile -Type "WebServer" -ProcessId $process.Id
        Write-StatusMessage "Web server process started (PID: $($process.Id))" "Cyan"

        # Wait for ready state using common module function
        $maxWait = 30
        $waited = 0
        
        while ($waited -lt $maxWait) {
            if ($process.HasExited) {
                throw "Web server process terminated unexpectedly"
            }

            if ((Test-ReadyFile -Type "WebServer") -and (Test-ReadyFile -Type "WebSocket")) {
                Write-StatusMessage "Web server initialization complete" "Green"
                return $process
            }

            Start-Sleep -Seconds 1
            $waited++
            Write-StatusMessage "Waiting for initialization... ($waited/$maxWait)" "Cyan"
        }
        
        throw "Web server failed to initialize within $maxWait seconds"
    }
    catch {
        Write-StatusMessage "Failed to start web server: $_" "Red"
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

# Main execution block
try {
    if ($script:IsService) {
        # Service mode - no console needed
        Set-ProcessProperties -HideConsole
        Initialize-ServerManager -AsService
    } else {
        # Interactive mode - show console during initialization
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
        Write-StatusMessage "Press Enter to exit..." "Red"
        Read-Host
    }
    exit 1
}
finally {
    if ($script:logWriter) {
        $script:logWriter.Dispose()
    }
    if ($script:logStream) {
        $script:logStream.Dispose()
    }
    # Clean up event subscribers
    Get-EventSubscriber | Unregister-Event -Force
}

# Modify the launch sequence
try {
    Write-StatusMessage "Initializing Server Manager..." -Color Cyan
    
    # Start web server first and wait for ready state
    $webServerProcess = Start-WebServer
    
    # Only start tray icon after web server is confirmed running
    Start-Sleep -Seconds 2
    $trayProcess = Start-TrayIcon
    
    # Hide console and set process name
    Set-ProcessProperties

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

# Modify module loading section with enhanced logging
Write-StatusMessage "Loading core modules..." "Cyan" -LogOnly
Write-StatusMessage "Module search path: $modulesPath" "Cyan" -Verbose

# First load and verify WebSocketServer module
try {
    Write-StatusMessage "Attempting to load WebSocketServer module..." "Cyan" -Verbose
    $webSocketModule = Join-Path $modulesPath "WebSocketServer.psm1"
    
    Write-StatusMessage "WebSocketServer module path: $webSocketModule" "Cyan" -Verbose
    if (-not (Test-Path $webSocketModule)) {
        throw "WebSocket module not found at: $webSocketModule"
    }
    
    Import-Module $webSocketModule -Force -Global -DisableNameChecking -Verbose:$true
    $module = Get-Module WebSocketServer -ErrorAction Stop
    Write-StatusMessage "Module object: $($module | ConvertTo-Json)" "Gray" -Verbose
    
    if (-not $module) {
        throw "WebSocketServer module failed to load"
    }
    
    # Verify required functions are available
    $requiredWebSocketFunctions = @(
        'Get-WebSocketPaths',
        'Test-WebSocketReady',
        'Set-WebSocketReady'
    )
    
    $missingFunctions = $requiredWebSocketFunctions | Where-Object {
        $fn = $_
        Write-StatusMessage "Checking for function: $fn" "Gray" -Verbose
        -not (Get-Command $fn -ErrorAction SilentlyContinue)
    }
    
    if ($missingFunctions) {
        throw "Missing required WebSocket functions: $($missingFunctions -join ', ')"
    }
    
    Write-StatusMessage "WebSocketServer module loaded successfully with all required functions" "Green" -LogOnly
    
    # Get WebSocket paths with error checking
    try {
        $webSocketPaths = Get-WebSocketPaths
        Write-StatusMessage "WebSocket paths retrieved: $($webSocketPaths | ConvertTo-Json)" "Gray" -Verbose
        
        if (-not $webSocketPaths) {
            throw "Get-WebSocketPaths returned null"
        }
    }
    catch {
        Write-StatusMessage "Error getting WebSocket paths: $($_.Exception.Message)" "Red"
        Write-StatusMessage "Stack trace: $($_.ScriptStackTrace)" "Red" -Verbose
        throw
    }
    
    # Store paths in script scope with validation
    foreach ($key in @('WebSocketReadyFile', 'WebServerReadyFile', 'DefaultWebSocketPort', 'DefaultWebPort')) {
        if (-not $webSocketPaths.ContainsKey($key)) {
            throw "Missing required path: $key"
        }
        Set-Variable -Name $key -Value $webSocketPaths[$key] -Scope Script
        Write-StatusMessage "Set $key to $($webSocketPaths[$key])" "Gray" -Verbose
    }
    
    Write-StatusMessage "WebSocket configuration initialized successfully" "Green" -LogOnly
}
catch {
    Write-StatusMessage "Failed to initialize WebSocket module: $($_.Exception.Message)" "Red"
    Write-StatusMessage "Stack trace: $($_.ScriptStackTrace)" "Red" -Verbose
    throw
}

# Load remaining modules with enhanced logging
$moduleLoadingSuccess = $true
foreach ($module in $coreModules | Where-Object { $_ -ne "WebSocketServer.psm1" }) {
    $modulePath = Join-Path $modulesPath $module
    Write-StatusMessage "Loading module: $module" "Cyan" -LogOnly
    Write-StatusMessage "Full module path: $modulePath" "Gray" -Verbose
    
    if (Test-Path $modulePath) {
        try {
            Write-StatusMessage "Importing module $module..." "Gray" -Verbose
            $moduleInfo = Import-Module -Name $modulePath -Force -Global -PassThru -ErrorAction Stop -DisableNameChecking -Verbose:$true
            
            if ($null -eq $moduleInfo) {
                throw "Module import returned null"
            }
            
            Write-StatusMessage "Module info: $($moduleInfo | Select-Object Name, Version, ModuleType | ConvertTo-Json)" "Gray" -Verbose
            
            # Verify module was loaded
            $loadedModule = Get-Module $module.Replace('.psm1', '') -ErrorAction SilentlyContinue
            if ($null -eq $loadedModule) {
                throw "Module appears to be loaded but Get-Module returns null"
            }
            
            # Verify required functions
            $requiredFunctions = $Global:requiredFunctions[$module]
            if ($requiredFunctions) {
                Write-StatusMessage "Checking required functions for $module" "Gray" -Verbose
                $missingFunctions = $requiredFunctions | Where-Object {
                    $fn = $_
                    Write-StatusMessage "Checking function: $fn" "Gray" -Verbose
                    -not (Get-Command $fn -ErrorAction SilentlyContinue)
                }
                
                if ($missingFunctions) {
                    throw "Missing required functions: $($missingFunctions -join ', ')"
                }
            }
            
            Write-StatusMessage "Module $module loaded successfully ($($loadedModule.ExportedFunctions.Count) functions)" "Green" -LogOnly
        }
        catch {
            $moduleLoadingSuccess = $false
            Write-StatusMessage "Error loading module $module" "Red"
            Write-StatusMessage "Error details: $($_.Exception.Message)" "Red"
            Write-StatusMessage "Stack trace: $($_.ScriptStackTrace)" "Red" -Verbose
            break
        }
    }
    else {
        $moduleLoadingSuccess = $false
        Write-StatusMessage "Module not found: $modulePath" "Red"
        break
    }
}

if (-not $moduleLoadingSuccess) {
    Write-StatusMessage "Dumping loaded modules for debugging:" "Yellow" -Verbose
    Get-Module | Format-Table -AutoSize | Out-String | Write-StatusMessage -Color Yellow -Verbose
    throw "Module loading failed. See above messages and logs for details."
}

# Modify the Start-WebServer function to be more thorough:
function Start-WebServer {
    $webserverPath = Join-Path $PSScriptRoot "webserver.ps1"
    
    # Add URL reservation check
    try {
        Write-StatusMessage "Checking URL reservations..." "Cyan"
        $null = netsh http show urlacl url=http://+:$script:Ports.WebServer/
    }
    catch {
        Write-StatusMessage "Adding URL reservation..." "Yellow"
        $null = netsh http add urlacl url=http://+:$script:Ports.WebServer/ user=Everyone
    }
    
    if (-not (Test-Path $webserverPath)) {
        throw "Web server script not found at: $webserverPath"
    }
    
    # Create process with proper configuration
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "powershell.exe"
    $pinfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$webserverPath`"" 
    $pinfo.UseShellExecute = $false
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
    $pinfo.CreateNoWindow = $false  # Show window for debugging
    $pinfo.WorkingDirectory = $PSScriptRoot
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $pinfo
    
    Write-StatusMessage "Starting web server process..." "Cyan"
    
    try {
        $null = $process.Start()
        $Global:ProcessTracker.WebServer = $process.Id
        Write-PidFile -Type "WebServer" -ProcessId $process.Id
        
        Write-StatusMessage "Waiting for servers to be ready..." "Cyan"
        
        # Wait for ready files
        $maxWait = 30
        $waited = 0
        $ready = $false
        
        while (-not $ready -and $waited -lt $maxWait) {
            if ($process.HasExited) {
                throw "Web server process terminated unexpectedly"
            }
            
            Write-StatusMessage "Checking ready flags... (attempt $($waited + 1)/$maxWait)" "Cyan"
            Write-StatusMessage "Looking for files:" "Gray" -Verbose
            Write-StatusMessage "WebSocket: $script:ReadyFiles.WebSocket" "Gray" -Verbose
            Write-StatusMessage "Web Server: $script:ReadyFiles.WebServer" "Gray" -Verbose
            
            if ((Test-Path $script:ReadyFiles.WebSocket) -and (Test-Path $script:ReadyFiles.WebServer)) {
                try {
                    $wsContent = Get-Content $script:ReadyFiles.WebSocket -Raw
                    $webContent = Get-Content $script:ReadyFiles.WebServer -Raw
                    Write-StatusMessage "WebSocket content: $wsContent" "Gray" -Verbose
                    Write-StatusMessage "Web Server content: $webContent" "Gray" -Verbose
                    
                    $wsConfig = $wsContent | ConvertFrom-Json
                    $webConfig = $webContent | ConvertFrom-Json
                    
                    if ($wsConfig.status -eq "ready" -and $webConfig.status -eq "ready") {
                        Write-StatusMessage "Both ready files indicate ready status" "Green"
                        $ready = $true
                        break
                    }
                }
                catch {
                    Write-StatusMessage "Error reading ready files: $_" "Red" -Verbose
                }
            }
            
            Start-Sleep -Seconds 1
            $waited++
        }
        
        if (-not $ready) {
            throw "Servers failed to initialize within $maxWait seconds"
        }

        Write-StatusMessage "Server initialization complete" "Green"
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start web server: $_" "Red"
        if ($process -and -not $process.HasExited) {
            $process.Kill()
        }
        throw
    }
}

# Modify the Initialize-ServerManager function to be more sequential:
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
    Remove-Item -Path "$script:ReadyFiles.WebSocket" -ErrorAction SilentlyContinue
    Remove-Item -Path "$script:ReadyFiles.WebServer" -ErrorAction SilentlyContinue

    # Start web server with proper verification
    try {
        Write-StatusMessage "Starting web server component..." "Cyan" -LogOnly
        $webServerProcess = Start-WebServer
        Write-StatusMessage "Waiting for web server initialization..." "Cyan" -LogOnly
        
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
            $wsReadyFile = $script:ReadyFiles.WebSocket
            $httpReadyFile = $script:ReadyFiles.WebServer
            
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
            Write-StatusMessage "Starting components..." "Cyan" -LogOnly
            
            # Start tray icon first
            $trayProcess = Start-TrayIcon
            Write-StatusMessage "Tray icon started successfully" "Green" -LogOnly
            
            # Final initialization messages
            Write-StatusMessage "`nServer Manager initialized successfully!" "Green"
            Write-StatusMessage "Web Interface available at: http://localhost:$script:Ports.WebServer/" "Cyan"
            Write-StatusMessage "System tray icon active for management" "Cyan"
            Write-StatusMessage "Logs directory: $script:Paths.Logs" "Gray"
            
            # Give user time to read messages if not in service mode
            if (-not $AsService) {
                Start-Sleep -Seconds 3
                Write-StatusMessage "Console window will be hidden in 3 seconds..." "Yellow"
                Start-Sleep -Seconds 3
            }
            
            # Hide console window after initialization
            Set-ProcessProperties -HideConsole
            
            return $true
        }

        return $true
    }
    catch {
        Write-StatusMessage "Failed to initialize Server Manager: $_" "Red"
        throw
    }
}

# Get registry paths at startup
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir

# Define paths using server manager directory
$script:TempPath = Join-Path $serverManagerDir "temp"
$script:WebServerReadyFile = Join-Path $script:TempPath "webserver.ready"
$script:WebSocketReadyFile = Join-Path $script:TempPath "websocket.ready"

# Modify the server ready check function
function Test-ServerReady {
    param (
        [int]$timeout = 30
    )
    
    $startTime = Get-Date
    while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($timeout)) {
        Write-StatusMessage "Checking server status..." "Cyan" -Verbose
        
        # First check ready files
        if ((Test-Path $script:ReadyFiles.WebSocket) -and (Test-Path $script:ReadyFiles.WebServer)) {
            try {
                $wsContent = Get-Content $script:ReadyFiles.WebSocket -Raw | ConvertFrom-Json
                $webContent = Get-Content $script:ReadyFiles.WebServer -Raw | ConvertFrom-Json
                
                Write-StatusMessage "Ready file contents:" "Gray" -Verbose
                Write-StatusMessage "WebSocket: $($wsContent | ConvertTo-Json)" "Gray" -Verbose
                Write-StatusMessage "WebServer: $($webContent | ConvertTo-Json)" "Gray" -Verbose
                
                # Check both services report ready
                if ($wsContent.status -eq "ready" -and $webContent.status -eq "ready") {
                    # Test WebSocket port
                    $tcpClient = New-Object System.Net.Sockets.TcpClient
                    try {
                        Write-StatusMessage "Testing WebSocket port $($wsContent.port)..." "Gray" -Verbose
                        if ($tcpClient.ConnectAsync("127.0.0.1", $wsContent.port).Wait(2000)) {
                            Write-StatusMessage "WebSocket port responding" "Green" -Verbose
                            $tcpClient.Close()
                            
                            # Test Web port
                            $tcpClient = New-Object System.Net.Sockets.TcpClient
                            Write-StatusMessage "Testing Web port $($webContent.port)..." "Gray" -Verbose
                            if ($tcpClient.ConnectAsync("127.0.0.1", $webContent.port).Wait(2000)) {
                                Write-StatusMessage "Web port responding" "Green" -Verbose
                                return $true
                            }
                        }
                    }
                    catch {
                        Write-StatusMessage "TCP connection failed: $_" "Yellow" -Verbose
                    }
                    finally {
                        if ($tcpClient) { $tcpClient.Close() }
                    }
                }
            }
            catch {
                Write-StatusMessage "Error checking status: $_" "Yellow" -Verbose
            }
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    Write-StatusMessage "Server failed to respond within $timeout seconds" "Red"
    return $false
}

# Modify Initialize-ServerManager to include proper ready check
function Initialize-ServerManager {
    param([switch]$AsService)
    
    Write-StatusMessage "Initializing Server Manager..." "Cyan"
    
    try {
        Write-StatusMessage "Starting web server component..." "Cyan" -LogOnly
        $webServerProcess = Start-WebServer
        
        Write-StatusMessage "Waiting for server initialization..." "Cyan" -LogOnly
        # Give the server a moment to bind to ports
        Start-Sleep -Seconds 2
        
        $ready = Test-ServerReady -timeout 30
        if ($ready) {
            Write-StatusMessage "Starting components..." "Cyan" -LogOnly
            
            # Start tray icon
            $trayProcess = Start-TrayIcon
            Write-StatusMessage "Tray icon started successfully" "Green" -LogOnly
            
            Write-StatusMessage "`nServer Manager initialized successfully!" "Green"
            Write-StatusMessage "Web Interface available at: http://localhost:$($script:Ports.WebServer)/" "Cyan"
            Write-StatusMessage "System tray icon active for management" "Cyan"
            Write-StatusMessage "Logs directory: $script:Paths.Logs" "Gray"
            
            if (-not $AsService) {
                Start-Sleep -Seconds 3
                Write-StatusMessage "Console window will be hidden in 3 seconds..." "Yellow"
                Start-Sleep -Seconds 3
                Set-ProcessProperties -HideConsole
            }
            
            return $true
        }
        else {
            # Collect additional diagnostic information
            $diagnostics = @{
                ProcessInfo = Get-Process -Id $webServerProcess.Id | Select-Object *
                Ports = @{
                    WebServer = $script:Ports.WebServer
                    WebSocket = $script:Ports.WebSocket
                }
                NetstatOutput = netstat -ano | Where-Object { $_ -match ":$($script:Ports.WebServer)|:$($script:Ports.WebSocket)" }
                ReadyFiles = @{
                    WebSocket = if (Test-Path $script:ReadyFiles.WebSocket) { 
                        Get-Content $script:ReadyFiles.WebSocket -Raw 
                    } else { "File not found" }
                    WebServer = if (Test-Path $script:ReadyFiles.WebServer) { 
                        Get-Content $script:ReadyFiles.WebServer -Raw 
                    } else { "File not found" }
                }
            }
            
            Write-StatusMessage "Initialization failed. Diagnostic data:`n$($diagnostics | ConvertTo-Json -Depth 5)" "Red" -Verbose
            throw "Server initialization timed out - services not responding on required ports"
        }
    }
    catch {
        Write-StatusMessage "Failed to initialize Server Manager: $_" "Red"
        throw
    }
}

# Verify registry paths at startup
Write-StatusMessage "Verifying registry configuration..." "Cyan"
try {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
    
    Write-StatusMessage "Server Manager directory: $serverManagerDir" "Gray"
    Write-StatusMessage "Ready file paths:" "Gray"
    Write-StatusMessage "WebSocket: $($script:ReadyFiles.WebSocket)" "Gray"
    Write-StatusMessage "WebServer: $($script:ReadyFiles.WebServer)" "Gray"
    
    # Verify paths exist
    if (-not (Test-Path $serverManagerDir)) {
        throw "Server Manager directory not found: $serverManagerDir"
    }
}
catch {
    Write-StatusMessage "Registry configuration error: $_" "Red"
    exit 1
}

# Add PID tracking system after paths initialization
$script:PidFiles = @{
    Launcher = Join-Path $script:Paths.Temp "launcher.pid"
    WebServer = Join-Path $script:Paths.Temp "webserver.pid"
    TrayIcon = Join-Path $script:Paths.Temp "trayicon.pid"
    WebSocket = Join-Path $script:Paths.Temp "websocket.pid"
}

# Write launcher PID file at startup
Write-PidFile -Type "Launcher" -ProcessId $PID

# Replace the module loading section with this improved version
Write-StatusMessage "Loading core modules..." "Cyan" -LogOnly
Write-StatusMessage "Module search path: $modulesPath" "Cyan" -LogOnly

# Function to capture and redirect verbose output
function Import-ModuleWithLogging {
    param(
        [string]$ModulePath,
        [string]$ModuleName
    )
    
    try {
        # Temporarily redirect verbose output to variable
        $verbose = $VerbosePreference
        $VerbosePreference = 'SilentlyContinue'
        
        # Import module and capture all output
        $output = Import-Module -Name $ModulePath -Force -Global -PassThru -Verbose 4>&1 3>&1 2>&1
        
        # Process captured output
        $output | ForEach-Object {
            $message = $_.ToString()
            Write-StatusMessage $message "Gray" -LogOnly -Verbose
        }
        
        # Verify module loaded
        $loadedModule = Get-Module $ModuleName -ErrorAction Stop
        if ($loadedModule) {
            Write-StatusMessage "Module $ModuleName loaded successfully" "Green" -LogOnly
            
            # Log exported functions
            $loadedModule.ExportedFunctions.Keys | ForEach-Object {
                Write-StatusMessage "Exported function: $_" "Gray" -LogOnly -Verbose
            }
            
            return $true
        }
        throw "Module did not load properly"
    }
    catch {
        Write-StatusMessage "Failed to load module $ModuleName : $_" "Red" -LogOnly
        return $false
    }
    finally {
        $VerbosePreference = $verbose
    }
}

# Clear existing modules
Write-StatusMessage "Clearing module cache..." "Cyan" -LogOnly
Get-Module | Where-Object { $_.Path -like "*$modulesPath*" } | Remove-Module -Force -ErrorAction SilentlyContinue
Remove-Module Network, WebSocketServer, ServerManager -ErrorAction SilentlyContinue

# Load modules with suppressed console output
$moduleLoadingSuccess = $true
foreach ($module in $coreModules) {
    $modulePath = Join-Path $modulesPath $module
    $moduleName = [System.IO.Path]::GetFileNameWithoutExtension($module)
    
    if (-not (Test-Path $modulePath)) {
        Write-StatusMessage "Module not found: $modulePath" "Red"
        $moduleLoadingSuccess = $false
        break
    }
    
    if (-not (Import-ModuleWithLogging -ModulePath $modulePath -ModuleName $moduleName)) {
        $moduleLoadingSuccess = $false
        break
    }
}

if ($moduleLoadingSuccess) {
    Write-StatusMessage "All modules loaded successfully" "Green"
} else {
    throw "Module loading failed. Check logs for details."
}