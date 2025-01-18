using namespace System.Net.WebSockets
using namespace System.Net
using namespace System.Text

class WebSocketServer {
    hidden [System.Net.Sockets.TcpListener]$Server
    hidden [bool]$IsRunning
    hidden [hashtable]$Connections
    
    WebSocketServer() {
        $this.IsRunning = $false
        $this.Connections = @{}
    }
    
    [bool] Initialize([int]$Port = 8080, [string]$HostName = "localhost") {
        try {
            $endpoint = [IPEndPoint]::new([IPAddress]::Parse($HostName), $Port)
            $this.Server = [System.Net.Sockets.TcpListener]::new($endpoint)
            Write-Host "WebSocket Server initialized on $($HostName):$Port"
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

# Ensure these functions are defined at the module level with proper scope
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

# Explicitly export functions and make them visible
Export-ModuleMember -Function New-WebSocketServer, New-WebSocketClient

# Add type data for classes if needed
Update-TypeData -TypeName WebSocketServer -MemberType NoteProperty -MemberName IsWebSocketServer -Value $true -Force
Update-TypeData -TypeName WebSocketClient -MemberType NoteProperty -MemberName IsWebSocketClient -Value $true -Force
