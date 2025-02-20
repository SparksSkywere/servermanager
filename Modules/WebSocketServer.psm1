# Module initialization
using namespace System.Net.WebSockets
using namespace System.Net
using namespace System.Text

# Initialize module variables with default paths
$script:DefaultWebSocketPort = 8081
$script:DefaultWebPort = 8080

# Get registry path for server manager directory
$script:ServerManagerDir = (Get-ItemProperty -Path "HKLM:\Software\SkywereIndustries\servermanager" -ErrorAction Stop).servermanagerdir
$script:ServerManagerDir = $script:ServerManagerDir.Trim('"', ' ', '\')

# Initialize paths structure
$script:Paths = @{
    Root = $script:ServerManagerDir
    Logs = Join-Path $script:ServerManagerDir "logs"
    Config = Join-Path $script:ServerManagerDir "config"
    Temp = Join-Path $script:ServerManagerDir "temp"
    Modules = Join-Path $script:ServerManagerDir "Modules"
}

# Initialize ready file paths
$script:ReadyFiles = @{
    WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
    WebServer = Join-Path $script:Paths.Temp "webserver.ready"
}

# Define Get-WebSocketPaths to use initialized paths
function Get-WebSocketPaths {
    # Return cached paths from module scope
    return @{
        WebSocketReadyFile = $script:ReadyFiles.WebSocket
        WebServerReadyFile = $script:ReadyFiles.WebServer
        DefaultWebSocketPort = $script:DefaultWebSocketPort
        DefaultWebPort = $script:DefaultWebPort
        TempPath = $script:Paths.Temp
    }
}

# Add these helper functions at the top after the using statements
function Get-WebSocketAcceptKey {
    param([string]$key)
    
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
        $hash = $sha1.ComputeHash($bytes)
        return [Convert]::ToBase64String($hash)
    }
    finally {
        $sha1.Dispose()
    }
}

# WebSocket server and client classes
class WebSocketServer {
    hidden [System.Net.HttpListener]$Listener
    hidden [bool]$IsRunning
    hidden [hashtable]$Connections
    hidden [string]$ServerDirectory
    
    WebSocketServer([string]$serverDir) {
        $this.IsRunning = $false
        $this.Connections = @{}
        $this.ServerDirectory = $serverDir
        $this.Listener = [System.Net.HttpListener]::new()
    }
    
    [bool] Initialize([int]$Port = 8081, [string]$HostName = "localhost") {
        try {
            Write-WebSocketLog "Initializing WebSocket server on ${HostName}:${Port}" -Level INFO
            
            # Clear ready file first
            if (Test-Path $script:ReadyFiles.WebSocket) {
                Remove-Item $script:ReadyFiles.WebSocket -Force
            }

            # Check and add URL reservation if needed
            $urlPrefix = "http://+:${Port}/"
            try {
                Write-WebSocketLog "Checking URL ACL for $urlPrefix" -Level DEBUG
                $null = netsh http show urlacl url=$urlPrefix 2>&1
            }
            catch {
                Write-WebSocketLog "Adding URL ACL for $urlPrefix" -Level INFO
                $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
                $result = netsh http add urlacl url=$urlPrefix user=$currentUser
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to add URL ACL: $result"
                }
            }

            # Check and add firewall rule if needed
            $ruleName = "ServerManager_WebSocket_$Port"
            $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            if (-not $existingRule) {
                Write-WebSocketLog "Adding firewall rule for port $Port" -Level INFO
                New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
            }

            # Test port availability with proper error handling
            try {
                $tcpTest = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
                $tcpTest.Start()
                $tcpTest.Stop()
                Write-WebSocketLog "Port $Port is available" -Level DEBUG
            }
            catch {
                throw "Port $Port is not available: $_"
            }
            
            # Setup listener with proper prefix
            $this.Listener.Prefixes.Clear()
            $this.Listener.Prefixes.Add($urlPrefix)
            
            # Try to start the listener
            try {
                $this.Listener.Start()
                Write-WebSocketLog "WebSocket listener started successfully" -Level INFO
            }
            catch {
                throw "Failed to start listener: $_"
            }

            # Write ready file
            $config = @{
                status = "ready"
                port = $Port
                timestamp = Get-Date -Format "o"
            }
            
            $config | ConvertTo-Json | Set-Content -Path $script:ReadyFiles.WebSocket -Force
            Write-WebSocketLog "Ready file created at: $($script:ReadyFiles.WebSocket)" -Level INFO
            
            return $true
        }
        catch {
            Write-WebSocketLog "Failed to initialize WebSocket server: $_" -Level ERROR
            return $false
        }
    }
    
    [void] Start() {
        if (-not $this.Listener) {
            throw "WebSocket server not initialized"
        }
        
        try {
            # Add URL reservation if needed
            $prefix = $this.Listener.Prefixes | Select-Object -First 1
            if ($prefix) {
                $urlAcl = netsh http show urlacl $prefix
                if (-not $urlAcl) {
                    Write-WebSocketLog "Adding URL reservation for $prefix" -Level INFO
                    $null = netsh http add urlacl url=$prefix user=Everyone
                }
            }

            Write-WebSocketLog "Starting WebSocket listener..." -Level INFO
            $this.Listener.Start()
            $this.IsRunning = $true
            
            Write-WebSocketLog "Starting message handling loop..." -Level INFO
            while ($this.IsRunning) {
                try {
                    $context = $this.Listener.GetContext()
                    
                    # Handle request in background job to prevent blocking
                    Start-ThreadJob -ScriptBlock {
                        param($context, $server)
                        try {
                            $server.HandleClient($context)
                        }
                        catch {
                            Write-WebSocketLog "Client handler error: $_" -Level ERROR
                        }
                    } -ArgumentList $context, $this
                }
                catch {
                    if ($this.IsRunning) {
                        Write-WebSocketLog "Error accepting connection: $_" -Level ERROR
                    }
                }
            }
        }
        catch {
            Write-WebSocketLog "Critical WebSocket server error: $_" -Level ERROR
            $this.IsRunning = $false
            throw
        }
        finally {
            Write-WebSocketLog "WebSocket server shutting down..." -Level INFO
            if ($this.Listener.IsListening) {
                $this.Listener.Stop()
            }
        }
    }
    
    hidden [void] HandleClient($context) {
        $clientId = [Guid]::NewGuid().ToString()  # Define ID at the start
        
        try {
            if ($context.Request.IsWebSocketRequest) {
                $wsContext = $context.AcceptWebSocketAsync().Result
                $this.Connections[$clientId] = $wsContext.WebSocket
                
                Write-WebSocketLog "Client ${clientId} connected" -Level INFO
                
                # Handle messages in a loop
                $buffer = [byte[]]::new(4096)
                $segment = [ArraySegment[byte]]::new($buffer)
                
                while ($wsContext.WebSocket.State -eq [WebSocketState]::Open) {
                    $result = $wsContext.WebSocket.ReceiveAsync($segment, [Threading.CancellationToken]::None).Result
                    
                    if ($result.MessageType -eq [WebSocketMessageType]::Text) {
                        $messageText = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                        Write-WebSocketLog "Received from ${clientId}: ${messageText}" -Level DEBUG
                        
                        # Echo back
                        $response = [Text.Encoding]::UTF8.GetBytes("Echo: ${messageText}")
                        $responseSegment = [ArraySegment[byte]]::new($response)
                        $wsContext.WebSocket.SendAsync(
                            $responseSegment,
                            [WebSocketMessageType]::Text,
                            $true,
                            [Threading.CancellationToken]::None
                        ).Wait()
                    }
                }
            }
            else {
                Write-WebSocketLog "Non-WebSocket request received" -Level WARN
                $context.Response.StatusCode = 400
                $context.Response.Close()
            }
        }
        catch {
            Write-WebSocketLog "Client handler error: $_" -Level ERROR
        }
        finally {
            if ($this.Connections.ContainsKey($clientId)) {
                $this.Connections.Remove($clientId)
                Write-WebSocketLog "Removed client ${clientId}" -Level DEBUG
            }
        }
    }
    
    hidden [bool] PerformHandshake($context) {
        try {
            Write-WebSocketLog "Starting WebSocket handshake" -Level DEBUG
            $request = $context.Request
            $response = $context.Response
            
            # Log headers for debugging
            Write-WebSocketLog "Request headers:" -Level DEBUG
            foreach ($key in $request.Headers.AllKeys) {
                Write-WebSocketLog "${key}: $($request.Headers[$key])" -Level DEBUG
            }
            
            # Check for WebSocket upgrade
            $upgrade = $request.Headers["Upgrade"]
            $connection = $request.Headers["Connection"]
            if ((-not $upgrade) -or ($upgrade -ne "websocket") -or
                (-not $connection) -or ($connection -notlike "*upgrade*")) {
                Write-WebSocketLog "Not a valid WebSocket upgrade request" -Level WARN
                $response.StatusCode = 400
                $response.Close()
                return $false
            }

            # Verify WebSocket version
            $version = $request.Headers["Sec-WebSocket-Version"]
            if (-not $version -or $version -ne "13") {
                Write-WebSocketLog "Invalid WebSocket version" -Level WARN
                $response.StatusCode = 426
                $response.Headers.Add("Sec-WebSocket-Version", "13")
                $response.Close()
                return $false
            }

            # Get and validate security key
            $secKey = $request.Headers["Sec-WebSocket-Key"]
            if ([string]::IsNullOrEmpty($secKey)) {
                Write-WebSocketLog "Missing Sec-WebSocket-Key header" -Level WARN
                $response.StatusCode = 400
                $response.Close()
                return $false
            }

            # Calculate accept key
            $acceptKey = Get-WebSocketAcceptKey $secKey
            
            # Check for subprotocols
            $protocols = $request.Headers.GetValues("Sec-WebSocket-Protocol")
            if ($protocols -and $protocols.Contains("dashboard")) {
                $response.Headers.Add("Sec-WebSocket-Protocol", "dashboard")
            }

            # Send handshake response
            $response.StatusCode = 101
            $response.Headers.Add("Upgrade", "websocket")
            $response.Headers.Add("Connection", "Upgrade")
            $response.Headers.Add("Sec-WebSocket-Accept", $acceptKey)
            
            Write-WebSocketLog "Handshake response headers:" -Level DEBUG
            foreach ($key in $response.Headers.AllKeys) {
                Write-WebSocketLog "${key}: $($response.Headers[$key])" -Level DEBUG
            }
            
            $response.Close()
            
            Write-WebSocketLog "WebSocket handshake completed successfully" -Level DEBUG
            return $true
        }
        catch {
            Write-WebSocketLog "Handshake error: $_" -Level ERROR
            Write-WebSocketLog $_.ScriptStackTrace -Level ERROR
            return $false
        }
    }
    
    [void] Stop() {
        $this.IsRunning = $false
        if ($this.Listener) {
            $this.Listener.Stop()
            $this.Listener.Close()
        }
        
        # Clean up runspace resources
        if ($this.PSObject.Properties['PowerShell']) {
            $this.PowerShell.Stop()
            $this.PowerShell.Dispose()
        }
        if ($this.PSObject.Properties['Runspace']) {
            $this.Runspace.Dispose()
        }
        
        Write-WebSocketLog "WebSocket server stopped" -Level INFO
    }
    
    [hashtable] GetStatus() {
        return @{
            IsRunning = $this.IsRunning
            ConnectionCount = $this.Connections.Count
            ListenerActive = $this.Listener -and $this.Listener.IsListening
        }
    }
}

class WebSocketClient {
    hidden [System.Net.WebSockets.ClientWebSocket]$Socket
    hidden [string]$Id
    hidden [string]$ServerUrl
    
    WebSocketClient([string]$serverUrl) {
        $this.Socket = [ClientWebSocket]::new()
        $this.Id = [Guid]::NewGuid().ToString()
        $this.ServerUrl = $serverUrl
    }
    
    [void] Connect() {
        if ($this.Socket.State -ne [WebSocketState]::None) {
            throw "WebSocket is not in initial state"
        }
        
        try {
            $task = $this.Socket.ConnectAsync([Uri]::new($this.ServerUrl), [Threading.CancellationToken]::None)
            $task.Wait()
            Write-Host "Connected to WebSocket server at $($this.ServerUrl)"
        }
        catch {
            Write-Error "Failed to connect to WebSocket server: $($_.Exception.Message)"
            throw
        }
    }
    
    [void] Disconnect() {
        if ($this.Socket.State -eq [WebSocketState]::Open) {
            try {
                $task = $this.Socket.CloseAsync([WebSocketCloseStatus]::NormalClosure, "Client disconnecting", [Threading.CancellationToken]::None)
                $task.Wait()
                Write-Host "Disconnected from WebSocket server"
            }
            catch {
                Write-Error "Failed to disconnect from WebSocket server: $($_.Exception.Message)"
                throw
            }
        }
    }
    
    [string] GetId() {
        return $this.Id
    }
}

# Core WebSocket functions
function New-WebSocketServer {
    [CmdletBinding()]
    [OutputType([WebSocketServer])]
    param (
        [Parameter(Mandatory=$false)]
        [int]$Port = 8081,
        
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost",
        
        [Parameter(Mandatory=$true)]
        [string]$ServerDirectory
    )
    
    Write-Verbose "Creating WebSocket server with directory: $ServerDirectory"
    
    try {
        # Create and initialize server
        $server = [WebSocketServer]::new($ServerDirectory)
        if (-not $server.Initialize($Port, $HostName)) {
            throw "Server initialization failed"
        }

        # Create a runspace for the server
        $runspace = [runspacefactory]::CreateRunspace()
        $runspace.Open()
        $runspace.SessionStateProxy.SetVariable('server', $server)
        
        # Create PowerShell instance to run server
        $ps = [powershell]::Create().AddScript({
            param($server)
            try {
                $server.Start()
            }
            catch {
                Write-Error "WebSocket server error: $_"
            }
        }).AddArgument($server)
        
        # Set runspace and start async
        $ps.Runspace = $runspace
        
        # Store async handle to prevent GC and allow checking status
        $server | Add-Member -NotePropertyName AsyncHandle -NotePropertyValue ($ps.BeginInvoke())
        $server | Add-Member -NotePropertyName PowerShell -NotePropertyValue $ps
        $server | Add-Member -NotePropertyName Runspace -NotePropertyValue $runspace
        
        # Wait briefly and verify server started
        Start-Sleep -Seconds 2
        if (-not (Test-WebSocketReady)) {
            throw "Server failed to start and become ready"
        }
        
        return $server
    }
    catch {
        Write-Error "Error creating WebSocket server: $_"
        if ($runspace) { $runspace.Dispose() }
        if ($ps) { $ps.Dispose() }
        throw
    }
}

function New-WebSocketClient {
    [CmdletBinding()]
    [OutputType([WebSocketClient])]
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerUrl
    )
    
    return [WebSocketClient]::new($ServerUrl)
}

function Send-WebSocketMessage {
    [CmdletBinding()]
    param(
        [System.Net.WebSockets.WebSocket]$WebSocket,
        [string]$Message
    )
    
    $buffer = [System.Text.Encoding]::UTF8.GetBytes($Message)
    $segment = [ArraySegment[byte]]::new($buffer)
    
    $WebSocket.SendAsync(
        $segment,
        [WebSocketMessageType]::Text,
        $true,
        [System.Threading.CancellationToken]::None
    ).Wait()
}

function Test-WebSocketConnection {
    [CmdletBinding()]
    param(
        [int]$Port = 8081,
        [string]$HostName = "localhost",
        [int]$Timeout = 2000
    )
    
    $tcpClient = $null
    try {
        Write-WebSocketLog "Testing TCP connection to ${HostName}:${Port}" -Level DEBUG -DetailLog
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connectResult = $tcpClient.ConnectAsync($HostName, $Port).Wait($Timeout)
        
        if ($connectResult) {
            Write-WebSocketLog "TCP connection test successful" -Level DEBUG -DetailLog
            return $true
        } else {
            Write-WebSocketLog "TCP connection test failed (timeout)" -Level WARN
            return $false
        }
    }
    catch {
        Write-WebSocketLog "TCP connection test error: $($_.Exception.Message)" -Level ERROR
        return $false
    }
    finally {
        if ($null -ne $tcpClient) {
            $tcpClient.Dispose()
        }
    }
}

function Set-WebSocketReady {
    param(
        [string]$Status = "ready",
        [int]$Port = 8081,
        [string]$ReadyFile = (Join-Path $script:Paths.Temp "websocket.ready")
    )
    
    $config = @{
        status = $Status
        port = $Port
        timestamp = Get-Date -Format "o"
    } | ConvertTo-Json
    
    Set-Content -Path $ReadyFile -Value $config -Force
}

function Test-WebSocketReady {
    param(
        [string]$ReadyFile = (Join-Path $script:Paths.Temp "websocket.ready")
    )
    
    if (Test-Path $ReadyFile) {
        $content = Get-Content $ReadyFile -Raw | ConvertFrom-Json
        return $content.status -eq "ready"
    }
    return $false
}

# Add WebSocket message handling helpers
function Get-WebSocketFrameBytes {
    param(
        [string]$Message,
        [bool]$Masked = $false
    )
    
    $bytes = [Text.Encoding]::UTF8.GetBytes($Message)
    $length = $bytes.Length
    $frameBytes = New-Object System.Collections.ArrayList
    
    # Add frame header
    $header = 0x81  # Final fragment, text frame
    $frameBytes.Add($header) | Out-Null
    
    # Add length
    if ($length -le 125) {
        $frameBytes.Add($length) | Out-Null
    }
    elseif ($length -le 65535) {
        $frameBytes.Add(126) | Out-Null
        $frameBytes.Add(($length -shr 8) -band 0xFF) | Out-Null
        $frameBytes.Add($length -band 0xFF) | Out-Null
    }
    else {
        $frameBytes.Add(127) | Out-Null
        for ($i = 7; $i -ge 0; $i--) {
            $frameBytes.Add(($length -shr ($i * 8)) -band 0xFF) | Out-Null
        }
    }
    
    # Add message bytes
    $frameBytes.AddRange($bytes)
    return $frameBytes.ToArray()
}

# Export everything at the end
$ExportFunctions = @(
    'Get-WebSocketPaths',  # Make sure this is first
    'New-WebSocketServer',
    'New-WebSocketClient',
    'Send-WebSocketMessage',
    'Test-WebSocketConnection',
    'Set-WebSocketReady',
    'Test-WebSocketReady'
)

# Export functions to global scope
foreach ($function in $ExportFunctions) {
    Set-Item "function:Global:$function" -Value (Get-Item "function:$function").ScriptBlock
}

# Export module members
Export-ModuleMember -Function @(
    'New-WebSocketServer',
    'Get-WebSocketPaths',
    'Test-WebSocketReady',
    'Set-WebSocketReady'
) -Variable @(
    'DefaultWebSocketPort',
    'DefaultWebPort',
    'WebSocketReadyFile',
    'WebServerReadyFile'
)

# Type data for classes
Update-TypeData -TypeName WebSocketServer -MemberType NoteProperty -MemberName IsWebSocketServer -Value $true -Force
Update-TypeData -TypeName WebSocketClient -MemberType NoteProperty -MemberName IsWebSocketClient -Value $true -Force
