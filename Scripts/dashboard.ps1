# Add at the very beginning of the file, before any other code
# Function to show or hide the console window
function Show-Console {
    param ([Switch]$Show, [Switch]$Hide)
    if (-not ("Console.Window" -as [type])) {
        Add-Type -Name Window -Namespace Console -MemberDefinition '
        [DllImport("Kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        '
    }
    $consolePtr = [Console.Window]::GetConsoleWindow()
    $nCmdShow = if ($Show) { 5 } elseif ($Hide) { 0 } else { return }
    [Console.Window]::ShowWindow($consolePtr, $nCmdShow) | Out-Null
    $global:DebugLoggingEnabled = $Show.IsPresent
    Write-DashboardLog "Console visibility set to: $($Show.IsPresent)" -Level DEBUG
}

# Add enhanced logging function at the beginning
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "dashboard.log"

function Write-DashboardLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [$Level] - $Message" | Add-Content -Path $logFile -ErrorAction Stop
        
        # Only write to host if debugging is enabled and it's an error or debug message
        if ($global:DebugLoggingEnabled -and ($Level -eq "ERROR" -or $Level -eq "DEBUG")) {
            $color = if ($Level -eq "ERROR") { "Red" } else { "Yellow" }
            Write-Host "[$Level] $Message" -ForegroundColor $color
        }
    }
    catch {
        # If we can't write to the log file, try to write to the Windows Event Log
        try {
            Write-EventLog -LogName Application -Source "ServerManager" -EventId 1001 -EntryType Error -Message "Failed to write to log file: $Message"
        }
        catch {
            # If all logging fails, we can't do much else
        }
    }
}

# Hide the console immediately
Show-Console -Hide

$host.UI.RawUI.WindowStyle = 'Hidden'

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
$form.Size = New-Object System.Drawing.Size(1200,700)
$form.StartPosition = "CenterScreen"

# Remove existing tab control setup and create main layout panel
$mainPanel = New-Object System.Windows.Forms.TableLayoutPanel
$mainPanel.Size = New-Object System.Drawing.Size(1160,480)
$mainPanel.Location = New-Object System.Drawing.Point(20,20)
$mainPanel.ColumnCount = 2
$mainPanel.RowCount = 1
$mainPanel.Dock = [System.Windows.Forms.DockStyle]::None
$mainPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))
$mainPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 30)))
$mainPanel.CellBorderStyle = [System.Windows.Forms.TableLayoutPanelCellBorderStyle]::Single

# Move existing ListView to servers tab
$listView = New-Object System.Windows.Forms.ListView
$listView.View = [System.Windows.Forms.View]::Details
$listView.Size = New-Object System.Drawing.Size(750,400)
$listView.Location = New-Object System.Drawing.Point(5,5)
$listView.FullRowSelect = $true
$listView.GridLines = $true

# Add columns to match web dashboard
$listView.Columns.Add("Server Name", 150)
$listView.Columns.Add("Status", 100)
$listView.Columns.Add("CPU Usage", 100)
$listView.Columns.Add("Memory Usage", 100)
$listView.Columns.Add("Uptime", 150)

# Modify ListView settings
$listView.Dock = [System.Windows.Forms.DockStyle]::Fill
$listView.Size = New-Object System.Drawing.Size(800,470)

# Create left panel for server list
$serversPanel = New-Object System.Windows.Forms.Panel
$serversPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$serversPanel.Controls.Add($listView)

# Create host information panel
$hostPanel = New-Object System.Windows.Forms.TableLayoutPanel
$hostPanel.ColumnCount = 2
$hostPanel.RowCount = 6
$hostPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$hostPanel.Padding = New-Object System.Windows.Forms.Padding(10)
$hostPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 30)))
$hostPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))

# Function to create metric labels
function New-MetricLabel {
    param($text)
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $text
    $label.AutoSize = $true
    $label.Margin = New-Object System.Windows.Forms.Padding(5)
    return $label
}

# Add metric rows
$metrics = @{
    "CPU Usage" = "Loading..."
    "Memory Usage" = "Loading..."
    "Disk Usage" = "Loading..."
    "GPU Info" = "Loading..."
    "Network Usage" = "Loading..."
    "System Uptime" = "Loading..."
}

$row = 0
$metrics.GetEnumerator() | ForEach-Object {
    $hostPanel.Controls.Add((New-MetricLabel $_.Key), 0, $row)
    $valueLabel = New-MetricLabel $_.Value
    $valueLabel.Name = "lbl$($_.Key -replace '\s','')"
    $hostPanel.Controls.Add($valueLabel, 1, $row)
    $row++
}

# Modify host panel settings
$hostPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$hostPanel.AutoSize = $true

# Add panels to main layout
$mainPanel.Controls.Add($serversPanel, 0, 0)
$mainPanel.Controls.Add($hostPanel, 1, 0)

# Create buttons panel
$buttonPanel = New-Object System.Windows.Forms.Panel
$buttonPanel.Location = New-Object System.Drawing.Point(20,520)
$buttonPanel.Size = New-Object System.Drawing.Size(1160,40)

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
    Update-HostInformation
})

# Add sync button next to refresh button
$syncButton = New-Object System.Windows.Forms.Button
$syncButton.Location = New-Object System.Drawing.Point(440,0)
$syncButton.Size = New-Object System.Drawing.Size(100,30)
$syncButton.Text = "Sync All"
$syncButton.Add_Click({
    Sync-AllDashboards
})

# Add new agent button next to sync button
$agentButton = New-Object System.Windows.Forms.Button
$agentButton.Location = New-Object System.Drawing.Point(550,0)
$agentButton.Size = New-Object System.Drawing.Size(100,30)
$agentButton.Text = "Add Agent"
$agentButton.Add_Click({
    $agentFormPath = Join-Path $serverManagerDir "Scripts\agent-form.ps1"
    if (Test-Path $agentFormPath) {
        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$agentFormPath`"" -WindowStyle Normal
    } else {
        [System.Windows.Forms.MessageBox]::Show("Agent form script not found.", "Error")
    }
})

# Add WebSocket client with connection state tracking
$script:webSocketClient = $null
$script:isWebSocketConnected = $false

# Define WebSocket connection parameters with new port
$wsUri = "ws://localhost:8081/ws"  # Changed to match new WebSocket port
$webSocket = $null

# Add status label to the form (add this near the form creation code)
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Location = New-Object System.Drawing.Point(20, 630)
$statusLabel.Size = New-Object System.Drawing.Size(1160, 20)
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
            Write-DashboardLog "Checking WebSocket ready file: $wsReadyFile" -Level DEBUG
            
            if (-not (Test-Path $wsReadyFile)) {
                throw "WebSocket ready file not found: $wsReadyFile"
            }

            # Read and validate WebSocket configuration
            $wsConfig = Get-Content $wsReadyFile | ConvertFrom-Json
            Write-DashboardLog "WebSocket config loaded: $($wsConfig | ConvertTo-Json)" -Level DEBUG
            
            if ($wsConfig.status -ne "ready") {
                throw "WebSocket server not ready. Status: $($wsConfig.status)"
            }

            # Test TCP connection first
            Write-DashboardLog "Testing TCP connection to localhost:$($wsConfig.port)" -Level DEBUG
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            $connectionTimeout = $tcpClient.BeginConnect("localhost", $wsConfig.port, $null, $null)
            $connected = $connectionTimeout.AsyncWaitHandle.WaitOne(1000)
            
            if (-not $connected) {
                $tcpClient.Close()
                throw "Failed to establish TCP connection to WebSocket server"
            }
            Write-DashboardLog "TCP connection successful" -Level DEBUG

            # Create and configure WebSocket with longer timeout
            $webSocket = New-Object System.Net.WebSockets.ClientWebSocket
            $wsUri = "ws://localhost:$($wsConfig.port)/ws"
            Write-DashboardLog "Attempting WebSocket connection to $wsUri" -Level DEBUG
            
            $cancelToken = New-Object System.Threading.CancellationToken
            $connectTask = $webSocket.ConnectAsync([System.Uri]::new($wsUri), $cancelToken)
            
            # Increase timeout to 10 seconds
            if (-not $connectTask.Wait(10000)) {
                throw "WebSocket connection timed out after 10 seconds"
            }

            if ($webSocket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                Write-DashboardLog "WebSocket connected successfully" -Level DEBUG
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
            Write-DashboardLog "Connection attempt $retryCount failed: $($_.Exception.Message)" -Level ERROR
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
            Write-DashboardLog "Failed to send WebSocket update: $($_.Exception.Message)" -Level ERROR
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
    Update-HostInformation
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
            Write-DashboardLog "Failed to send sync command: $($_.Exception.Message)" -Level ERROR
            $script:isWebSocketConnected = $false
        }
    }
}

# Add the function to get GPU information
function Get-GPUInfo {
    try {
        $gpu = Get-WmiObject Win32_VideoController | Select-Object -First 1
        return "$($gpu.Name) - $('{0:N0}' -f ($gpu.AdapterRAM/1MB))MB"
    } catch {
        return "GPU information unavailable"
    }
}

# Replace the Get-NetworkUsage function with this new version
function Get-NetworkUsage {
    try {
        # Store previous values in script-level variables if they don't exist
        if (-not $script:previousNetworkStats) {
            $script:previousNetworkStats = @{}
            $script:previousNetworkTime = Get-Date
        }

        $adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        $currentStats = $adapter | Get-NetAdapterStatistics
        $currentTime = Get-Date

        # Calculate time difference in seconds
        $timeDiff = ($currentTime - $script:previousNetworkTime).TotalSeconds

        if ($timeDiff -gt 0 -and $script:previousNetworkStats.ContainsKey($adapter.Name)) {
            $prevStats = $script:previousNetworkStats[$adapter.Name]
            
            # Calculate bytes per second
            $receiveBps = ($currentStats.ReceivedBytes - $prevStats.ReceivedBytes) / $timeDiff
            $sentBps = ($currentStats.SentBytes - $prevStats.SentBytes) / $timeDiff

            # Convert to Mbps (Megabits per second)
            $receiveMbps = [Math]::Round(($receiveBps * 8) / 1MB, 2)
            $sentMbps = [Math]::Round(($sentBps * 8) / 1MB, 2)

            # Store current values for next calculation
            $script:previousNetworkStats[$adapter.Name] = $currentStats
            $script:previousNetworkTime = $currentTime

            return "Down: $receiveMbps Mbps Up: $sentMbps Mbps"
        }

        # Store initial values
        $script:previousNetworkStats[$adapter.Name] = $currentStats
        $script:previousNetworkTime = $currentTime
        return "Calculating..."

    } catch {
        return "Network statistics unavailable"
    }
}

# Update the Update-HostInformation function with corrected string formatting
function Update-HostInformation {
    try {
        # CPU Usage
        $cpu = (Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
        $lblCPUUsage = $hostPanel.Controls["lblCPUUsage"]
        $lblCPUUsage.Text = "$([Math]::Round($cpu, 2))%"

        # Memory Usage
        $memory = Get-CimInstance Win32_OperatingSystem
        $memoryUsage = 100 - [Math]::Round(($memory.FreePhysicalMemory/$memory.TotalVisibleMemorySize)*100, 2)
        $lblMemoryUsage = $hostPanel.Controls["lblMemoryUsage"]
        $lblMemoryUsage.Text = "$memoryUsage% ($([Math]::Round($memory.TotalVisibleMemorySize/1MB, 2))GB Total)"

        # Disk Usage
        $disk = Get-PSDrive C
        $diskUsage = 100 - [Math]::Round(($disk.Free/$disk.Used)*100, 2)
        $lblDiskUsage = $hostPanel.Controls["lblDiskUsage"]
        $diskFreeGB = [Math]::Round($disk.Free/1GB, 2)
        $lblDiskUsage.Text = "$diskUsage% ($diskFreeGB GB Free)"

        # GPU Info
        $lblGPUInfo = $hostPanel.Controls["lblGPUInfo"]
        $lblGPUInfo.Text = Get-GPUInfo

        # Network Usage
        $lblNetworkUsage = $hostPanel.Controls["lblNetworkUsage"]
        $lblNetworkUsage.Text = Get-NetworkUsage

        # System Uptime
        $uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        $lblSystemUptime = $hostPanel.Controls["lblSystemUptime"]
        $lblSystemUptime.Text = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"

    } catch {
        Write-DashboardLog "Error updating host information: $($_.Exception.Message)" -Level ERROR
    }
}

# Add controls to form
$buttonPanel.Controls.AddRange(@($addButton, $removeButton, $importButton, $refreshButton, $syncButton, $agentButton))
$form.Controls.Clear()
$form.Controls.AddRange(@($mainPanel, $buttonPanel, $statusLabel))

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
                Write-DashboardLog "Ping failed: $($_.Exception.Message)" -Level ERROR
                $script:isWebSocketConnected = $false
                $statusLabel.Text = "WebSocket: Disconnected"
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
                $pingTimer.Stop()
            }
        }
    })
    $pingTimer.Start()
}

# Remove any existing timer definitions first
# Add performance optimization variables
$script:lastServerListUpdate = [DateTime]::MinValue
$script:lastFullUpdate = [DateTime]::MinValue
$script:cpuCounter = (New-Object System.Diagnostics.PerformanceCounter("Processor", "% Processor Time", "_Total"))
$script:updateThrottle = 2  # Seconds between updates

# Replace refresh timer with optimized version
$refreshTimer = New-Object System.Windows.Forms.Timer
$refreshTimer.Interval = 1000 # 1 second interval
$refreshTimer.Add_Tick({
    try {
        $currentTime = Get-Date
        
        # Update high-frequency items (CPU, Memory)
        if (($currentTime - $script:lastFullUpdate).TotalSeconds -ge $script:updateThrottle) {
            # Get CPU more efficiently
            $cpu = $script:cpuCounter.NextValue()
            
            # Update CPU immediately
            $lblCPUUsage = $hostPanel.Controls["lblCPUUsage"]
            $lblCPUUsage.Text = "$([Math]::Round($cpu, 1))%"
            
            # Memory update (relatively fast operation)
            $memInfo = Get-CimInstance Win32_OperatingSystem -Property FreePhysicalMemory,TotalVisibleMemorySize
            $memoryUsage = 100 - [Math]::Round(($memInfo.FreePhysicalMemory/$memInfo.TotalVisibleMemorySize)*100, 2)
            $lblMemoryUsage = $hostPanel.Controls["lblMemoryUsage"]
            $lblMemoryUsage.Text = "$memoryUsage% ($([Math]::Round($memInfo.TotalVisibleMemorySize/1MB, 2))GB Total)"
            
            $script:lastFullUpdate = $currentTime
        }

        # Update low-frequency items every 5 seconds
        if (($currentTime - $script:lastServerListUpdate).TotalSeconds -ge 5) {
            # Update disk info
            $disk = Get-PSDrive C
            $diskUsage = 100 - [Math]::Round(($disk.Free/$disk.Used)*100, 2)
            $lblDiskUsage = $hostPanel.Controls["lblDiskUsage"]
            $lblDiskUsage.Text = "$diskUsage% ($([Math]::Round($disk.Free/1GB, 2))GB Free)"
            
            # Network and GPU updates
            $lblNetworkUsage = $hostPanel.Controls["lblNetworkUsage"]
            $lblNetworkUsage.Text = Get-NetworkUsage
            
            $lblGPUInfo = $hostPanel.Controls["lblGPUInfo"]
            $lblGPUInfo.Text = Get-GPUInfo
            
            # Update uptime (cheap operation)
            $uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem -Property LastBootUpTime).LastBootUpTime
            $lblSystemUptime = $hostPanel.Controls["lblSystemUptime"]
            $lblSystemUptime.Text = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
            
            # Update server list
            Update-ServerList
            
            $script:lastServerListUpdate = $currentTime
        }
    }
    catch {
        Write-DashboardLog "Error updating dashboard: $($_.Exception.Message)" -Level ERROR
    }
})

# Modify form shown event
$form.Add_Shown({
    Connect-WebSocket
    Start-KeepAlivePing
    $refreshTimer.Start()
})

# Initial update
Update-ServerList
Update-HostInformation

# Modify form closing event to include logging
$form.Add_FormClosing({
    Write-DashboardLog "Dashboard closing, performing cleanup..." -Level DEBUG
    
    if ($refreshTimer) {
        $refreshTimer.Stop()
        $refreshTimer.Dispose()
    }

    # Remove all event subscribers
    Get-EventSubscriber | Unregister-Event
    
    # Stop and clean up background job
    if ($script:backgroundJob) {
        Stop-Job -Job $script:backgroundJob
        Remove-Job -Job $script:backgroundJob
    }

    # Stop and clean up runspace
    if ($script:powerShell) {
        $script:powerShell.Stop()
        $script:powerShell.Dispose()
    }
    if ($script:runspace) {
        $script:runspace.AsyncWaitHandle.Close()
    }

    if ($script:webSocketClient -ne $null) {
        try {
            # Attempt graceful closure
            $closeTask = $script:webSocketClient.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "Closing",
                [System.Threading.CancellationToken]::None
            )
            $closeTask.Wait(1000)
            Write-DashboardLog "WebSocket closed successfully" -Level DEBUG
        } catch {
            Write-DashboardLog "Error closing WebSocket: $($_.Exception.Message)" -Level ERROR
        } finally {
            $script:webSocketClient.Dispose()
        }
    }
    if ($script:cpuCounter) {
        $script:cpuCounter.Dispose()
    }
    $timer.Stop()
    $timer.Dispose()
    Write-DashboardLog "Dashboard closed successfully" -Level DEBUG
})

# Show the form
$form.ShowDialog()
