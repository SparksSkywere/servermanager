# Get registry values for paths
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

# Import required modules
$modulesPath = Join-Path $serverManagerDir "Modules"
Import-Module (Join-Path $modulesPath "ServerManager.psm1") -Force
Import-Module (Join-Path $modulesPath "Authentication.psm1") -Force

# Add Windows Forms and Drawing assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Create the main form
$form = New-Object System.Windows.Forms.Form
$form.Text = "Server Manager Dashboard"
$form.Size = New-Object System.Drawing.Size(800,600)
$form.StartPosition = "CenterScreen"

# Create the server list view
$listView = New-Object System.Windows.Forms.ListView
$listView.View = [System.Windows.Forms.View]::Details
$listView.Size = New-Object System.Drawing.Size(760,400)
$listView.Location = New-Object System.Drawing.Point(20,20)
$listView.FullRowSelect = $true
$listView.GridLines = $true

# Add columns to match web dashboard
$listView.Columns.Add("Server Name", 150)
$listView.Columns.Add("Status", 100)
$listView.Columns.Add("CPU Usage", 100)
$listView.Columns.Add("Memory Usage", 100)
$listView.Columns.Add("Uptime", 150)

# Create buttons panel
$buttonPanel = New-Object System.Windows.Forms.Panel
$buttonPanel.Location = New-Object System.Drawing.Point(20,440)
$buttonPanel.Size = New-Object System.Drawing.Size(760,40)

# Create buttons with similar functionality to web dashboard
$addButton = New-Object System.Windows.Forms.Button
$addButton.Location = New-Object System.Drawing.Point(0,0)
$addButton.Size = New-Object System.Drawing.Size(100,30)
$addButton.Text = "Add Server"
$addButton.Add_Click({
    $createServerPath = Join-Path $serverManagerDir "Scripts\create-server.ps1"
    if (Test-Path $createServerPath) {
        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$createServerPath`"" -WindowStyle Normal
    }
})

$removeButton = New-Object System.Windows.Forms.Button
$removeButton.Location = New-Object System.Drawing.Point(110,0)
$removeButton.Size = New-Object System.Drawing.Size(100,30)
$removeButton.Text = "Remove Server"
$removeButton.Add_Click({
    $destroyServerPath = Join-Path $serverManagerDir "Scripts\destroy-server.ps1"
    if (Test-Path $destroyServerPath) {
        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$destroyServerPath`"" -WindowStyle Normal
    }
})

$importButton = New-Object System.Windows.Forms.Button
$importButton.Location = New-Object System.Drawing.Point(220,0)
$importButton.Size = New-Object System.Drawing.Size(100,30)
$importButton.Text = "Import Server"
$importButton.Add_Click({
    Import-ExistingServer
})

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Location = New-Object System.Drawing.Point(330,0)
$refreshButton.Size = New-Object System.Drawing.Size(100,30)
$refreshButton.Text = "Refresh"
$refreshButton.Add_Click({
    Update-ServerList
})

# Add sync button next to refresh button
$syncButton = New-Object System.Windows.Forms.Button
$syncButton.Location = New-Object System.Drawing.Point(440,0)
$syncButton.Size = New-Object System.Drawing.Size(100,30)
$syncButton.Text = "Sync All"
$syncButton.Add_Click({
    Sync-AllDashboards
})

# Add WebSocket client with connection state tracking
$script:webSocketClient = $null
$script:isWebSocketConnected = $false

# Define WebSocket connection parameters with new port
$wsUri = "ws://localhost:8081/ws"  # Changed to match new WebSocket port
$webSocket = $null

# Add status label to the form (add this near the form creation code)
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Location = New-Object System.Drawing.Point(20, 530)
$statusLabel.Size = New-Object System.Drawing.Size(760, 20)
$statusLabel.Text = "WebSocket: Disconnected"
$statusLabel.ForeColor = [System.Drawing.Color]::Red
$form.Controls.Add($statusLabel)

# Modified Connect-WebSocket function with retry logic and more debugging
function Connect-WebSocket {
    $maxRetries = 5
    $retryCount = 0
    $retryDelay = 2
    $connected = $false

    while (-not $connected -and $retryCount -lt $maxRetries) {
        try {
            $retryCount++
            $statusLabel.Text = "WebSocket: Attempting connection (Try $retryCount of $maxRetries)..."
            $statusLabel.ForeColor = [System.Drawing.Color]::Blue
            $form.Refresh()

            # Check WebSocket ready file with better error handling
            $wsReadyFile = Join-Path $env:TEMP "websocket_ready.flag"
            Write-Host "Checking WebSocket ready file: $wsReadyFile"
            
            if (-not (Test-Path $wsReadyFile)) {
                throw "WebSocket ready file not found: $wsReadyFile"
            }

            # Read and validate WebSocket configuration
            $wsConfig = Get-Content $wsReadyFile | ConvertFrom-Json
            Write-Host "WebSocket config loaded: $($wsConfig | ConvertTo-Json)"
            
            if ($wsConfig.status -ne "ready") {
                throw "WebSocket server not ready. Status: $($wsConfig.status)"
            }

            # Test TCP connection first
            Write-Host "Testing TCP connection to localhost:$($wsConfig.port)"
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            $connectionTimeout = $tcpClient.BeginConnect("localhost", $wsConfig.port, $null, $null)
            $connected = $connectionTimeout.AsyncWaitHandle.WaitOne(1000)
            
            if (-not $connected) {
                $tcpClient.Close()
                throw "Failed to establish TCP connection to WebSocket server"
            }
            Write-Host "TCP connection successful"

            # Create and configure WebSocket with longer timeout
            $webSocket = New-Object System.Net.WebSockets.ClientWebSocket
            $wsUri = "ws://localhost:$($wsConfig.port)/ws"
            Write-Host "Attempting WebSocket connection to $wsUri"
            
            $cancelToken = New-Object System.Threading.CancellationToken
            $connectTask = $webSocket.ConnectAsync([System.Uri]::new($wsUri), $cancelToken)
            
            # Increase timeout to 10 seconds
            if (-not $connectTask.Wait(10000)) {
                throw "WebSocket connection timed out after 10 seconds"
            }

            if ($webSocket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                Write-Host "WebSocket connected successfully"
                $script:webSocketClient = $webSocket
                $script:isWebSocketConnected = $true
                $statusLabel.Text = "WebSocket: Connected"
                $statusLabel.ForeColor = [System.Drawing.Color]::Green
                $connected = $true
                
                Start-WebSocketListener
            } else {
                throw "WebSocket failed to connect. State: $($webSocket.State)"
            }
        } catch {
            Write-Host "Connection attempt $retryCount failed: $($_.Exception.Message)" -ForegroundColor Yellow
            if ($retryCount -lt $maxRetries) {
                Start-Sleep -Seconds $retryDelay
            } else {
                $statusLabel.Text = "WebSocket: Connection failed after $maxRetries attempts"
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
                [System.Windows.Forms.MessageBox]::Show(
                    "Could not connect to WebSocket server. Please ensure Server Manager is properly initialized.`n`nError: $($_.Exception.Message)",
                    "Connection Error",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
            }
        } finally {
            if ($tcpClient -and $tcpClient.Connected) {
                $tcpClient.Close()
            }
        }
    }
}

# Add new function to handle WebSocket listening
function Start-WebSocketListener {
    $buffer = [byte[]]::new(4096)
    $receiveTask = $script:webSocketClient.ReceiveAsync(
        [System.ArraySegment[byte]]::new($buffer),
        [System.Threading.CancellationToken]::None
    )

    $receiveTask.ContinueWith({
        param($Task)
        if ($Task.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) {
            if ($Task.Result.Count -gt 0) {
                $jsonData = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $Task.Result.Count)
                $updateData = $jsonData | ConvertFrom-Json
                
                $form.Invoke({
                    Update-ServerList
                })
                
                # Continue listening
                Start-WebSocketListener
            }
        } else {
            $form.Invoke({
                $statusLabel.Text = "WebSocket: Disconnected"
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
                $script:isWebSocketConnected = $false
            })
        }
    })
}

# Function to update the server list
function Update-ServerList {
    $listView.Items.Clear()
    
    # Get the PIDS.txt file path from registry
    $pidFile = Join-Path $serverManagerDir "PIDS.txt"
    
    if (Test-Path $pidFile) {
        $servers = Get-Content $pidFile
        foreach ($server in $servers) {
            $serverInfo = $server -split ' - '
            if ($serverInfo.Count -ge 2) {
                $processId = $serverInfo[0]
                $name = $serverInfo[1]
                
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                $status = if ($process) { "Running" } else { "Stopped" }
                
                if ($process) {
                    $cpu = [math]::Round($process.CPU, 2)
                    $memory = [math]::Round($process.WorkingSet64 / 1MB, 2)
                    $uptime = (Get-Date) - $process.StartTime
                    
                    $item = New-Object System.Windows.Forms.ListViewItem($name)
                    $item.SubItems.Add($status)
                    $item.SubItems.Add("$cpu%")
                    $item.SubItems.Add("$memory MB")
                    $item.SubItems.Add("$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m")
                    
                    $listView.Items.Add($item)
                }
            }
        }
    }
    
    # Only attempt to broadcast if WebSocket is connected
    if ($script:isWebSocketConnected -and $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            $updateData = @{
                Type = "ServerListUpdate"
                Servers = $listView.Items | ForEach-Object {
                    @{
                        Name = $_.Text
                        Status = $_.SubItems[1].Text
                        CPU = $_.SubItems[2].Text
                        Memory = $_.SubItems[3].Text
                        Uptime = $_.SubItems[4].Text
                    }
                }
            }
            
            $jsonData = $updateData | ConvertTo-Json
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($jsonData)
            $script:webSocketClient.SendAsync(
                [System.ArraySegment[byte]]::new($buffer),
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait()
        } catch {
            Write-Host "Failed to send WebSocket update: $($_.Exception.Message)" -ForegroundColor Yellow
            $script:isWebSocketConnected = $false
        }
    }
}

# Add the Import Server function
function Import-ExistingServer {
    $importForm = New-Object System.Windows.Forms.Form
    $importForm.Text = "Import Existing Server"
    $importForm.Size = New-Object System.Drawing.Size(400,300)
    $importForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($nameLabel)

    $nameBox = New-Object System.Windows.Forms.TextBox
    $nameBox.Location = New-Object System.Drawing.Point(120,20)
    $nameBox.Size = New-Object System.Drawing.Size(250,20)
    $importForm.Controls.Add($nameBox)

    $pathLabel = New-Object System.Windows.Forms.Label
    $pathLabel.Text = "Server Path:"
    $pathLabel.Location = New-Object System.Drawing.Point(10,50)
    $pathLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($pathLabel)

    $pathBox = New-Object System.Windows.Forms.TextBox
    $pathBox.Location = New-Object System.Drawing.Point(120,50)
    $pathBox.Size = New-Object System.Drawing.Size(200,20)
    $importForm.Controls.Add($pathBox)

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "..."
    $browseButton.Location = New-Object System.Drawing.Point(330,50)
    $browseButton.Size = New-Object System.Drawing.Size(40,20)
    $browseButton.Add_Click({
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "Select Server Directory"
        if ($folderBrowser.ShowDialog() -eq 'OK') {
            $pathBox.Text = $folderBrowser.SelectedPath
        }
    })
    $importForm.Controls.Add($browseButton)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "Steam AppID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10,80)
    $appIdLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($appIdLabel)

    $appIdBox = New-Object System.Windows.Forms.TextBox
    $appIdBox.Location = New-Object System.Drawing.Point(120,80)
    $appIdBox.Size = New-Object System.Drawing.Size(250,20)
    $importForm.Controls.Add($appIdBox)

    $importButton = New-Object System.Windows.Forms.Button
    $importButton.Text = "Import"
    $importButton.Location = New-Object System.Drawing.Point(150,200)
    $importButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text) -or 
            [string]::IsNullOrWhiteSpace($pathBox.Text) -or 
            [string]::IsNullOrWhiteSpace($appIdBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("Please fill in all fields.", "Error")
            return
        }

        # Get registry path for server manager
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

        # Create server configuration
        $serverConfig = @{
            Name = $nameBox.Text
            Path = $pathBox.Text
            AppID = $appIdBox.Text
        }

        # Save server configuration
        $configPath = Join-Path $serverManagerDir "servers"
        if (-not (Test-Path $configPath)) {
            New-Item -ItemType Directory -Path $configPath | Out-Null
        }
        $serverConfig | ConvertTo-Json | Set-Content -Path (Join-Path $configPath "$($nameBox.Text).json")

        [System.Windows.Forms.MessageBox]::Show("Server imported successfully!", "Success")
        $importForm.Close()
        Update-ServerList
    })
    $importForm.Controls.Add($importButton)

    $importForm.ShowDialog()
}

# Modify Sync-AllDashboards to handle WebSocket disconnection
function Sync-AllDashboards {
    Update-ServerList
    if ($script:isWebSocketConnected -and $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            $updateData = @{
                Type = "ForcedSync"
                Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            }
            
            $jsonData = $updateData | ConvertTo-Json
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($jsonData)
            $script:webSocketClient.SendAsync(
                [System.ArraySegment[byte]]::new($buffer),
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait()
        } catch {
            Write-Host "Failed to send sync command: $($_.Exception.Message)" -ForegroundColor Yellow
            $script:isWebSocketConnected = $false
        }
    }
}

# Add controls to form
$buttonPanel.Controls.AddRange(@($addButton, $removeButton, $importButton, $refreshButton, $syncButton))
$form.Controls.AddRange(@($listView, $buttonPanel))

# Create a timer for auto-refresh (every 3 minutes)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 180000  # 3 minutes in milliseconds
$timer.Add_Tick({ Update-ServerList })
$timer.Start()

# Connect WebSocket when form loads
$form.Add_Shown({
    Connect-WebSocket
    Start-KeepAlivePing
})

# Initial update
Update-ServerList

# Modify form closing event to cleanup WebSocket and timers
$form.Add_FormClosing({
    if ($script:webSocketClient -ne $null) {
        try {
            # Attempt graceful closure
            $closeTask = $script:webSocketClient.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "Closing",
                [System.Threading.CancellationToken]::None
            )
            $closeTask.Wait(1000)
        } catch {
            Write-Host "Error closing WebSocket: $($_.Exception.Message)"
        } finally {
            $script:webSocketClient.Dispose()
        }
    }
    $timer.Stop()
    $timer.Dispose()
})

# Show the form
$form.ShowDialog()

# Add keep-alive ping function
function Start-KeepAlivePing {
    if (-not $script:webSocketClient) { return }
    
    $pingTimer = New-Object System.Windows.Forms.Timer
    $pingTimer.Interval = 30000 # 30 seconds
    $pingTimer.Add_Tick({
        if ($script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            try {
                $buffer = [byte[]]::new(0)
                $segment = [System.ArraySegment[byte]]::new($buffer)
                $script:webSocketClient.SendAsync(
                    $segment,
                    [System.Net.WebSockets.WebSocketMessageType]::Binary,
                    $true,
                    [System.Threading.CancellationToken]::None
                ).Wait(1000)
            }
            catch {
                Write-Host "Ping failed: $($_.Exception.Message)"
                $script:isWebSocketConnected = $false
                $statusLabel.Text = "WebSocket: Disconnected"
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
                $pingTimer.Stop()
            }
        }
    })
    $pingTimer.Start()
}
