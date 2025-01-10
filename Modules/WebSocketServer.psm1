using namespace System.Net.WebSockets
using namespace System.Net
using namespace System.Text

class WebSocketServer {
    [int]$Port
    [HttpListener]$Listener
    [System.Collections.ArrayList]$Clients
    [scriptblock]$OnClientConnect
    [scriptblock]$OnClientDisconnect

    WebSocketServer([int]$port) {
        $this.Port = $port
        $this.Listener = [HttpListener]::new()
        $this.Listener.Prefixes.Add("http://localhost:$port/")
        $this.Clients = [System.Collections.ArrayList]::new()
    }

    [void]Start() {
        $this.Listener.Start()
        Write-Host "WebSocket server started on port $($this.Port)"

        while ($this.Listener.IsListening) {
            $context = $this.Listener.GetContext()
            if ($context.Request.Headers["Upgrade"] -eq "websocket") {
                $this.HandleWebSocket($context)
            }
        }
    }

    [void]Stop() {
        $this.Listener.Stop()
        $this.Listener.Close()
    }

    hidden [void]HandleWebSocket($context) {
        $client = $null
        try {
            $webSocket = $context.AcceptWebSocketAsync().Result
            $client = [WebSocketClient]::new($webSocket.WebSocket)
            $this.Clients.Add($client)
            
            if ($this.OnClientConnect) {
                $this.OnClientConnect.Invoke($client)
            }

            while ($client.WebSocket.State -eq [WebSocketState]::Open) {
                $buffer = [byte[]]::new(4096)
                $received = $client.WebSocket.ReceiveAsync($buffer, [System.Threading.CancellationToken]::None).Result
                if ($received.Count -gt 0) {
                    $message = [Encoding]::UTF8.GetString($buffer, 0, $received.Count)
                    $client.OnMessage($message)
                }
            }
        }
        catch {
            Write-Host "WebSocket error: $($_.Exception.Message)"
        }
        finally {
            if ($this.OnClientDisconnect) {
                $this.OnClientDisconnect.Invoke($client)
            }
            $this.Clients.Remove($client)
        }
    }

    [void]Broadcast([string]$message) {
        foreach ($client in $this.Clients) {
            $client.Send($message)
        }
    }
}

class WebSocketClient {
    [WebSocket]$WebSocket
    [scriptblock]$OnMessageReceived

    WebSocketClient([WebSocket]$webSocket) {
        $this.WebSocket = $webSocket
    }

    [void]Send([string]$message) {
        $buffer = [Encoding]::UTF8.GetBytes($message)
        $this.WebSocket.SendAsync($buffer, [WebSocketMessageType]::Text, $true, [System.Threading.CancellationToken]::None)
    }

    [void]OnMessage([string]$message) {
        if ($this.OnMessageReceived) {
            $this.OnMessageReceived.Invoke($message)
        }
    }

    [void]Close() {
        $this.WebSocket.CloseAsync([WebSocketCloseStatus]::NormalClosure, "Closing", [System.Threading.CancellationToken]::None)
    }
}

Export-ModuleMember -Class WebSocketServer, WebSocketClient
