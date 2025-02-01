# Add global script variables at the beginning of the file
$script:previousNetworkStats = @{}
$script:previousNetworkTime = Get-Date
$script:webSocketClient = $null
$script:isWebSocketConnected = $false
$script:lastServerListUpdate = [DateTime]::MinValue
$script:lastFullUpdate = [DateTime]::MinValue
$script:DebugLoggingEnabled = $false
$script:pingTimer = $null

# Add initial variable declarations at the top
$script:outputBuilder = $null
$script:errorBuilder = $null
$script:output = $null
$script:errorMessage = $null
$script:errorOutput = $null
$script:steamCmdPath = $null
$script:timer = $null
$script:process = $null
$script:webSocket = $null
$script:result = $null
$script:configFile = $null
$script:serverConfig = $null

# Initialize performance counter
try {
    $script:cpuCounter = New-Object System.Diagnostics.PerformanceCounter("Processor", "% Processor Time", "_Total")
    $script:cpuCounter.NextValue() # First call to initialize
} catch {
    Write-DashboardLog "Failed to initialize CPU counter: $($_.Exception.Message)" -Level ERROR
    $script:cpuCounter = $null
}

# Add default variables for Steam installation
$script:defaultSteamPath = Join-Path ${env:ProgramFiles(x86)} "Steam"
$script:defaultInstallDir = Join-Path $script:defaultSteamPath "steamapps\common"

# Add refresh timer variable
$script:refreshTimer = $null

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

# Add credential handling functions at the top after initial variables
function Get-SecureCredentials {
    param (
        [string]$credentialName,
        [string]$keyFile = "C:\ProgramData\ServerManager\encryption.key"
    )
    try {
        if (-not (Test-Path $keyFile)) {
            throw "Encryption key not found. Please run installer first."
        }

        $key = Get-Content $keyFile -Encoding Byte
        $secureKey = $key | ConvertTo-SecureString -AsPlainText -Force
        
        $credPath = Join-Path $env:ProgramData "ServerManager\Credentials"
        $credFile = Join-Path $credPath "$credentialName.cred"
        
        if (Test-Path $credFile) {
            $encrypted = Get-Content $credFile | ConvertTo-SecureString -Key $key
            $cred = [PSCredential]::new("steam", $encrypted)
            return $cred
        }
        return $null
    }
    catch {
        Write-DashboardLog "Failed to get secure credentials: $($_.Exception.Message)" -Level ERROR
        return $null
    }
}

function Save-SecureCredentials {
    param (
        [string]$credentialName,
        [SecureString]$password,
        [string]$keyFile = "C:\ProgramData\ServerManager\encryption.key"
    )
    try {
        if (-not (Test-Path $keyFile)) {
            throw "Encryption key not found. Please run installer first."
        }

        $key = Get-Content $keyFile -Encoding Byte
        $credPath = Join-Path $env:ProgramData "ServerManager\Credentials"
        
        if (-not (Test-Path $credPath)) {
            New-Item -Path $credPath -ItemType Directory -Force | Out-Null
        }

        $credFile = Join-Path $credPath "$credentialName.cred"
        $password | ConvertFrom-SecureString -Key $key | Set-Content $credFile
        return $true
    }
    catch {
        Write-DashboardLog "Failed to save secure credentials: $($_.Exception.Message)" -Level ERROR
        return $false
    }
}

# Add this after the Write-DashboardLog function and before other functions
$script:jobScriptBlock = {
    param($name, $appId, $installDir, $serverManagerDir, $credentials)
    
    $output = New-Object System.Text.StringBuilder
    $errorOutput = $null
    $steamCmdPath = $null
    $process = $null
    
    try {
        # Get SteamCMD path from registry
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $regValues = Get-ItemProperty -Path $registryPath -ErrorAction Stop
        $steamCmdDir = $regValues.SteamCmdPath
        Write-Output "Using SteamCMD directory: $steamCmdDir"
        
        # If installDir is empty, let Steam choose the default path
        if ([string]::IsNullOrWhiteSpace($installDir)) {
            Write-Output "Using Steam's default installation path"
            $installDir = "" # Empty string will let Steam use its default path
        }

        # Only create directory if a custom path is specified
        if ($installDir -and -not (Test-Path $installDir)) {
            Write-Output "Creating custom install directory: $installDir"
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        }

        Write-Output "Starting server installation..."
        
        # Build SteamCMD command
        $steamCmdArgs = if ($credentials.Anonymous) {
            "+login anonymous"
        } else {
            "+login `"$($credentials.Username)`" `"$($credentials.Password)`""
        }

        if ($installDir) {
            $steamCmdArgs += " +force_install_dir `"$installDir`""
        }

        $steamCmdArgs += " +app_update $appId validate +quit"
        
        Write-Output "Running SteamCMD with arguments: $steamCmdArgs"

        # Start SteamCMD process
        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $steamCmdPath
        $pinfo.Arguments = $steamCmdArgs
        $pinfo.UseShellExecute = $false
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true
        $pinfo.RedirectStandardInput = $true
        $pinfo.CreateNoWindow = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $pinfo
        
        Write-Output "Starting SteamCMD process..."
        $process.Start() | Out-Null

        # Capture output in real-time
        $output = New-Object System.Text.StringBuilder
        while (!$process.StandardOutput.EndOfStream) {
            $line = $process.StandardOutput.ReadLine()
            $output.AppendLine($line)
            Write-Output $line
        }

        $errorOutput = $process.StandardError.ReadToEnd()
        $process.WaitForExit()

        Write-Output "SteamCMD process completed with exit code: $($process.ExitCode)"
        
        if ($errorOutput) {
            Write-Output "SteamCMD Errors:"
            Write-Output $errorOutput
        }

        if ($process.ExitCode -ne 0) {
            throw "SteamCMD failed with exit code: $($process.ExitCode)`nOutput: $($output.ToString())`nErrors: $errorOutput"
        }

        # Verify installation
        if (-not (Test-Path $installDir)) {
            throw "Installation directory not created: $installDir"
        }

        $installedFiles = Get-ChildItem -Path $installDir -Recurse
        if (-not $installedFiles) {
            throw "No files were installed to: $installDir"
        }

        # Create server configuration
        Write-Output "Creating server configuration..."
        $serverConfig = @{
            Name = $name
            AppID = $appId
            InstallDir = $installDir
            Created = Get-Date -Format "o"
            LastUpdate = Get-Date -Format "o"
        }

        $configPath = Join-Path $serverManagerDir "servers"
        if (-not (Test-Path $configPath)) {
            Write-Output "Creating servers directory: $configPath"
            New-Item -ItemType Directory -Path $configPath -Force | Out-Null
        }

        $configFile = Join-Path $configPath "$name.json"
        Write-Output "Saving configuration to: $configFile"
        $serverConfig | ConvertTo-Json | Set-Content -Path $configFile -Force

        Write-Output "Configuration saved successfully"

        return @{
            Success = $true
            Message = "Server created successfully at $installDir"
            InstallPath = $installDir
        }
    }
    catch {
        Write-Output "Error occurred: $($_.Exception.Message)"
        Write-Output "Stack trace: $($_.ScriptStackTrace)"
        return @{
            Success = $false
            Message = $_.Exception.Message
        }
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

function Get-SteamCredentials {
    $loginForm = New-Object System.Windows.Forms.Form
    $loginForm.Text = "Steam Login"
    $loginForm.Size = New-Object System.Drawing.Size(300,250)
    $loginForm.StartPosition = "CenterScreen"
    $loginForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $loginForm.MaximizeBox = $false

    $usernameLabel = New-Object System.Windows.Forms.Label
    $usernameLabel.Text = "Username:"
    $usernameLabel.Location = New-Object System.Drawing.Point(10,20)
    $usernameLabel.Size = New-Object System.Drawing.Size(100,20)

    $usernameBox = New-Object System.Windows.Forms.TextBox
    $usernameBox.Location = New-Object System.Drawing.Point(110,20)
    $usernameBox.Size = New-Object System.Drawing.Size(150,20)

    $passwordLabel = New-Object System.Windows.Forms.Label
    $passwordLabel.Text = "Password:"
    $passwordLabel.Location = New-Object System.Drawing.Point(10,50)
    $passwordLabel.Size = New-Object System.Drawing.Size(100,20)

    $passwordBox = New-Object System.Windows.Forms.TextBox
    $passwordBox.Location = New-Object System.Drawing.Point(110,50)
    $passwordBox.Size = New-Object System.Drawing.Size(150,20)
    $passwordBox.PasswordChar = '*'

    $guardLabel = New-Object System.Windows.Forms.Label
    $guardLabel.Text = "Steam Guard Code:"
    $guardLabel.Location = New-Object System.Drawing.Point(10,80)
    $guardLabel.Size = New-Object System.Drawing.Size(100,20)
    $guardLabel.Visible = $false

    $guardBox = New-Object System.Windows.Forms.TextBox
    $guardBox.Location = New-Object System.Drawing.Point(110,80)
    $guardBox.Size = New-Object System.Drawing.Size(150,20)
    $guardBox.MaxLength = 5
    $guardBox.Visible = $false

    $loginButton = New-Object System.Windows.Forms.Button
    $loginButton.Text = "Login"
    $loginButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $loginButton.Location = New-Object System.Drawing.Point(110,120)

    $anonButton = New-Object System.Windows.Forms.Button
    $anonButton.Text = "Anonymous"
    $anonButton.DialogResult = [System.Windows.Forms.DialogResult]::Ignore
    $anonButton.Location = New-Object System.Drawing.Point(110,150)

    $loginForm.Controls.AddRange(@(
        $usernameLabel, $usernameBox, 
        $passwordLabel, $passwordBox,
        $guardLabel, $guardBox,
        $loginButton, $anonButton
    ))

    $result = $loginForm.ShowDialog()
    
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return @{
            Username = $usernameBox.Text
            Password = $passwordBox.Text
            GuardCode = $guardBox.Text
            Anonymous = $false
        }
    }
    elseif ($result -eq [System.Windows.Forms.DialogResult]::Ignore) {
        return @{
            Anonymous = $true
        }
    }
    else {
        return $null
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

# Modify form properties
$form.Text = "Server Manager Dashboard"
$form.MinimumSize = New-Object System.Drawing.Size(800,600)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.AutoSize = $false
$form.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$form.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right

# Remove existing tab control setup and create main layout panel
$mainPanel = New-Object System.Windows.Forms.TableLayoutPanel
$mainPanel.Size = New-Object System.Drawing.Size(1160,480)
$mainPanel.Location = New-Object System.Drawing.Point(20,20)
$mainPanel.ColumnCount = 2
$mainPanel.RowCount = 1
$mainPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$mainPanel.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$mainPanel.AutoSize = $false
$mainPanel.Margin = New-Object System.Windows.Forms.Padding(10)
$mainPanel.Padding = New-Object System.Windows.Forms.Padding(5)
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
$buttonPanel.Dock = [System.Windows.Forms.DockStyle]::Bottom
$buttonPanel.Height = 50
$buttonPanel.Padding = New-Object System.Windows.Forms.Padding(10, 5, 10, 5)

# Add these functions before creating the buttons
function New-IntegratedGameServer {
    param (
        [Parameter(Mandatory=$true)]
        [hashtable]$SteamCredentials
    )
    
    $createForm = New-Object System.Windows.Forms.Form
    $createForm.Text = "Create Game Server"
    $createForm.Size = New-Object System.Drawing.Size(600,500)
    $createForm.StartPosition = "CenterScreen"

    # Keep existing input controls but adjust their positions
    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $nameTextBox = New-Object System.Windows.Forms.TextBox
    $nameTextBox.Location = New-Object System.Drawing.Point(120,20)
    $nameTextBox.Size = New-Object System.Drawing.Size(250,20)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "App ID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10,50)
    $appIdLabel.Size = New-Object System.Drawing.Size(100,20)

    $appIdTextBox = New-Object System.Windows.Forms.TextBox
    $appIdTextBox.Location = New-Object System.Drawing.Point(120,50)
    $appIdTextBox.Size = New-Object System.Drawing.Size(250,20)

    $installDirLabel = New-Object System.Windows.Forms.Label
    $installDirLabel.Text = "Install Directory:"
    $installDirLabel.Location = New-Object System.Drawing.Point(10,80)
    $installDirLabel.Size = New-Object System.Drawing.Size(100,20)

    $installDirTextBox = New-Object System.Windows.Forms.TextBox
    $installDirTextBox.Location = New-Object System.Drawing.Point(120,80)
    $installDirTextBox.Size = New-Object System.Drawing.Size(200,20)

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse"
    $browseButton.Location = New-Object System.Drawing.Point(330,78)
    $browseButton.Size = New-Object System.Drawing.Size(60,22)
    $browseButton.Add_Click({
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "Select Installation Directory"
        if ($folderBrowser.ShowDialog() -eq 'OK') {
            $installDirTextBox.Text = $folderBrowser.SelectedPath
        }
    })

    # Add console output window
    $consoleOutput = New-Object System.Windows.Forms.RichTextBox
    $consoleOutput.Location = New-Object System.Drawing.Point(10,120)
    $consoleOutput.Size = New-Object System.Drawing.Size(560,250)  # Wide console window
    $consoleOutput.MultiLine = $true
    $consoleOutput.ScrollBars = "Vertical"
    $consoleOutput.BackColor = [System.Drawing.Color]::Black
    $consoleOutput.ForeColor = [System.Drawing.Color]::White
    $consoleOutput.Font = New-Object System.Drawing.Font("Consolas", 9)
    $consoleOutput.ReadOnly = $true

    # Move progress elements below console
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(10,390)  # Moved down
    $progressBar.Size = New-Object System.Drawing.Size(560,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(10,370)  # Moved down
    $statusLabel.Size = New-Object System.Drawing.Size(560,20)
    $statusLabel.Text = ""

    $createButton = New-Object System.Windows.Forms.Button
    $createButton.Text = "Create"
    $createButton.Location = New-Object System.Drawing.Point(10,420)  # Moved down
    $createButton.Size = New-Object System.Drawing.Size(100,30)

    # Modify the click handler to update the console output
    $createButton.Add_Click({
        try {
            Write-DashboardLog "Starting server creation process" -Level DEBUG
            
            # Validate required fields
            if ([string]::IsNullOrWhiteSpace($nameTextBox.Text)) {
                [System.Windows.Forms.MessageBox]::Show("Server name is required.", "Validation Error")
                Write-DashboardLog "Validation failed: Server name missing" -Level ERROR
                return
            }

            if ([string]::IsNullOrWhiteSpace($appIdTextBox.Text)) {
                [System.Windows.Forms.MessageBox]::Show("Steam App ID is required.", "Validation Error")
                Write-DashboardLog "Validation failed: App ID missing" -Level ERROR
                return
            }

            # Validate App ID is numeric
            if (-not [int]::TryParse($appIdTextBox.Text, [ref]$null)) {
                [System.Windows.Forms.MessageBox]::Show("Steam App ID must be a number.", "Validation Error")
                Write-DashboardLog "Validation failed: Invalid App ID format" -Level ERROR
                return
            }

            # Validate server name doesn't already exist
            $existingConfigPath = Join-Path $serverManagerDir "servers\$($nameTextBox.Text).json"
            if (Test-Path $existingConfigPath) {
                [System.Windows.Forms.MessageBox]::Show("A server with this name already exists.", "Validation Error")
                Write-DashboardLog "Validation failed: Server name already exists" -Level ERROR
                return
            }

            # Validate install directory if specified
            if (-not [string]::IsNullOrWhiteSpace($installDirTextBox.Text)) {
                $installPath = $installDirTextBox.Text
                
                # Check if path is valid
                try {
                    $null = [System.IO.Path]::GetFullPath($installPath)
                }
                catch {
                    [System.Windows.Forms.MessageBox]::Show("Invalid installation path specified.", "Validation Error")
                    Write-DashboardLog "Validation failed: Invalid install path" -Level ERROR
                    return
                }

                # Check if path exists and is empty, or can be created
                if (Test-Path $installPath) {
                    if ((Get-ChildItem $installPath -Force).Count -gt 0) {
                        $result = [System.Windows.Forms.MessageBox]::Show(
                            "The specified installation directory is not empty. Continue anyway?",
                            "Warning",
                            [System.Windows.Forms.MessageBoxButtons]::YesNo,
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        if ($result -eq [System.Windows.Forms.DialogResult]::No) {
                            Write-DashboardLog "User cancelled due to non-empty directory" -Level DEBUG
                            return
                        }
                    }
                }
                else {
                    try {
                        $null = New-Item -ItemType Directory -Path $installPath -Force -ErrorAction Stop
                        Remove-Item $installPath -Force
                    }
                    catch {
                        [System.Windows.Forms.MessageBox]::Show("Cannot create installation directory. Please check permissions.", "Validation Error")
                        Write-DashboardLog "Validation failed: Cannot create install directory - $($_.Exception.Message)" -Level ERROR
                        return
                    }
                }
            }

            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Installing server..."
            $createButton.Enabled = $false

            # Clear console output
            $consoleOutput.Clear()
            $consoleOutput.AppendText("Starting server installation...\n")

            # Modify job scriptblock to include output
            $job = Start-Job -ScriptBlock {
                param($name, $appId, $installDir, $serverManagerDir, $credentials)
                
                try {
                    # Get SteamCMD path from registry
                    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
                    $regValues = Get-ItemProperty -Path $registryPath -ErrorAction Stop
                    $steamCmdDir = $regValues.SteamCmdPath
                    Write-Output "[INFO] Initializing installation..."
                    Write-Output "[INFO] Server Name: $name"
                    Write-Output "[INFO] App ID: $appId"
                    Write-Output "[INFO] Install Directory: $installDir"
                    Write-Output "[INFO] Using SteamCMD directory: $steamCmdDir"
                    
                    # Create install directory if needed
                    if ($installDir -and -not (Test-Path $installDir)) {
                        Write-Output "[INFO] Creating installation directory"
                        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
                    }

                    # Start SteamCMD installation
                    Write-Output "[INFO] Starting SteamCMD download"
                    $result = Start-SteamCmdProcess -steamCmdPath $steamCmdPath -appId $appId -installDir $installDir -credentials $credentials

                    if ($result.Success) {
                        Write-Output "[SUCCESS] Installation completed successfully"
                        return @{
                            Success = $true
                            Message = "Server installed successfully"
                        }
                    } else {
                        throw $result.Message
                    }
                    
                } catch {
                    Write-Output "[ERROR] $($_.Exception.Message)"
                    throw $_
                }
            } -ArgumentList $nameTextBox.Text, $appIdTextBox.Text, $installDirTextBox.Text, $serverManagerDir, $SteamCredentials

            # Create timer to monitor job and update console
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 100
            $timer.Add_Tick({
                $job | Receive-Job | ForEach-Object {
                    $consoleOutput.AppendText("$_`n")
                    $consoleOutput.ScrollToCaret()
                }

                if ($job.State -eq 'Completed') {
                    $timer.Stop()
                    $result = Receive-Job -Job $job -Keep
                    Remove-Job -Job $job
                    $progressBar.MarqueeAnimationSpeed = 0
                    
                    if ($result.Success) {
                        $statusLabel.Text = "Installation complete!"
                        $consoleOutput.AppendText("[SUCCESS] Server created successfully.`n")
                        [System.Windows.Forms.MessageBox]::Show("Server created successfully.", "Success")
                        $createForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                        $createForm.Close()
                        Update-ServerList
                    } else {
                        $statusLabel.Text = "Installation failed!"
                        $consoleOutput.AppendText("[ERROR] Failed to create server: $($result.Message)`n")
                        $createButton.Enabled = $true
                    }
                }
            })
            $timer.Start()
        }
        catch {
            Write-DashboardLog "Critical error in server creation: $($_.Exception.Message)" -Level ERROR
            $consoleOutput.AppendText("[ERROR] Critical error: $($_.Exception.Message)`n")
            $statusLabel.Text = "Critical error!"
            $createButton.Enabled = $true
        }
    })

    # Add all controls to form
    $createForm.Controls.AddRange(@(
        $nameLabel, $nameTextBox,
        $appIdLabel, $appIdTextBox,
        $installDirLabel, $installDirTextBox,
        $browseButton, $consoleOutput,
        $statusLabel, $progressBar,
        $createButton
    ))

    $createForm.ShowDialog()
}

function Remove-IntegratedGameServer {
    $removeForm = New-Object System.Windows.Forms.Form
    $removeForm.Text = "Remove Game Server"
    $removeForm.Size = New-Object System.Drawing.Size(400,200)
    $removeForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $serverComboBox = New-Object System.Windows.Forms.ComboBox
    $serverComboBox.Location = New-Object System.Drawing.Point(120,20)
    $serverComboBox.Size = New-Object System.Drawing.Size(250,20)
    $serverComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList

    # Populate server list
    $configPath = Join-Path $serverManagerDir "servers"
    if (Test-Path $configPath) {
        Get-ChildItem -Path $configPath -Filter "*.json" | ForEach-Object {
            $serverComboBox.Items.Add($_.BaseName)
        }
    }

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(120,80)
    $progressBar.Size = New-Object System.Drawing.Size(250,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(120,60)
    $statusLabel.Size = New-Object System.Drawing.Size(250,20)
    $statusLabel.Text = ""

    $removeButton = New-Object System.Windows.Forms.Button
    $removeButton.Text = "Remove"
    $removeButton.Location = New-Object System.Drawing.Point(120,110)
    $removeButton.Add_Click({
        $serverName = $serverComboBox.SelectedItem

        if ([string]::IsNullOrEmpty($serverName)) {
            [System.Windows.Forms.MessageBox]::Show("Please select a server.", "Error")
            return
        }

        $confirmResult = [System.Windows.Forms.MessageBox]::Show(
            "Are you sure you want to remove the server '$serverName'?",
            "Confirm Removal",
            [System.Windows.Forms.MessageBoxButtons]::YesNo
        )

        if ($confirmResult -eq [System.Windows.Forms.DialogResult]::Yes) {
            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Removing server..."
            $removeButton.Enabled = $false

            # Start removal in background job
            $job = Start-Job -ScriptBlock {
                param($serverName, $serverManagerDir)
                
                try {
                    # Stop server if running
                    $configFile = Join-Path $serverManagerDir "servers\$serverName.json"
                    if (Test-Path $configFile) {
                        Remove-Item $configFile -Force
                    }
                    
                    return @{
                        Success = $true
                        Message = "Server removed successfully"
                    }
                }
                catch {
                    return @{
                        Success = $false
                        Message = $_.Exception.Message
                    }
                }
            } -ArgumentList $serverName, $serverManagerDir

            # Monitor the job
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 500
            $timer.Add_Tick({
                if ($job.State -eq 'Completed') {
                    $result = Receive-Job -Job $job
                    Remove-Job -Job $job
                    $timer.Stop()
                    $progressBar.MarqueeAnimationSpeed = 0
                    
                    if ($result.Success) {
                        $statusLabel.Text = "Removal complete!"
                        [System.Windows.Forms.MessageBox]::Show("Server removed successfully.", "Success")
                        $removeForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                        $removeForm.Close()
                        Update-ServerList
                    } else {
                        $statusLabel.Text = "Removal failed!"
                        [System.Windows.Forms.MessageBox]::Show("Failed to remove server: $($result.Message)", "Error")
                        $removeButton.Enabled = $true
                    }
                }
            })
            $timer.Start()
        }
    })

    $removeForm.Controls.AddRange(@(
        $nameLabel, $serverComboBox,
        $removeButton, $progressBar, $statusLabel
    ))

    $removeForm.ShowDialog()
}

function New-IntegratedAgent {
    $agentForm = New-Object System.Windows.Forms.Form
    $agentForm.Text = "Add Agent"
    $agentForm.Size = New-Object System.Drawing.Size(400,300)
    $agentForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Agent Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)
    
    $nameBox = New-Object System.Windows.Forms.TextBox
    $nameBox.Location = New-Object System.Drawing.Point(120,20)
    $nameBox.Size = New-Object System.Drawing.Size(250,20)

    $ipLabel = New-Object System.Windows.Forms.Label
    $ipLabel.Text = "IP Address:"
    $ipLabel.Location = New-Object System.Drawing.Point(10,50)
    $ipLabel.Size = New-Object System.Drawing.Size(100,20)

    $ipBox = New-Object System.Windows.Forms.TextBox
    $ipBox.Location = New-Object System.Drawing.Point(120,50)
    $ipBox.Size = New-Object System.Drawing.Size(250,20)

    $portLabel = New-Object System.Windows.Forms.Label
    $portLabel.Text = "Port:"
    $portLabel.Location = New-Object System.Drawing.Point(10,80)
    $portLabel.Size = New-Object System.Drawing.Size(100,20)

    $portBox = New-Object System.Windows.Forms.TextBox
    $portBox.Location = New-Object System.Drawing.Point(120,80)
    $portBox.Size = New-Object System.Drawing.Size(250,20)
    $portBox.Text = "8080"  # Default port

    $addButton = New-Object System.Windows.Forms.Button
    $addButton.Text = "Add Agent"
    $addButton.Location = New-Object System.Drawing.Point(120,120)
    $addButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text) -or 
            [string]::IsNullOrWhiteSpace($ipBox.Text) -or 
            [string]::IsNullOrWhiteSpace($portBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("Please fill in all fields.", "Error")
            return
        }

        try {
            $agentConfig = @{
                Name = $nameBox.Text
                IP = $ipBox.Text
                Port = $portBox.Text
                Added = Get-Date -Format "o"
            }

            $agentsPath = Join-Path $serverManagerDir "agents"
            if (-not (Test-Path $agentsPath)) {
                New-Item -ItemType Directory -Path $agentsPath -Force | Out-Null
            }

            $agentConfig | ConvertTo-Json | Set-Content -Path (Join-Path $agentsPath "$($nameBox.Text).json")
            [System.Windows.Forms.MessageBox]::Show("Agent added successfully!", "Success")
            $agentForm.Close()
        }
        catch {
            [System.Windows.Forms.MessageBox]::Show("Failed to add agent: $($_.Exception.Message)", "Error")
        }
    })

    $agentForm.Controls.AddRange(@(
        $nameLabel, $nameBox,
        $ipLabel, $ipBox,
        $portLabel, $portBox,
        $addButton
    ))

    $agentForm.ShowDialog()
}

# Create buttons with similar functionality to web dashboard
$addButton = New-Object System.Windows.Forms.Button
$addButton.Location = New-Object System.Drawing.Point(0,0)
$addButton.Size = New-Object System.Drawing.Size(100,30)
$addButton.Text = "Add Server"
$addButton.Add_Click({
    # Get Steam credentials first
    $credentials = Get-SteamCredentials
    if ($credentials -eq $null) {
        Write-DashboardLog "User cancelled Steam login" -Level DEBUG
        return
    }

    Write-DashboardLog "Steam login type: $(if ($credentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG
    New-IntegratedGameServer -SteamCredentials $credentials
})

$removeButton = New-Object System.Windows.Forms.Button
$removeButton.Location = New-Object System.Drawing.Point(110,0)
$removeButton.Size = New-Object System.Drawing.Size(100,30)
$removeButton.Text = "Remove Server"
$removeButton.Add_Click({
    Remove-IntegratedGameServer
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
$syncButton.Location = New-Object System.Windows.Forms.Point(440,0)
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
    New-IntegratedAgent
})

# Add WebSocket client with connection state tracking
$script:webSocketClient = $null
$script:isWebSocketConnected = $false

# Define WebSocket connection parameters with new port
$wsUri = "ws://localhost:8081/ws"  # Changed to match new WebSocket port
$webSocket = $null

# Add status label to the form (add this near the form creation code)
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Dock = [System.Windows.Forms.DockStyle]::Bottom
$statusLabel.Height = 25
$statusLabel.Padding = New-Object System.Windows.Forms.Padding(10, 0, 10, 5)
$statusLabel.Text = "WebSocket: Disconnected"
$statusLabel.ForeColor = [System.Drawing.Color]::Red
$form.Controls.Add($statusLabel)

# Replace the Connect-WebSocket function with this complete implementation
function Connect-WebSocket {
    # Variable setup
    $maxRetries = 5
    $retryCount = 0
    $retryDelay = 2
    $connected = $false
    $tcpClient = $null
    $webSocket = $null
    $cancellationToken = [System.Threading.CancellationToken]::None
    $connectionTimeout = 5000  # 5 seconds timeout

    Write-DashboardLog "Initializing WebSocket connection..." -Level DEBUG

    while (-not $connected -and $retryCount -lt $maxRetries) {
        try {
            $retryCount++
            Write-DashboardLog "Connection attempt $retryCount of $maxRetries" -Level DEBUG
            
            # Update UI status
            $form.Invoke([Action]{
                $statusLabel.Text = "WebSocket: Attempting connection (Try $retryCount of $maxRetries)..."
                $statusLabel.ForeColor = [System.Drawing.Color]::Blue
                $form.Refresh()
            })

            # Wait for both web server and WebSocket server to be ready
            $webReady = Test-Path $script:WebServerReadyFile
            $wsReady = Test-WebSocketReady
            
            if (-not ($webReady -and $wsReady)) {
                Write-DashboardLog "Waiting for servers to be ready (Try $retryCount/$maxRetries)" -Level DEBUG
                Start-Sleep -Seconds $retryDelay
                continue
            }
            
            # Get WebSocket configuration
            $wsConfig = Get-Content $script:WebSocketReadyFile -Raw | ConvertFrom-Json
            if (-not $wsConfig -or $wsConfig.status -ne "ready") {
                throw "WebSocket server not ready. Config: $($wsConfig | ConvertTo-Json)"
            }

            # Test TCP connection first
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            Write-DashboardLog "Testing TCP connection to localhost:$($wsConfig.port)" -Level DEBUG
            
            if (-not ($tcpClient.ConnectAsync("localhost", $wsConfig.port).Wait(2000))) {
                throw "TCP connection timeout"
            }
            $tcpClient.Close()

            # Initialize WebSocket connection
            $webSocket = New-Object System.Net.WebSockets.ClientWebSocket
            $wsUri = "ws://localhost:$($wsConfig.port)/ws"
            Write-DashboardLog "Connecting to WebSocket at $wsUri" -Level DEBUG

            # Set up WebSocket options
            $webSocket.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(30)
            $webSocket.Options.SetBuffer(8192, 8192)  # 8KB buffer size

            # Attempt connection with timeout
            $connectTask = $webSocket.ConnectAsync([System.Uri]::new($wsUri), $cancellationToken)
            if (-not $connectTask.Wait($connectionTimeout)) {
                throw "WebSocket connection timeout after $($connectionTimeout/1000) seconds"
            }

            if ($webSocket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                Write-DashboardLog "WebSocket connected successfully" -Level DEBUG
                $script:webSocketClient = $webSocket
                $script:isWebSocketConnected = $true
                
                # Update UI status
                $form.Invoke([Action]{
                    $statusLabel.Text = "WebSocket: Connected"
                    $statusLabel.ForeColor = [System.Drawing.Color]::Green
                })
                
                # Set up message handling
                $connected = $true
                
                # Initialize WebSocket listener
                Start-WebSocketListener
                
                # Send initial handshake message
                $handshake = @{
                    type = "handshake"
                    client = "dashboard"
                    version = "1.0"
                    timestamp = Get-Date -Format "o"
                } | ConvertTo-Json
                
                $buffer = [System.Text.Encoding]::UTF8.GetBytes($handshake)
                $segment = [ArraySegment[byte]]::new($buffer)
                
                $sendTask = $webSocket.SendAsync(
                    $segment,
                    [System.Net.WebSockets.WebSocketMessageType]::Text,
                    $true,
                    $cancellationToken
                )
                $sendTask.Wait(2000)
                
                Write-DashboardLog "WebSocket handshake sent" -Level DEBUG
            } else {
                throw "WebSocket failed to connect. State: $($webSocket.State)"
            }
        }
        catch {
            Write-DashboardLog "Connection attempt failed: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog $_.ScriptStackTrace -Level DEBUG
            
            if ($webSocket) {
                $webSocket.Dispose()
                $webSocket = $null
            }
            
            if ($retryCount -lt $maxRetries) {
                Write-DashboardLog "Retrying in $retryDelay seconds..." -Level DEBUG
                Start-Sleep -Seconds $retryDelay
            } else {
                # Update UI status for final failure
                $form.Invoke([Action]{
                    $statusLabel.Text = "WebSocket: Connection failed after $maxRetries attempts"
                    $statusLabel.ForeColor = [System.Drawing.Color]::Red
                })
                Write-DashboardLog "Connection failed after $maxRetries attempts" -Level ERROR
            }
        }
        finally {
            if ($null -ne $tcpClient) {
                $tcpClient.Dispose()
            }
        }
    }

    # Return connection status
    return $connected
}

# Update the Start-WebSocketListener function to handle messages properly
function Start-WebSocketListener {
    $buffer = [byte[]]::new(8192)  # 8KB buffer
    $cancelToken = [System.Threading.CancellationToken]::None
    
    $receiveTask = $script:webSocketClient.ReceiveAsync(
        [System.ArraySegment[byte]]::new($buffer),
        $cancelToken
    )

    $receiveTask.ContinueWith({
        param($Task)
        
        try {
            if ($Task.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) {
                if ($Task.Result.Count -gt 0) {
                    $jsonData = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $Task.Result.Count)
                    Write-DashboardLog "Received WebSocket message: $jsonData" -Level DEBUG
                    
                    $updateData = $jsonData | ConvertFrom-Json
                    
                    # Handle different message types
                    switch ($updateData.Type) {
                        "ServerListUpdate" {
                            $form.Invoke([Action]{
                                Update-ServerList
                            })
                        }
                        "HostUpdate" {
                            $form.Invoke([Action]{
                                Update-HostInformation
                            })
                        }
                        "Ping" {
                            # Respond to ping with pong
                            $pongMessage = @{
                                Type = "Pong"
                                Timestamp = Get-Date -Format "o"
                            } | ConvertTo-Json
                            
                            $pongBuffer = [System.Text.Encoding]::UTF8.GetBytes($pongMessage)
                            $script:webSocketClient.SendAsync(
                                [ArraySegment[byte]]::new($pongBuffer),
                                [System.Net.WebSockets.WebSocketMessageType]::Text,
                                $true,
                                $cancelToken
                            ).Wait()
                        }
                    }
                    
                    # Continue listening
                    Start-WebSocketListener
                }
            } else {
                $form.Invoke([Action]{
                    $statusLabel.Text = "WebSocket: Disconnected"
                    $statusLabel.ForeColor = [System.Drawing.Color]::Red
                    $script:isWebSocketConnected = $false
                })
                
                Write-DashboardLog "WebSocket disconnected. Task status: $($Task.Status)" -Level ERROR
                
                # Attempt reconnection
                Start-Sleep -Seconds 5
                Connect-WebSocket
            }
        }
        catch {
            Write-DashboardLog "Error in WebSocket listener: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog $_.ScriptStackTrace -Level DEBUG
            
            $form.Invoke([Action]{
                $statusLabel.Text = "WebSocket: Error"
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

# Create container panel for main content
$containerPanel = New-Object System.Windows.Forms.TableLayoutPanel
$containerPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$containerPanel.RowCount = 3
$containerPanel.ColumnCount = 1
$containerPanel.Padding = New-Object System.Windows.Forms.Padding(10)

# Set row styles for container panel
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))

# Modify form controls
$form.Controls.Clear()
$containerPanel.Controls.Add($mainPanel, 0, 0)
$containerPanel.Controls.Add($buttonPanel, 0, 1)
$containerPanel.Controls.Add($statusLabel, 0, 2)
$form.Controls.Add($containerPanel)

# Update button layout
$buttonPanel.AutoSize = $true
$buttonFlowPanel = New-Object System.Windows.Forms.FlowLayoutPanel
$buttonFlowPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$buttonFlowPanel.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$buttonFlowPanel.WrapContents = $false
$buttonFlowPanel.AutoSize = $true

# Add buttons to flow panel
@($addButton, $removeButton, $importButton, $refreshButton, $syncButton, $agentButton) | ForEach-Object {
    $_.AutoSize = $true
    $_.Margin = New-Object System.Windows.Forms.Padding(5)
    $buttonFlowPanel.Controls.Add($_)
}

$buttonPanel.Controls.Clear()
$buttonPanel.Controls.Add($buttonFlowPanel)

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

# Modify form shown event to remove credentials prompt
$form.Add_Shown({
    Connect-WebSocket
    Start-KeepAlivePing
    $refreshTimer.Start()
})

# Initial update
Update-ServerList
Update-HostInformation

# Replace the form closing event with this enhanced version
$form.Add_FormClosing({
    param($eventSender, $e)
    
    Write-DashboardLog "Dashboard closing initiated..." -Level DEBUG

    # If it's a user closing the form (not a system shutdown)
    if ($e.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing) {
        $result = [System.Windows.Forms.MessageBox]::Show(
            "Are you sure you want to close the Server Manager Dashboard?",
            "Confirm Exit",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )

        if ($result -eq [System.Windows.Forms.DialogResult]::No) {
            $e.Cancel = $true
            return
        }
    }
    
    Write-DashboardLog "Performing cleanup..." -Level DEBUG
    
    # Stop all timers
    if ($refreshTimer) {
        $refreshTimer.Stop()
        $refreshTimer.Dispose()
    }
    if ($script:pingTimer) {
        $script:pingTimer.Stop()
        $script:pingTimer.Dispose()
    }

    # Remove all event subscribers
    Get-EventSubscriber | Unregister-Event
    
    # Stop and clean up background jobs
    Get-Job | Stop-Job
    Get-Job | Remove-Job
    
    # Stop and clean up WebSocket
    if ($script:webSocketClient -ne $null) {
        try {
            $closeTask = $script:webSocketClient.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "Closing",
                [System.Threading.CancellationToken]::None
            )
            $closeTask.Wait(1000)
        } catch {
            Write-DashboardLog "Error closing WebSocket: $($_.Exception.Message)" -Level ERROR
        } finally {
            $script:webSocketClient.Dispose()
        }
    }

    # Cleanup performance counters
    if ($script:cpuCounter) {
        $script:cpuCounter.Dispose()
    }

    # Create a marker file to indicate clean shutdown
    $shutdownMarker = Join-Path $env:TEMP "dashboard_clean_shutdown"
    Set-Content -Path $shutdownMarker -Value (Get-Date -Format "o")
    
    Write-DashboardLog "Dashboard closed successfully" -Level DEBUG

    # Force the process to exit after cleanup
    [System.Windows.Forms.Application]::Exit()
    Stop-Process $pid -Force
})

# Show the form
$form.ShowDialog()

# Add these new integrated server management functions before the Import-ExistingServer function
function New-IntegratedGameServer {
    $createForm = New-Object System.Windows.Forms.Form
    $createForm.Text = "Create Game Server"
    $createForm.Size = New-Object System.Drawing.Size(450,300)
    $createForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $nameTextBox = New-Object System.Windows.Forms.TextBox
    $nameTextBox.Location = New-Object System.Drawing.Point(120,20)
    $nameTextBox.Size = New-Object System.Drawing.Size(250,20)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "App ID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10,60)
    $appIdLabel.Size = New-Object System.Drawing.Size(100,20)

    $appIdTextBox = New-Object System.Windows.Forms.TextBox
    $appIdTextBox.Location = New-Object System.Drawing.Point(120,60)
    $appIdTextBox.Size = New-Object System.Drawing.Size(250,20)

    $installDirLabel = New-Object System.Windows.Forms.Label
    $installDirLabel.Text = "Install Directory:"
    $installDirLabel.Location = New-Object System.Drawing.Point(10,100)
    $installDirLabel.Size = New-Object System.Drawing.Size(100,20)

    $installDirTextBox = New-Object System.Windows.Forms.TextBox
    $installDirTextBox.Location = New-Object System.Drawing.Point(120,100)
    $installDirTextBox.Size = New-Object System.Drawing.Size(200,20)

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse"
    $browseButton.Location = New-Object System.Drawing.Point(330,98)
    $browseButton.Size = New-Object System.Drawing.Size(60,22)
    $browseButton.Add_Click({
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "Select Installation Directory"
        if ($folderBrowser.ShowDialog() -eq 'OK') {
            $installDirTextBox.Text = $folderBrowser.SelectedPath
        }
    })

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(120,180)
    $progressBar.Size = New-Object System.Drawing.Size(250,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0
    
    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(120,160)
    $statusLabel.Size = New-Object System.Drawing.Size(250,20)
    $statusLabel.Text = ""

    $createButton = New-Object System.Windows.Forms.Button
    $createButton.Text = "Create"
    $createButton.Location = New-Object System.Drawing.Point(120,140)
    $createButton.Add_Click({
        try {
            Write-DashboardLog "Starting server creation process" -Level DEBUG
            
            $serverName = $nameTextBox.Text
            $appId = $appIdTextBox.Text
            $installDir = if ([string]::IsNullOrWhiteSpace($installDirTextBox.Text)) {
                Write-DashboardLog "Using default install directory" -Level DEBUG
                $defaultInstallDir
            } else {
                Write-DashboardLog "Using custom install directory: $($installDirTextBox.Text)" -Level DEBUG
                $installDirTextBox.Text
            }

            Write-DashboardLog "Server Name: $serverName, AppID: $appId, Install Dir: $installDir" -Level DEBUG

            if ([string]::IsNullOrWhiteSpace($serverName) -or [string]::IsNullOrWhiteSpace($appId)) {
                Write-DashboardLog "Validation failed: Missing required fields" -Level ERROR
                [System.Windows.Forms.MessageBox]::Show("Please fill in server name and App ID.", "Error")
                return
            }

            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Installing server..."
            $createButton.Enabled = $false

            Write-DashboardLog "Starting background job for server installation" -Level DEBUG

            # Get Steam credentials first
            $credentials = Get-SteamCredentials
            if ($credentials -eq $null) {
                Write-DashboardLog "User cancelled Steam login" -Level DEBUG
                return
            }

            Write-DashboardLog "Steam login type: $(if ($credentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG

            # Start the installation in a background job
            $job = Start-Job -ScriptBlock $script:jobScriptBlock -ArgumentList $serverName, $appId, $installDir, $serverManagerDir, $credentials

            Write-DashboardLog "Background job started with ID: $($job.Id)" -Level DEBUG

            # Monitor the job
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 500
            $timer.Add_Tick({
                if ($job.State -eq 'Completed') {
                    $result = Receive-Job -Job $job
                    Remove-Job -Job $job
                    $timer.Stop()
                    $progressBar.MarqueeAnimationSpeed = 0
                    
                    if ($result.Success) {
                        $statusLabel.Text = "Installation complete!"
                        [System.Windows.Forms.MessageBox]::Show("Server created successfully.", "Success")
                        $createForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                        $createForm.Close()
                        Update-ServerList
                    } else {
                        $statusLabel.Text = "Installation failed!"
                        [System.Windows.Forms.MessageBox]::Show("Failed to create server: $($result.Message)", "Error")
                        $createButton.Enabled = $true
                    }
                }
            })
            $timer.Start()
        }
        catch {
            Write-DashboardLog "Critical error in server creation: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog $_.ScriptStackTrace -Level ERROR
            $statusLabel.Text = "Critical error!"
            $createButton.Enabled = $true
            [System.Windows.Forms.MessageBox]::Show("Critical error occurred: $($_.Exception.Message)", "Error")
        }
    })

    $createForm.Controls.AddRange(@(
        $nameLabel, $nameTextBox,
        $appIdLabel, $appIdTextBox,
        $installDirLabel, $installDirTextBox,
        $browseButton, $createButton,
        $progressBar, $statusLabel
    ))

    $createForm.ShowDialog()
}

function Remove-IntegratedGameServer {
    $removeForm = New-Object System.Windows.Forms.Form
    $removeForm.Text = "Remove Game Server"
    $removeForm.Size = New-Object System.Drawing.Size(400,200)
    $removeForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
        $confirmResult = [System.Windows.Forms.MessageBox]::Show(
            "Are you sure you want to remove the server '$serverName'?",
            "Confirm Removal",
            [System.Windows.Forms.MessageBoxButtons]::YesNo
        )

        if ($confirmResult -eq [System.Windows.Forms.DialogResult]::Yes) {
            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Removing server..."
            $removeButton.Enabled = $false

            # Start removal in background job
            $job = Start-Job -ScriptBlock {
                param($serverName, $serverManagerDir)
                
                try {
                    # Stop server if running
                    $configFile = Join-Path $serverManagerDir "servers\$serverName.json"
                    if (Test-Path $configFile) {
                        Remove-Item $configFile -Force
                    }
                    
                    return @{
                        Success = $true
                        Message = "Server removed successfully"
                    }
                }
                catch {
                    return @{
                        Success = $false
                        Message = $_.Exception.Message
                    }
                }
            } -ArgumentList $serverName, $serverManagerDir

            # Monitor the job
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 500
            $timer.Add_Tick({
                if ($job.State -eq 'Completed') {
                    $result = Receive-Job -Job $job
                    Remove-Job -Job $job
                    $timer.Stop()
                    $progressBar.MarqueeAnimationSpeed = 0
                    
                    if ($result.Success) {
                        $statusLabel.Text = "Removal complete!"
                        [System.Windows.Forms.MessageBox]::Show("Server removed successfully.", "Success")
                        $removeForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                        $removeForm.Close()
                        Update-ServerList
                    } else {
                        $statusLabel.Text = "Removal failed!"
                        [System.Windows.Forms.MessageBox]::Show("Failed to remove server: $($result.Message)", "Error")
                        $removeButton.Enabled = $true
                    }
                }
            })
            $timer.Start()
        }
    }

    $removeForm.Controls.AddRange(@(
        $nameLabel, $serverComboBox,
        $removeButton, $progressBar, $statusLabel
    ))

    $removeForm.ShowDialog()

# Add new Steam login form function
function Get-SteamCredentials {
    $loginForm = New-Object System.Windows.Forms.Form
    $loginForm.Text = "Steam Login"
    $loginForm.Size = New-Object System.Drawing.Size(300,250)
    $loginForm.StartPosition = "CenterScreen"
    $loginForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $loginForm.MaximizeBox = $false

    $usernameLabel = New-Object System.Windows.Forms.Label
    $usernameLabel.Text = "Username:"
    $usernameLabel.Location = New-Object System.Drawing.Point(10,20)
    $usernameLabel.Size = New-Object System.Drawing.Size(100,20)

    $usernameBox = New-Object System.Windows.Forms.TextBox
    $usernameBox.Location = New-Object System.Drawing.Point(110,20)
    $usernameBox.Size = New-Object System.Drawing.Size(150,20)

    $passwordLabel = New-Object System.Windows.Forms.Label
    $passwordLabel.Text = "Password:"
    $passwordLabel.Location = New-Object System.Drawing.Point(10,50)
    $passwordLabel.Size = New-Object System.Drawing.Size(100,20)

    $passwordBox = New-Object System.Windows.Forms.TextBox
    $passwordBox.Location = New-Object System.Drawing.Point(110,50)
    $passwordBox.Size = New-Object System.Drawing.Size(150,20)
    $passwordBox.PasswordChar = '*'

    # Add Steam Guard controls (initially hidden)
    $guardLabel = New-Object System.Windows.Forms.Label
    $guardLabel.Text = "Steam Guard Code:"
    $guardLabel.Location = New-Object System.Drawing.Point(10,80)
    $guardLabel.Size = New-Object System.Drawing.Size(100,20)
    $guardLabel.Visible = $false

    $guardBox = New-Object System.Windows.Forms.TextBox
    $guardBox.Location = New-Object System.Drawing.Point(110,80)
    $guardBox.Size = New-Object System.Drawing.Size(150,20)
    $guardBox.MaxLength = 5
    $guardBox.Visible = $false

    $loginButton = New-Object System.Windows.Forms.Button
    $loginButton.Text = "Login"
    $loginButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $loginButton.Location = New-Object System.Drawing.Point(110,120)

    $anonButton = New-Object System.Windows.Forms.Button
    $anonButton.Text = "Anonymous"
    $anonButton.DialogResult = [System.Windows.Forms.DialogResult]::Ignore
    $anonButton.Location = New-Object System.Drawing.Point(110,150)

    $loginForm.Controls.AddRange(@(
        $usernameLabel, $usernameBox, 
        $passwordLabel, $passwordBox,
        $guardLabel, $guardBox,
        $loginButton, $anonButton
    ))

    $script:needsGuardCode = $false
    $script:guardCode = $null

    $result = $loginForm.ShowDialog()
    
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return @{
            Username = $usernameBox.Text
            Password = $passwordBox.Text
            GuardCode = $guardBox.Text
            Anonymous = $false
        }
    }
    elseif ($result -eq [System.Windows.Forms.DialogResult]::Ignore) {
        return @{
            Anonymous = $true
        }
    }
    else {
        return $null
    }
}

# Modify the server creation job to handle Steam Guard
function Start-SteamCmdProcess {
    param(
        [string]$steamCmdPath,
        [string]$appId,
        [string]$installDir,
        [hashtable]$credentials
    )

    $outputBuilder = New-Object System.Text.StringBuilder
    $errorBuilder = New-Object System.Text.StringBuilder
    $output = $null
    $errorOutput = $null
    $subscription_required = $false

    try {
        Write-DashboardLog "Starting SteamCMD process with following parameters:" -Level DEBUG
        Write-DashboardLog "SteamCMD Path: $steamCmdPath" -Level DEBUG
        Write-DashboardLog "App ID: $appId" -Level DEBUG
        Write-DashboardLog "Install Directory: $installDir" -Level DEBUG
        Write-DashboardLog "Login Type: $(if ($credentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG

        # Build the complete SteamCMD command
        $steamCmdArgs = if ($credentials.Anonymous) {
            "+login anonymous"
        } else {
            "+login `"$($credentials.Username)`" `"$($credentials.Password)`""
        }

        if ($installDir) {
            $steamCmdArgs += " +force_install_dir `"$installDir`""
        }

        # Add the app update command
        $steamCmdArgs += " +app_update $appId validate +quit"

        Write-DashboardLog "Final SteamCMD arguments: $steamCmdArgs" -Level DEBUG

        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $steamCmdPath
        $pinfo.Arguments = $steamCmdArgs
        $pinfo.UseShellExecute = $false
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true
        $pinfo.RedirectStandardInput = $true
        $pinfo.CreateNoWindow = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $pinfo

        # Create event handlers for output
        $outputBuilder = New-Object System.Text.StringBuilder
        $errorBuilder = New-Object System.Text.StringBuilder

        $process.OutputDataReceived = {
            param($eventSender, $e)
            if ($null -ne $e.Data) {
                $outputBuilder.AppendLine($e.Data)
                Write-DashboardLog "SteamCMD: $($e.Data)" -Level DEBUG
            }
        }

        $process.ErrorDataReceived = {
            param($eventSender, $e)
            if ($null -ne $e.Data) {
                $errorBuilder.AppendLine($e.Data)
                Write-DashboardLog "SteamCMD Error: $($e.Data)" -Level ERROR
            }
        }

        Write-DashboardLog "Starting SteamCMD process..." -Level DEBUG
        $process.Start() | Out-Null
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()

        # Wait for the process to complete with a timeout
        $timeout = 600 # 10 minutes
        if (!$process.WaitForExit($timeout * 1000)) {
            Write-DashboardLog "SteamCMD process timed out after $timeout seconds" -Level ERROR
            $process.Kill()
            throw "SteamCMD process timed out after $timeout seconds"
        }

        $output = $outputBuilder.ToString()
        $errorOutput = $errorBuilder.ToString()

        Write-DashboardLog "SteamCMD process completed with exit code: $($process.ExitCode)" -Level DEBUG

        # Check for common errors in the output
        $subscription_required = $output -match "No subscription|Ownership check failed|Access denied|Purchase required"
        $invalid_credentials = $output -match "Invalid Password|Login Failure|Account not found"
        $invalid_guard_code = $output -match "Invalid Steam Guard code"

        if ($invalid_credentials) {
            throw "Login failed: Invalid credentials"
        }
        if ($invalid_guard_code) {
            throw "Invalid Steam Guard code"
        }

        return @{
            ExitCode = $process.ExitCode
            Output = $output
            Error = $errorOutput
            SubscriptionRequired = $subscription_required
        }
    }
    catch {
        Write-DashboardLog "Error in Start-SteamCmdProcess: $($_.Exception.Message)" -Level ERROR
        Write-DashboardLog $_.ScriptStackTrace -Level ERROR
        throw
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

# Modify the server creation job scriptblock
$job = Start-Job -ScriptBlock {
    param($name, $appId, $installDir, $serverManagerDir, $credentials)
    
    try {
        # Get SteamCMD path from registry
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $regValues = Get-ItemProperty -Path $registryPath -ErrorAction Stop
        $steamCmdPath = Join-Path $regValues.SteamCmdPath "steamcmd.exe"
        
        if (-not (Test-Path $steamCmdPath)) {
            throw "SteamCMD not found at: $steamCmdPath"
        }

        # If installDir is empty, create a default path
        if ([string]::IsNullOrWhiteSpace($installDir)) {
            $installDir = Join-Path $regValues.SteamCmdPath "steamapps\common\$name"
        }

        # Ensure install directory exists
        if (-not (Test-Path $installDir)) {
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        }

        Write-Output "Starting SteamCMD installation process..."
        $result = Start-SteamCmdProcess -steamCmdPath $steamCmdPath -appId $appId -installDir $installDir -credentials $credentials

        if ($result.SubscriptionRequired) {
            throw "This server requires a valid Steam subscription or game ownership"
        }

        if ($result.ExitCode -ne 0) {
            throw "SteamCMD failed with exit code: $($result.ExitCode)`nErrors: $($result.Error)"
        }

        # Create server configuration
        Write-Output "Creating server configuration..."
        $serverConfig = @{
            Name = $name
            AppID = $appId
            InstallDir = $installDir
            Created = Get-Date -Format "o"
            LastUpdate = Get-Date -Format "o"
        }

        $configPath = Join-Path $serverManagerDir "servers"
        if (-not (Test-Path $configPath)) {
            New-Item -ItemType Directory -Path $configPath -Force | Out-Null
        }

        $configFile = Join-Path $configPath "$name.json"
        $serverConfig | ConvertTo-Json | Set-Content -Path $configFile

        return @{
            Success = $true
            Message = "Server created successfully"
            InstallPath = $installDir
        }
    }
    catch {
        return @{
            Success = $false
            Message = $_.Exception.Message
            SubscriptionRequired = $false
        }
    }
} -ArgumentList $serverName, $appId, $installDir, $serverManagerDir, $credentials

# Create timer to monitor installation progress
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
    if ($job.State -eq 'Completed') {
        $result = Receive-Job -Job $job
        Remove-Job -Job $job
        $timer.Stop()
        $progressBar.MarqueeAnimationSpeed = 0
        
        if ($result.Success) {
            $statusLabel.Text = "Installation complete!"
            [System.Windows.Forms.MessageBox]::Show("Server created successfully.", "Success")
            $createForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $createForm.Close()
            Update-ServerList
        } else {
            $statusLabel.Text = "Installation failed!"
            [System.Windows.Forms.MessageBox]::Show("Failed to create server: $($result.Message)", "Error")
            $createButton.Enabled = $true
        }
    }
})
$timer.Start()

# Define the job script block before the New-IntegratedGameServer function
$script:jobScriptBlock = {
    param($name, $appId, $installDir, $serverManagerDir, $credentials)
    
    try {
        # Get SteamCMD path from registry
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $regValues = Get-ItemProperty -Path $registryPath -ErrorAction Stop
        $steamCmdDir = $regValues.SteamCmdPath
        Write-Output "Using SteamCMD directory: $steamCmdDir"
        
        # If installDir is empty, let Steam choose the default path
        if ([string]::IsNullOrWhiteSpace($installDir)) {
            Write-Output "Using Steam's default installation path"
            $installDir = "" # Empty string will let Steam use its default path
        }

        # Only create directory if a custom path is specified
        if ($installDir -and -not (Test-Path $installDir)) {
            Write-Output "Creating custom install directory: $installDir"
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        }

        Write-Output "Starting server installation..."
        
        # Build SteamCMD command
        $steamCmdArgs = if ($credentials.Anonymous) {
            "+login anonymous"
        } else {
            "+login `"$($credentials.Username)`" `"$($credentials.Password)`""
        }

        if ($installDir) {
            $steamCmdArgs += " +force_install_dir `"$installDir`""
        }

        $steamCmdArgs += " +app_update $appId validate +quit"
        
        Write-Output "Running SteamCMD with arguments: $steamCmdArgs"

        # Start SteamCMD process
        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $steamCmdPath
        $pinfo.Arguments = $steamCmdArgs
        $pinfo.UseShellExecute = $false
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true
        $pinfo.RedirectStandardInput = $true
        $pinfo.CreateNoWindow = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $pinfo
        
        Write-Output "Starting SteamCMD process..."
        $process.Start() | Out-Null

        # Capture output in real-time
        $output = New-Object System.Text.StringBuilder
        while (!$process.StandardOutput.EndOfStream) {
            $line = $process.StandardOutput.ReadLine()
            $output.AppendLine($line)
            Write-Output $line
        }

        $errorOutput = $process.StandardError.ReadToEnd()
        $process.WaitForExit()

        Write-Output "SteamCMD process completed with exit code: $($process.ExitCode)"
        
        if ($errorOutput) {
            Write-Output "SteamCMD Errors:"
            Write-Output $errorOutput
        }

        if ($process.ExitCode -ne 0) {
            throw "SteamCMD failed with exit code: $($process.ExitCode)`nOutput: $($output.ToString())`nErrors: $errorOutput"
        }

        # Verify installation
        if (-not (Test-Path $installDir)) {
            throw "Installation directory not created: $installDir"
        }

        $installedFiles = Get-ChildItem -Path $installDir -Recurse
        if (-not $installedFiles) {
            throw "No files were installed to: $installDir"
        }

        # Create server configuration
        Write-Output "Creating server configuration..."
        $serverConfig = @{
            Name = $name
            AppID = $appId
            InstallDir = $installDir
            Created = Get-Date -Format "o"
            LastUpdate = Get-Date -Format "o"
        }

        $configPath = Join-Path $serverManagerDir "servers"
        if (-not (Test-Path $configPath)) {
            Write-Output "Creating servers directory: $configPath"
            New-Item -ItemType Directory -Path $configPath -Force | Out-Null
        }

        $configFile = Join-Path $configPath "$name.json"
        Write-Output "Saving configuration to: $configFile"
        $serverConfig | ConvertTo-Json | Set-Content -Path $configFile -Force

        Write-Output "Configuration saved successfully"

        return @{
            Success = $true
            Message = "Server created successfully at $installDir"
            InstallPath = $installDir
        }
    }
    catch {
        Write-Output "Error occurred: $($_.Exception.Message)"
        Write-Output "Stack trace: $($_.ScriptStackTrace)"
        return @{
            Success = $false
            Message = $_.Exception.Message
        }
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

# Show the form (this should be at the end of the script)
$form.ShowDialog()
# Add buttons to panel
$buttonPanel.Controls.Add($addButton)
$buttonPanel.Controls.Add($removeButton)
$buttonPanel.Controls.Add($importButton)
$buttonPanel.Controls.Add($refreshButton)
$buttonPanel.Controls.Add($syncButton)
$buttonPanel.Controls.Add($agentButton)

# Connect WebSocket
Connect-WebSocket

# Start refresh timer
$refreshTimer.Start()

# Initial updates
Update-ServerList
Update-HostInformation

# Modify Connect-WebSocket function
function Connect-WebSocket {
    # Variable setup
    $maxRetries = 5
    $retryCount = 0
    $retryDelay = 2
    $connected = $false
    $tcpClient = $null
    $webSocket = $null
    $cancellationToken = [System.Threading.CancellationToken]::None
    $connectionTimeout = 5000  # 5 seconds timeout

    Write-DashboardLog "Initializing WebSocket connection..." -Level DEBUG
    
    while (-not $connected -and $retryCount -lt $maxRetries) {
        try {
            # Wait for both web server and WebSocket server to be ready
            $webReady = Test-Path $script:WebServerReadyFile
            $wsReady = Test-WebSocketReady
            
            if (-not ($webReady -and $wsReady)) {
                Write-DashboardLog "Waiting for servers to be ready (Try $retryCount/$maxRetries)" -Level DEBUG
                Start-Sleep -Seconds $retryDelay
                continue
            }
            
            # Get WebSocket configuration
            $wsConfig = Get-Content $script:WebSocketReadyFile -Raw | ConvertFrom-Json
            $wsUri = "ws://localhost:$($wsConfig.port)/ws"
        }
        catch {
            Write-DashboardLog "Failed to initialize WebSocket connection: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog $_.ScriptStackTrace -Level DEBUG
            
            if ($retryCount -lt $maxRetries) {
                Write-DashboardLog "Retrying in $retryDelay seconds..." -Level DEBUG
                Start-Sleep -Seconds $retryDelay
                $retryCount++
            } else {
                Write-DashboardLog "Max retries reached. WebSocket connection failed." -Level ERROR
                $form.Invoke([Action]{
                    $statusLabel.Text = "WebSocket: Connection failed"
                    $statusLabel.ForeColor = [System.Drawing.Color]::Red
                })
                return $false
            }
        }
    }
}

# Add periodic health check
$script:healthCheckTimer = New-Object System.Windows.Forms.Timer
$script:healthCheckTimer.Interval = 5000 # 5 seconds
$script:healthCheckTimer.Add_Tick({
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing
        $health = $response.Content | ConvertFrom-Json
        
        if (-not $health.webSocketConnected -and $script:isWebSocketConnected) {
            Write-DashboardLog "WebSocket disconnected, attempting reconnect..." -Level WARN
            Connect-WebSocket
        }
    }
    catch {
        Write-DashboardLog "Health check failed: $_" -Level ERROR
        if ($script:isWebSocketConnected) {
            $script:isWebSocketConnected = $false
            $statusLabel.Text = "WebSocket: Disconnected"
            $statusLabel.ForeColor = [System.Drawing.Color]::Red
        }
    }
})

# Start health check timer in form shown event
$form.Add_Shown({
    $script:healthCheckTimer.Start()
})

# Clean up timer in form closing event
$form.Add_FormClosing({
    param($eventSender, $e)
  
    if ($script:healthCheckTimer) {
        $script:healthCheckTimer.Stop()
        $script:healthCheckTimer.Dispose()
    }
})
