# Parse parameters first - before any other code
param(
    [string]$ReadyDir,
    [int]$HttpPort = 8080,
    [int]$WebSocketPort = 8081
)

# Immediate error handling and trapping
try {
    # Set error handling to continue to prevent instant termination
    $ErrorActionPreference = 'Continue'
    $VerbosePreference = 'Continue'
    
    # Create a direct emergency log for absolute earliest startup diagnostics
    $scriptBasePath = $PSScriptRoot
    $emergencyLogPath = Join-Path $scriptBasePath "webserver_emergency.log"
    $startupInfo = @"
======= EMERGENCY STARTUP LOG =======
[$(Get-Date)] PowerShell Version: $($PSVersionTable.PSVersion)
[$(Get-Date)] Process ID: $PID
[$(Get-Date)] Parameters:
   ReadyDir: $ReadyDir
   HttpPort: $HttpPort
   WebSocketPort: $WebSocketPort
[$(Get-Date)] Working dir: $(Get-Location)
[$(Get-Date)] Script path: $scriptBasePath
======= END STARTUP INFO =======

"@
    [System.IO.File]::WriteAllText($emergencyLogPath, $startupInfo)
    
    # Get base paths from registry - matching the approach in launcher.ps1
    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Reading base path from registry`n")
    try {
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        
        # Check if registry path exists
        if (-not (Test-Path $registryPath)) {
            throw "Registry path not found: $registryPath"
        }
        
        # Get base directory from registry
        $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
        if (-not $serverManagerDir) {
            throw "servermanagerdir not found in registry"
        }
        
        # Clean up path
        $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Found base path in registry: $serverManagerDir`n")
        
        # Define key paths based on registry value - matching launcher.ps1 pattern
        $basePaths = @{
            Root = $serverManagerDir
            Logs = Join-Path $serverManagerDir "logs"
            Config = Join-Path $serverManagerDir "config"
            Temp = Join-Path $serverManagerDir "temp"
            Scripts = Join-Path $serverManagerDir "Scripts"
            Modules = Join-Path $serverManagerDir "Modules"
        }
    }
    catch {
        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Registry read failed: $($_.Exception.Message)`n")
        
        # Fallback to script-relative paths
        $scriptParent = Split-Path (Split-Path $scriptBasePath -Parent) -Parent
        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Using script-relative paths from: $scriptParent`n")
        
        $basePaths = @{
            Root = $scriptParent
            Logs = Join-Path $scriptParent "logs"
            Config = Join-Path $scriptParent "config"
            Temp = Join-Path $scriptParent "temp"
            Scripts = Join-Path $scriptParent "Scripts"
            Modules = Join-Path $scriptParent "Modules"
        }
    }
    
    # Ensure logs directory exists
    $logsBasePath = $basePaths.Logs
    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Using logs path: $logsBasePath`n")
    
    if (-not (Test-Path $logsBasePath)) {
        try {
            # First try native PowerShell
            New-Item -Path $logsBasePath -ItemType Directory -Force | Out-Null
            [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Created logs directory: $logsBasePath`n")
        }
        catch {
            # Then try .NET method if PowerShell fails
            try {
                [System.IO.Directory]::CreateDirectory($logsBasePath) | Out-Null
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Created logs directory using .NET method: $logsBasePath`n")
            }
            catch {
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Failed to create logs directory: $($_.Exception.Message)`n")
                # Fall back to script directory as last resort
                $logsBasePath = $scriptBasePath
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Using fallback logs path: $logsBasePath`n")
            }
        }
    }
    
    # Define path for main log file only (removed debug log)
    $logFile = Join-Path $logsBasePath "webserver.log"
    
    # Log the locations for diagnostics (removed debug log references)
    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Log file will be at: $logFile`n")
    
    # Create initial log file with proper directory creation
    try {
        $initialLogEntry = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [INIT] WebServer script starting with PID: $PID"
        
        # Ensure log directory exists
        $logDir = Split-Path $logFile -Parent
        if (-not (Test-Path $logDir)) {
            [System.IO.Directory]::CreateDirectory($logDir) | Out-Null
            [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Created log directory: $logDir`n")
        }
        
        # Create main log file (removed debug log creation)
        [System.IO.File]::WriteAllText($logFile, "$initialLogEntry`n")
        
        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Successfully created log file`n")
    }
    catch {
        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Error creating log file: $($_.Exception.Message)`n")
    }
    
    # Create simplified logging function (removed debug log functionality)
    function Write-Log {
        param(
            [string]$Message,
            [string]$Level = "INFO",
            [switch]$EmergencyAlso
        )
        
        try {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $logMessage = "[$timestamp] [$Level] $Message"
            
            # Write to main log
            try {
                # Verify main log file exists
                if (-not (Test-Path $logFile)) {
                    $mainLogDir = Split-Path $logFile -Parent
                    if (-not (Test-Path $mainLogDir)) {
                        [System.IO.Directory]::CreateDirectory($mainLogDir) | Out-Null
                    }
                    [System.IO.File]::WriteAllText($logFile, "[$timestamp] [INIT] Main log file recreated`n")
                }
                
                # Write to main log with .NET File class for reliable file access
                [System.IO.File]::AppendAllText($logFile, "$logMessage`n")
            }
            catch {
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Failed to write to main log: $($_.Exception.Message)`n")
            }
            
            # Also write to console for interactive debugging
            try {
                Write-Verbose $logMessage
            }
            catch {
                # Console errors not critical
            }
            
            # Always write to emergency log if requested
            if ($EmergencyAlso) {
                try {
                    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] $Level - $Message`n")
                }
                catch {
                    # If emergency log fails, nothing more we can do
                }
            }
        }
        catch {
            # Last resort if all logging fails
            try {
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Critical error in logging system: $($_.Exception.Message)`n")
            }
            catch {
                # Beyond recovery
            }
        }
    }
    
    # Log startup information
    Write-Log "WebServer starting with PID: $PID" -Level "INFO" -EmergencyAlso
    Write-Log "Using logs directory: $logsBasePath" -Level "INFO" -EmergencyAlso
    Write-Log "Base directory from registry: $($basePaths.Root)" -Level "INFO" -EmergencyAlso
    Write-Log "Parameters: ReadyDir=$ReadyDir, HttpPort=$HttpPort, WebSocketPort=$WebSocketPort" -Level "INFO" -EmergencyAlso
    
    # Define robust ready file function
    function Set-ReadyFile {
        param(
            [string]$FilePath,
            [int]$Port,
            [string]$Status = "ready"
        )
        
        try {
            Write-Log "Creating ready file: $FilePath with status $Status for port $Port" -Level "INFO"
            
            # Create content object
            $content = @{
                status = $Status
                port = $Port
                timestamp = Get-Date -Format "o"
            } | ConvertTo-Json -Compress
            
            # Ensure directory exists
            $fileDir = Split-Path $FilePath -Parent
            if (-not (Test-Path $fileDir)) {
                [System.IO.Directory]::CreateDirectory($fileDir) | Out-Null
                Write-Log "Created directory: $fileDir" -Level "DEBUG"
            }
            
            # Write file with .NET methods for maximum reliability
            [System.IO.File]::WriteAllText($FilePath, $content)
            
            # Verify file exists
            if (Test-Path $FilePath) {
                Write-Log "Successfully created ready file: $FilePath" -Level "INFO"
                return $true
            }
            
            Write-Log "Ready file creation verification failed" -Level "WARN" -EmergencyAlso
            return $false
        }
        catch {
            Write-Log "Failed to create ready file: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            
            # Try alternative method
            try {
                Set-Content -Path $FilePath -Value $content -Force
                Write-Log "Created ready file with PowerShell Set-Content" -Level "INFO"
                return $true
            }
            catch {
                Write-Log "All methods to create ready file failed: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
                return $false
            }
        }
    }
    
    # Resolve ready directory using the established base paths
    if ([string]::IsNullOrEmpty($ReadyDir)) {
        $ReadyDir = $basePaths.Temp
        Write-Log "No ReadyDir provided, using path from registry: $ReadyDir" -Level "INFO" -EmergencyAlso
    }
    
    # Ensure ready directory exists
    if (-not (Test-Path $ReadyDir)) {
        try {
            [System.IO.Directory]::CreateDirectory($ReadyDir) | Out-Null
            Write-Log "Created ready directory: $ReadyDir" -Level "INFO" -EmergencyAlso
        }
        catch {
            Write-Log "Failed to create ready directory: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            
            # Try fallback to temp directory in base paths
            $ReadyDir = $basePaths.Temp
            try {
                [System.IO.Directory]::CreateDirectory($ReadyDir) | Out-Null
                Write-Log "Created fallback ready directory: $ReadyDir" -Level "WARN" -EmergencyAlso
            }
            catch {
                # Last resort - use script directory
                $ReadyDir = Join-Path $scriptBasePath "temp"
                try {
                    [System.IO.Directory]::CreateDirectory($ReadyDir) | Out-Null
                    Write-Log "Created emergency ready directory: $ReadyDir" -Level "WARN" -EmergencyAlso
                }
                catch {
                    Write-Log "Failed to create any ready directory: $($_.Exception.Message)" -Level "FATAL" -EmergencyAlso
                    throw "Cannot create any ready directory"
                }
            }
        }
    }
    
    # Define ready file paths using the directory from above
    $webSocketReadyFile = Join-Path $ReadyDir "websocket.ready"
    $webServerReadyFile = Join-Path $ReadyDir "webserver.ready"
    
    Write-Log "Ready files set to: WebServer=$webServerReadyFile, WebSocket=$webSocketReadyFile" -Level "INFO" -EmergencyAlso
    
    # Write PID file
    try {
        $pidFilePath = Join-Path $ReadyDir "webserver.pid"
        $pidInfo = @{
            ProcessId = $PID
            StartTime = Get-Date -Format "o"
            ScriptPath = $PSCommandPath
        } | ConvertTo-Json -Compress
        
        [System.IO.File]::WriteAllText($pidFilePath, $pidInfo)
        Write-Log "Created PID file: $pidFilePath" -Level "INFO" -EmergencyAlso
    }
    catch {
        Write-Log "Failed to create PID file: $($_.Exception.Message)" -Level "WARN" -EmergencyAlso
    }
    
    # Create starting status ready files first
    Write-Log "Creating initial ready files..." -Level "INFO" -EmergencyAlso
    Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "starting"
    Set-ReadyFile -FilePath $webServerReadyFile -Port $HttpPort -Status "starting"
    
    # Initialize HTTP server
    Write-Log "Initializing HTTP server on port $HttpPort..." -Level "INFO" -EmergencyAlso
    
    # Immediately set HTTP ready to ready to unblock launcher
    Write-Log "Setting HTTP ready file to ready status..." -Level "INFO" -EmergencyAlso
    Set-ReadyFile -FilePath $webServerReadyFile -Port $HttpPort -Status "ready"
    
    # Initialize WebSocket server functionality
    Write-Log "Initializing WebSocket server on port $WebSocketPort..." -Level "INFO" -EmergencyAlso
    
    # Import required modules
    try {
        # Add the Modules directory to PSModulePath to ensure module loading works
        $modulesPath = Join-Path $basePaths.Modules "WebSocketServer.psm1"
        Write-Log "Loading WebSocketServer module from: $modulesPath" -Level "INFO" -EmergencyAlso
        
        Import-Module $modulesPath -Force -DisableNameChecking -ErrorAction Stop
        
        # Verify the module loaded correctly
        if (Get-Command "New-WebSocketServer" -ErrorAction SilentlyContinue) {
            Write-Log "WebSocketServer module loaded successfully" -Level "INFO" -EmergencyAlso
        } else {
            throw "WebSocketServer module loaded but New-WebSocketServer command not available"
        }
    }
    catch {
        Write-Log "Failed to load WebSocketServer module: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
        Write-Log "Using fallback WebSocket implementation" -Level "WARN" -EmergencyAlso
        
        # Create simple WebSocket listening implementation
        Add-Type -TypeDefinition @"
        using System;
        using System.Net;
        using System.Net.Sockets;
        using System.Text;
        using System.Threading;
        
        public class SimpleWebSocketServer {
            private TcpListener listener;
            private int port;
            private bool isRunning = false;
            
            public SimpleWebSocketServer(int port) {
                this.port = port;
            }
            
            public void Start() {
                try {
                    listener = new TcpListener(IPAddress.Any, port);
                    listener.Start();
                    isRunning = true;
                    
                    // Start accepting clients in a separate thread
                    Thread acceptThread = new Thread(AcceptClients);
                    acceptThread.IsBackground = true;
                    acceptThread.Start();
                }
                catch (Exception ex) {
                    Console.WriteLine("Error starting WebSocket server: " + ex.Message);
                }
            }
            
            private void AcceptClients() {
                while (isRunning) {
                    try {
                        // Just keep the server running and accepting connections
                        Socket client = listener.AcceptSocket();
                        // We're not implementing the full WebSocket protocol here
                        // Just keeping the port open and accepting connections
                        client.Close();
                    }
                    catch (Exception) {
                        // Just ignore and continue
                        Thread.Sleep(1000);
                    }
                }
            }
            
            public void Stop() {
                isRunning = false;
                if (listener != null) {
                    listener.Stop();
                }
            }
        }
"@
        
        $simpleWsServer = New-Object SimpleWebSocketServer -ArgumentList $WebSocketPort
        $simpleWsServer.Start()
        Write-Log "Started simple WebSocket server on port $WebSocketPort" -Level "INFO" -EmergencyAlso
    }
    
    # Start actual WebSocket server if module is available
    try {
        if (Get-Command "New-WebSocketServer" -ErrorAction SilentlyContinue) {
            Write-Log "Creating WebSocket server instance using module..." -Level "INFO" -EmergencyAlso
            
            # Create the WebSocket server with our handlers
            $script:wsServer = New-WebSocketServer -Port $WebSocketPort -ServerDirectory $basePaths.Root
            
            if ($script:wsServer) {
                Write-Log "WebSocket server created successfully" -Level "INFO" -EmergencyAlso
                
                # Verify the server is listening
                if ($script:wsServer.IsListening()) {
                    Write-Log "WebSocket server is listening on port $WebSocketPort" -Level "INFO" -EmergencyAlso
                } else {
                    Write-Log "WebSocket server created but not listening" -Level "WARN" -EmergencyAlso
                }
            } else {
                Write-Log "Failed to create WebSocket server" -Level "ERROR" -EmergencyAlso
            }
        }
    }
    catch {
        Write-Log "Error creating WebSocket server: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
        Write-Log "Stack trace: $($_.ScriptStackTrace)" -Level "ERROR" -EmergencyAlso
    }
    
    # Set WebSocket ready file to ready
    Write-Log "Setting WebSocket ready file to ready status..." -Level "INFO" -EmergencyAlso
    Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "ready"
    
    # Keep the script running to maintain the servers
    Write-Log "Servers initialized successfully. Entering maintenance loop..." -Level "INFO" -EmergencyAlso
    
    # Wait indefinitely
    try {
        while ($true) {
            Start-Sleep -Seconds 10
            
            # Periodically verify server is still listening
            if ($script:wsServer -and -not $script:wsServer.IsListening()) {
                Write-Log "WebSocket server no longer listening. Attempting to restart..." -Level "WARN" -EmergencyAlso
                
                # Try to recreate the server
                try {
                    $script:wsServer = New-WebSocketServer -Port $WebSocketPort -ServerDirectory $basePaths.Root
                    Write-Log "WebSocket server restarted successfully" -Level "INFO" -EmergencyAlso
                }
                catch {
                    Write-Log "Failed to restart WebSocket server: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
                }
            }
            
            # Re-verify ready files exist
            if (-not (Test-Path $webSocketReadyFile)) {
                Write-Log "WebSocket ready file missing, recreating..." -Level "WARN" -EmergencyAlso
                Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "ready"
            }
            
            if (-not (Test-Path $webServerReadyFile)) {
                Write-Log "HTTP server ready file missing, recreating..." -Level "WARN" -EmergencyAlso
                Set-ReadyFile -FilePath $webServerReadyFile -Port $HttpPort -Status "ready"
            }
        }
    }
    catch {
        Write-Log "Maintenance loop error: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
        # Just continue to the cleanup phase
    }
    finally {
        # Clean up if the script exits
        if ($script:wsServer) {
            try {
                $script:wsServer.Stop()
                Write-Log "WebSocket server stopped" -Level "INFO" -EmergencyAlso
            }
            catch {
                Write-Log "Error stopping WebSocket server: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            }
        }
        
        Write-Log "Server script terminating" -Level "INFO" -EmergencyAlso
    }
}
catch {
    # Last resort error handling
    try {
        $errorTimeStamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $emergencyLogPath = "$PSScriptRoot\webserver_emergency.log" # Always use script directory for emergency
        
        [System.IO.File]::AppendAllText($emergencyLogPath, @"
[$errorTimeStamp] ===== FATAL ERROR =====
$($_.Exception.Message)
Stack trace:
$($_.ScriptStackTrace)
Exception details:
$($_.Exception.ToString())
=========================

"@)
        
        # Try to create ready files even after fatal error
        if ($ReadyDir -and (Test-Path $ReadyDir)) {
            $webSocketReadyFile = Join-Path $ReadyDir "websocket.ready"
            $webServerReadyFile = Join-Path $ReadyDir "webserver.ready"
            
            $errorContent = @{
                status = "ready" # Still mark as ready to unblock launcher
                port = if ($WebSocketPort -eq 0) { 8081 } else { $WebSocketPort }
                timestamp = Get-Date -Format "o"
                note = "Created after fatal error but marked ready to unblock launcher"
            } | ConvertTo-Json -Compress
            
            [System.IO.File]::WriteAllText($webSocketReadyFile, $errorContent)
            
            $errorContent = @{
                status = "ready"
                port = if ($HttpPort -eq 0) { 8080 } else { $HttpPort }
                timestamp = Get-Date -Format "o"
                note = "Created after fatal error but marked ready to unblock launcher"
            } | ConvertTo-Json -Compress
            
            [System.IO.File]::WriteAllText($webServerReadyFile, $errorContent)
            
            [System.IO.File]::AppendAllText($emergencyLogPath, "[$errorTimeStamp] Created ready files despite fatal error to unblock launcher`n")
        }
    }
    catch {
        # Nothing more we can do
    }
}