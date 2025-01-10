# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "Modules\ServerManager\ServerManager.psm1"
Import-Module $serverManagerPath -Force

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

# Add columns
$listView.Columns.Add("Server Name", 150)
$listView.Columns.Add("Status", 100)
$listView.Columns.Add("CPU Usage", 100)
$listView.Columns.Add("Memory Usage", 100)
$listView.Columns.Add("Uptime", 150)

# Create buttons
$addButton = New-Object System.Windows.Forms.Button
$addButton.Location = New-Object System.Drawing.Point(20,440)
$addButton.Size = New-Object System.Drawing.Size(100,30)
$addButton.Text = "Add Server"
$addButton.Add_Click({
    # Launch create-server.ps1
    & "$PSScriptRoot\create-server.ps1"
})

$removeButton = New-Object System.Windows.Forms.Button
$removeButton.Location = New-Object System.Drawing.Point(130,440)
$removeButton.Size = New-Object System.Drawing.Size(100,30)
$removeButton.Text = "Remove Server"
$removeButton.Add_Click({
    # Launch destroy-server.ps1
    & "$PSScriptRoot\destroy-server.ps1"
})

$importButton = New-Object System.Windows.Forms.Button
$importButton.Location = New-Object System.Drawing.Point(240,440)
$importButton.Size = New-Object System.Drawing.Size(100,30)
$importButton.Text = "Import Server"
$importButton.Add_Click({
    Import-ExistingServer
})

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Location = New-Object System.Drawing.Point(350,440)
$refreshButton.Size = New-Object System.Drawing.Size(100,30)
$refreshButton.Text = "Refresh"
$refreshButton.Add_Click({
    Update-ServerList
})

# Add sync button next to refresh button
$syncButton = New-Object System.Windows.Forms.Button
$syncButton.Location = New-Object System.Drawing.Point(460,440)
$syncButton.Size = New-Object System.Drawing.Size(100,30)
$syncButton.Text = "Sync All"
$syncButton.Add_Click({
    Sync-AllDashboards
})

function Sync-AllDashboards {
    Update-ServerList
    $updateData = @{
        Type = "ForcedSync"
        Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
    
    $jsonData = $updateData | ConvertTo-Json
    $buffer = [System.Text.Encoding]::UTF8.GetBytes($jsonData)
    $webSocketClient.SendAsync(
        [System.ArraySegment[byte]]::new($buffer),
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [System.Threading.CancellationToken]::None
    ).Wait()
}

# Add WebSocket client
$webSocketClient = New-Object System.Net.WebSockets.ClientWebSocket
$webSocketUri = New-Object System.Uri("ws://localhost:8081")

function Connect-WebSocket {
    try {
        $webSocketClient.ConnectAsync($webSocketUri, [System.Threading.CancellationToken]::None).Wait()
        
        # Start listening for updates
        $buffer = [byte[]]::new(4096)
        $receiveTask = $webSocketClient.ReceiveAsync(
            [System.ArraySegment[byte]]::new($buffer),
            [System.Threading.CancellationToken]::None
        )
        
        # Handle received updates
        $receiveTask.ContinueWith({
            param($Task)
            if ($Task.Result.Count -gt 0) {
                $jsonData = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $Task.Result.Count)
                $updateData = $jsonData | ConvertFrom-Json
                
                # Update UI on UI thread
                $form.Invoke({
                    Update-ServerList
                })
            }
        })
    } catch {
        Write-Host "WebSocket connection failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Function to update the server list
function Update-ServerList {
    $listView.Items.Clear()
    
    # Get the registry path
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    
    if (Test-Path $registryPath) {
        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
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
    }
    
    # Broadcast update to other clients
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
    $webSocketClient.SendAsync(
        [System.ArraySegment[byte]]::new($buffer),
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [System.Threading.CancellationToken]::None
    ).Wait()
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

# Add controls to form
$form.Controls.Add($listView)
$form.Controls.Add($addButton)
$form.Controls.Add($removeButton)
$form.Controls.Add($importButton)
$form.Controls.Add($refreshButton)
$form.Controls.Add($syncButton)  # Add the new sync button

# Initial update
Update-ServerList

# Create a timer for auto-refresh (every 3 minutes)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 180000  # 3 minutes in milliseconds
$timer.Add_Tick({ Update-ServerList })
$timer.Start()

# Connect WebSocket when form loads
$form.Add_Shown({
    Connect-WebSocket
})

# Show the form
$form.ShowDialog()
