using namespace System.Net.WebSockets
using namespace System.Net
using namespace System.Text

# Module-level variables
$script:DefaultWebSocketPort = 8081
$script:DefaultWebPort = 8080
$script:WebSocketReadyFile = Join-Path $env:TEMP "websocket_ready.flag"
$script:WebServerReadyFile = Join-Path $env:TEMP "webserver_ready.flag"

# Main module functions
function Global:Get-WebSocketPaths {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param()
    
    return @{
        WebSocketReadyFile = $script:WebSocketReadyFile
        WebServerReadyFile = $script:WebServerReadyFile
        DefaultWebSocketPort = $script:DefaultWebSocketPort
        DefaultWebPort = $script:DefaultWebPort
    }
}

# WebSocket server and client classes
class WebSocketServer {
    hidden [System.Net.Sockets.TcpListener]$Server
    hidden [bool]$IsRunning
    hidden [hashtable]$Connections
    
    WebSocketServer() {
        $this.IsRunning = $false
        $this.Connections = @{}
    }
    
    [bool] Initialize([int]$Port = $script:DefaultWebSocketPort, [string]$HostName = "localhost") {
        try {
            # Remove any stale ready files
            if (Test-Path $script:WebSocketReadyFile) {
                Remove-Item $script:WebSocketReadyFile -Force
            }
            
            $endpoint = [IPEndPoint]::new([IPAddress]::Any, $Port)
            $this.Server = [System.Net.Sockets.TcpListener]::new($endpoint)
            Write-Host "WebSocket Server initialized on port $Port"
            
            # Signal ready state
            Set-WebSocketReady -Port $Port
            return $true
        }
        catch {
            Write-Error "Failed to initialize WebSocket server: $($_.Exception.Message)"
            return $false
        }
    }
    
    [void] Start() {
        if (-not $this.Server) {
            throw "WebSocket server not initialized"
        }
        
        try {
            $this.Server.Start()
            $this.IsRunning = $true
            Write-Host "WebSocket Server started"
        }
        catch {
            Write-Error "Failed to start WebSocket server: $($_.Exception.Message)"
            throw
        }
    }
    
    [void] Stop() {
        if ($this.Server -and $this.IsRunning) {
            try {
                $this.Server.Stop()
                $this.IsRunning = $false
                Write-Host "WebSocket Server stopped"
            }
            catch {
                Write-Error "Failed to stop WebSocket server: $($_.Exception.Message)"
                throw
            }
        }
    }
    
    [hashtable] GetStatus() {
        return @{
            IsRunning = $this.IsRunning
            ConnectionCount = $this.Connections.Count
            ServerObject = $this.Server
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
function Global:New-WebSocketServer {
    [CmdletBinding()]
    [OutputType([WebSocketServer])]
    param (
        [Parameter(Mandatory=$false)]
        [int]$Port = 8080,
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost"
    )
    
    $server = [WebSocketServer]::new()
    if ($server.Initialize($Port, $HostName)) {
        return $server
    }
    throw "Failed to initialize WebSocket server"
}

function Global:New-WebSocketClient {
    [CmdletBinding()]
    [OutputType([WebSocketClient])]
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerUrl
    )
    
    return [WebSocketClient]::new($ServerUrl)
}

function Global:Send-WebSocketMessage {
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

function Global:Test-WebSocketConnection {
    [CmdletBinding()]
    param(
        [int]$Port = 8081,
        [string]$HostName = "localhost"
    )
    
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connected = $tcpClient.ConnectAsync($HostName, $Port).Wait(2000)
        $tcpClient.Close()
        return $connected
    }
    catch {
        return $false
    }
}

function Global:Set-WebSocketReady {
    [CmdletBinding()]
    param(
        [int]$Port = $script:DefaultWebSocketPort,
        [string]$Status = "ready"
    )
    
    if ([string]::IsNullOrEmpty($script:WebSocketReadyFile)) {
        throw "WebSocket ready file path not initialized"
    }
    
    $config = @{
        status = $Status
        port = $Port
        timestamp = Get-Date -Format "o"
    }
    
    $configJson = $config | ConvertTo-Json
    Write-Verbose "Writing WebSocket ready config to $($script:WebSocketReadyFile): $configJson"
    $configJson | Set-Content -Path $script:WebSocketReadyFile -Force
}

function Global:Test-WebSocketReady {
    [CmdletBinding()]
    [OutputType([bool])]
    param()
    
    if ([string]::IsNullOrEmpty($script:WebSocketReadyFile)) {
        Write-Warning "WebSocket ready file path not initialized"
        return $false
    }
    
    if (-not (Test-Path $script:WebSocketReadyFile)) { 
        Write-Verbose "WebSocket ready file not found at: $script:WebSocketReadyFile"
        return $false 
    }
    
    try {
        $config = Get-Content $script:WebSocketReadyFile -Raw | ConvertFrom-Json
        if ($config.status -ne "ready") { return $false }
        
        # Test actual connection
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connected = $tcpClient.ConnectAsync("localhost", $config.port).Wait(2000)
        $tcpClient.Dispose()
        
        return $connected
    }
    catch {
        return $false
    }
}

# Module exports
Export-ModuleMember -Function @(
    'Get-WebSocketPaths',
    'New-WebSocketServer',
    'New-WebSocketClient',
    'Send-WebSocketMessage',
    'Test-WebSocketConnection',
    'Set-WebSocketReady',
    'Test-WebSocketReady'
) -Variable @(
    'DefaultWebSocketPort',
    'DefaultWebPort',
    'WebSocketReadyFile',
    'WebServerReadyFile'
)

# Type data for classes
Update-TypeData -TypeName WebSocketServer -MemberType NoteProperty -MemberName IsWebSocketServer -Value $true -Force
Update-TypeData -TypeName WebSocketClient -MemberType NoteProperty -MemberName IsWebSocketClient -Value $true -Force
