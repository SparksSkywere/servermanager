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
Add-Type -AssemblyName System.Windows.Forms

# Add logging setup
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "create-server.log"

function Write-CreateServerLog {
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

Add-Type -AssemblyName System.Windows.Forms

# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "..\Modules\ServerManager.psm1"
Import-Module $serverManagerPath -Force

# Function to create a new game server
function New-GameServer {
    # Prompt user for server details
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Create Game Server"
    $form.Width = 400
    $form.Height = 300
    $form.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10, 20)
    $form.Controls.Add($nameLabel)

    $nameTextBox = New-Object System.Windows.Forms.TextBox
    $nameTextBox.Location = New-Object System.Drawing.Point(120, 20)
    $form.Controls.Add($nameTextBox)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "App ID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10, 60)
    $form.Controls.Add($appIdLabel)

    $appIdTextBox = New-Object System.Windows.Forms.TextBox
    $appIdTextBox.Location = New-Object System.Drawing.Point(120, 60)
    $form.Controls.Add($appIdTextBox)

    $installDirLabel = New-Object System.Windows.Forms.Label
    $installDirLabel.Text = "Install Directory:"
    $installDirLabel.Location = New-Object System.Drawing.Point(10, 100)
    $form.Controls.Add($installDirLabel)

    $installDirTextBox = New-Object System.Windows.Forms.TextBox
    $installDirTextBox.Location = New-Object System.Drawing.Point(120, 100)
    $form.Controls.Add($installDirTextBox)

    $createButton = New-Object System.Windows.Forms.Button
    $createButton.Text = "Create"
    $createButton.Location = New-Object System.Drawing.Point(120, 140)
    $createButton.Add_Click({
        $serverName = $nameTextBox.Text
        $appId = $appIdTextBox.Text
        $installDir = $installDirTextBox.Text

        if (-not [string]::IsNullOrEmpty($serverName) -and -not [string]::IsNullOrEmpty($appId) -and -not [string]::IsNullOrEmpty($installDir)) {
            # Call the relevant script or function to install a game server
            .\install-server.ps1 -AppName $serverName -AppID $appId -InstallDir $installDir
            [System.Windows.Forms.MessageBox]::Show("Game server created successfully.", "Success")
            $form.Close()
        } else {
            [System.Windows.Forms.MessageBox]::Show("Please fill in all fields.", "Error")
        }
    })
    $form.Controls.Add($createButton)

    $form.ShowDialog()
}

# Function to create a new server instance
function New-ServerInstance {
    param (
        [string]$ServerName,
        [string]$AppID,
        [string]$InstallDir
    )
    
    try {
        # Get registry paths
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
        
        # Create server instance
        $configDir = Join-Path $serverManagerDir "servers"
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }
        
        $configFile = Join-Path $configDir "$ServerName.json"
        $config = @{
            Name = $ServerName
            AppID = $AppID
            InstallDir = $InstallDir
            Created = Get-Date -Format "o"
            LastUpdate = Get-Date -Format "o"
        }
        
        $config | ConvertTo-Json | Set-Content -Path $configFile
        Write-ServerLog -Message "Created new server instance: $ServerName" -Level Info -ServerName $ServerName
        return $config
    }
    catch {
        Write-ServerLog -Message "Failed to create server instance: $_" -Level Error -ServerName $ServerName
        throw
    }
}

# Function to connect to the PID console
function Connect-PIDConsole {
    param (
        [int]$ProcessId
    )
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $process | Out-Host
    } catch {
        Write-Host "Failed to connect to process (PID: $ProcessId): $_" -ForegroundColor Red
    }
}

New-GameServer
