using module "..\Modules\WebSocketServer.psm1"

# Add port verification before starting WebSocket server
$wsPort = 8081
$portInUse = Get-NetTCPConnection -LocalPort $wsPort -ErrorAction SilentlyContinue
if ($portInUse) {
    throw "WebSocket port $wsPort is already in use by process: $((Get-Process -Id $portInUse.OwningProcess).ProcessName)"
}

$webSocketServer = [WebSocketServer]::new($wsPort)
$connectedClients = @()

function Broadcast-ServerUpdate {
    param($UpdateData)
    
    $jsonData = $UpdateData | ConvertTo-Json
    foreach ($client in $connectedClients) {
        try {
            $client.SendMessage($jsonData)
        } catch {
            Write-Host "Failed to send to client: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# Event handlers for WebSocket
$webSocketServer.OnClientConnect = {
    param($Client)
    $connectedClients += $Client
}

$webSocketServer.OnClientDisconnect = {
    param($Client)
    $connectedClients = $connectedClients | Where-Object { $_ -ne $Client }
}

$webSocketServer.Start()
