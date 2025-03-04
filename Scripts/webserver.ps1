# Set strict error handling and debugging
$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

# Initialize basic logging first
$logFile = Join-Path $PSScriptRoot "webserver.log"

function Write-WebServerLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    Write-Verbose $logMessage
    Add-Content -Path $logFile -Value $logMessage -ErrorAction SilentlyContinue
}

# Add WebSocket initialization check
function Test-WebSocketServer {
    param (
        [int]$TimeoutSeconds = 30
    )
    
    $startTime = Get-Date
    while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($TimeoutSeconds)) {
        if (Test-Path $script:ReadyFiles.WebSocket) {
            $config = Get-Content $script:ReadyFiles.WebSocket -Raw | ConvertFrom-Json
            if ($config.status -eq "ready") {
                # Verify port is actually listening
                $tcpClient = New-Object System.Net.Sockets.TcpClient
                try {
                    if ($tcpClient.ConnectAsync("localhost", $config.port).Wait(1000)) {
                        Write-WebServerLog "WebSocket server is ready on port $($config.port)"
                        return $true
                    }
                }
                catch {
                    Write-WebServerLog "WebSocket port not responding: $_"
                }
                finally {
                    $tcpClient.Dispose()
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Add before starting servers
function Add-RequiredAccess {
    param(
        [int]$Port,
        [string]$Protocol = "http"
    )
    
    try {
        $urlPrefix = "${Protocol}://+:${Port}/"
        Write-WebServerLog "Setting up access for $urlPrefix"
        
        # Get current user
        $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        
        # Check existing URL ACL
        $existingAcl = netsh http show urlacl url=$urlPrefix 2>&1
        if ($existingAcl -match 'URL reservation successfully') {
            Write-WebServerLog "URL ACL already exists for $urlPrefix"
            
            # Check if we need to modify the ACL
            if ($existingAcl -notmatch [regex]::Escape($currentUser)) {
                Write-WebServerLog "Updating URL ACL for $urlPrefix"
                # Delete existing ACL first
                $null = netsh http delete urlacl url=$urlPrefix
                # Add new ACL
                $result = netsh http add urlacl url=$urlPrefix user=$currentUser
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to update URL ACL: $result"
                }
            }
        } else {
            Write-WebServerLog "Adding URL ACL for $urlPrefix"
            $result = netsh http add urlacl url=$urlPrefix user=$currentUser
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to add URL ACL: $result"
            }
        }
        
        # Add firewall rule if needed
        $ruleName = "ServerManager_${Protocol}_${Port}"
        $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if (-not $existingRule) {
            Write-WebServerLog "Adding firewall rule for port $Port"
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
        }
        
        return $true
    }
    catch {
        Write-WebServerLog "Failed to set up access: $_"
        return $false
    }
}

try {
    Write-WebServerLog "Starting web server initialization..."
    
    # Define script-scoped variables
    $script:http = $null
    $script:wsServer = $null
    $script:isRunning = $true

    # Get registry and base paths
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')

    # Initialize paths structure
    $paths = @{
        Root = $serverManagerDir
        Logs = Join-Path $serverManagerDir "logs"
        Config = Join-Path $serverManagerDir "config"
        Temp = Join-Path $serverManagerDir "temp"
        Modules = Join-Path $serverManagerDir "Modules"
    }

    # Create directories and move log file
    foreach ($dir in $paths.Values) {
        New-Item -Path $dir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
    }
    
    $properLogPath = Join-Path $paths.Logs "webserver.log"
    Move-Item -Path $logFile -Destination $properLogPath -Force -ErrorAction SilentlyContinue
    $logFile = $properLogPath

    Write-WebServerLog "Directories initialized"

    # Import required modules
    $modulesToLoad = @(
        "WebSocketServer",
        "Common"
    )

    # Define Write-WebSocketLog for the WebSocketServer module to use
    function Global:Write-WebSocketLog {
        param(
            [string]$Message,
            [string]$Level = "INFO",
            [switch]$DetailLog
        )
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $logMessage = "[$timestamp] [$Level] $Message"
        Write-WebServerLog $logMessage
    }

    foreach ($module in $modulesToLoad) {
        try {
            $modulePath = Join-Path $paths.Modules "$module.psm1"
            Write-WebServerLog "Loading module: $modulePath"
            Import-Module $modulePath -Force -ErrorAction Stop
            Write-WebServerLog "Successfully loaded $module module"
        }
        catch {
            throw "Failed to load $module module: $_"
        }
    }

    # Test ports directly
    foreach ($port in @(8080, 8081)) {
        try {
            $tcpTest = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $port)
            $tcpTest.Start()
            $tcpTest.Stop()
            Write-WebServerLog "Port $port is available"
        }
        catch {
            Write-WebServerLog "Port $port is in use, attempting to release..."
            # Try to get process using the port
            $processInfo = netstat -ano | Select-String ":$port " | ForEach-Object {
                if ($_ -match ":$port.*LISTENING.*?(\d+)") {
                    return $matches[1]
                }
            }
            
            if ($processInfo) {
                Write-WebServerLog "Found process $processInfo using port $port"
                Stop-Process -Id $processInfo -Force
                Start-Sleep -Seconds 1
                
                # Test port again
                $tcpTest = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $port)
                $tcpTest.Start()
                $tcpTest.Stop()
                Write-WebServerLog "Successfully cleared port $port"
            }
            else {
                throw "Could not clear port $port"
            }
        }
    }

    # Add required access
    foreach ($port in @(8080, 8081)) {
        $success = Add-RequiredAccess -Port $port
        if (-not $success) {
            # Instead of throwing, try to delete and recreate
            Write-WebServerLog "Attempting to reset URL ACL for port $port"
            $urlPrefix = "http://+:${port}/"
            $null = netsh http delete urlacl url=$urlPrefix 2>&1
            Start-Sleep -Seconds 1
            
            $success = Add-RequiredAccess -Port $port
            if (-not $success) {
                throw "Failed to set up server access for port $port after reset attempt"
            }
        }
    }

    # Start WebSocket server first
    $script:wsServer = New-WebSocketServer -Port 8081 -HostName "+" -ServerDirectory $serverManagerDir
    if (-not (Test-WebSocketServer -TimeoutSeconds 30)) {
        throw "WebSocket server failed to initialize"
    }

    Write-WebServerLog "Starting HTTP listener on port 8080"
    $script:http = New-Object System.Net.HttpListener
    $script:http.Prefixes.Add("http://+:8080/")

    try {
        # Create ready file to indicate web server is initialized
        $config = @{
            status = "ready"
            port = 8080
            timestamp = Get-Date -Format "o"
        }

        Write-WebServerLog "Creating web server ready file..." -Level DEBUG
        $config | ConvertTo-Json | Set-Content -Path (Join-Path $paths.Temp "webserver.ready") -Force
        Write-WebServerLog "Web server ready file created at: $($script:ReadyFiles.WebServer)" -Level INFO

        # Start the web server
        Write-WebServerLog "Starting web server..." -Level INFO
        $script:http.Start()

        Write-WebServerLog "HTTP server started successfully"
        
        # Signal HTTP ready immediately after successful start
        $readyConfig = @{
            status = "ready"
            port = 8080
            timestamp = Get-Date -Format "o"
        }
        $readyConfig | ConvertTo-Json | Set-Content -Path (Join-Path $paths.Temp "webserver.ready") -Force
        Write-WebServerLog "HTTP ready status written"
        
        Write-WebServerLog "WebSocket server initialized"

        # Write WebSocket PID after initialization
        try {
            $pidInfo = @{
                ProcessId = $PID
                StartTime = Get-Date -Format "o"
                ProcessPath = (Get-Process -Id $PID).Path
                CommandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $PID").CommandLine
            }
            
            $pidFile = Join-Path $paths.Temp "websocket.pid"
            $pidInfo | ConvertTo-Json | Set-Content -Path $pidFile -Force
        } catch {
            Write-WebServerLog "Failed to write PID file: $_"
        }

        # Add cleanup on exit
        $exitScript = {
            $pidFile = Join-Path $paths.Temp "websocket.pid"
            Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
        }

        Register-EngineEvent PowerShell.Exiting -Action $exitScript | Out-Null
        
        # Main server loop
        while ($true) {
            try {
                $context = $script:http.GetContext()
                
                Start-ThreadJob -ScriptBlock {
                    param($ctx)
                    try {
                        $response = $ctx.Response
                        $content = [System.Text.Encoding]::UTF8.GetBytes("Server Manager API")
                        $response.ContentLength64 = $content.Length
                        $response.ContentType = "text/plain"
                        $response.OutputStream.Write($content, 0, $content.Length)
                    }
                    finally {
                        if ($response) { $response.Close() }
                    }
                } -ArgumentList $context
            }
            catch {
                Write-WebServerLog "Error in request handling: $_"
                if (-not $script:http.IsListening) { break }
            }
        }
    }
    catch {
        Write-WebServerLog "Failed to start web server: $_" -Level ERROR
        throw
    }
}
catch {
    Write-WebServerLog "Fatal error: $_"
    Write-WebServerLog $_.ScriptStackTrace
    throw
}
finally {
    $script:isRunning = $false
    
    if ($script:http -and $script:http.IsListening) {
        $script:http.Stop()
        $script:http.Close()
    }
    
    if ($script:wsServer) {
        $script:wsServer.Stop()
    }
    
    Write-WebServerLog "Server shutdown complete"
}