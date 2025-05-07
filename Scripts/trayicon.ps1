# Parameters should be defined first
param(
    [string]$LogPath
)

# Load required assemblies at the very beginning
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Force STA threading right at the start - this is critical for WinForms UI
if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
    try {
        $scriptPath = $MyInvocation.MyCommand.Path
        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -STA -File `"$scriptPath`"" -WindowStyle Hidden
        exit
    }
    catch {
        # If restart fails, we'll continue but UI might have issues
        Write-Host "Failed to restart in STA mode: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Initialize logging first to capture any startup errors
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    try {
        New-Item -Path $logDir -ItemType Directory -Force | Out-Null
    } catch {
        # If we can't create the log directory, fall back to temp
        $logDir = $env:TEMP
    }
}
$logFile = if ($LogPath) { $LogPath } else { Join-Path $logDir "trayicon.log" }

function Write-TrayLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [$Level] - $Message" | Add-Content -Path $logFile -ErrorAction Stop
        
        # Only show errors and debug messages in console if debug mode
        if (($null -ne $script:DebugMode -and $script:DebugMode) -or $Level -eq "ERROR") {
            Write-Host "$timestamp [$Level] - $Message" -ForegroundColor $(if ($Level -eq "ERROR") { "Red" } else { "Cyan" })
        }
    }
    catch {
        # Last resort logging to the Application event log
        try {
            $eventLogSource = "ServerManager"
            if (-not [System.Diagnostics.EventLog]::SourceExists($eventLogSource)) {
                [System.Diagnostics.EventLog]::CreateEventSource($eventLogSource, "Application")
            }
            [System.Diagnostics.EventLog]::WriteEntry($eventLogSource, $Message, [System.Diagnostics.EventLogEntryType]::Information, 1001)
        }
        catch {
            # If all else fails, try writing to console
            Write-Host "$Message" -ForegroundColor Red
        }
    }
}

Write-TrayLog "Tray icon script starting..." -Level INFO

# Script-scope variables initialization
$script:DebugMode = $false
$script:webSocketClient = $null
$script:connectionTimer = $null
$script:wsUri = "ws://localhost:8081/ws"
$script:connectionAttempts = 0
$script:maxConnectionRetries = 5
$script:serverRunning = $false
$script:serverStatus = "Unknown"
$script:lastConnectionCheck = [DateTime]::MinValue
$script:connectionCheckInterval = 30 # seconds
$script:trayIcon = $null
$script:assemblyLoadFailed = $false
$script:appContext = $null  # Store application context

# Check .NET Framework version
try {
    $dotNetVersion = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full").Release
    if ($dotNetVersion -lt 394802) { # This is .NET Framework 4.6.2
        Write-TrayLog "Warning: .NET Framework version may be too old for proper operation. Installed: $dotNetVersion" -Level WARN
    }
}
catch {
    Write-TrayLog "Could not determine .NET Framework version: $($_.Exception.Message)" -Level WARN
}

# Pre-load required assemblies with error handling
function Load-RequiredAssemblies {
    try {
        # Try to load System.Windows.Forms first
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        Write-TrayLog "System.Windows.Forms loaded successfully" -Level DEBUG
        
        # Try to load System.Drawing
        Add-Type -AssemblyName System.Drawing -ErrorAction Stop
        Write-TrayLog "System.Drawing loaded successfully" -Level DEBUG
        
        # These are optional but useful
        try { Add-Type -AssemblyName System.Net.WebSockets -ErrorAction SilentlyContinue } catch { }
        try { Add-Type -AssemblyName System.Threading -ErrorAction SilentlyContinue } catch { }
        
        return $true
    }
    catch {
        Write-TrayLog "Failed to load required assemblies: $($_.Exception.Message)" -Level ERROR
        
        # More detailed error diagnostics
        try {
            $frameworkDir = [System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
            Write-TrayLog "Runtime directory: $frameworkDir" -Level DEBUG
            
            $assemblyList = [System.AppDomain]::CurrentDomain.GetAssemblies() | 
                Select-Object -Property FullName, Location |
                Format-Table -AutoSize | Out-String -Width 120
            
            Write-TrayLog "Currently loaded assemblies: $assemblyList" -Level DEBUG
        }
        catch {
            Write-TrayLog "Error during assembly diagnostics: $($_.Exception.Message)" -Level ERROR
        }
        
        return $false
    }
}

# Try to hide console window if assemblies load correctly
function Hide-ConsoleWindow {
    try {
        # Define the console window methods for hiding
        Add-Type -Name Window -Namespace Console -MemberDefinition '
            [DllImport("Kernel32.dll")]
            public static extern IntPtr GetConsoleWindow();
            [DllImport("user32.dll")]
            public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        ' -ErrorAction Stop
        
        $consolePtr = [Console.Window]::GetConsoleWindow()
        [void][Console.Window]::ShowWindow($consolePtr, 0)
        
        # Try to set window style but catch if not supported in this PowerShell host
        try {
            if ($host.UI.RawUI.PSObject.Properties.Name -contains "WindowStyle") {
                $host.UI.RawUI.WindowStyle = 'Hidden'
            }
        } catch {
            Write-TrayLog "WindowStyle property not available in this PowerShell host" -Level DEBUG
        }
        
        Write-TrayLog "Console window hidden successfully" -Level DEBUG
        return $true
    }
    catch {
        Write-TrayLog "Failed to hide console window: $($_.Exception.Message)" -Level WARN
        return $false
    }
}

# Helper function to get registry settings with fallback values
function Get-RegistrySettings {
    try {
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        if (-not (Test-Path $registryPath)) {
            Write-TrayLog "Registry path not found: $registryPath" -Level ERROR
            return @{ ServerManagerDir = $PSScriptRoot; IconPath = $null }
        }
        
        $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
        if (-not $serverManagerDir) {
            Write-TrayLog "ServerManagerDir registry value is empty" -Level ERROR
            $serverManagerDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
        }
        
        $iconPath = Join-Path $serverManagerDir "icons\servermanager.ico"
        
        return @{ 
            ServerManagerDir = $serverManagerDir
            IconPath = $iconPath
        }
    }
    catch {
        Write-TrayLog "Error reading registry settings: $($_.Exception.Message)" -Level ERROR
        return @{ 
            ServerManagerDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
            IconPath = $null
        }
    }
}

# Helper function to check server connection
function Test-ServerConnection {
    param([switch]$Silent)
    
    if (-not $Silent) {
        Write-TrayLog "Checking server connection..." -Level DEBUG
    }
    
    # Define the ports to check
    $webServerPort = 8080
    $webSocketPort = 8081
    $serverIsRunning = $false
    $limitedConnection = $false
    $connectionDetails = ""
    
    # Check for WebSocket ready file first to get correct ports
    try {
        $tempDir = Join-Path $settings.ServerManagerDir "temp"
        $wsReadyFile = Join-Path $tempDir "websocket.ready"
        $webReadyFile = Join-Path $tempDir "webserver.ready"
        
        # If WebSocket ready file exists, get the actual port
        if (Test-Path $wsReadyFile) {
            try {
                $wsConfig = Get-Content $wsReadyFile -Raw | ConvertFrom-Json
                if ($wsConfig.port) {
                    $webSocketPort = $wsConfig.port
                    if (-not $Silent) {
                        Write-TrayLog "WebSocket ready file found, using port: $webSocketPort" -Level DEBUG
                    }
                }
            }
            catch {
                if (-not $Silent) {
                    Write-TrayLog "Failed to parse WebSocket ready file: $($_.Exception.Message)" -Level DEBUG
                }
            }
        }
        
        # If web server ready file exists, get the actual port
        if (Test-Path $webReadyFile) {
            try {
                $webConfig = Get-Content $webReadyFile -Raw | ConvertFrom-Json
                if ($webConfig.port) {
                    $webServerPort = $webConfig.port
                    if (-not $Silent) {
                        Write-TrayLog "Web server ready file found, using port: $webServerPort" -Level DEBUG
                    }
                }
            }
            catch {
                if (-not $Silent) {
                    Write-TrayLog "Failed to parse web server ready file: $($_.Exception.Message)" -Level DEBUG
                }
            }
        }
    }
    catch {
        if (-not $Silent) {
            Write-TrayLog "Error checking ready files: $($_.Exception.Message)" -Level DEBUG
        }
    }
    
    # Try the TCP connection approach first as it's more reliable
    try {
        # Try WebSocket port first (usually more reliable)
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        try {
            # Use BeginConnect with a shorter timeout (1 second)
            $connectionResult = $tcpClient.BeginConnect("localhost", $webSocketPort, $null, $null)
            $wsSuccess = $connectionResult.AsyncWaitHandle.WaitOne(1000, $false)
            
            if ($wsSuccess) {
                try {
                    $tcpClient.EndConnect($connectionResult)
                    $serverIsRunning = $true
                    $limitedConnection = $true
                    $connectionDetails = "WebSocket Connection OK"
                    
                    if (-not $Silent) {
                        Write-TrayLog "WebSocket port $webSocketPort is accessible" -Level DEBUG
                    }
                }
                catch {
                    if (-not $Silent) {
                        Write-TrayLog "WebSocket connection attempt failed: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
        }
        finally {
            $tcpClient.Close()
        }
        
        # Now try HTTP port 
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        try {
            $connectionResult = $tcpClient.BeginConnect("localhost", $webServerPort, $null, $null)
            $httpSuccess = $connectionResult.AsyncWaitHandle.WaitOne(1000, $false)
            
            if ($httpSuccess) {
                try {
                    $tcpClient.EndConnect($connectionResult)
                    $serverIsRunning = $true
                    
                    if ($limitedConnection) {
                        # Both WebSocket and HTTP ports are accessible
                        $connectionDetails = "HTTP + WebSocket OK"
                        $limitedConnection = $false
                    } else {
                        # Only HTTP port is accessible
                        $connectionDetails = "HTTP Connection OK"
                    }
                    
                    if (-not $Silent) {
                        Write-TrayLog "HTTP port $webServerPort is accessible" -Level DEBUG
                    }
                }
                catch {
                    if (-not $Silent) {
                        Write-TrayLog "HTTP connection attempt failed: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
        }
        finally {
            $tcpClient.Close()
        }
    }
    catch {
        if (-not $Silent) {
            Write-TrayLog "TCP connection check failed: $($_.Exception.Message)" -Level DEBUG
        }
        # Continue to HTTP request check
    }
    
    # If TCP checks didn't succeed, try the HTTP request with stricter timeout
    if (-not $serverIsRunning) {
        try {
            # Don't use WebClient as it doesn't have good timeout control
            # Use HttpWebRequest with a very short timeout
            $url = "http://localhost:$webServerPort/health"
            $request = [System.Net.HttpWebRequest]::Create($url)
            $request.Timeout = 1000  # 1 second timeout
            $request.ReadWriteTimeout = 1000
            $request.Method = "GET"
            
            try {
                # Get response with timeout protection
                $response = $request.GetResponse()
                
                try {
                    $stream = $response.GetResponseStream()
                    $reader = New-Object System.IO.StreamReader($stream)
                    $content = $reader.ReadToEnd()
                    
                    if ($content -match '"status":"ok"') {
                        $serverIsRunning = $true
                        $connectionDetails = "HTTP API OK"
                        
                        if (-not $Silent) {
                            Write-TrayLog "HTTP health check successful" -Level DEBUG
                        }
                    }
                }
                finally {
                    if ($reader) { $reader.Close() }
                    if ($response) { $response.Close() }
                }
            }
            catch [System.Net.WebException] {
                if (-not $Silent) {
                    Write-TrayLog "Web request failed: $($_.Exception.Message)" -Level DEBUG
                }
                # Continue to the next check
            }
        }
        catch {
            if (-not $Silent) {
                Write-TrayLog "HTTP health check failed: $($_.Exception.Message)" -Level DEBUG
            }
            # Continue to the next check
        }
    }
    
    # Final check: Look for specific server processes as a last resort
    if (-not $serverIsRunning) {
        try {
            # Check for processes with PIDs from PID files
            $pidFileHttp = Join-Path $tempDir "webserver.pid"
            $pidFileWs = Join-Path $tempDir "websocket.pid" 
            
            $httpPid = $null
            $wsPid = $null
            
            if (Test-Path $pidFileHttp) {
                try {
                    $pidContent = Get-Content $pidFileHttp -Raw | ConvertFrom-Json
                    $httpPid = $pidContent.ProcessId
                }
                catch {
                    if (-not $Silent) {
                        Write-TrayLog "Failed to read HTTP PID file: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
            
            if (Test-Path $pidFileWs) {
                try {
                    $pidContent = Get-Content $pidFileWs -Raw | ConvertFrom-Json
                    $wsPid = $pidContent.ProcessId
                }
                catch {
                    if (-not $Silent) {
                        Write-TrayLog "Failed to read WebSocket PID file: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
            
            # Check if processes are running
            $httpRunning = $false
            $wsRunning = $false
            
            if ($httpPid) {
                try {
                    $process = Get-Process -Id $httpPid -ErrorAction SilentlyContinue
                    if ($process -and -not $process.HasExited) {
                        $httpRunning = $true
                    }
                }
                catch {
                    # Process not found, ignore error
                }
            }
            
            if ($wsPid) {
                try {
                    $process = Get-Process -Id $wsPid -ErrorAction SilentlyContinue
                    if ($process -and -not $process.HasExited) {
                        $wsRunning = $true
                    }
                }
                catch {
                    # Process not found, ignore error
                }
            }
            
            # If any of the processes are running, mark as running
            if ($httpRunning -or $wsRunning) {
                $serverIsRunning = $true
                $limitedConnection = $true
                
                $connectionDetails = if ($httpRunning -and $wsRunning) {
                    "Processes Running (Both)"
                } elseif ($httpRunning) {
                    "HTTP Process Running"
                } else {
                    "WebSocket Process Running"
                }
                
                if (-not $Silent) {
                    Write-TrayLog "Server processes found running: HTTP=$httpRunning, WebSocket=$wsRunning" -Level DEBUG
                }
            }
        }
        catch {
            if (-not $Silent) {
                Write-TrayLog "Process check failed: $($_.Exception.Message)" -Level DEBUG
            }
        }
    }
    
    # Update status based on findings
    if ($serverIsRunning) {
        if ($limitedConnection) {
            Update-ServerStatus -Status "Running (Limited) - $connectionDetails" -IsConnected $true
        } else {
            Update-ServerStatus -Status "Running - $connectionDetails" -IsConnected $true
        }
        return $true
    } else {
        Update-ServerStatus -Status "Not Running (Connected: False)" -IsConnected $false
        return $false
    }
}

# Define the TrayIconApplicationContext class using a proper inline C# class that compiles correctly
Add-Type -TypeDefinition @"
using System;
using System.Windows.Forms;

public class TrayIconApplicationContext : ApplicationContext
{
    private NotifyIcon trayIcon;
    
    public TrayIconApplicationContext(NotifyIcon icon)
    {
        this.trayIcon = icon;
    }
    
    protected override void Dispose(bool disposing)
    {
        if (disposing && trayIcon != null)
        {
            trayIcon.Visible = false;
            trayIcon.Dispose();
        }
        
        base.Dispose(disposing);
    }
    
    public new void ExitThread()
    {
        Application.ExitThread();
    }
}
"@ -ReferencedAssemblies System.Windows.Forms

# MAIN SCRIPT EXECUTION
try {
    Write-TrayLog "Starting tray icon initialization..." -Level DEBUG
    
    # First try to load required assemblies
    if (-not (Load-RequiredAssemblies)) {
        $script:assemblyLoadFailed = $true
        throw "Required assemblies could not be loaded. Tray icon cannot initialize."
    }
    
    # Hide console window as early as possible
    Hide-ConsoleWindow
    
    # Configure PowerShell window
    $host.UI.RawUI.WindowTitle = "Server Manager Tray"
    
    # Try to set window style but catch if not supported in this PowerShell host
    try {
        if ($host.UI.RawUI.PSObject.Properties.Name -contains "WindowStyle") {
            $host.UI.RawUI.WindowStyle = 'Hidden'
        }
    } catch {
        Write-TrayLog "WindowStyle property not available in this PowerShell host" -Level DEBUG
    }
    
    # Get registry settings with fallbacks
    $settings = Get-RegistrySettings
    $serverManagerDir = $settings.ServerManagerDir
    $iconPath = $settings.IconPath
    
    Write-TrayLog "Using server manager directory: $serverManagerDir" -Level DEBUG
    
    # Create the tray icon
    $script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
    $script:trayIcon.Text = "Server Manager"
    
    # Set the tray icon
    if ($iconPath -and (Test-Path $iconPath)) {
        Write-TrayLog "Loading icon from: $iconPath" -Level DEBUG
        
        try {
            $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($iconPath)
        }
        catch {
            Write-TrayLog "Failed to load icon from $iconPath ${$_.Exception.Message}" -Level WARN
            # Use PowerShell icon as fallback
            $psPath = (Get-Process -Id $PID).Path
            $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($psPath)
        }
    } else {
        Write-TrayLog "Using default PowerShell icon (icon not found at: $iconPath)" -Level DEBUG
        # Use PowerShell icon as fallback
        $psPath = (Get-Process -Id $PID).Path
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($psPath)
    }

    # Initialize context menu
    $contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
    
    # Status item
    $statusItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $statusItem.Text = "Server Status: Unknown"
    $statusItem.Enabled = $false

    # Helper function to update status display
    function Update-ServerStatus {
        param([string]$Status, [bool]$IsConnected = $false)
        
        $script:serverStatus = $Status
        $script:serverRunning = $IsConnected
        
        # Update status text
        $statusText = "Server Status: $Status"
        
        # Thread-safe UI updates
        try {
            # Safely update UI controls - use proper thread synchronization
            if ($statusItem -ne $null) {
                if ($statusItem.InvokeRequired) {
                    $statusItem.BeginInvoke([Action]{ $statusItem.Text = $statusText })
                } else {
                    $statusItem.Text = $statusText
                }
            }
            
            if ($script:trayIcon -ne $null) {
                if ($script:trayIcon.InvokeRequired) {
                    $script:trayIcon.BeginInvoke([Action]{ $script:trayIcon.Text = "Server Manager - $Status" })
                } else {
                    $script:trayIcon.Text = "Server Manager - $Status"
                }
            }
            
            if ($openDashboardMenuItem -ne $null) {
                if ($openDashboardMenuItem.InvokeRequired) {
                    $openDashboardMenuItem.BeginInvoke([Action]{ $openDashboardMenuItem.Enabled = $IsConnected })
                } else {
                    $openDashboardMenuItem.Enabled = $IsConnected
                }
            }
        }
        catch {
            Write-TrayLog "Error updating UI: $($_.Exception.Message)" -Level ERROR
            # Fall back to direct update if invoke fails
            try {
                if ($statusItem -ne $null) { $statusItem.Text = $statusText }
                if ($script:trayIcon -ne $null) { $script:trayIcon.Text = "Server Manager - $Status" }
                if ($openDashboardMenuItem -ne $null) { $openDashboardMenuItem.Enabled = $IsConnected }
            } catch {
                Write-TrayLog "Failed fallback UI update: $($_.Exception.Message)" -Level ERROR
            }
        }
        
        Write-TrayLog "Server status updated: $Status (Connected: $IsConnected)" -Level DEBUG
    }
    
    # Start periodic connection checker
    function Start-ConnectionTimer {
        $script:connectionTimer = New-Object System.Windows.Forms.Timer
        $script:connectionTimer.Interval = 10000  # Check every 10 seconds
        $script:connectionTimer.Add_Tick({
            try {
                # Only do full check periodically to reduce resource usage
                $now = Get-Date
                $timeSinceLastCheck = ($now - $script:lastConnectionCheck).TotalSeconds
                
                if ($timeSinceLastCheck -ge $script:connectionCheckInterval) {
                    Test-ServerConnection
                    $script:lastConnectionCheck = $now
                }
                else {
                    # Do a silent check in between full checks
                    Test-ServerConnection -Silent
                }
            }
            catch {
                Write-TrayLog "Error in connection timer: $($_.Exception.Message)" -Level ERROR
            }
        })
        $script:connectionTimer.Start()
        
        Write-TrayLog "Connection timer started" -Level DEBUG
    }

    $openDashboardMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $openDashboardMenuItem.Text = "Open Web Dashboard"
    $openDashboardMenuItem.Add_Click({
        try {
            Start-Process "http://localhost:8080"
            Write-TrayLog "Web dashboard opened" -Level DEBUG
        }
        catch {
            Write-TrayLog "Failed to open web dashboard: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard. Please ensure the web server is running.", "Error")
        }
    })

    $openPSFormItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $openPSFormItem.Text = "Open PowerShell Dashboard"
    $openPSFormItem.Add_Click({
        try {
            $dashboardPath = Join-Path $serverManagerDir "Scripts\dashboard.ps1"
            if (Test-Path $dashboardPath) {
                # Create a launcher script that will ensure proper STA threading
                $launcherPath = Join-Path $env:TEMP "LaunchDashboard.ps1"
                @"
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms
Set-StrictMode -Off
`$scriptPath = '$dashboardPath'
& `$scriptPath
"@ | Out-File -FilePath $launcherPath -Encoding utf8
                
                # Launch with appropriate parameters for GUI
                Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Normal -File `"$launcherPath`"" -WindowStyle Normal
                Write-TrayLog "Dashboard launched via launcher script" -Level DEBUG
            } else {
                throw "Dashboard script not found: $dashboardPath"
            }
        }
        catch {
            Write-TrayLog "Failed to open dashboard: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard: $($_.Exception.Message)", "Error")
        }
    })

    # Add debug toggle item
    $debugMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $debugMenuItem.Text = "Toggle Debug Mode"
    $debugMenuItem.Add_Click({
        $script:DebugMode = -not $script:DebugMode
        Write-TrayLog "Debug mode toggled: $($script:DebugMode)" -Level INFO
        
        # Show notification about debug mode
        $script:trayIcon.ShowBalloonTip(
            3000,
            "Debug Mode",
            "Debug mode has been " + $(if ($script:DebugMode) { "enabled" } else { "disabled" }),
            [System.Windows.Forms.ToolTipIcon]::Info
        )
        
        # Update the menu text to reflect current state
        $debugMenuItem.Text = if ($script:DebugMode) { "Disable Debug Mode" } else { "Enable Debug Mode" }
    })
    
    # Add restart server item
    $restartServerMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $restartServerMenuItem.Text = "Restart Server"
    $restartServerMenuItem.Add_Click({
        try {
            Write-TrayLog "Restarting server..." -Level INFO
            
            # Get kill-webserver.ps1 and restart-webserver.ps1 paths
            $killScript = Join-Path $serverManagerDir "Scripts\kill-webserver.ps1"
            $startScript = Join-Path $serverManagerDir "Scripts\launcher.ps1"
            
            if (Test-Path $killScript) {
                Update-ServerStatus -Status "Restarting..." -IsConnected $false
                
                # Stop the server first
                Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$killScript`"" -Verb RunAs -WindowStyle Hidden -Wait
                
                Write-TrayLog "Server stopped, restarting..." -Level INFO
                
                # Give it a moment to fully stop
                Start-Sleep -Seconds 2
                
                # Restart the server
                Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" -Verb RunAs -WindowStyle Hidden
                
                # Give the server a moment to start
                Start-Sleep -Seconds 5
                
                # Check connection
                Test-ServerConnection
            }
            else {
                throw "Kill script not found: $killScript"
            }
        }
        catch {
            Write-TrayLog "Failed to restart server: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to restart server: $($_.Exception.Message)", "Error")
        }
    })

    $exitMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $exitMenuItem.Text = "Exit"
    $exitMenuItem.Add_Click({
        try {
            Write-TrayLog "Starting exit process..." -Level DEBUG
            
            # Show console window during cleanup
            try {
                $consolePtr = [Console.Window]::GetConsoleWindow()
                [void][Console.Window]::ShowWindow($consolePtr, 1)
            } catch {
                Write-TrayLog "Failed to show console window during exit: $($_.Exception.Message)" -Level DEBUG
            }
            
            # Stop connection timer
            if ($script:connectionTimer) {
                $script:connectionTimer.Stop()
                $script:connectionTimer.Dispose()
            }
            
            # Remove tray icon immediately
            if ($script:trayIcon) {
                $script:trayIcon.Visible = $false
                $script:trayIcon.Dispose()
            }
            
            # Get script paths from registry
            try {
                $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
                $serverMgrDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
                $stopScript = Join-Path $serverMgrDir "Scripts\kill-webserver.ps1"
    
                if (Test-Path $stopScript) {
                    Write-TrayLog "Running kill-webserver script..." -Level DEBUG
                    # Start kill-webserver.ps1 as administrator without waiting
                    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$stopScript`"" -Verb RunAs -WindowStyle Normal
                }
            } catch {
                Write-TrayLog "Failed to run kill-webserver script: $($_.Exception.Message)" -Level ERROR
            }

            Write-TrayLog "Exit process complete" -Level DEBUG
            
            # End the application
            if ($script:appContext) {
                $script:appContext.CleanupNotifyIcon()
                [System.Windows.Forms.Application]::Exit()
            }

            # Force exit this script
            Stop-Process $pid -Force
        }
        catch {
            Write-TrayLog "Error during exit: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Error during shutdown: $($_.Exception.Message)", "Error")
            exit 1
        }
    })

    # Create a "Separator" after status item
    $separator1 = New-Object System.Windows.Forms.ToolStripSeparator

    # Add items to context menu in proper order
    $contextMenu.Items.AddRange(@(
        $statusItem,
        $separator1,
        $openDashboardMenuItem, 
        $openPSFormItem, 
        $restartServerMenuItem,
        $debugMenuItem,
        $exitMenuItem
    ))
    
    $script:trayIcon.ContextMenuStrip = $contextMenu
    $script:trayIcon.Visible = $true

    # Register icon double-click handler to open dashboard
    $script:trayIcon.add_MouseDoubleClick({
        if ($script:serverRunning) {
            try {
                Start-Process "http://localhost:8080"
                Write-TrayLog "Web dashboard opened via double-click" -Level DEBUG
            }
            catch {
                Write-TrayLog "Failed to open web dashboard: $($_.Exception.Message)" -Level ERROR
            }
        }
    })

    # Show an initial startup notification
    $script:trayIcon.ShowBalloonTip(
        5000,
        "Server Manager",
        "Server Manager tray icon is now active. Right-click for options.",
        [System.Windows.Forms.ToolTipIcon]::Info
    )

    Write-TrayLog "Tray icon initialized successfully" -Level INFO
    
    # Do initial server connection check
    Test-ServerConnection
    
    # Start periodic connection checks
    Start-ConnectionTimer

    # Use application context to keep application running
    $script:appContext = New-Object TrayIconApplicationContext($script:trayIcon)
    
    # Register cleanup on exit
    $exitHandler = [System.EventHandler]{
        Write-TrayLog "Application exiting..." -Level INFO
        if ($script:trayIcon -ne $null) {
            $script:trayIcon.Visible = $false
            $script:trayIcon.Dispose()
        }
        
        if ($script:connectionTimer -ne $null) {
            $script:connectionTimer.Stop()
            $script:connectionTimer.Dispose()
        }
    }
    
    [System.AppDomain]::CurrentDomain.add_ProcessExit($exitHandler)
    
    # Run the application - this will block until the application exits
    [System.Windows.Forms.Application]::Run($script:appContext)
}
catch {
    Write-TrayLog "Critical error in tray icon: $($_.Exception.Message)" -Level ERROR
    Write-TrayLog $_.ScriptStackTrace -Level ERROR
    
    # If assemblies failed to load, show console with error message
    if ($script:assemblyLoadFailed) {
        $host.UI.RawUI.WindowStyle = 'Normal'
        Write-Host "ERROR: The tray icon could not be initialized due to missing assemblies." -ForegroundColor Red
        Write-Host "Please verify that .NET Framework 4.6.2 or later is installed." -ForegroundColor Red
        Write-Host "Press any key to exit..."
        $null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
    
    throw
}
finally {
    # Cleanup resources
    if ($script:connectionTimer) {
        try { $script:connectionTimer.Stop() } catch {}
        try { $script:connectionTimer.Dispose() } catch {}
    }
    
    if ($script:trayIcon) {
        try { $script:trayIcon.Visible = $false } catch {}
        try { $script:trayIcon.Dispose() } catch {}
    }
    
    Write-TrayLog "Tray icon script exited" -Level INFO
}
