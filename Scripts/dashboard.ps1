# Initialize essential paths first
$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

try {
    # Get base paths from registry
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    if (-not (Test-Path $registryPath)) {
        throw "Server Manager registry path not found"
    }

    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    if (-not $serverManagerDir) {
        throw "Server Manager directory not found in registry"
    }

    # Clean up path
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')

    # Initialize essential script-scope paths
    $script:Paths = @{
        Root = $serverManagerDir
        Logs = Join-Path $serverManagerDir "logs"
        Config = Join-Path $serverManagerDir "config"
        Temp = Join-Path $serverManagerDir "temp"
        Servers = Join-Path $serverManagerDir "servers"
        Modules = Join-Path $serverManagerDir "Modules"
    }

    # Ensure temp directory exists
    if (-not (Test-Path $script:Paths.Temp)) {
        New-Item -Path $script:Paths.Temp -ItemType Directory -Force | Out-Null
    }

    # Define ready file paths
    $script:ReadyFiles = @{
        WebServer = Join-Path $script:Paths.Temp "webserver.ready"
        WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
    }

    # Initialize log path
    $script:LogPath = Join-Path $script:Paths.Logs "dashboard.log"
}
catch {
    Write-Error "Failed to initialize paths: $_"
    exit 1
}

# Define required modules
$moduleImports = @(
    "Common.psm1",
    "Network.psm1",
    "WebSocketServer.psm1",
    "ServerManager.psm1",
    "Authentication.psm1"
)

# Get registry paths at startup
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir

# Get module path from registry
$modulesPath = Join-Path $serverManagerDir "Modules"

# Load all required modules
foreach ($module in $moduleImports) {
    $modulePath = Join-Path $modulesPath $module
    if (Test-Path $modulePath) {
        Import-Module $modulePath -Force -DisableNameChecking
    } else {
        throw "Required module not found: $modulePath"
    }
}

# Set strict error handling
$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

# Add Windows Forms assemblies first
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName PresentationFramework

# Initialize base paths
$script:Paths = @{
    Logs = Join-Path $serverManagerDir "logs"
    Config = Join-Path $serverManagerDir "config"
    Temp = Join-Path $serverManagerDir "temp"
    Servers = Join-Path $serverManagerDir "servers"
}

# Ensure required directories exist
foreach ($path in $script:Paths.Values) {
    if (-not (Test-Path $path)) {
        New-Item -Path $path -ItemType Directory -Force | Out-Null
    }
}

# Add ready files paths
$script:ReadyFiles = @{
    WebServer = Join-Path $script:Paths.Temp "webserver.ready"
    WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
}

# Add console window handling functions first
function Hide-ConsoleWindow {
    try {
        if (-not ("Win32.NativeMethods" -as [Type])) {
            Add-Type -Name NativeMethods -Namespace Win32 -MemberDefinition '
                [DllImport("kernel32.dll")]
                public static extern IntPtr GetConsoleWindow();
                [DllImport("user32.dll")]
                public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
            '
        }
        $consolePtr = [Win32.NativeMethods]::GetConsoleWindow()
        [Win32.NativeMethods]::ShowWindow($consolePtr, 0) | Out-Null
        Write-DashboardLog "Console window hidden" -Level DEBUG
    }
    catch {
        Write-Warning "Failed to hide console window: $($_.Exception.Message)"
    }
}

function Show-ConsoleWindow {
    try {
        if (-not ("Win32.NativeMethods" -as [Type])) {
            Add-Type -Name NativeMethods -Namespace Win32 -MemberDefinition '
                [DllImport("kernel32.dll")]
                public static extern IntPtr GetConsoleWindow();
                [DllImport("user32.dll")]
                public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
            '
        }
        $consolePtr = [Win32.NativeMethods]::GetConsoleWindow()
        [Win32.NativeMethods]::ShowWindow($consolePtr, 5) | Out-Null
        Write-DashboardLog "Console window shown" -Level DEBUG
    }
    catch {
        Write-Warning "Failed to show console window: $($_.Exception.Message)"
    }
}

# Add script variables
$script:previousNetworkStats = @{}
$script:previousNetworkTime = Get-Date
$script:webSocketClient = $null
$script:isWebSocketConnected = $false
$script:lastServerListUpdate = [DateTime]::MinValue
$script:lastFullUpdate = [DateTime]::MinValue

# Initialize logging
function Write-DashboardLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [$Level] - $Message" | Add-Content -Path $script:LogPath -ErrorAction Stop
        
        if ($script:DebugLoggingEnabled -or $Level -eq "ERROR") {
            $color = switch ($Level) {
                "ERROR" { "Red" }
                "DEBUG" { "Yellow" }
                "WARN"  { "Magenta" }
                default { "White" }
            }
            Write-Host "[$Level] $Message" -ForegroundColor $color
        }
    }
    catch {
        Write-Warning "Failed to write to log: $_"
    }
}

# Add verification before WebSocket connection
function Test-ServerPaths {
    Write-DashboardLog "Verifying server paths..." -Level DEBUG
    Write-DashboardLog "TempPath: $($script:Paths.Temp)" -Level DEBUG
    Write-DashboardLog "WebServerReadyFile: $($script:ReadyFiles.WebServer)" -Level DEBUG
    Write-DashboardLog "WebSocketReadyFile: $($script:ReadyFiles.WebSocket)" -Level DEBUG
    
    if (-not (Test-Path $script:Paths.Temp)) {
        Write-DashboardLog "Temp directory not found" -Level ERROR
        return $false
    }
    
    return $true
}

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
        $serverConfig | ConvertTo-Json | Set-Content $configFile -Force

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
Hide-ConsoleWindow

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
$hostnamePanel = New-Object System.Windows.Forms.TableLayoutPanel
$hostnamePanel.ColumnCount = 2
$hostnamePanel.RowCount = 6
$hostnamePanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$hostnamePanel.Padding = New-Object System.Windows.Forms.Padding(10)
$hostnamePanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 30)))
$hostnamePanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))

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
    $hostnamePanel.Controls.Add((New-MetricLabel $_.Key), 0, $row)
    $valueLabel = New-MetricLabel $_.Value
    $valueLabel.Name = "lbl$($_.Key -replace '\s','')"
    $hostnamePanel.Controls.Add($valueLabel, 1, $row)
    $row++
}

# Modify host panel settings
$hostnamePanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$hostnamePanel.AutoSize = $true

# Add panels to main layout
$mainPanel.Controls.Add($serversPanel, 0, 0)
$mainPanel.Controls.Add($hostnamePanel, 1, 0)

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

# Fix the Size property for the sync button
$syncButton = New-Object System.Windows.Forms.Button
$syncButton.Location = New-Object System.Drawing.Point(440, 0)
$syncButton.Size = New-Object System.Drawing.Size(100, 30)
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

# First, simplify the WebSocket connection function to be more direct and handle async operations better
function Connect-WebSocket {
    param (
        [int]$MaxAttempts = 5,
        [int]$RetryDelay = 2,
        [int]$ConnectionTimeout = 5000  # 5 seconds timeout
    )
    
    Write-DashboardLog "Starting WebSocket connection sequence..." -Level DEBUG
    
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Write-DashboardLog "Connection attempt $attempt of $MaxAttempts" -Level DEBUG
            
            # Check ready file with retry
            $startTime = Get-Date
            while (-not (Test-Path $script:ReadyFiles.WebSocket)) {
                if ((Get-Date) - $startTime -gt [TimeSpan]::FromSeconds(5)) {
                    throw "Timeout waiting for WebSocket ready file"
                }
                Start-Sleep -Milliseconds 500
            }

            $wsConfig = Get-Content $script:ReadyFiles.WebSocket -Raw | ConvertFrom-Json
            $port = $wsConfig.port
            Write-DashboardLog "Found WebSocket port: $port" -Level DEBUG

            # TCP connection test with proper cleanup
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            try {
                Write-DashboardLog "Testing TCP connection..." -Level DEBUG
                $tcpResult = $tcpClient.BeginConnect("localhost", $port, $null, $null)
                $tcpSuccess = $tcpResult.AsyncWaitHandle.WaitOne(2000) # 2 second timeout
                
                if (-not $tcpSuccess) {
                    throw "TCP connection test failed - timeout"
                }
                
                $tcpClient.EndConnect($tcpResult)
                Write-DashboardLog "TCP connection test successful" -Level DEBUG
            }
            finally {
                $tcpClient.Close()
                $tcpClient.Dispose()
            }

            # Create WebSocket with proper disposal
            $ws = New-Object System.Net.WebSockets.ClientWebSocket
            try {
                $ws.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(30)
                $ws.Options.SetBuffer(8192, 8192) # Increase buffer size
                
                Write-DashboardLog "Initializing WebSocket connection..." -Level DEBUG
                
                # Create URI and cancellation token
                $uri = New-Object System.Uri "ws://localhost:$port/ws"
                $cts = New-Object System.Threading.CancellationTokenSource
                $cts.CancelAfter($ConnectionTimeout)
                
                Write-DashboardLog "Attempting WebSocket connection to $uri" -Level DEBUG
                
                # Connect with task-based approach
                $connectTask = $ws.ConnectAsync($uri, $cts.Token)
                
                # Wait for connection with progress tracking
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                while (-not $connectTask.IsCompleted) {
                    if ($sw.ElapsedMilliseconds -gt $ConnectionTimeout) {
                        throw "Connection timed out after $($ConnectionTimeout)ms"
                    }
                    
                    if ($cts.Token.IsCancellationRequested) {
                        throw "Connection cancelled by timeout"
                    }
                    
                    Start-Sleep -Milliseconds 100
                }
                
                if ($connectTask.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion) {
                    if ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                        Write-DashboardLog "WebSocket connected successfully" -Level DEBUG
                        $script:webSocketClient = $ws
                        $script:isWebSocketConnected = $true
                        
                        # Update UI status
                        $form.Invoke([Action]{
                            $statusLabel.Text = "WebSocket: Connected"
                            $statusLabel.ForeColor = [System.Drawing.Color]::Green
                        })

                        # Start message listener
                        Start-WebSocketListener
                        return $true
                    }
                }
                
                throw "WebSocket failed to enter Open state (State: $($ws.State))"
            }
            catch {
                Write-DashboardLog "WebSocket connection error: $($_.Exception.Message)" -Level ERROR
                if ($ws -ne $null) {
                    $ws.Dispose()
                }
                throw
            }
            finally {
                if ($cts) { $cts.Dispose() }
            }
        }
        catch {
            Write-DashboardLog "Connection attempt failed: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog $_.ScriptStackTrace -Level DEBUG
            
            if ($attempt -lt $MaxAttempts) {
                Write-DashboardLog "Retrying in $RetryDelay seconds..." -Level DEBUG
                Start-Sleep -Seconds $RetryDelay
            }
        }
    }
    
    Write-DashboardLog "Failed to connect after $MaxAttempts attempts" -Level ERROR
    $form.Invoke([Action]{
        $statusLabel.Text = "WebSocket: Connection Failed"
        $statusLabel.ForeColor = [System.Drawing.Color]::Red
    })
    return $false
}

# Add this helper function to verify WebSocket server status
function Test-WebSocketServer {
    param (
        [int]$TimeoutSeconds = 5
    )
    
    try {
        $startTime = Get-Date
        while ((Get-Date) - $startTime -lt [TimeSpan]::FromSeconds($TimeoutSeconds)) {
            if (Test-Path $script:ReadyFiles.WebSocket) {
                $config = Get-Content $script:ReadyFiles.WebSocket -Raw | ConvertFrom-Json
                if ($config.status -eq "ready" -and $config.port) {
                    # Try TCP connection
                    $tcpClient = New-Object System.Net.Sockets.TcpClient
                    try {
                        $result = $tcpClient.BeginConnect("localhost", $config.port, $null, $null)
                        if ($result.AsyncWaitHandle.WaitOne(2000)) {
                            $tcpClient.EndConnect($result)
                            return $true
                        }
                    }
                    finally {
                        $tcpClient.Close()
                        $tcpClient.Dispose()
                    }
                }
            }
            Start-Sleep -Milliseconds 500
        }
        return $false
    }
    catch {
        Write-DashboardLog "Error testing WebSocket server: $_" -Level ERROR
        return $false
    }
}

# Modify the form's Shown event to use the new test function
$form.Add_Shown({
    Write-DashboardLog "Dashboard form shown, initializing components..." -Level DEBUG
    
    # First verify WebSocket server is running
    if (-not (Test-WebSocketServer -TimeoutSeconds 10)) {
        Write-DashboardLog "WebSocket server not available" -Level ERROR
        [System.Windows.Forms.MessageBox]::Show(
            "WebSocket server is not running or not accessible. Please ensure the server is started.",
            "Connection Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
        return
    }

    # Attempt WebSocket connection
    if (Connect-WebSocket -MaxAttempts 5 -RetryDelay 2 -ConnectionTimeout 10000) {
        Write-DashboardLog "WebSocket connection established, starting services..." -Level DEBUG
        Start-KeepAlivePing
        $refreshTimer.Start()
    } else {
        Write-DashboardLog "Failed to establish WebSocket connection" -Level ERROR
        [System.Windows.Forms.MessageBox]::Show(
            "Failed to connect to WebSocket server. The dashboard will continue in limited mode.",
            "Connection Warning",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
    }
})

# Modify the form's Shown event to be more sequential
$form.Add_Shown({
    Write-DashboardLog "Dashboard form shown, initializing components..." -Level DEBUG
    
    # First verify all required files exist
    if (-not (Test-Path $script:ReadyFiles.WebSocket)) {
        Write-DashboardLog "Waiting for WebSocket ready file..." -Level DEBUG
        Start-Sleep -Seconds 2
    }

    # Attempt WebSocket connection
    if (Connect-WebSocket) {
        Write-DashboardLog "WebSocket connection established, starting services..." -Level DEBUG
        Start-KeepAlivePing
        $refreshTimer.Start()
    } else {
        Write-DashboardLog "Failed to establish WebSocket connection" -Level ERROR
        [System.Windows.Forms.MessageBox]::Show(
            "Failed to connect to WebSocket server. The dashboard will continue in limited mode.",
            "Connection Warning",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
    }
})

# Modify Start-WebSocketListener to be more robust
function Start-WebSocketListener {
    if (-not $script:webSocketClient -or $script:webSocketClient.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
        Write-DashboardLog "Cannot start listener - WebSocket not connected" -Level ERROR
        return
    }

    [System.Threading.Tasks.Task]::Run({
        $buffer = [byte[]]::new(4096)
        $ct = [System.Threading.CancellationToken]::None

        while ($script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            try {
                $segment = [ArraySegment[byte]]::new($buffer)
                $result = $script:webSocketClient.ReceiveAsync($segment, $ct).GetAwaiter().GetResult()

                if ($result.Count -gt 0) {
                    $message = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                    Write-DashboardLog "Received: $message" -Level DEBUG

                    $form.Invoke([Action]{
                        try {
                            $data = $message | ConvertFrom-Json
                            switch ($data.Type) {
                                "ServerUpdate" {
                                    # Update server information in the UI
                                    if ($data.Servers) {
                                        $listView.Items.Clear()
                                        foreach ($server in $data.Servers) {
                                            $item = New-Object System.Windows.Forms.ListViewItem($server.Name)
                                            $item.SubItems.Add($server.Status)
                                            $item.SubItems.Add($server.CPU)
                                            $item.SubItems.Add($server.Memory)
                                            $item.SubItems.Add($server.Uptime)
                                            $listView.Items.Add($item)
                                        }
                                    }
                                }
                                "HostUpdate" {
                                    # Update host metrics
                                    if ($data.CPUUsage) {
                                        $lblCPUUsage = $hostnamePanel.Controls["lblCPUUsage"]
                                        $lblCPUUsage.Text = $data.CPUUsage
                                    }
                                    if ($data.MemoryUsage) {
                                        $lblMemoryUsage = $hostnamePanel.Controls["lblMemoryUsage"]
                                        $lblMemoryUsage.Text = $data.MemoryUsage
                                    }
                                    if ($data.DiskUsage) {
                                        $lblDiskUsage = $hostnamePanel.Controls["lblDiskUsage"]
                                        $lblDiskUsage.Text = $data.DiskUsage
                                    }
                                    if ($data.NetworkUsage) {
                                        $lblNetworkUsage = $hostnamePanel.Controls["lblNetworkUsage"]
                                        $lblNetworkUsage.Text = $data.NetworkUsage
                                    }
                                    if ($data.GPUInfo) {
                                        $lblGPUInfo = $hostnamePanel.Controls["lblGPUInfo"]
                                        $lblGPUInfo.Text = $data.GPUInfo
                                    }
                                    if ($data.SystemUptime) {
                                        $lblSystemUptime = $hostnamePanel.Controls["lblSystemUptime"]
                                        $lblSystemUptime.Text = $data.SystemUptime
                                    }
                                }
                                "Ping" {
                                    # Respond with Pong message
                                    Send-PongMessage
                                }
                                "Error" {
                                    Write-DashboardLog "Server error: $($data.Message)" -Level ERROR
                                }
                            }
                        }
                        catch {
                            Write-DashboardLog "Failed to process message: $_" -Level ERROR
                        }
                    })
                }
            }
            catch {
                Write-DashboardLog "Error in receive loop: $_" -Level ERROR
                break
            }
        }

        Write-DashboardLog "WebSocket connection closed" -Level DEBUG
        $script:isWebSocketConnected = $false
        
        $form.Invoke([Action]{
            $statusLabel.Text = "WebSocket: Disconnected"
            $statusLabel.ForeColor = [System.Drawing.Color]::Red
        })

        # Attempt reconnection after a delay
        Start-Sleep -Seconds 5
        $form.Invoke([Action]{ Connect-WebSocket })
    })
}

# Function to implement the websocket keep-alive ping
function Start-KeepAlivePing {
    $script:pingTimer = New-Object System.Windows.Forms.Timer
    $script:pingTimer.Interval = 30000 # 30 seconds
    $script:pingTimer.Add_Tick({
        if ($script:webSocketClient -and $script:isWebSocketConnected -and 
            $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            try {
                $pingMessage = @{
                    Type = "Ping"
                    Timestamp = Get-Date -Format "o"
                } | ConvertTo-Json

                $buffer = [System.Text.Encoding]::UTF8.GetBytes($pingMessage)
                $segment = [ArraySegment[byte]]::new($buffer)
                
                $script:webSocketClient.SendAsync(
                    $segment,
                    [System.Net.WebSockets.WebSocketMessageType]::Text,
                    $true,
                    [System.Threading.CancellationToken]::None
                ).Wait()
                
                Write-DashboardLog "Ping sent" -Level DEBUG
            }
            catch {
                Write-DashboardLog "Failed to send ping: $_" -Level ERROR
                $script:isWebSocketConnected = $false
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
                $statusLabel.Text = "WebSocket: Disconnected"
                
                # Attempt reconnection
                Connect-WebSocket
            }
        }
    })
    $script:pingTimer.Start()
}

# Add helper function for Pong responses
function Send-PongMessage {
    if (-not $script:webSocketClient -or $script:webSocketClient.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
        return
    }

    try {
        $pongMessage = @{
            Type = "Pong"
            Timestamp = Get-Date -Format "o"
        } | ConvertTo-Json

        $buffer = [System.Text.Encoding]::UTF8.GetBytes($pongMessage)
        $segment = [ArraySegment[byte]]::new($buffer)
        
        $script:webSocketClient.SendAsync(
            $segment,
            [System.Net.WebSockets.WebSocketMessageType]::Text,
            $true,
            [System.Threading.CancellationToken]::None
        ).Wait(1000)
    }
    catch {
        Write-DashboardLog "Failed to send pong: $_" -Level ERROR
    }
}

# Function to update the server list
function Update-ServerList {
    $listView.Items.Clear()
    
    # Get the servers directory from registry
    $serversPath = Join-Path $serverManagerDir "servers"
    
    if (Test-Path $serversPath) {
        $serverConfigs = Get-ChildItem -Path $serversPath -Filter "*.json"
        foreach ($configFile in $serverConfigs) {
            try {
                $serverConfig = Get-Content $configFile.FullName -Raw | ConvertFrom-Json
                
                $item = New-Object System.Windows.Forms.ListViewItem($serverConfig.Name)
                
                # Check if server is running
                $status = "Offline"
                $cpuUsage = "N/A"
                $memoryUsage = "N/A"
                $uptime = "N/A"
                
                # Get process if running
                if ($serverConfig.ProcessId) {
                    $process = Get-Process -Id $serverConfig.ProcessId -ErrorAction SilentlyContinue
                    if ($process) {
                        $status = "Running"
                        $cpuUsage = "Checking..."
                        $memoryUsage = [Math]::Round($process.WorkingSet64 / 1MB, 2) + " MB"
                        $uptime = "Checking..."
                    }
                }
                
                $item.SubItems.Add($status)
                $item.SubItems.Add($cpuUsage)
                $item.SubItems.Add($memoryUsage)
                $item.SubItems.Add($uptime)
                
                $listView.Items.Add($item)
            }
            catch {
                Write-DashboardLog "Failed to process server config $($configFile.Name): $_" -Level ERROR
            }
        }
    }
    
    # Broadcast update if WebSocket is connected
    if ($script:isWebSocketConnected -and $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            $serverData = $listView.Items | ForEach-Object {
                @{
                    Name = $_.Text
                    Status = $_.SubItems[1].Text
                    CPU = $_.SubItems[2].Text
                    Memory = $_.SubItems[3].Text
                    Uptime = $_.SubItems[4].Text
                }
            }
            
            $updateMessage = @{
                Type = "ServerListUpdate"
                Servers = $serverData
                Timestamp = Get-Date -Format "o"
            } | ConvertTo-Json
            
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($updateMessage)
            $segment = [ArraySegment[byte]]::new($buffer)
            
            $script:webSocketClient.SendAsync(
                $segment,
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait(1000)
        } catch {
            Write-DashboardLog "Failed to send server list update: $_" -Level ERROR
        }
    }
    
    $script:lastServerListUpdate = Get-Date
}

# Add the Import Server function
function Import-ExistingServer {
    $importForm = New-Object System.Windows.Forms.Form
    $importForm.Text = "Import Existing Server"
    $importForm.Size = New-Object System.Drawing.Size(450,250)
    $importForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($nameLabel)

    $nameBox = New-Object System.Windows.Forms.TextBox
    $nameBox.Location = New-Object System.Drawing.Point(120,20)
    $nameBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($nameBox)

    $pathLabel = New-Object System.Windows.Forms.Label
    $pathLabel.Text = "Server Path:"
    $pathLabel.Location = New-Object System.Drawing.Point(10,50)
    $pathLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($pathLabel)

    $pathBox = New-Object System.Windows.Forms.TextBox
    $pathBox.Location = New-Object System.Drawing.Point(120,50)
    $pathBox.Size = New-Object System.Drawing.Size(250,20)
    $importForm.Controls.Add($pathBox)

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse"
    $browseButton.Location = New-Object System.Drawing.Point(380,48)
    $browseButton.Size = New-Object System.Drawing.Size(40,24)
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
    $appIdBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($appIdBox)

    $execPathLabel = New-Object System.Windows.Forms.Label
    $execPathLabel.Text = "Executable Path:"
    $execPathLabel.Location = New-Object System.Drawing.Point(10,110)
    $execPathLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($execPathLabel)

    $execPathBox = New-Object System.Windows.Forms.TextBox
    $execPathBox.Location = New-Object System.Drawing.Point(120,110)
    $execPathBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($execPathBox)

    $importButton = New-Object System.Windows.Forms.Button
    $importButton.Text = "Import"
    $importButton.Location = New-Object System.Drawing.Point(180,170)
    $importButton.Size = New-Object System.Drawing.Size(90,30)
    $importButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text) -or 
            [string]::IsNullOrWhiteSpace($pathBox.Text) -or 
            [string]::IsNullOrWhiteSpace($appIdBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("Server name, path and AppID are required fields.", "Error")
            return
        }

        # Validate if the path exists
        if (-not (Test-Path $pathBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("The specified server path does not exist.", "Error")
            return
        }

        try {
            # Create server configuration
            $serverConfig = @{
                Name = $nameBox.Text
                InstallDir = $pathBox.Text
                AppID = $appIdBox.Text
                ExecutablePath = $execPathBox.Text
                Created = Get-Date -Format "o"
                LastUpdate = Get-Date -Format "o"
                Imported = $true
            }

            # Save server configuration
            $configPath = Join-Path $serverManagerDir "servers"
            if (-not (Test-Path $configPath)) {
                New-Item -ItemType Directory -Path $configPath -Force | Out-Null
            }

            $configFile = Join-Path $configPath "$($nameBox.Text).json"
            if (Test-Path $configFile) {
                $result = [System.Windows.Forms.MessageBox]::Show(
                    "A server with this name already exists. Do you want to overwrite it?",
                    "Warning",
                    [System.Windows.Forms.MessageBoxButtons]::YesNo,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                if ($result -eq [System.Windows.Forms.DialogResult]::No) {
                    return
                }
            }

            $serverConfig | ConvertTo-Json | Set-Content $configFile -Force

            [System.Windows.Forms.MessageBox]::Show("Server imported successfully!", "Success")
            $importForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $importForm.Close()
            
            # Update server list
            Update-ServerList
        }
        catch {
            Write-DashboardLog "Failed to import server: $_" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to import server: $($_.Exception.Message)", "Error")
        }
    })
    $importForm.Controls.Add($importButton)

    $importForm.ShowDialog()
}

# Add the function to get GPU information
function Get-GPUInfo {
    try {
        $gpu = Get-WmiObject Win32_VideoController | Select-Object -First 1
        if ($gpu) {
            return "$($gpu.Name) - $('{0:N0}' -f ($gpu.AdapterRAM/1MB))MB"
        }
        return "GPU information unavailable"
    } catch {
        Write-DashboardLog "Failed to get GPU information: $_" -Level ERROR
        return "GPU information unavailable"
    }
}

# Function to get network usage
function Get-NetworkUsage {
    try {
        # Store previous values in script-level variables if they don't exist
        if (-not $script:previousNetworkStats) {
            $script:previousNetworkStats = @{}
            $script:previousNetworkTime = Get-Date
        }

        $adapter = Get-NetAdapter | Where-Object Status -eq "Up" | Select-Object -First 1
        if (-not $adapter) {
            return "No active network adapter found"
        }
        
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
        Write-DashboardLog "Failed to get network usage: $_" -Level ERROR
        return "Network statistics unavailable"
    }
}

# Function to update host information
function Update-HostInformation {
    try {
        # CPU Usage
        if ($script:cpuCounter) {
            $cpu = $script:cpuCounter.NextValue()
            $lblCPUUsage = $hostnamePanel.Controls["lblCPUUsage"]
            $lblCPUUsage.Text = "$([Math]::Round($cpu, 2))%"
        } else {
            # Fallback to Get-Counter if performance counter fails
            try {
                $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop).CounterSamples.CookedValue
                $lblCPUUsage = $hostnamePanel.Controls["lblCPUUsage"]
                $lblCPUUsage.Text = "$([Math]::Round($cpu, 2))%"
            } catch {
                $lblCPUUsage = $hostnamePanel.Controls["lblCPUUsage"]
                $lblCPUUsage.Text = "Not available"
            }
        }

        # Memory Usage
        try {
            $memory = Get-CimInstance Win32_OperatingSystem
            $memoryUsage = 100 - [Math]::Round(($memory.FreePhysicalMemory/$memory.TotalVisibleMemorySize)*100, 2)
            $lblMemoryUsage = $hostnamePanel.Controls["lblMemoryUsage"]
            $lblMemoryUsage.Text = "$memoryUsage% ($([Math]::Round($memory.TotalVisibleMemorySize/1MB, 2))GB Total)"
        } catch {
            $lblMemoryUsage = $hostnamePanel.Controls["lblMemoryUsage"]
            $lblMemoryUsage.Text = "Not available"
        }

        # Disk Usage
        try {
            $disk = Get-PSDrive C
            $diskUsagePercent = [Math]::Round(($disk.Used / ($disk.Used + $disk.Free)) * 100, 2)
            $diskFreeGB = [Math]::Round($disk.Free/1GB, 2)
            $lblDiskUsage = $hostnamePanel.Controls["lblDiskUsage"]
            $lblDiskUsage.Text = "$diskUsagePercent% ($diskFreeGB GB Free)"
        } catch {
            $lblDiskUsage = $hostnamePanel.Controls["lblDiskUsage"]
            $lblDiskUsage.Text = "Not available"
        }

        # GPU Info
        $lblGPUInfo = $hostnamePanel.Controls["lblGPUInfo"]
        $lblGPUInfo.Text = Get-GPUInfo

        # Network Usage
        $lblNetworkUsage = $hostnamePanel.Controls["lblNetworkUsage"]
        $lblNetworkUsage.Text = Get-NetworkUsage

        # System Uptime
        try {
            $uptime = (Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
            $lblSystemUptime = $hostnamePanel.Controls["lblSystemUptime"]
            $lblSystemUptime.Text = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
        } catch {
            $lblSystemUptime = $hostnamePanel.Controls["lblSystemUptime"]
            $lblSystemUptime.Text = "Not available"
        }

    } catch {
        Write-DashboardLog "Error updating host information: $($_.Exception.Message)" -Level ERROR
    }
}

# Function to sync all dashboards
function Sync-AllDashboards {
    Write-DashboardLog "Syncing all dashboards..." -Level DEBUG
    Update-ServerList
    Update-HostInformation
    
    if ($script:isWebSocketConnected -and $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            $updateData = @{
                Type = "ForcedSync"
                Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            } | ConvertTo-Json
            
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($updateData)
            $segment = [ArraySegment[byte]]::new($buffer)
            
            $script:webSocketClient.SendAsync(
                $segment,
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait(1000)
            
            Write-DashboardLog "Sync command sent successfully" -Level DEBUG
            
            # Show success message
            [System.Windows.Forms.MessageBox]::Show(
                "All dashboards synced successfully!",
                "Sync Complete",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            )
        } catch {
            Write-DashboardLog "Failed to send sync command: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show(
                "Failed to sync dashboards: $($_.Exception.Message)",
                "Sync Failed",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            )
        }
    } else {
        Write-DashboardLog "Cannot sync dashboards: WebSocket not connected" -Level WARN
        [System.Windows.Forms.MessageBox]::Show(
            "Cannot sync dashboards: WebSocket not connected. Local data has been refreshed.",
            "Sync Incomplete",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
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

# Set up refresh timer
$refreshTimer = New-Object System.Windows.Forms.Timer
$refreshTimer.Interval = 1000 # 1 second interval
$refreshTimer.Add_Tick({
    try {
        $currentTime = Get-Date
        
        # Update high-frequency items (CPU, Memory)
        if (($currentTime - $script:lastFullUpdate).TotalSeconds -ge 2) {
            # CPU update
            if ($script:cpuCounter) {
                $cpu = $script:cpuCounter.NextValue()
                $lblCPUUsage = $hostnamePanel.Controls["lblCPUUsage"]
                $lblCPUUsage.Text = "$([Math]::Round($cpu, 1))%"
            }
            
            # Memory update
            try {
                $memInfo = Get-CimInstance Win32_OperatingSystem -Property FreePhysicalMemory,TotalVisibleMemorySize
                $memoryUsage = 100 - [Math]::Round(($memInfo.FreePhysicalMemory/$memInfo.TotalVisibleMemorySize)*100, 2)
                $lblMemoryUsage = $hostnamePanel.Controls["lblMemoryUsage"]
                $lblMemoryUsage.Text = "$memoryUsage% ($([Math]::Round($memInfo.TotalVisibleMemorySize/1MB, 2))GB Total)"
            } catch {
                # Silently handle memory update errors
            }
            
            $script:lastFullUpdate = $currentTime
        }

        # Update low-frequency items every 5 seconds
        if (($currentTime - $script:lastServerListUpdate).TotalSeconds -ge 5) {
            # Update disk, network, GPU, uptime
            Update-HostInformation
            
            # Update server list
            Update-ServerList
            
            $script:lastServerListUpdate = $currentTime
        }
    }
    catch {
        Write-DashboardLog "Error updating dashboard: $($_.Exception.Message)" -Level ERROR
    }
})

# Form closing event handler
$form.Add_FormClosing({
    param($sender, $e)
    
    Write-DashboardLog "Dashboard closing initiated..." -Level DEBUG

    if ($e.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing) {
        $result = [System.Windows.Forms.MessageBox]::Show(
            "Are you sure you want to exit Server Manager Dashboard?",
            "Confirm Exit",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )

        if ($result -eq [System.Windows.Forms.DialogResult]::No) {
            $e.Cancel = $true
            return
        }
    }
    
    Write-DashboardLog "Cleaning up resources..." -Level DEBUG
    
    # Stop all timers
    if ($refreshTimer) {
        $refreshTimer.Stop()
        $refreshTimer.Dispose()
    }
    if ($script:pingTimer) {
        $script:pingTimer.Stop()
        $script:pingTimer.Dispose()
    }

    # Close WebSocket connection
    if ($script:webSocketClient -ne $null -and 
        $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            Write-DashboardLog "Closing WebSocket connection..." -Level DEBUG
            $closeTask = $script:webSocketClient.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "Dashboard closing",
                [System.Threading.CancellationToken]::None
            )
            $closeTask.Wait(2000)
        }
        catch {
            Write-DashboardLog "Error closing WebSocket: $($_.Exception.Message)" -Level ERROR
        }
        finally {
            $script:webSocketClient.Dispose()
        }
    }

    # Clean up performance counters
    if ($script:cpuCounter) {
        $script:cpuCounter.Dispose()
    }

    # Terminate any running jobs
    Get-Job | Where-Object { $_.State -eq "Running" } | Stop-Job
    Get-Job | Remove-Job
    
    Write-DashboardLog "Dashboard closed successfully" -Level INFO
})

# Show the form
[System.Windows.Forms.Application]::EnableVisualStyles()
$form.ShowDialog()