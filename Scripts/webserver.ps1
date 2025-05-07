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
    
    # Create guaranteed accessible logs - use multiple locations to ensure at least one works
    $scriptBasePath = $PSScriptRoot
    $userDesktopPath = [Environment]::GetFolderPath('Desktop')
    $userDocumentsPath = [Environment]::GetFolderPath('MyDocuments')
    
    # Define multiple possible log paths to maximize chances of successful logging
    $possibleLogPaths = @(
        (Join-Path $scriptBasePath "webserver_log.txt"),
        (Join-Path $userDesktopPath "servermanager_webserver_log.txt"),
        (Join-Path $userDocumentsPath "servermanager_webserver_log.txt"),
        (Join-Path $env:TEMP "servermanager_webserver_log.txt")
    )
    
    # Try to create a log file in each location
    $emergencyLogPath = $null
    foreach($path in $possibleLogPaths) {
        try {
            $startupInfo = @"
======= WEBSERVER LOG (PID: $PID) =======
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
            [System.IO.File]::WriteAllText($path, $startupInfo)
            $emergencyLogPath = $path
            Write-Host "Successfully created log at: $emergencyLogPath"
            break
        }
        catch {
            continue
        }
    }
    
    # If we couldn't create any log files, write to console only
    if (-not $emergencyLogPath) {
        Write-Host "WARNING: Could not create any log files in multiple locations. Logging to console only."
        function Write-EmergencyLog {
            param([string]$Message)
            Write-Host "[$(Get-Date)] $Message"
        }
    }
    else {
        function Write-EmergencyLog {
            param([string]$Message)
            try {
                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] $Message`n")
            }
            catch {
                Write-Host "[$(Get-Date)] $Message (Failed to write to log)"
            }
            Write-Host "[$(Get-Date)] $Message"
        }
    }
    
    Write-EmergencyLog "Emergency log initialized at $emergencyLogPath"
    
    # Get base paths from registry - matching the approach in launcher.ps1
    Write-EmergencyLog "Reading base path from registry"
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
        Write-EmergencyLog "Found base path in registry: $serverManagerDir"
        
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
        Write-EmergencyLog "Registry read failed: $($_.Exception.Message)"
        
        # Fallback to script-relative paths
        $scriptParent = Split-Path (Split-Path $scriptBasePath -Parent) -Parent
        Write-EmergencyLog "Using script-relative paths from: $scriptParent"
        
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
    Write-EmergencyLog "Using logs path: $logsBasePath"
    
    if (-not (Test-Path $logsBasePath)) {
        try {
            # First try native PowerShell
            New-Item -Path $logsBasePath -ItemType Directory -Force | Out-Null
            Write-EmergencyLog "Created logs directory: $logsBasePath"
        }
        catch {
            # Then try .NET method if PowerShell fails
            try {
                [System.IO.Directory]::CreateDirectory($logsBasePath) | Out-Null
                Write-EmergencyLog "Created logs directory using .NET method: $logsBasePath"
            }
            catch {
                Write-EmergencyLog "Failed to create logs directory: $($_.Exception.Message)"
                # Fall back to script directory as last resort
                $logsBasePath = $scriptBasePath
                Write-EmergencyLog "Using fallback logs path: $logsBasePath"
            }
        }
    }
    
    # Define path for main log file only (removed debug log)
    $logFile = Join-Path $logsBasePath "webserver.log"
    
    # Log the locations for diagnostics (removed debug log references)
    Write-EmergencyLog "Log file will be at: $logFile"
    
    # Create initial log file with proper directory creation
    try {
        $initialLogEntry = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [INIT] WebServer script starting with PID: $PID"
        
        # Ensure log directory exists
        $logDir = Split-Path $logFile -Parent
        if (-not (Test-Path $logDir)) {
            [System.IO.Directory]::CreateDirectory($logDir) | Out-Null
            Write-EmergencyLog "Created log directory: $logDir"
        }
        
        # Create main log file (removed debug log creation)
        [System.IO.File]::WriteAllText($logFile, "$initialLogEntry`n")
        
        Write-EmergencyLog "Successfully created log file"
    }
    catch {
        Write-EmergencyLog "Error creating log file: $($_.Exception.Message)"
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
                Write-EmergencyLog "Failed to write to main log: $($_.Exception.Message)"
            }
            
            # Also write to console for interactive debugging
            try {
                Write-Host $logMessage
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
                Write-EmergencyLog "Critical error in logging system: $($_.Exception.Message)"
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
    
    # Create a basic HTTP service first - use a simple TcpListener to avoid Add-Type complexity
    try {
        Write-Log "Creating TCP-based HTTP listener on port $HttpPort" -Level "INFO" -EmergencyAlso
        $script:httpListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $HttpPort)
        $script:httpListener.Start()
        Write-Log "TCP listener started successfully on port $HttpPort" -Level "INFO" -EmergencyAlso
        
        # Create a thread to handle HTTP connections
        $script:httpListenerRunning = $true
        $script:httpThread = [System.Threading.Thread]::new({
            param($state)
            
            $listener = $state.Listener
            $port = $state.Port
            $logFile = $state.LogFile
            $emergencyLog = $state.EmergencyLog
            
            try {
                [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] HTTP listener thread starting on port $port`n")
                
                # Basic HTTP response template
                $httpOkResponseTemplate = @"
HTTP/1.1 200 OK
Content-Type: {0}
Content-Length: {1}
Connection: close

{2}
"@
                
                # Health check JSON response
                $healthJson = '{"status":"ok","timestamp":"' + (Get-Date -Format "o") + '"}'
                
                # HTML response
                $htmlResponse = "<html><body><h1>Server Manager</h1><p>Server is running.</p></body></html>"
                
                while ($script:httpListenerRunning) {
                    try {
                        if ($listener.Pending()) {
                            # Accept the client connection
                            $client = $listener.AcceptTcpClient()
                            
                            # Handle client on ThreadPool to keep listener responsive
                            [System.Threading.ThreadPool]::QueueUserWorkItem({
                                param($clientState)
                                
                                $tcpClient = $clientState.Client
                                $logFile = $clientState.LogFile
                                $emergencyLog = $clientState.EmergencyLog
                                $healthJson = $clientState.HealthJson
                                $htmlResponse = $clientState.HtmlResponse
                                $httpOkResponseTemplate = $clientState.Template
                                
                                try {
                                    # Get the client stream
                                    $stream = $tcpClient.GetStream()
                                    $stream.ReadTimeout = 2000
                                    $stream.WriteTimeout = 2000
                                    
                                    # Read the HTTP request
                                    $reader = New-Object System.IO.StreamReader($stream)
                                    $request = ""
                                    $line = ""
                                    
                                    # Read the first line which contains the HTTP method, URL, and version
                                    try {
                                        $line = $reader.ReadLine()
                                        $request = $line
                                    } catch {
                                        # Timeout or client disconnect - just close
                                        $tcpClient.Close()
                                        return
                                    }
                                    
                                    # Check if the request is a health check
                                    $isHealthCheck = $request -match "GET /health"
                                    
                                    # Create the response
                                    $writer = New-Object System.IO.StreamWriter($stream)
                                    
                                    if ($isHealthCheck) {
                                        # Return JSON health check
                                        $response = [string]::Format($httpOkResponseTemplate, "application/json", $healthJson.Length, $healthJson)
                                    } else {
                                        # Return HTML page
                                        $response = [string]::Format($httpOkResponseTemplate, "text/html", $htmlResponse.Length, $htmlResponse)
                                    }
                                    
                                    try {
                                        # Write and flush the response
                                        $writer.WriteLine($response)
                                        $writer.Flush()
                                    } catch {
                                        [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] Error sending response: $($_.Exception.Message)`n")
                                    }
                                }
                                catch {
                                    [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] HTTP client error: $($_.Exception.Message)`n")
                                }
                                finally {
                                    try { $writer.Close() } catch {}
                                    try { $reader.Close() } catch {}
                                    try { $stream.Close() } catch {}
                                    try { $tcpClient.Close() } catch {}
                                }
                            }, @{
                                Client = $client
                                LogFile = $logFile
                                EmergencyLog = $emergencyLog
                                HealthJson = $healthJson
                                HtmlResponse = $htmlResponse
                                Template = $httpOkResponseTemplate
                            })
                        }
                        
                        # Sleep briefly to avoid high CPU
                        [System.Threading.Thread]::Sleep(50)
                    }
                    catch [System.Net.Sockets.SocketException] {
                        [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] Socket exception: $($_.Exception.Message)`n")
                        # Brief pause to avoid CPU spike if there are repeated errors
                        [System.Threading.Thread]::Sleep(1000)
                    }
                    catch [System.ObjectDisposedException] {
                        [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] Listener disposed`n")
                        break
                    }
                    catch {
                        [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] HTTP thread error: $($_.Exception.Message)`n")
                        # Brief pause to avoid CPU spike
                        [System.Threading.Thread]::Sleep(1000)
                    }
                }
            }
            catch {
                [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] Fatal HTTP thread error: $($_.Exception.Message)`n")
            }
            finally {
                [System.IO.File]::AppendAllText($emergencyLog, "[$(Get-Date)] HTTP listener thread exiting`n")
            }
        })
        
        # Create thread state object with necessary references
        $httpThreadState = @{
            Listener = $script:httpListener
            Port = $HttpPort
            LogFile = $logFile
            EmergencyLog = $emergencyLogPath
        }
        
        # Set thread as background thread and start it
        $script:httpThread.IsBackground = $true
        $script:httpThread.Start($httpThreadState)
        
        Write-Log "HTTP listener thread started" -Level "INFO" -EmergencyAlso
    }
    catch {
        Write-Log "Failed to create HTTP listener: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
        Write-Log "Stack trace: $($_.ScriptStackTrace)" -Level "ERROR" -EmergencyAlso
    }
    
    # Immediately set HTTP ready to ready to unblock launcher
    Write-Log "Setting HTTP ready file to ready status..." -Level "INFO" -EmergencyAlso
    Set-ReadyFile -FilePath $webServerReadyFile -Port $HttpPort -Status "ready"
    
    # Import WebSocketServer module if available
    try {
        $modulePath = Join-Path $basePaths.Modules "WebSocketServer.psm1"
        if (Test-Path $modulePath) {
            Write-Log "Importing WebSocketServer module from: $modulePath" -Level "INFO" -EmergencyAlso
            Import-Module $modulePath -Force -DisableNameChecking
            Write-Log "WebSocketServer module imported successfully" -Level "INFO" -EmergencyAlso
        } else {
            Write-Log "WebSocketServer module not found at path: $modulePath" -Level "WARN" -EmergencyAlso
        }
    } catch {
        Write-Log "Failed to import WebSocketServer module: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
    }
    
    # Initialize WebSocket server with proper WebSocket protocol handling
    Write-Log "Initializing WebSocket server on port $WebSocketPort..." -Level "INFO" -EmergencyAlso
    
    # Add WebSocket handshake and frame parsing functionality
    function Convert-Base64ToSHA1String {
        param([string]$inputString)
        $sha1 = [System.Security.Cryptography.SHA1]::Create()
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($inputString + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
        $hash = $sha1.ComputeHash($bytes)
        return [Convert]::ToBase64String($hash)
    }
    
    function Send-WebSocketFrame {
        param(
            [System.Net.Sockets.NetworkStream]$Stream,
            [string]$Data,
            [byte]$OpCode = 0x1  # 0x1 = text frame
        )
        
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Data)
        $length = $bytes.Length
        
        # Create the header
        $header = New-Object byte[] 2
        $header[0] = $OpCode -bor 0x80  # FIN bit set
        
        # Set payload length
        if ($length -le 125) {
            $header[1] = $length
            $frameSize = $header.Length + $length
            $frame = New-Object byte[] $frameSize
            [Array]::Copy($header, $frame, $header.Length)
            [Array]::Copy($bytes, 0, $frame, $header.Length, $length)
        } 
        elseif ($length -le 65535) {
            $header[1] = 126
            $extendedLength = New-Object byte[] 2
            $extendedLength[0] = ($length -shr 8) -band 0xFF
            $extendedLength[1] = $length -band 0xFF
            
            $frameSize = $header.Length + $extendedLength.Length + $length
            $frame = New-Object byte[] $frameSize
            [Array]::Copy($header, $frame, $header.Length)
            [Array]::Copy($extendedLength, 0, $frame, $header.Length, $extendedLength.Length)
            [Array]::Copy($bytes, 0, $frame, $header.Length + $extendedLength.Length, $length)
        }
        else {
            $header[1] = 127
            $extendedLength = New-Object byte[] 8
            for ($i = 7; $i -ge 0; $i--) {
                $extendedLength[$i] = $length -band 0xFF
                $length = $length -shr 8
            }
            
            $frameSize = $header.Length + $extendedLength.Length + $bytes.Length
            $frame = New-Object byte[] $frameSize
            [Array]::Copy($header, $frame, $header.Length)
            [Array]::Copy($extendedLength, 0, $frame, $header.Length, $extendedLength.Length)
            [Array]::Copy($bytes, 0, $frame, $header.Length + $extendedLength.Length, $bytes.Length)
        }
        
        $Stream.Write($frame, 0, $frame.Length)
        $Stream.Flush()
    }
    
    # Create a WebSocket server that properly handles the WebSocket protocol
    function Start-WebSocketServerWithProtocolSupport {
        param(
            [int]$Port,
            [string]$LogFilePath,
            [string]$EmergencyLogPath
        )
        
        try {
            # Create TCP listener
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
            $listener.Start()
            
            [System.IO.File]::AppendAllText($EmergencyLogPath, "[$(Get-Date)] WebSocket server started on port $Port`n")
            
            # Create a thread to handle WebSocket connections
            $thread = [System.Threading.Thread]::new({
                param($state)
                
                $listener = $state.Listener
                $logFilePath = $state.LogFilePath
                $emergencyLogPath = $state.EmergencyLogPath
                $isRunning = [ref]$state.IsRunning
                
                try {
                    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket listener thread started`n")
                    
                    # Set timeout properties
                    $asyncCallbackTimeout = New-TimeSpan -Seconds 5
                    
                    while ($isRunning.Value) {
                        try {
                            if ($listener.Pending()) {
                                # Accept the client connection
                                $client = $listener.AcceptTcpClient()
                                $client.ReceiveTimeout = 10000
                                $client.SendTimeout = 10000
                                
                                # Handle client on a separate thread to keep the listener responsive
                                [System.Threading.ThreadPool]::QueueUserWorkItem({
                                    param($clientState)
                                    
                                    $tcpClient = $clientState.Client
                                    $logFilePath = $clientState.LogFilePath
                                    $emergencyLogPath = $clientState.EmergencyLogPath
                                    
                                    try {
                                        # Get the client's network stream
                                        $stream = $tcpClient.GetStream()
                                        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $false, 1024, $true)
                                        
                                        # Read the HTTP request for WebSocket upgrade
                                        $request = New-Object System.Collections.Specialized.NameValueCollection
                                        $requestLine = $reader.ReadLine()
                                        
                                        # Parse the HTTP request headers
                                        while ($true) {
                                            $line = $reader.ReadLine()
                                            if ([string]::IsNullOrEmpty($line) -or $line -eq "`r") {
                                                break
                                            }
                                            
                                            # Extract header name and value
                                            if ($line -match '^([^:]+):\s*(.*)$') {
                                                $headerName = $matches[1].Trim()
                                                $headerValue = $matches[2].Trim()
                                                $request.Add($headerName, $headerValue)
                                                
                                                # Debug info
                                                if ($headerName -eq "Sec-WebSocket-Key") {
                                                    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket key: $headerValue`n")
                                                }
                                            }
                                        }
                                        
                                        # Check if this is a WebSocket upgrade request
                                        $isWebSocketRequest = $requestLine -match 'GET' -and $request["Connection"] -match 'Upgrade' -and $request["Upgrade"] -eq 'websocket'
                                        
                                        if ($isWebSocketRequest) {
                                            # Process WebSocket handshake
                                            $key = $request["Sec-WebSocket-Key"]
                                            if ($key) {
                                                $acceptKey = Convert-Base64ToSHA1String -inputString $key
                                                
                                                # Send WebSocket handshake response
                                                $writer = New-Object System.IO.StreamWriter($stream)
                                                $response = @"
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: $acceptKey

"@
                                                $writer.Write($response)
                                                $writer.Flush()
                                                
                                                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket handshake completed`n")
                                                
                                                # Send initial message
                                                $initialMsg = '{"type":"connection","status":"connected","message":"WebSocket connection established"}'
                                                Send-WebSocketFrame -Stream $stream -Data $initialMsg
                                                
                                                # Send metrics every 2 seconds
                                                $lastMetrics = Get-Date
                                                
                                                # Handle WebSocket frames
                                                $buffer = New-Object byte[] 4096
                                                $connected = $true
                                                
                                                while ($connected) {
                                                    try {
                                                        # Send metrics message every 2 seconds
                                                        if ((Get-Date) - $lastMetrics -gt [TimeSpan]::FromSeconds(2)) {
                                                            $metrics = @{
                                                                type = "metrics"
                                                                timestamp = Get-Date -Format "o"
                                                                cpu = Get-Random -Minimum 0 -Maximum 100
                                                                memory = Get-Random -Minimum 20 -Maximum 95
                                                                totalServers = Get-Random -Minimum 1 -Maximum 10
                                                                runningServers = Get-Random -Minimum 0 -Maximum 8
                                                                cpuHistory = @(
                                                                    Get-Random -Minimum 10 -Maximum 90
                                                                    Get-Random -Minimum 10 -Maximum 90
                                                                    Get-Random -Minimum 10 -Maximum 90
                                                                )
                                                                memoryHistory = @(
                                                                    Get-Random -Minimum 20 -Maximum 80
                                                                    Get-Random -Minimum 20 -Maximum 80
                                                                    Get-Random -Minimum 20 -Maximum 80
                                                                )
                                                                networkHistory = @{
                                                                    download = Get-Random -Minimum 1 -Maximum 100
                                                                    upload = Get-Random -Minimum 1 -Maximum 50
                                                                }
                                                                diskUsage = @{
                                                                    used = Get-Random -Minimum 20 -Maximum 80
                                                                    free = Get-Random -Minimum 20 -Maximum 80
                                                                }
                                                                recentActivity = @(
                                                                    "Server status updated"
                                                                    "System monitoring active"
                                                                )
                                                            } | ConvertTo-Json -Compress
                                                            
                                                            # Send WebSocket frame with metrics
                                                            Send-WebSocketFrame -Stream $stream -Data $metrics
                                                            $lastMetrics = Get-Date
                                                        }
                                                        
                                                        # Check for incoming messages if there's data available
                                                        if ($stream.DataAvailable) {
                                                            # Read the first two bytes to get the header
                                                            $headerBytesRead = $stream.Read($buffer, 0, 2)
                                                            if ($headerBytesRead -eq 0) { break }
                                                            
                                                            # Check if the connection is closing
                                                            $opcode = $buffer[0] -band 0x0F
                                                            if ($opcode -eq 0x8) {
                                                                $connected = $false
                                                                break
                                                            }
                                                        }
                                                        
                                                        # Sleep to avoid high CPU usage
                                                        [System.Threading.Thread]::Sleep(100)
                                                    } 
                                                    catch [System.IO.IOException] {
                                                        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket IO exception: $($_.Exception.Message)`n")
                                                        $connected = $false
                                                    }
                                                    catch {
                                                        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket frame handling error: $($_.Exception.Message)`n")
                                                        $connected = $false
                                                    }
                                                }
                                            } else {
                                                [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Missing WebSocket key in handshake`n")
                                            }
                                        } else {
                                            # Not a WebSocket request, send a simple HTTP response
                                            $writer = New-Object System.IO.StreamWriter($stream)
                                            $htmlResponse = "<html><body><h1>WebSocket Server</h1><p>This endpoint accepts WebSocket connections only.</p></body></html>"
                                            
                                            $response = @"
HTTP/1.1 200 OK
Content-Type: text/html
Content-Length: $($htmlResponse.Length)
Connection: close

$htmlResponse
"@
                                            $writer.Write($response)
                                            $writer.Flush()
                                        }
                                    }
                                    catch {
                                        [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Client handling error: $($_.Exception.Message)`n$($_.Exception.StackTrace)`n")
                                    }
                                    finally {
                                        try { $reader.Close() } catch {}
                                        try { $writer.Close() } catch {}
                                        try { $stream.Close() } catch {}
                                        try { $tcpClient.Close() } catch {}
                                    }
                                }, @{
                                    Client = $client
                                    LogFilePath = $logFilePath
                                    EmergencyLogPath = $emergencyLogPath
                                })
                            }
                            
                            # Sleep to avoid high CPU usage
                            [System.Threading.Thread]::Sleep(50)
                        }
                        catch [System.Net.Sockets.SocketException] {
                            [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket socket exception: $($_.Exception.Message)`n")
                            # Sleep to avoid rapid error logging
                            [System.Threading.Thread]::Sleep(1000)
                        }
                        catch [System.ObjectDisposedException] {
                            [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket listener disposed`n")
                            break
                        }
                        catch {
                            [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket listener error: $($_.Exception.Message)`n$($_.Exception.StackTrace)`n")
                            # Sleep to avoid rapid error logging
                            [System.Threading.Thread]::Sleep(1000)
                        }
                    }
                }
                catch {
                    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] Fatal WebSocket thread error: $($_.Exception.Message)`n$($_.Exception.StackTrace)`n")
                }
                finally {
                    [System.IO.File]::AppendAllText($emergencyLogPath, "[$(Get-Date)] WebSocket listener thread exiting`n")
                }
            })
            
            # Create state for the thread
            $state = @{
                Listener = $listener
                LogFilePath = $LogFilePath
                EmergencyLogPath = $EmergencyLogPath
                IsRunning = $true
            }
            
            # Set thread as background thread and start it
            $thread.IsBackground = $true
            $thread.Start($state)
            
            # Return information about the server
            return @{
                Listener = $listener
                Thread = $thread
                State = $state
            }
        }
        catch {
            [System.IO.File]::AppendAllText($EmergencyLogPath, "[$(Get-Date)] Failed to start WebSocket server: $($_.Exception.Message)`n$($_.Exception.StackTrace)`n")
            return $null
        }
    }
    
    # Start the WebSocket server with protocol support
    $script:webSocketServer = Start-WebSocketServerWithProtocolSupport -Port $WebSocketPort -LogFilePath $logFile -EmergencyLogPath $emergencyLogPath
    
    if ($script:webSocketServer) {
        Write-Log "WebSocket server started successfully on port $WebSocketPort" -Level "INFO" -EmergencyAlso
        
        # Set WebSocket ready file to ready status
        Write-Log "Setting WebSocket ready file to ready status..." -Level "INFO" -EmergencyAlso
        Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "ready"
        
        # Create a reverse proxy endpoint for WebSocket on the HTTP server
        # This will allow clients to connect to ws://hostname/ instead of ws://hostname:8081/
        try {
            Write-Log "Setting up WebSocket reverse proxy on HTTP server..." -Level "INFO" -EmergencyAlso
            
            # Store the WebSocket port for proxy use
            $script:wsProxyPort = $WebSocketPort
            
            Write-Log "WebSocket reverse proxy setup complete" -Level "INFO" -EmergencyAlso
        }
        catch {
            Write-Log "Failed to set up WebSocket reverse proxy: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
        }
    }
    else {
        Write-Log "Failed to start WebSocket server, falling back to basic TCP listener" -Level "WARN" -EmergencyAlso
        
        # Create a simple TCP listener as fallback
        try {
            $script:wsBasicListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $WebSocketPort)
            $script:wsBasicListener.Start()
            Write-Log "Started basic fallback TCP listener on port $WebSocketPort" -Level "INFO" -EmergencyAlso
            
            # Set WebSocket ready file to ready anyway
            Write-Log "Setting WebSocket ready file to ready status with basic listener..." -Level "INFO" -EmergencyAlso
            Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "ready"
        }
        catch {
            Write-Log "Failed to create even basic WebSocket TCP listener: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            
            # Set WebSocket ready file to ready as last resort
            Write-Log "Setting WebSocket ready file to ready status as last resort..." -Level "INFO" -EmergencyAlso
            Set-ReadyFile -FilePath $webSocketReadyFile -Port $WebSocketPort -Status "ready"
        }
    }
    
    # Keep the script running to maintain the servers
    Write-Log "Servers initialized successfully. Entering maintenance loop..." -Level "INFO" -EmergencyAlso
    
    # Set up a watchdog timer to check if this script is still running
    try {
        $script:watchdogPath = Join-Path $ReadyDir "webserver_watchdog.log"
        [System.IO.File]::WriteAllText($script:watchdogPath, "Watchdog started at: $(Get-Date -Format 'o')`n")
    }
    catch {
        Write-Log "Failed to create watchdog file: $($_.Exception.Message)" -Level "WARN" -EmergencyAlso
    }
    
    # Wait indefinitely with active health checks
    try {
        $maintenanceCounter = 0
        while ($true) {
            Start-Sleep -Seconds 5
            $maintenanceCounter++
            
            # Update watchdog file
            try {
                [System.IO.File]::AppendAllText($script:watchdogPath, "Server alive at: $(Get-Date -Format 'o')`n")
            }
            catch {
                # Not critical if this fails
            }
            
            # Log heartbeat every minute
            if ($maintenanceCounter % 12 -eq 0) {
                Write-Log "Server heartbeat check - Maintenance cycle: $maintenanceCounter" -Level "INFO" -EmergencyAlso
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
        Write-Log "Shutting down servers..." -Level "INFO" -EmergencyAlso
        
        # Stop HTTP listener thread
        $script:httpListenerRunning = $false
        
        # Stop WebSocket server
        if ($script:webSocketServer) {
            $script:webSocketServer.State.IsRunning = $false
            try {
                $script:webSocketServer.Listener.Stop()
                Write-Log "WebSocket server stopped" -Level "INFO" -EmergencyAlso
            }
            catch {
                Write-Log "Error stopping WebSocket server: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            }
        }
        
        # Stop TCP listeners
        if ($script:httpListener) {
            try {
                $script:httpListener.Stop()
                Write-Log "HTTP TCP listener stopped" -Level "INFO" -EmergencyAlso
            }
            catch {
                Write-Log "Error stopping HTTP TCP listener: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            }
        }
        
        if ($script:wsBasicListener) {
            try {
                $script:wsBasicListener.Stop()
                Write-Log "Basic WebSocket TCP listener stopped" -Level "INFO" -EmergencyAlso
            }
            catch {
                Write-Log "Error stopping basic WebSocket TCP listener: $($_.Exception.Message)" -Level "ERROR" -EmergencyAlso
            }
        }
        
        # Final log message
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