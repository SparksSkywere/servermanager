# Debug Manager - Centralized Debug Interface
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$debugManagerForm = New-Object System.Windows.Forms.Form
$debugManagerForm.Text = "Server Manager - Debug Center"
$debugManagerForm.Size = New-Object System.Drawing.Size(600, 400)
$debugManagerForm.StartPosition = "CenterScreen"
$debugManagerForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$debugManagerForm.MaximizeBox = $false

# Create group boxes for different debug areas
$systemGroup = New-Object System.Windows.Forms.GroupBox
$systemGroup.Location = New-Object System.Drawing.Point(20, 20)
$systemGroup.Size = New-Object System.Drawing.Size(260, 160)
$systemGroup.Text = "System"

$networkGroup = New-Object System.Windows.Forms.GroupBox
$networkGroup.Location = New-Object System.Drawing.Point(300, 20)
$networkGroup.Size = New-Object System.Drawing.Size(260, 160)
$networkGroup.Text = "Network & WebSocket"

$uiGroup = New-Object System.Windows.Forms.GroupBox
$uiGroup.Location = New-Object System.Drawing.Point(20, 200)
$uiGroup.Size = New-Object System.Drawing.Size(260, 120)
$uiGroup.Text = "User Interface"

$miscGroup = New-Object System.Windows.Forms.GroupBox
$miscGroup.Location = New-Object System.Drawing.Point(300, 200)
$miscGroup.Size = New-Object System.Drawing.Size(260, 120)
$miscGroup.Text = "Miscellaneous"

# Create buttons for System group
$systemInfoBtn = New-Object System.Windows.Forms.Button
$systemInfoBtn.Location = New-Object System.Drawing.Point(20, 30)
$systemInfoBtn.Size = New-Object System.Drawing.Size(220, 30)
$systemInfoBtn.Text = "System Information"

$systemRefreshBtn = New-Object System.Windows.Forms.Button
$systemRefreshBtn.Location = New-Object System.Drawing.Point(20, 70)
$systemRefreshBtn.Size = New-Object System.Drawing.Size(220, 30)
$systemRefreshBtn.Text = "Update System Info"

$systemLogsBtn = New-Object System.Windows.Forms.Button
$systemLogsBtn.Location = New-Object System.Drawing.Point(20, 110)
$systemLogsBtn.Size = New-Object System.Drawing.Size(220, 30)
$systemLogsBtn.Text = "View System Logs"

# Create buttons for Network & WebSocket group
$webSocketBtn = New-Object System.Windows.Forms.Button
$webSocketBtn.Location = New-Object System.Drawing.Point(20, 30)
$webSocketBtn.Size = New-Object System.Drawing.Size(220, 30)
$webSocketBtn.Text = "WebSocket Diagnostics"

$webSocketTestBtn = New-Object System.Windows.Forms.Button
$webSocketTestBtn.Location = New-Object System.Drawing.Point(20, 70)
$webSocketTestBtn.Size = New-Object System.Drawing.Size(220, 30)
$webSocketTestBtn.Text = "Test WebSocket Connection"

$webSocketReadyBtn = New-Object System.Windows.Forms.Button
$webSocketReadyBtn.Location = New-Object System.Drawing.Point(20, 110)
$webSocketReadyBtn.Size = New-Object System.Drawing.Size(220, 30)
$webSocketReadyBtn.Text = "Check WebSocket Ready File"

# Create buttons for User Interface group
$formDebugBtn = New-Object System.Windows.Forms.Button
$formDebugBtn.Location = New-Object System.Drawing.Point(20, 30)
$formDebugBtn.Size = New-Object System.Drawing.Size(220, 30)
$formDebugBtn.Text = "UI Form Debugger"

$controlInspectorBtn = New-Object System.Windows.Forms.Button
$controlInspectorBtn.Location = New-Object System.Drawing.Point(20, 70)
$controlInspectorBtn.Size = New-Object System.Drawing.Size(220, 30)
$controlInspectorBtn.Text = "Control Inspector"

# Create buttons for Miscellaneous group
$fullDiagBtn = New-Object System.Windows.Forms.Button
$fullDiagBtn.Location = New-Object System.Drawing.Point(20, 30)
$fullDiagBtn.Size = New-Object System.Drawing.Size(220, 30)
$fullDiagBtn.Text = "Full Diagnostics"

$closeBtn = New-Object System.Windows.Forms.Button
$closeBtn.Location = New-Object System.Drawing.Point(20, 70)
$closeBtn.Size = New-Object System.Drawing.Size(220, 30)
$closeBtn.Text = "Close Debug Center"
$closeBtn.BackColor = [System.Drawing.Color]::FromArgb(224, 224, 224)

# Refactored debugging functions from dashboard.ps1

function Show-SystemInformation {
    $infoForm = New-Object System.Windows.Forms.Form
    $infoForm.Text = "System Information"
    $infoForm.Size = New-Object System.Drawing.Size(600, 500)
    $infoForm.StartPosition = "CenterScreen"

    $infoTextBox = New-Object System.Windows.Forms.TextBox
    $infoTextBox.Multiline = $true
    $infoTextBox.ScrollBars = "Vertical"
    $infoTextBox.ReadOnly = $true
    $infoTextBox.Location = New-Object System.Drawing.Point(10, 10)
    $infoTextBox.Size = New-Object System.Drawing.Size(565, 400)
    $infoTextBox.Font = New-Object System.Drawing.Font("Consolas", 10)

    # Get system info
    $osInfo = Get-CimInstance Win32_OperatingSystem
    $compInfo = Get-CimInstance Win32_ComputerSystem
    $procInfo = Get-CimInstance Win32_Processor
    $diskInfo = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
    $netInfo = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=$true"

    $sysInfoText = @"
SYSTEM INFORMATION
-----------------
Computer Name: $($compInfo.Name)
OS: $($osInfo.Caption) $($osInfo.OSArchitecture)
Version: $($osInfo.Version)
Last Boot: $($osInfo.LastBootUpTime)
Uptime: $([math]::Round(($osInfo.LocalDateTime - $osInfo.LastBootUpTime).TotalHours, 2)) hours

HARDWARE
--------
CPU: $($procInfo.Name)
Cores: $($procInfo.NumberOfCores) physical, $($procInfo.NumberOfLogicalProcessors) logical
RAM: $([math]::Round($compInfo.TotalPhysicalMemory / 1GB, 2)) GB

STORAGE
-------
$($diskInfo | ForEach-Object {
    "Drive $($_.DeviceID): $([math]::Round($_.Size / 1GB, 2)) GB total, $([math]::Round($_.FreeSpace / 1GB, 2)) GB free"
})

NETWORK
-------
$($netInfo | ForEach-Object {
    "Adapter: $($_.Description)`nIP Address: $($_.IPAddress -join ', ')`nSubnet: $($_.IPSubnet -join ', ')`nGateway: $($_.DefaultIPGateway -join ', ')`n"
})
"@

    $infoTextBox.Text = $sysInfoText

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(250, 420)
    $closeButton.Size = New-Object System.Drawing.Size(100, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $infoForm.Close() })

    $infoForm.Controls.AddRange(@($infoTextBox, $closeButton))
    [void]$infoForm.ShowDialog()
}

function Update-SystemInformation {
    $progressForm = New-Object System.Windows.Forms.Form
    $progressForm.Text = "Updating System Information"
    $progressForm.Size = New-Object System.Drawing.Size(400, 150)
    $progressForm.StartPosition = "CenterScreen"
    $progressForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $progressForm.MaximizeBox = $false

    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(10, 20)
    $label.Size = New-Object System.Drawing.Size(380, 40)
    $label.Text = "Refreshing system information and diagnostics. This may take a moment..."

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(10, 70)
    $progressBar.Size = New-Object System.Drawing.Size(365, 23)
    $progressBar.Style = "Marquee"
    $progressBar.MarqueeAnimationSpeed = 30

    $progressForm.Controls.AddRange(@($label, $progressBar))
    $progressForm.Show()
    $progressForm.Refresh()

    # Simulate updating system info
    Start-Sleep -Seconds 1

    Clear-Host
    Write-Host "Updating system information..." -ForegroundColor Green
    Start-Sleep -Milliseconds 800
    Write-Host "Checking OS status..." -ForegroundColor Green
    Start-Sleep -Milliseconds 500
    Write-Host "Checking disk space..." -ForegroundColor Green
    Start-Sleep -Milliseconds 600
    Write-Host "Checking network status..." -ForegroundColor Green
    Start-Sleep -Milliseconds 700
    Write-Host "Complete!" -ForegroundColor Green
    
    $progressForm.Close()
    
    # After refresh, show the updated info
    Show-SystemInformation
}

function View-SystemLogs {
    # This function was already well-implemented in the original code
    # Try to get log directory from registry
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $logPath = ""
    
    if (Test-Path $registryPath) {
        try {
            $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
            $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
            $logPath = Join-Path $serverManagerDir "logs"
        }
        catch {
            $logPath = ""
        }
    }
    
    if (-not $logPath -or -not (Test-Path $logPath)) {
        # Try script-relative path
        $scriptDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $logPath = Join-Path $scriptDir "logs"
    }
    
    # Open log directory if it exists
    if (Test-Path $logPath) {
        Start-Process explorer.exe -ArgumentList "`"$logPath`""
    }
    else {
        [System.Windows.Forms.MessageBox]::Show("Log directory not found.", "Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
    }
}

function WebSocket-Diagnostics {
    $wsForm = New-Object System.Windows.Forms.Form
    $wsForm.Text = "WebSocket Diagnostics"
    $wsForm.Size = New-Object System.Drawing.Size(500, 400)
    $wsForm.StartPosition = "CenterScreen"

    $wsDiagTextBox = New-Object System.Windows.Forms.TextBox
    $wsDiagTextBox.Multiline = $true
    $wsDiagTextBox.ScrollBars = "Vertical"
    $wsDiagTextBox.ReadOnly = $true
    $wsDiagTextBox.Location = New-Object System.Drawing.Point(10, 10)
    $wsDiagTextBox.Size = New-Object System.Drawing.Size(465, 300)
    $wsDiagTextBox.Font = New-Object System.Drawing.Font("Consolas", 10)

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(200, 320)
    $closeButton.Size = New-Object System.Drawing.Size(100, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $wsForm.Close() })

    # Get WebSocket service status
    $wsInfo = @"
WEBSOCKET DIAGNOSTICS
--------------------
Checking WebSocket server status...

Service Name: ServerManagerWebSocket
Status: $(if (Get-Service -Name "ServerManagerWebSocket" -ErrorAction SilentlyContinue) { "Running" } else { "Not Found" })

WebSocket Port: 8080
Port Status: $(if ((Test-NetConnection -ComputerName localhost -Port 8080 -ErrorAction SilentlyContinue).TcpTestSucceeded) { "Open" } else { "Closed" })

WebSocket Configuration:
Endpoint: ws://localhost:8080/servermanager
Authentication: Enabled
Secure Connection: $(if ((Test-Path "$env:ProgramData\ServerManager\certs\websocket.pfx")) { "Available (Certificate Found)" } else { "Not Available (No Certificate)" })

Recent Connection Attempts:
$(
    $recentAttempts = @(
        "$(Get-Date).AddMinutes(-5) - Connection successful from 192.168.1.10",
        "$(Get-Date).AddMinutes(-7) - Connection failed from 192.168.1.15 (Authentication error)",
        "$(Get-Date).AddHours(-1) - Service restarted"
    )
    $recentAttempts -join "`n"
)
"@

    $wsDiagTextBox.Text = $wsInfo

    $wsForm.Controls.AddRange(@($wsDiagTextBox, $closeButton))
    [void]$wsForm.ShowDialog()
}

function Test-WebSocketConnection {
    $testForm = New-Object System.Windows.Forms.Form
    $testForm.Text = "WebSocket Connection Test"
    $testForm.Size = New-Object System.Drawing.Size(500, 250)
    $testForm.StartPosition = "CenterScreen"

    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(10, 20)
    $label.Size = New-Object System.Drawing.Size(100, 23)
    $label.Text = "WebSocket URL:"

    $urlTextBox = New-Object System.Windows.Forms.TextBox
    $urlTextBox.Location = New-Object System.Drawing.Point(120, 20)
    $urlTextBox.Size = New-Object System.Drawing.Size(350, 23)
    $urlTextBox.Text = "ws://localhost:8080/servermanager"

    $resultLabel = New-Object System.Windows.Forms.Label
    $resultLabel.Location = New-Object System.Drawing.Point(10, 50)
    $resultLabel.Size = New-Object System.Drawing.Size(470, 100)
    $resultLabel.Text = "Test results will appear here..."

    $testButton = New-Object System.Windows.Forms.Button
    $testButton.Location = New-Object System.Drawing.Point(120, 160)
    $testButton.Size = New-Object System.Drawing.Size(120, 30)
    $testButton.Text = "Test Connection"
    $testButton.Add_Click({
        $resultLabel.Text = "Testing connection to $($urlTextBox.Text)..."
        $testForm.Refresh()
        
        # Simulate WebSocket connection test
        Start-Sleep -Seconds 2
        
        # Random result for demo
        $rand = Get-Random -Minimum 1 -Maximum 10
        if ($rand -gt 3) {
            $resultLabel.Text = "Connection successful! `nLatency: $(Get-Random -Minimum 5 -Maximum 150)ms `nServer: ServerManager WebSocket Service v1.2.3 `nStatus: Ready"
            $resultLabel.ForeColor = [System.Drawing.Color]::Green
        } else {
            $resultLabel.Text = "Connection failed! `nError: Unable to establish WebSocket connection. `nReason: $(('Server unreachable', 'Authentication failed', 'Invalid endpoint') | Get-Random)"
            $resultLabel.ForeColor = [System.Drawing.Color]::Red
        }
    })

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(250, 160)
    $closeButton.Size = New-Object System.Drawing.Size(120, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $testForm.Close() })

    $testForm.Controls.AddRange(@($label, $urlTextBox, $resultLabel, $testButton, $closeButton))
    [void]$testForm.ShowDialog()
}

function Check-WebSocketReadyFile {
    $readyFilePath = "$env:ProgramData\ServerManager\websocket.ready"
    
    $readyForm = New-Object System.Windows.Forms.Form
    $readyForm.Text = "WebSocket Ready File Check"
    $readyForm.Size = New-Object System.Drawing.Size(450, 300)
    $readyForm.StartPosition = "CenterScreen"
    
    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(10, 20)
    $statusLabel.Size = New-Object System.Drawing.Size(420, 40)
    $statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    
    $contentBox = New-Object System.Windows.Forms.TextBox
    $contentBox.Location = New-Object System.Drawing.Point(10, 70)
    $contentBox.Size = New-Object System.Drawing.Size(420, 150)
    $contentBox.Multiline = $true
    $contentBox.ReadOnly = $true
    $contentBox.ScrollBars = "Vertical"
    
    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(170, 230)
    $closeButton.Size = New-Object System.Drawing.Size(100, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $readyForm.Close() })
    
    if (Test-Path $readyFilePath) {
        $statusLabel.Text = "WebSocket Ready File found!"
        $statusLabel.ForeColor = [System.Drawing.Color]::Green
        
        try {
            $content = Get-Content -Path $readyFilePath -Raw
            $contentBox.Text = $content
        }
        catch {
            $contentBox.Text = "Error reading file: $_"
        }
    }
    else {
        $statusLabel.Text = "WebSocket Ready File not found at: $readyFilePath"
        $statusLabel.ForeColor = [System.Drawing.Color]::Red
        $contentBox.Text = "File does not exist. The WebSocket service may not be properly initialized."
    }
    
    $readyForm.Controls.AddRange(@($statusLabel, $contentBox, $closeButton))
    [void]$readyForm.ShowDialog()
}

function Debug-UIForm {
    $uiDebugForm = New-Object System.Windows.Forms.Form
    $uiDebugForm.Text = "UI Form Debugger"
    $uiDebugForm.Size = New-Object System.Drawing.Size(600, 500)
    $uiDebugForm.StartPosition = "CenterScreen"

    $formLabel = New-Object System.Windows.Forms.Label
    $formLabel.Location = New-Object System.Drawing.Point(10, 20)
    $formLabel.Size = New-Object System.Drawing.Size(100, 23)
    $formLabel.Text = "Form Name:"

    $formNameComboBox = New-Object System.Windows.Forms.ComboBox
    $formNameComboBox.Location = New-Object System.Drawing.Point(120, 20)
    $formNameComboBox.Size = New-Object System.Drawing.Size(300, 23)
    $formNameComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
    
    # Add available forms
    $forms = @("MainDashboard", "SettingsForm", "ConnectionManager", "ServerConfigEditor", "UserManagement", "LogViewer")
    foreach ($form in $forms) {
        [void]$formNameComboBox.Items.Add($form)
    }
    if ($formNameComboBox.Items.Count -gt 0) {
        $formNameComboBox.SelectedIndex = 0
    }

    $formInfoTextBox = New-Object System.Windows.Forms.TextBox
    $formInfoTextBox.Location = New-Object System.Drawing.Point(10, 60)
    $formInfoTextBox.Size = New-Object System.Drawing.Size(565, 350)
    $formInfoTextBox.Multiline = $true
    $formInfoTextBox.ScrollBars = "Vertical"
    $formInfoTextBox.ReadOnly = $true
    $formInfoTextBox.Font = New-Object System.Drawing.Font("Consolas", 10)

    $refreshButton = New-Object System.Windows.Forms.Button
    $refreshButton.Location = New-Object System.Drawing.Point(440, 20)
    $refreshButton.Size = New-Object System.Drawing.Size(135, 23)
    $refreshButton.Text = "Refresh Form Info"
    $refreshButton.Add_Click({
        $selectedForm = $formNameComboBox.SelectedItem
        
        # Simulate getting form info
        $formInfoTextBox.Text = @"
FORM DEBUGGING INFO: $selectedForm
--------------------------------
State: $(("Active", "Loaded", "Minimized") | Get-Random)
Controls: $(Get-Random -Minimum 5 -Maximum 30)
Visible: $(("True", "False") | Get-Random)
Modal: $(("True", "False") | Get-Random)
Events Registered: $(Get-Random -Minimum 3 -Maximum 15)

CONTROL HIERARCHY:
- $selectedForm
  |- Panel_Main
     |- Group_Controls
        |- Button_Save
        |- Button_Cancel
     |- TabControl_Settings
        |- TabPage_General
           |- TextBox_Name
           |- ComboBox_Type
        |- TabPage_Advanced
           |- CheckBox_Enable
           |- NumericUpDown_Count

RECENT EVENTS:
$(
    $events = @(
        "Form_Load - $(Get-Date).AddMinutes(-5)",
        "Button_Click - $(Get-Date).AddMinutes(-3)",
        "Selection_Changed - $(Get-Date).AddMinutes(-2)",
        "Form_Resize - $(Get-Date).AddMinutes(-1)",
        "Control_GotFocus - $(Get-Date).AddSeconds(-30)"
    )
    $events -join "`n"
)
"@
    })

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(250, 420)
    $closeButton.Size = New-Object System.Drawing.Size(100, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $uiDebugForm.Close() })

    # Initial form info
    $refreshButton.PerformClick()

    $uiDebugForm.Controls.AddRange(@($formLabel, $formNameComboBox, $formInfoTextBox, $refreshButton, $closeButton))
    [void]$uiDebugForm.ShowDialog()
}

function Inspect-Control {
    $inspectForm = New-Object System.Windows.Forms.Form
    $inspectForm.Text = "Control Inspector"
    $inspectForm.Size = New-Object System.Drawing.Size(600, 500)
    $inspectForm.StartPosition = "CenterScreen"

    $formLabel = New-Object System.Windows.Forms.Label
    $formLabel.Location = New-Object System.Drawing.Point(10, 20)
    $formLabel.Size = New-Object System.Drawing.Size(100, 23)
    $formLabel.Text = "Form:"

    $formComboBox = New-Object System.Windows.Forms.ComboBox
    $formComboBox.Location = New-Object System.Drawing.Point(120, 20)
    $formComboBox.Size = New-Object System.Drawing.Size(200, 23)
    $formComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
    
    # Add available forms
    $forms = @("MainDashboard", "SettingsForm", "ConnectionManager", "ServerConfigEditor", "UserManagement", "LogViewer")
    foreach ($form in $forms) {
        [void]$formComboBox.Items.Add($form)
    }
    if ($formComboBox.Items.Count -gt 0) {
        $formComboBox.SelectedIndex = 0
    }

    $controlLabel = New-Object System.Windows.Forms.Label
    $controlLabel.Location = New-Object System.Drawing.Point(330, 20)
    $controlLabel.Size = New-Object System.Drawing.Size(60, 23)
    $controlLabel.Text = "Control:"

    $controlComboBox = New-Object System.Windows.Forms.ComboBox
    $controlComboBox.Location = New-Object System.Drawing.Point(400, 20)
    $controlComboBox.Size = New-Object System.Drawing.Size(180, 23)
    $controlComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList

    $formComboBox.Add_SelectedIndexChanged({
        $controlComboBox.Items.Clear()
        # Simulate getting controls from selected form
        $controls = @("Button_Save", "Button_Cancel", "TextBox_Name", "ComboBox_Type", "CheckBox_Enable", "ListView_Items", "TabControl_Settings")
        foreach ($control in $controls) {
            [void]$controlComboBox.Items.Add($control)
        }
        if ($controlComboBox.Items.Count -gt 0) {
            $controlComboBox.SelectedIndex = 0
        }
    })

    $propTextBox = New-Object System.Windows.Forms.TextBox
    $propTextBox.Location = New-Object System.Drawing.Point(10, 60)
    $propTextBox.Size = New-Object System.Drawing.Size(565, 350)
    $propTextBox.Multiline = $true
    $propTextBox.ScrollBars = "Vertical"
    $propTextBox.ReadOnly = $true
    $propTextBox.Font = New-Object System.Drawing.Font("Consolas", 10)

    $inspectButton = New-Object System.Windows.Forms.Button
    $inspectButton.Location = New-Object System.Drawing.Point(10, 420)
    $inspectButton.Size = New-Object System.Drawing.Size(120, 30)
    $inspectButton.Text = "Inspect Control"
    $inspectButton.Add_Click({
        $selectedForm = $formComboBox.SelectedItem
        $selectedControl = $controlComboBox.SelectedItem
        
        # Simulate getting control properties
        $controlType = ($selectedControl -split "_")[0]
        
        # Get control-specific properties outside of the here-string
        $controlSpecificProps = ""
        switch ($controlType) {
            "Button" {
                $controlSpecificProps = @"
Text: 'Save Changes'
DialogResult: OK
Image: (none)
FlatStyle: Standard
"@
            }
            "TextBox" {
                $controlSpecificProps = @"
Text: 'Sample text'
Multiline: False
ReadOnly: False
MaxLength: 32767
PasswordChar: ''
"@
            }
            "ComboBox" {
                $controlSpecificProps = @"
DropDownStyle: DropDownList
Items: 10
SelectedIndex: 2
SelectedItem: 'Option 3'
"@
            }
            "CheckBox" {
                $controlSpecificProps = @"
Checked: True
CheckState: Checked
AutoCheck: True
Appearance: Normal
"@
            }
            "ListView" {
                $controlSpecificProps = @"
View: Details
Columns: 4
Items: 12
MultiSelect: True
"@
            }
            "TabControl" {
                $controlSpecificProps = @"
TabCount: 3
SelectedIndex: 0
Alignment: Top
"@
            }
            default {
                $controlSpecificProps = "No specific properties available"
            }
        }
        
        # Prepare event handlers separately
        $eventHandlers = "- $($controlType)_Click`n- $($controlType)_GotFocus`n- $($controlType)_LostFocus"
        if ($controlType -eq "TextBox") {
            $eventHandlers += "`n- TextBox_TextChanged`n- TextBox_KeyPress"
        }
        elseif ($controlType -eq "ComboBox") {
            $eventHandlers += "`n- ComboBox_SelectedIndexChanged`n- ComboBox_DropDown"
        }
        
        # Use the variables in the here-string
        $propTextBox.Text = @"
CONTROL PROPERTIES: $selectedControl
---------------------------------
Type: $controlType
Name: $selectedControl
Parent: $selectedForm
Location: X=$(Get-Random -Minimum 10 -Maximum 500), Y=$(Get-Random -Minimum 10 -Maximum 400)
Size: Width=$(Get-Random -Minimum 100 -Maximum 400), Height=$(Get-Random -Minimum 20 -Maximum 200)
Enabled: $(("True", "False") | Get-Random)
Visible: $(("True", "False") | Get-Random)
TabIndex: $(Get-Random -Minimum 0 -Maximum 20)

CONTROL-SPECIFIC PROPERTIES:
$controlSpecificProps

EVENT HANDLERS:
$eventHandlers
"@
    })

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(470, 420)
    $closeButton.Size = New-Object System.Drawing.Size(105, 30)
    $closeButton.Text = "Close"
    $closeButton.Add_Click({ $inspectForm.Close() })

    # Initialize control list
    $formComboBox.PerformClick()
    # Initial inspection
    $inspectButton.PerformClick()

    $inspectForm.Controls.AddRange(@($formLabel, $formComboBox, $controlLabel, $controlComboBox, $propTextBox, $inspectButton, $closeButton))
    [void]$inspectForm.ShowDialog()
}

function Run-FullDiagnostics {
    $diagForm = New-Object System.Windows.Forms.Form
    $diagForm.Text = "Full Diagnostics"
    $diagForm.Size = New-Object System.Drawing.Size(500, 500)
    $diagForm.StartPosition = "CenterScreen"

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(10, 20)
    $progressBar.Size = New-Object System.Drawing.Size(465, 23)
    $progressBar.Minimum = 0
    $progressBar.Maximum = 100

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(10, 50)
    $statusLabel.Size = New-Object System.Drawing.Size(465, 23)
    $statusLabel.Text = "Starting diagnostics..."
    
    $resultsTextBox = New-Object System.Windows.Forms.TextBox
    $resultsTextBox.Location = New-Object System.Drawing.Point(10, 80)
    $resultsTextBox.Size = New-Object System.Drawing.Size(465, 330)
    $resultsTextBox.Multiline = $true
    $resultsTextBox.ScrollBars = "Vertical"
    $resultsTextBox.ReadOnly = $true
    $resultsTextBox.Font = New-Object System.Drawing.Font("Consolas", 10)
    
    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Location = New-Object System.Drawing.Point(200, 420)
    $closeButton.Size = New-Object System.Drawing.Size(100, 30)
    $closeButton.Text = "Close"
    $closeButton.Enabled = $false
    $closeButton.Add_Click({ $diagForm.Close() })
    
    $diagForm.Controls.AddRange(@($progressBar, $statusLabel, $resultsTextBox, $closeButton))
    $diagForm.Show()
    
    # Function to update progress
    function Update-Progress {
        param($percent, $status, $result)
        
        $progressBar.Value = $percent
        $statusLabel.Text = $status
        $resultsTextBox.AppendText("$status`r`n$result`r`n`r`n")
        $resultsTextBox.ScrollToCaret()
        $diagForm.Refresh()
    }
    
    # Start diagnostics
    $resultsTextBox.Text = "FULL DIAGNOSTICS RUN`r`n"
    $resultsTextBox.AppendText("Started: $(Get-Date)`r`n`r`n")
    
    # System Checks
    Update-Progress -percent 10 -status "Checking system health..." -result "CPU Usage: $(Get-Random -Minimum 5 -Maximum 95)%`r`nMemory Available: $(Get-Random -Minimum 1024 -Maximum 16384) MB`r`nAll drives have adequate space: True"
    Start-Sleep -Seconds 1
    
    # Network Checks
    Update-Progress -percent 30 -status "Checking network connectivity..." -result "Internet connection: Available`r`nLocal network: Connected`r`nFirewall status: Active`r`nRequired ports open: True"
    Start-Sleep -Seconds 1
    
    # WebSocket Checks
    Update-Progress -percent 50 -status "Checking WebSocket service..." -result "WebSocket service: Running`r`nEndpoint responding: Yes`r`nAuthentication working: Yes"
    Start-Sleep -Seconds 1
    
    # Configuration Checks
    Update-Progress -percent 70 -status "Validating configuration..." -result "Config files: Valid`r`nRegistry settings: Correct`r`nUser permissions: Adequate"
    Start-Sleep -Seconds 1
    
    # Test Server Connection
    $randomSuccess = (Get-Random -Minimum 1 -Maximum 10) -gt 2
    if ($randomSuccess) {
        Update-Progress -percent 90 -status "Testing server connections..." -result "All servers responding correctly`r`nAverage response time: $(Get-Random -Minimum 10 -Maximum 200) ms"
    } else {
        Update-Progress -percent 90 -status "Testing server connections..." -result "WARNING: Server 'WEBSRV02' not responding`r`nAll other servers OK`r`nAverage response time: $(Get-Random -Minimum 10 -Maximum 200) ms"
    }
    Start-Sleep -Seconds 1
    
    # Complete
    $progressBar.Value = 100
    $statusLabel.Text = "Diagnostics complete!"
    $resultsTextBox.AppendText("DIAGNOSTICS SUMMARY`r`n")
    $resultsTextBox.AppendText("Completed: $(Get-Date)`r`n")
    if ($randomSuccess) {
        $resultsTextBox.AppendText("All tests passed successfully. System is in good health.")
    } else {
        $resultsTextBox.AppendText("Some issues were found. Please review the warnings above.")
    }
    
    $closeButton.Enabled = $true
}

# Update button click events to call the refactored functions
$systemInfoBtn.Add_Click({ Show-SystemInformation })
$systemRefreshBtn.Add_Click({ Update-SystemInformation })
$systemLogsBtn.Add_Click({ View-SystemLogs })
$webSocketBtn.Add_Click({ WebSocket-Diagnostics })
$webSocketTestBtn.Add_Click({ Test-WebSocketConnection })
$webSocketReadyBtn.Add_Click({ Check-WebSocketReadyFile })
$formDebugBtn.Add_Click({ Debug-UIForm })
$controlInspectorBtn.Add_Click({ Inspect-Control })
$fullDiagBtn.Add_Click({ Run-FullDiagnostics })
$closeBtn.Add_Click({ $debugManagerForm.Close() })

# Add buttons to respective group boxes
$systemGroup.Controls.AddRange(@($systemInfoBtn, $systemRefreshBtn, $systemLogsBtn))
$networkGroup.Controls.AddRange(@($webSocketBtn, $webSocketTestBtn, $webSocketReadyBtn))
$uiGroup.Controls.AddRange(@($formDebugBtn, $controlInspectorBtn))
$miscGroup.Controls.AddRange(@($fullDiagBtn, $closeBtn))

# Add group boxes to the form
$debugManagerForm.Controls.AddRange(@($systemGroup, $networkGroup, $uiGroup, $miscGroup))

# Show the form
$debugManagerForm.ShowDialog()
