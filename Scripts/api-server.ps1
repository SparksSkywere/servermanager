using module "..\Modules\WebSocketServer.psm1"

# Hide console window
Add-Type -Name Window -Namespace Console -MemberDefinition '
[DllImport("Kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
'
$consolePtr = [Console.Window]::GetConsoleWindow()
[void][Console.Window]::ShowWindow($consolePtr, 0)

$host.UI.RawUI.WindowStyle = 'Hidden'

# Add logging setup
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "api-server.log"

function Write-ApiLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        if ($Level -eq "ERROR" -or $Level -eq "DEBUG") {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "$timestamp [$Level] - $Message" | Add-Content -Path $logFile -ErrorAction Stop
        }
    }
    catch {
        # If logging fails, try Windows Event Log
        try {
            Write-EventLog -LogName Application -Source "ServerManager" -EventId 1001 -EntryType Error -Message "Failed to write to log file: $Message"
        }
        catch { }
    }
}

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
    Write-ApiLog "Client connected: $($Client.Id)" -Level DEBUG
}

$webSocketServer.OnClientDisconnect = {
    param($Client)
    $connectedClients = $connectedClients | Where-Object { $_ -ne $Client }
    Write-ApiLog "Client disconnected: $($Client.Id)" -Level DEBUG
}

# Add error handling and logging
try {
    $webSocketServer.Start()
    Write-ApiLog "WebSocket server started successfully on port $wsPort" -Level DEBUG
}
catch {
    Write-ApiLog "Failed to start WebSocket server: $($_.Exception.Message)" -Level ERROR
    throw
}
