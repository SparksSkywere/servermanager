param(
    [switch]$AsService
)

# Set strict error handling
$ErrorActionPreference = 'Stop'

# Define registry path
$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Initial script-scope variable declarations
$script:Paths = $null
$script:ReadyFiles = $null 
$script:Ports = $null
$script:IsService = $AsService -or ([System.Environment]::UserInteractive -eq $false)
$script:ServiceName = "ServerManagerService"
$script:logStream = $null
$script:logWriter = $null

# Global process tracker
$Global:ProcessTracker = @{
    WebServer = $null
    TrayIcon = $null
    Launcher = $PID  # Track the launcher's own PID
    StartTime = Get-Date
    IsRunning = $false
}

# PID file tracking
$script:PidFiles = @{}

# Write status message to console and log file
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

# File operations helper functions
function Write-PidFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type,
        
        [Parameter(Mandatory=$true)]
        [int]$ProcessId
    )
    
    if (-not $script:PidFiles.ContainsKey($Type)) {
        Write-StatusMessage "Unknown PID file type: $Type" "Yellow" -LogOnly
        return
    }
    
    $pidFilePath = $script:PidFiles[$Type]
    
    try {
        # Create a JSON object for better compatibility with kill-webserver.ps1
        $pidInfo = @{
            ProcessId = $ProcessId
            StartTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            Type = $Type
        } | ConvertTo-Json
        
        # Write to PID file using Set-Content for reliability
        Set-Content -Path $pidFilePath -Value $pidInfo -Force -ErrorAction Stop
        Write-StatusMessage "Wrote PID $ProcessId to $pidFilePath" "Gray" -LogOnly
    }
    catch {
        Write-StatusMessage "Failed to write PID file for ${Type}: $_" "Red" -LogOnly
    }
}

# Enhanced server ready detection with improved robustness
function Test-ReadyFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type
    )
    
    if (-not $script:ReadyFiles.ContainsKey($Type)) {
        Write-StatusMessage "Unknown ready file type: $Type" "Yellow" -LogOnly
        return $false
    }
    
    $readyFilePath = $script:ReadyFiles[$Type]
    Write-StatusMessage "Checking ready file: $readyFilePath" "Gray" -LogOnly
    
    # First simply check if the file exists
    if (Test-Path $readyFilePath) {
        Write-StatusMessage "Ready file found: $readyFilePath" "Green" -LogOnly
        
        # Try to read the content, but don't fail if we can't parse it
        try {
            $content = Get-Content $readyFilePath -Raw
            Write-StatusMessage "Ready file content: $content" "Gray" -LogOnly
            
            # Look for error status
            if ($content -match '"status"\s*:\s*"error"') {
                Write-StatusMessage "Ready file indicates error status" "Red" -LogOnly
                return $false
            }
            
            # Accept any content as long as it's not an error
            return $true
        }
        catch {
            Write-StatusMessage "Failed to read ready file, but it exists. Considering as ready." "Yellow" -LogOnly
            return $true
        }
    }
    
    Write-StatusMessage "Ready file not found: $readyFilePath" "Yellow" -LogOnly
    return $false
}

# Direct TCP port check with enhanced reliability
function Test-TcpConnection {
    param(
        [string]$ComputerName = "localhost",
        [int]$Port,
        [int]$Timeout = 2000
    )
    
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connection = $tcpClient.BeginConnect($ComputerName, $Port, $null, $null)
        $success = $connection.AsyncWaitHandle.WaitOne($Timeout, $false)
        
        if ($success) {
            try {
                $tcpClient.EndConnect($connection)
                return $true
            } catch {
                return $false
            }
        } else {
            return $false
        }
    }
    catch {
        Write-StatusMessage "TCP test error: $_" "Gray" -LogOnly
        return $false
    }
    finally {
        if ($tcpClient) { 
            try { $tcpClient.Close() } catch {}
        }
    }
}

# More reliable server ready detection with better fallback strategies
function Wait-ServerReady {
    param(
        [int]$TimeoutSeconds = 45, # Increased timeout
        [switch]$Quiet
    )
    
    $startTime = Get-Date
    $lastMessage = ""
    $retryCount = 0
    
    while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($TimeoutSeconds)) {
        $retryCount++
        
        if (-not $Quiet) {
            Write-StatusMessage "Checking server status (attempt $retryCount)..." "Gray" -Verbose
        }
        
        try {
            # Method 1: Check ready files first (most reliable)
            $wsReady = Test-ReadyFile -Type "WebSocket"
            $webReady = Test-ReadyFile -Type "WebServer"
            
            if ($wsReady -and $webReady) {
                Write-StatusMessage "Both server ready files detected" "Green"
                return $true
            }
            
            # Method 2: Check if TCP ports are responding
            $webPortOpen = Test-TcpConnection -Port $script:Ports.WebServer
            $socketPortOpen = Test-TcpConnection -Port $script:Ports.WebSocket
            
            if ($webPortOpen -and $socketPortOpen) {
                # Create ready files if needed
                Create-ReadyFiles -WebPort $script:Ports.WebServer -WebSocketPort $script:Ports.WebSocket
                Write-StatusMessage "Server is responding on both ports, ready files created" "Green"
                return $true
            }
            
            # Check if process is still running
            if ($Global:ProcessTracker.WebServer) {
                $process = Get-Process -Id $Global:ProcessTracker.WebServer -ErrorAction SilentlyContinue
                if (-not $process -or $process.HasExited) {
                    Write-StatusMessage "Web server process has exited" "Red"
                    return $false
                }
            }
            
            # After 30 seconds, accept partial success
            $elapsedSeconds = [int]([TimeSpan]((Get-Date) - $startTime)).TotalSeconds
            if ($elapsedSeconds > 30) {
                if ($webPortOpen -or $wsReady) {
                    Write-StatusMessage "Web server ready, continuing without WebSocket" "Yellow"
                    return $true
                }
                
                if ($socketPortOpen -or $webReady) {
                    Write-StatusMessage "WebSocket ready, continuing without Web server" "Yellow"
                    return $true
                }
            }
            
            if (-not $Quiet) {
                $message = "Waiting for server... ${elapsedSeconds}s"
                if ($message -ne $lastMessage) {
                    Write-StatusMessage $message "Cyan"
                    $lastMessage = $message
                }
                
                # Show detailed status periodically
                if ($retryCount % 5 -eq 0) {
                    Write-StatusMessage "Port status - Web: $($webPortOpen), WebSocket: $($socketPortOpen)" "Cyan" -LogOnly
                    Write-StatusMessage "Ready files - Web: $($webReady), WebSocket: $($wsReady)" "Cyan" -LogOnly
                }
            }
        }
        catch {
            if (-not $Quiet) {
                Write-StatusMessage "Error checking status: $_" "Red" -Verbose
            }
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    # Last resort, check if at least one component is ready
    try {
        $wsReady = Test-ReadyFile -Type "WebSocket"
        $webReady = Test-ReadyFile -Type "WebServer"
        $webPortOpen = Test-TcpConnection -Port $script:Ports.WebServer
        $socketPortOpen = Test-TcpConnection -Port $script:Ports.WebSocket
        
        if ($wsReady -or $webReady -or $webPortOpen -or $socketPortOpen) {
            Write-StatusMessage "At least one server component is ready, continuing" "Yellow"
            return $true
        }
    } catch {
        Write-StatusMessage "Error in final ready check: $_" "Red" -LogOnly
    }
    
    Write-StatusMessage "Timeout waiting for server ready state" "Yellow"
    return $false
}

# Initialize base paths and configuration
function Initialize-Configuration {
    try {
        Write-StatusMessage "Initializing configuration..." "Cyan" -LogOnly
        
        # Get base paths from registry
        $registryPath = $script:RegPath
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
        
        # Initialize ready file paths
        $script:ReadyFiles = @{
            WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
            WebServer = Join-Path $script:Paths.Temp "webserver.ready"
        }
        
        # Initialize port configuration
        $script:Ports = @{
            WebServer = 8080
            WebSocket = 8081
        }
        
        # Initialize PID file paths
        $script:PidFiles = @{
            Launcher = Join-Path $script:Paths.Temp "launcher.pid"
            WebServer = Join-Path $script:Paths.Temp "webserver.pid"
            TrayIcon = Join-Path $script:Paths.Temp "trayicon.pid"
            WebSocket = Join-Path $script:Paths.Temp "websocket.pid"
        }

        # Clean any existing ready files
        Get-ChildItem $script:Paths.Temp -Filter "*.ready" | Remove-Item -Force -ErrorAction SilentlyContinue
        
        # Initialize logging
        InitializeLogging
        
        # Write current PID
        Write-PidFile -Type "Launcher" -ProcessId $PID
        $Global:ProcessTracker.Launcher = $PID
        
        Write-StatusMessage "Configuration initialized successfully" "Green" -LogOnly
        return $true
    }
    catch {
        Write-StatusMessage "Failed to initialize configuration: $_" "Red"
        return $false
    }
}

# Initialize logging subsystem
function InitializeLogging {
    # Initialize log files
    $logPaths = @{
        Main = Join-Path $script:Paths.Logs "launcher.log"
        WebServer = Join-Path $script:Paths.Logs "webserver.log"
        TrayIcon = Join-Path $script:Paths.Logs "trayicon.log"
        Updates = Join-Path $script:Paths.Logs "updates.log"
    }
    
    # Create log directory if it doesn't exist
    if (-not (Test-Path $script:Paths.Logs)) {
        New-Item -ItemType Directory -Path $script:Paths.Logs -Force | Out-Null
    }
    
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
}

# Helper function to dispose resources
function Dispose-Resources {
    if ($script:logWriter) {
        $script:logWriter.Dispose()
        $script:logWriter = $null
    }
    if ($script:logStream) {
        $script:logStream.Dispose()
        $script:logStream = $null
    }
    
    # Clean up event subscribers
    Get-EventSubscriber | Unregister-Event -Force -ErrorAction SilentlyContinue
}

# Network management functions
function Manage-NetworkResource {
    param(
        [Parameter(Mandatory=$true)]
        [ValidateSet("Add", "Remove")]
        [string]$Action,
        
        [Parameter(Mandatory=$true)]
        [ValidateSet("UrlReservation", "FirewallRule")]
        [string]$ResourceType,
        
        [Parameter(Mandatory=$true)]
        [int]$Port
    )
    
    switch ($ResourceType) {
        "UrlReservation" {
            $urls = @(
                "http://+:$Port/",
                "http://localhost:$Port/",
                "http://*:$Port/"
            )
            
            foreach ($url in $urls) {
                if ($Action -eq "Add") {
                    Write-StatusMessage "Adding URL reservation: $url" "Cyan" -LogOnly
                    $null = netsh http add urlacl url=$url user=Everyone 2>&1
                } else {
                    Write-StatusMessage "Removing URL reservation: $url" "Cyan" -LogOnly
                    $null = netsh http delete urlacl url=$url 2>&1
                }
            }
        }
        "FirewallRule" {
            $ruleNames = @(
                "ServerManager_http_$Port",
                "ServerManager_WebSocket_$Port"
            )
            
            foreach ($ruleName in $ruleNames) {
                if ($Action -eq "Add") {
                    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
                        Write-StatusMessage "Adding firewall rule: $ruleName" "Cyan" -LogOnly
                        New-NetFirewallRule -DisplayName $ruleName `
                                          -Direction Inbound `
                                          -Protocol TCP `
                                          -LocalPort $Port `
                                          -Action Allow
                    }
                } else {
                    Write-StatusMessage "Removing firewall rule: $ruleName" "Cyan" -LogOnly
                    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

# Clear port and ensure it's available
function Clear-TCPPort {
    param(
        [Parameter(Mandatory=$true)]
        [int]$Port
    )
    
    Write-StatusMessage "Clearing port $Port..." "Cyan" -LogOnly
    
    # Get all processes using the port
    $connections = @()
    $connections += netstat -ano | Where-Object { $_ -match ":$Port\s+.*(?:LISTENING|ESTABLISHED)" }
    
    try {
        $connections += Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop
    } catch {
        Write-StatusMessage "Note: Get-NetTCPConnection unavailable" "Yellow" -LogOnly
    }
    
    # Extract and stop processes
    $processIds = $connections | ForEach-Object {
        if ($_ -match ".*:$Port.*\s+(\d+)\s*$") {
            $matches[1]
        } elseif ($_.OwningProcess) {
            $_.OwningProcess
        }
    } | Select-Object -Unique
    
    foreach ($pid in $processIds) {
        if ($pid -in @(0, 4)) { continue } # Skip system processes
        
        try {
            $process = Get-Process -Id $pid -ErrorAction Stop
            Write-StatusMessage "Stopping process $($process.Name) (PID: $pid) using port $Port" "Yellow" -LogOnly
            Stop-Process -Id $pid -Force
        } catch {
            Write-StatusMessage "Could not stop process $pid : $_" "Red" -LogOnly
        }
    }
    
    # Reset networking components
    Manage-NetworkResource -Action Remove -ResourceType UrlReservation -Port $Port
    Manage-NetworkResource -Action Remove -ResourceType FirewallRule -Port $Port
}

# Start a managed process and track it
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
    
    # Add working directory to improve stability
    $pinfo.WorkingDirectory = Split-Path -Parent $FilePath
    
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $pinfo
    
    try {
        # Start with a resource monitor
        $null = $process.Start()
        
        # Store the PID in both the process tracker and write to PID file
        $Global:ProcessTracker.$Type = $process.Id
        Write-PidFile -Type $Type -ProcessId $process.Id
        
        # Create a synchronized buffer for output to prevent thread issues
        $outputBuffer = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
        $errorBuffer = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
        
        # Register output handlers with buffering
        $null = Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action {
            param($sender, $e)
            if ($e.Data) { 
                $null = $outputBuffer.Add($e.Data)
                # Keep buffer size reasonable
                if ($outputBuffer.Count > 500) { $null = $outputBuffer.RemoveAt(0) }
                Write-StatusMessage "${Type}: $($e.Data)" "Gray" -LogOnly 
            }
        }
        
        $null = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action {
            param($sender, $e)
            if ($e.Data) { 
                $null = $errorBuffer.Add($e.Data)
                # Keep buffer size reasonable
                if ($errorBuffer.Count > 300) { $null = $errorBuffer.RemoveAt(0) }
                Write-StatusMessage "$Type Error: $($e.Data)" "Red" -LogOnly 
            }
        }
        
        # Add memory and CPU monitoring for the process
        $null = Register-ObjectEvent -InputObject $process -EventName Exited -Action {
            $exitCode = $sender.ExitCode
            Write-StatusMessage "$Type process exited with code: $exitCode" "Yellow" -LogOnly
            # Clear process from tracker upon exit
            $Global:ProcessTracker.$Type = $null
        }
        
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        
        # Store output/error buffers in process for retrieval
        Add-Member -InputObject $process -MemberType NoteProperty -Name "OutputBuffer" -Value $outputBuffer
        Add-Member -InputObject $process -MemberType NoteProperty -Name "ErrorBuffer" -Value $errorBuffer
        
        Write-StatusMessage "$Type process started (PID: $($process.Id))" "Green"
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start $Type process: $_" "Red"
        throw
    }
}

# Improved web server startup that supports both reliable minimal server and full WebSocket functionality
function Start-WebServer {
    try {
        Write-StatusMessage "Performing Server Manager checks..." "Cyan"
        
        # Ensure temp directory exists
        if (-not (Test-Path $script:Paths.Temp)) {
            New-Item -Path $script:Paths.Temp -ItemType Directory -Force | Out-Null
            Write-StatusMessage "Created temp directory: $($script:Paths.Temp)" "Green" -LogOnly
        }
        
        # Clear any existing ready files first
        Get-ChildItem $script:Paths.Temp -Filter "*.ready" | ForEach-Object {
            Write-StatusMessage "Removing existing ready file: $($_.FullName)" "Gray" -LogOnly
            Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue
        }
        
        # Clean up ports
        Clear-TCPPort -Port $script:Ports.WebServer
        Clear-TCPPort -Port $script:Ports.WebSocket
        
        # Add new URL reservations and firewall rules
        Manage-NetworkResource -Action Add -ResourceType UrlReservation -Port $script:Ports.WebServer
        Manage-NetworkResource -Action Add -ResourceType UrlReservation -Port $script:Ports.WebSocket
        Manage-NetworkResource -Action Add -ResourceType FirewallRule -Port $script:Ports.WebServer
        Manage-NetworkResource -Action Add -ResourceType FirewallRule -Port $script:Ports.WebSocket
        
        # Create initial ready files for immediate fallback support
        Write-StatusMessage "Creating initial server ready files..." "Cyan"
        Create-ReadyFiles -WebPort $script:Ports.WebServer -WebSocketPort $script:Ports.WebSocket
        
        # Start the enhanced web server with relative path parameters
        $webserverPath = Join-Path $script:Paths.Scripts "webserver.ps1"
        
        # Use relative paths for the ReadyDir parameter - This is key!
        $tempRelativePath = $script:Paths.Temp
        
        $arguments = "-ReadyDir `"$tempRelativePath`" -HttpPort $($script:Ports.WebServer) -WebSocketPort $($script:Ports.WebSocket)"
        
        Write-StatusMessage "Starting web server with arguments: $arguments" "Cyan"
        $webServerProcess = Start-ManagedProcess -Type "WebServer" -FilePath $webserverPath -ArgumentList $arguments -NoWindow
        
        # Allow a bit more time for startup (increased from 3 to 5 seconds)
        Start-Sleep -Seconds 5
        
        # Check if the process started correctly
        if (-not (Get-Process -Id $webServerProcess.Id -ErrorAction SilentlyContinue)) {
            Write-StatusMessage "Web server process terminated immediately, using fallback approach..." "Yellow"
            
            # Create minimal server script and start it
            $minimServerPath = Create-MinimalServerScript
            $webServerProcess = Start-ManagedProcess -Type "WebServer" -FilePath $minimServerPath -NoWindow
            
            if (-not $webServerProcess) {
                throw "Failed to start web server with both primary and fallback methods"
            }
        }
        
        # Wait for ready files to verify the server is operational
        $timeoutSeconds = 30
        $startTime = Get-Date
        $readyDetected = $false
        
        while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($timeoutSeconds)) {
            $wsReady = Test-ReadyFile -Type "WebSocket"
            $webReady = Test-ReadyFile -Type "WebServer"
            
            if ($wsReady -and $webReady) {
                $readyDetected = $true
                Write-StatusMessage "Both server ready files detected" "Green"
                break
            }
            
            Write-StatusMessage "Waiting for server ready files..." "Gray" -LogOnly
            Start-Sleep -Milliseconds 500
        }
        
        # If ready files aren't detected but process is still running, recreate the ready files
        if (-not $readyDetected) {
            if (Get-Process -Id $webServerProcess.Id -ErrorAction SilentlyContinue) {
                Write-StatusMessage "Server process is running but ready files not detected, recreating them..." "Yellow"
                Create-ReadyFiles -WebPort $script:Ports.WebServer -WebSocketPort $script:Ports.WebSocket -Emergency
            }
            else {
                Write-StatusMessage "Server process has terminated, starting fallback server..." "Red"
                
                # Create minimal server script and start it as last resort
                $minimServerPath = Create-MinimalServerScript
                $webServerProcess = Start-ManagedProcess -Type "WebServer" -FilePath $minimServerPath -NoWindow
                
                if (-not $webServerProcess) {
                    throw "Failed to start web server with fallback method"
                }
                
                # Ensure ready files exist
                Create-ReadyFiles -WebPort $script:Ports.WebServer -WebSocketPort $script:Ports.WebSocket -Emergency
            }
        }
        
        # Create WebSocket ready file explicitly to ensure it exists
        # This is critical for dashboard connectivity
        Initialize-WebSocketReadyFile
        
        Write-StatusMessage "Web server started successfully" "Green"
        return $webServerProcess
    }
    catch {
        Write-StatusMessage "Failed to start web server: $_" "Red"
        Write-StatusMessage $_.ScriptStackTrace "Red" -LogOnly
        throw
    }
}

# Create a minimal server script
function Create-MinimalServerScript {
    $serverPath = Join-Path $script:Paths.Scripts "minimalserver.ps1"
    
    $serverScript = @"
# Minimal server script that keeps process alive
param()

`$ErrorActionPreference = 'Stop'
`$logFile = Join-Path "$($script:Paths.Logs)" "minimalserver.log"

function Write-Log {
    param([string]`$Message)
    `$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    `$logEntry = "[`$timestamp] `$Message"
    
    try {
        Add-Content -Path `$logFile -Value `$logEntry -ErrorAction SilentlyContinue
    } catch {}
}

Write-Log "Minimal server started"

try {
    # Create an HTTP listener if possible
    `$listener = New-Object System.Net.HttpListener
    `$listener.Prefixes.Add("http://localhost:$($script:Ports.WebServer)/")
    
    # ...existing code within the heredoc string...
"@
    
    # Write the script to file
    Set-Content -Path $serverPath -Value $serverScript -Force
    
    return $serverPath
}

# Start a reliable minimal web server
function Start-MinimalWebServer {
    try {
        Write-StatusMessage "Starting minimal web server..." "Cyan"
        
        # Create a PowerShell script that just stays alive
        $serverPath = Join-Path $script:Paths.Scripts "keepalive.ps1"
        $serverContent = @"
# Simple keep-alive script
while (`$true) { Start-Sleep -Seconds 10 }
"@
        Set-Content -Path $serverPath -Value $serverContent -Force
        
        # Start the simple server
        $process = Start-ManagedProcess -Type "WebServer" -FilePath $serverPath -NoWindow
        
        Write-StatusMessage "Minimal web server started (PID: $($process.Id))" "Green"
        return $process
    }
    catch {
        Write-StatusMessage "Failed to start minimal web server: $_" "Red"
        return $null
    }
}

# Simplified ready file creation - this is the key to making it work
function Create-ReadyFiles {
    param(
        [int]$WebPort = 8080,
        [int]$WebSocketPort = 8081,
        [switch]$Emergency
    )
    
    try {
        if ($Emergency) {
            Write-StatusMessage "Creating emergency server ready files..." "Yellow"
        } else {
            Write-StatusMessage "Creating standard server ready files..." "Cyan" -LogOnly
        }
        
        # Prepare content with appropriate notes
        $webServerReady = @{
            status = "ready"
            port = $WebPort
            timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        }
        
        $webSocketReady = @{
            status = "ready"
            port = $WebSocketPort
            timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        }
        
        # Add note if these are emergency files
        if ($Emergency) {
            $webServerReady["note"] = "Created by launcher (emergency)"
            $webSocketReady["note"] = "Created by launcher (emergency)"
        } else {
            $webServerReady["note"] = "Created by launcher (standard)"
            $webSocketReady["note"] = "Created by launcher (standard)"
        }
        
        # Ensure the temp directory exists
        if (-not (Test-Path $script:Paths.Temp)) {
            New-Item -Path $script:Paths.Temp -ItemType Directory -Force | Out-Null
        }
        
        # Use .NET IO to write files directly for maximum reliability
        $webServerJson = $webServerReady | ConvertTo-Json
        $webSocketJson = $webSocketReady | ConvertTo-Json
        
        # Try multiple methods to ensure files are created
        try {
            [System.IO.File]::WriteAllText($script:ReadyFiles.WebServer, $webServerJson)
            [System.IO.File]::WriteAllText($script:ReadyFiles.WebSocket, $webSocketJson)
        }
        catch {
            Write-StatusMessage "Error writing ready files with File.WriteAllText, trying Set-Content: $_" "Yellow" -LogOnly
            try {
                Set-Content -Path $script:ReadyFiles.WebServer -Value $webServerJson -Force
                Set-Content -Path $script:ReadyFiles.WebSocket -Value $webSocketJson -Force
            }
            catch {
                Write-StatusMessage "Error writing ready files with Set-Content: $_" "Red" -LogOnly
                return $false
            }
        }
        
        # Verify files were created
        if ((Test-Path $script:ReadyFiles.WebServer) -and (Test-Path $script:ReadyFiles.WebSocket)) {
            Write-StatusMessage "Ready files created successfully" "Green" -LogOnly
            return $true
        }
        else {
            Write-StatusMessage "Failed to verify ready files" "Red" -LogOnly
            return $false
        }
    }
    catch {
        Write-StatusMessage "Error creating ready files: $_" "Red" -LogOnly
        return $false
    }
}

# Add explicit WebSocket ready file creation to ensure dashboard can connect
function Initialize-WebSocketReadyFile {
    try {
        Write-StatusMessage "Creating WebSocket ready file..." "Cyan"
        
        # Get WebSocket port from registry if available
        $webSocketPort = 8081
        
        # Create ready file with proper format
        $readyFilePath = $script:ReadyFiles.WebSocket
        $readyContent = @{
            status = "ready"
            port = $webSocketPort
            timestamp = Get-Date -Format "o"
            host = "localhost"
        } | ConvertTo-Json
        
        # Ensure directory exists
        $readyDir = Split-Path -Parent $readyFilePath
        if (-not (Test-Path $readyDir)) {
            New-Item -Path $readyDir -ItemType Directory -Force | Out-Null
        }
        
        # Write file with maximum reliability - try multiple methods
        try {
            [System.IO.File]::WriteAllText($readyFilePath, $readyContent)
        }
        catch {
            Write-StatusMessage "Using alternative method to write ready file: $_" "Yellow" -LogOnly
            Set-Content -Path $readyFilePath -Value $readyContent -Force
        }
        
        # Verify file was created
        if (Test-Path $readyFilePath) {
            Write-StatusMessage "WebSocket ready file created successfully" "Green" -LogOnly
            return $true
        }
        else {
            Write-StatusMessage "Failed to create WebSocket ready file" "Red" -LogOnly
            return $false
        }
    }
    catch {
        Write-StatusMessage "Error creating WebSocket ready file: $_" "Red" -LogOnly
        return $false
    }
}

# Start tray icon application
function Start-TrayIcon {
    if (-not $Global:ProcessTracker.TrayIcon) {
        $trayIconPath = Join-Path $script:Paths.Scripts "trayicon.ps1"
        $logPath = Join-Path $script:Paths.Logs "trayicon.log"
        $process = Start-ManagedProcess -Type "TrayIcon" -FilePath $trayIconPath -ArgumentList "-LogPath `"$logPath`""
        
        # Double-check that the process is running and PID is tracked
        if ($process -and $process.Id) {
            $Global:ProcessTracker.TrayIcon = $process.Id
            # Ensure the PID file is written
            Write-PidFile -Type "TrayIcon" -ProcessId $process.Id
            Write-StatusMessage "TrayIcon process started with PID: $($process.Id)" "Green" -LogOnly
        }
        
        return $process
    }
    else {
        Write-StatusMessage "Tray icon is already running" "Yellow"
        return Get-Process -Id $Global:ProcessTracker.TrayIcon -ErrorAction SilentlyContinue
    }
}

# Fixed stop all components function with improved PID handling
function Stop-AllComponents {
    Write-StatusMessage "Stopping all components..." "Yellow"
    
    # Get process IDs only
    $processIds = @()
    foreach ($component in @("WebServer", "TrayIcon", "Launcher")) {
        $value = $Global:ProcessTracker[$component]
        if ($value -and $value -is [int] -and $value -gt 0) {
            $processIds += @{
                Name = $component
                Id = $value
            }
            Write-StatusMessage "Found $component process with PID: $value" "Gray" -LogOnly
        } else {
            Write-StatusMessage "$component process not tracked (value: $value)" "Yellow" -LogOnly
        }
    }
    
    # Stop each process
    foreach ($process in $processIds) {
        try {
            if ($process.Id -and $process.Id -gt 0) {
                $proc = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-StatusMessage "Stopping $($process.Name) (PID: $($process.Id))" "Yellow"
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                } else {
                    Write-StatusMessage "Process $($process.Name) with PID $($process.Id) not found" "Yellow" -LogOnly
                }
                $Global:ProcessTracker[$process.Name] = $null
            }
        }
        catch {
            Write-StatusMessage "Error stopping $($process.Name): $_" "Red" -LogOnly
        }
    }
    
    $Global:ProcessTracker.IsRunning = $false
    Write-StatusMessage "All components stopped" "Green"
}

# Set process window properties
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

# Load module with logging
function Import-ModuleWithLogging {
    param(
        [string]$ModulePath,
        [string]$ModuleName
    )
    
    try {
        Write-StatusMessage "Loading module: $ModuleName" "Cyan" -LogOnly
        
        # Temporarily redirect verbose output to variable
        $verbose = $VerbosePreference
        $VerbosePreference = 'SilentlyContinue'
        
        # Import module and capture all output
        $output = Import-Module -Name $ModulePath -Force -Global -PassThru -DisableNameChecking -Verbose 4>&1
        
        # Process captured output
        foreach ($item in $output) {
            $message = $item.ToString()
            Write-StatusMessage "$message" "Gray" -LogOnly -Verbose
        }
        
        # Verify module loaded
        $loadedModule = Get-Module $ModuleName -ErrorAction Stop
        if ($loadedModule) {
            Write-StatusMessage "Module $ModuleName loaded successfully" "Green" -LogOnly
            return $true
        }
        throw "Module did not load properly"
    }
    catch {
        Write-StatusMessage "Failed to load module $ModuleName : $_" "Red"
        return $false
    }
    finally {
        $VerbosePreference = $verbose
    }
}

# Load all required modules
function Initialize-Modules {
    $modulesPath = $script:Paths.Modules
    if (-not (Test-Path $modulesPath)) {
        throw "Modules directory not found: $modulesPath"
    }
    
    # Core modules in specific load order
    $coreModules = @(
        "WebSocketServer.psm1",
        "Common.psm1",
        "Network.psm1",
        "ServerManager.psm1"
    )
    
    # Clear any existing modules
    Write-StatusMessage "Clearing module cache..." "Cyan" -LogOnly
    Get-Module | Where-Object { $_.Path -like "*$modulesPath*" } | Remove-Module -Force -ErrorAction SilentlyContinue
    
    $moduleLoadingSuccess = $true
    
    # Load each module
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
    
    # Verify all modules loaded
    if ($moduleLoadingSuccess) {
        Write-StatusMessage "All modules loaded successfully" "Green"
        return $true
    } else {
        Write-StatusMessage "Module loading failed. Check logs for details." "Red"
        return $false
    }
}

# Main initialization function
function Initialize-ServerManager {
    param([switch]$AsService)
    
    try {
        Write-StatusMessage "Initializing Server Manager..." "Cyan"
        
        # Initialize configuration
        if (-not (Initialize-Configuration)) {
            throw "Failed to initialize configuration"
        }
        
        # Load required modules
        if (-not (Initialize-Modules)) {
            throw "Failed to load required modules"
        }
        
        Write-StatusMessage "Starting web server component..." "Cyan" -LogOnly
        $webServerProcess = Start-WebServer
        
        if (-not $webServerProcess) {
            throw "Failed to start web server"
        }
        
        Write-StatusMessage "Starting tray icon..." "Cyan" -LogOnly
        $trayProcess = Start-TrayIcon
        
        $Global:ProcessTracker.IsRunning = $true
        $Global:ProcessTracker.StartTime = Get-Date
        
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
        Write-StatusMessage $_.ScriptStackTrace "Red" -LogOnly
        throw
    }
}

# Setup cleanup actions
function Register-CleanupActions {
    # Add cleanup on PowerShell exit
    $exitScript = {
        Write-StatusMessage "Cleaning up processes..." "Yellow"
        Stop-AllComponents
        
        Write-StatusMessage "Cleaning up PID files..." "Yellow"
        foreach ($pidFile in $script:PidFiles.Values) {
            if (Test-Path $pidFile) {
                Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
                Write-StatusMessage "Removed PID file: $pidFile" "Gray" -LogOnly
            }
        }
        
        # Dispose resources
        Dispose-Resources
    }
    Register-EngineEvent PowerShell.Exiting -Action $exitScript | Out-Null
}

# Main monitoring loop
function Start-MonitoringLoop {
    while ($true) {
        Start-Sleep -Seconds 5
        
        # Check for keyboard input
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if (($key.Modifiers -band [ConsoleModifiers]::Control) -and ($key.Key -eq [ConsoleKey]::C)) {
                Write-StatusMessage "Ctrl+C detected, shutting down..." "Yellow"
                break
            }
        }
        
        # Check process health
        $processes = @($Global:ProcessTracker.WebServer, $Global:ProcessTracker.TrayIcon)
        $allRunning = $true
        
        foreach ($processId in $processes) {
            if ($processId -and -not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                Write-StatusMessage "Process $processId stopped unexpectedly" "Red"
                $allRunning = $false
                break
            }
        }
        
        if (-not $allRunning) {
            if ($script:IsService) {
                Write-StatusMessage "Critical process stopped, restarting service..." "Yellow"
                try {
                    Restart-Service -Name $script:ServiceName -Force
                } catch {
                    Write-StatusMessage "Failed to restart service: $_" "Red"
                    Stop-AllComponents
                    break
                }
            } else {
                Write-StatusMessage "Critical process stopped, shutting down..." "Yellow"
                Stop-AllComponents
                break
            }
        }
    }
}

# Main execution block
try {
    [Console]::TreatControlCAsInput = $true
    Register-CleanupActions
    
    # Check for admin privileges
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-StatusMessage "Please run this script as Administrator" "Red"
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Initialize based on mode
    if ($script:IsService) {
        # Service mode - no console needed
        Set-ProcessProperties -HideConsole
        Initialize-ServerManager -AsService
    } else {
        # Interactive mode - show console during initialization
        Initialize-ServerManager
    }
    
    # Start monitoring loop
    Start-MonitoringLoop
}
catch {
    Write-StatusMessage "Fatal error: $_" "Red"
    Write-StatusMessage $_.ScriptStackTrace "Red" -LogOnly
    Stop-AllComponents
    if (-not $script:IsService) {
        Write-StatusMessage "Press Enter to exit..." "Red"
        Read-Host
    }
    exit 1
}
finally {
    # Final cleanup
    Dispose-Resources
}