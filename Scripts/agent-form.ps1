# Hide console window properly
Add-Type -Name Window -Namespace Console -MemberDefinition '
[DllImport("Kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
'
$consolePtr = [Console.Window]::GetConsoleWindow()
if ($consolePtr -ne [IntPtr]::Zero) {
    [Console.Window]::ShowWindow($consolePtr, 0)
}

$host.UI.RawUI.WindowStyle = 'Hidden'

# Add logging setup
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "agent-form.log"

function Write-AgentFormLog {
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
        try {
            Write-EventLog -LogName Application -Source "ServerManager" -EventId 1001 -EntryType Error -Message "Failed to write to log file: $Message"
        }
        catch { }
    }
}

# Add Windows Forms and Drawing assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Write-AgentFormLog "Starting agent form..." -Level DEBUG

# Create the main form
$agentForm = New-Object System.Windows.Forms.Form
$agentForm.Text = "Add Remote Agent"
$agentForm.Size = New-Object System.Drawing.Size(400,300)
$agentForm.StartPosition = "CenterScreen"

# Computer Name/IP
$hostLabel = New-Object System.Windows.Forms.Label
$hostLabel.Text = "Remote Host:"
$hostLabel.Location = New-Object System.Drawing.Point(10,20)
$hostLabel.Size = New-Object System.Drawing.Size(100,20)

$hostBox = New-Object System.Windows.Forms.TextBox
$hostBox.Location = New-Object System.Drawing.Point(120,20)
$hostBox.Size = New-Object System.Drawing.Size(250,20)

# Username
$userLabel = New-Object System.Windows.Forms.Label
$userLabel.Text = "Username:"
$userLabel.Location = New-Object System.Drawing.Point(10,50)
$userLabel.Size = New-Object System.Drawing.Size(100,20)

$userBox = New-Object System.Windows.Forms.TextBox
$userBox.Location = New-Object System.Drawing.Point(120,50)
$userBox.Size = New-Object System.Drawing.Size(250,20)

# Password
$passLabel = New-Object System.Windows.Forms.Label
$passLabel.Text = "Password:"
$passLabel.Location = New-Object System.Drawing.Point(10,80)
$passLabel.Size = New-Object System.Drawing.Size(100,20)

$passBox = New-Object System.Windows.Forms.TextBox
$passBox.PasswordChar = '*'
$passBox.Location = New-Object System.Drawing.Point(120,80)
$passBox.Size = New-Object System.Drawing.Size(250,20)

# Port
$portLabel = New-Object System.Windows.Forms.Label
$portLabel.Text = "Port:"
$portLabel.Location = New-Object System.Drawing.Point(10,110)
$portLabel.Size = New-Object System.Drawing.Size(100,20)

$portBox = New-Object System.Windows.Forms.TextBox
$portBox.Text = "5985"  # Default WinRM port
$portBox.Location = New-Object System.Drawing.Point(120,110)
$portBox.Size = New-Object System.Drawing.Size(250,20)

# Add Agent Button
$addButton = New-Object System.Windows.Forms.Button
$addButton.Text = "Add Agent"
$addButton.Location = New-Object System.Drawing.Point(150,200)
$addButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($hostBox.Text) -or 
        [string]::IsNullOrWhiteSpace($userBox.Text) -or 
        [string]::IsNullOrWhiteSpace($passBox.Text)) {
        Write-AgentFormLog "Missing required fields" -Level ERROR
        [System.Windows.Forms.MessageBox]::Show("Please fill in all required fields.", "Error")
        return
    }

    Write-AgentFormLog "Attempting to add agent for host: $($hostBox.Text)" -Level DEBUG

    # Create credential object
    $securePass = ConvertTo-SecureString $passBox.Text -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential ($userBox.Text, $securePass)

    # TODO: Implement agent deployment logic here
    Write-AgentFormLog "Agent deployment not yet implemented" -Level DEBUG
    [System.Windows.Forms.MessageBox]::Show("Agent deployment will be implemented in future version.", "Not Implemented")
})

# Add form closing event with logging
$agentForm.Add_FormClosing({
    Write-AgentFormLog "Agent form closing" -Level DEBUG
})

# Add controls to form
$agentForm.Controls.AddRange(@(
    $hostLabel, $hostBox,
    $userLabel, $userBox,
    $passLabel, $passBox,
    $portLabel, $portBox,
    $addButton
))

# Show the form
$agentForm.ShowDialog()
