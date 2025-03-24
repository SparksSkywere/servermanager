param(
    [string]$LogPath
)

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
$logFile = Join-Path $logDir "trayicon.log"

function Write-TrayLog {
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

# Force STA threading
if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$($MyInvocation.MyCommand.Path)`"" -WindowStyle Hidden
    exit
}

# Configure PowerShell window
$host.UI.RawUI.WindowTitle = "Server Manager Tray"
$host.UI.RawUI.WindowStyle = 'Hidden'

# Add logging setup
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "trayicon.log"

function Write-TrayLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [$Level] - $Message" | Add-Content -Path $logFile -ErrorAction Stop
    }
    catch {
        # Fallback to Windows Event Log if file logging fails
        try {
            Write-EventLog -LogName Application -Source "ServerManager" -EventId 1001 -EntryType Error -Message $Message
        }
        catch { }
    }
}

Write-TrayLog "Starting tray icon initialization..." -Level DEBUG

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
    $script:trayIcon.Text = "Server Manager"
    
    # Get icon from registry path
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $iconPath = Join-Path $serverManagerDir "icons\servermanager.ico"
    
    if (Test-Path $iconPath) {
        Write-TrayLog "Loading icon from: $iconPath" -Level DEBUG
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($iconPath)
    } else {
        Write-TrayLog "Using default PowerShell icon" -Level DEBUG
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon([System.Windows.Forms.Application]::ExecutablePath)
    }

    $contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

    $openDashboardMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $openDashboardMenuItem.Text = "Open Web Dashboard"
    $openDashboardMenuItem.Add_Click({
        try {
            Start-Process "http://localhost:8080"
            Write-TrayLog "Web dashboard opened" -Level DEBUG
        }
        catch {
            Write-TrayLog "Failed to open web dashboard: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard. Please ensure the web server is running.", "Error")
        }
    })

    $openPSFormItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $openPSFormItem.Text = "Open Powershell Dashboard"
    $openPSFormItem.Add_Click({
        try {
            $dashboardPath = Join-Path $serverManagerDir "Scripts\dashboard.ps1"
            if (Test-Path $dashboardPath) {
                # Create a launcher script that will ensure proper STA threading
                $launcherPath = Join-Path $env:TEMP "LaunchDashboard.ps1"
                @"
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms
Set-StrictMode -Off
`$scriptPath = '$dashboardPath'
& `$scriptPath
"@ | Out-File -FilePath $launcherPath -Encoding utf8
                
                # Launch with appropriate parameters for GUI
                Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Normal -File `"$launcherPath`"" -WindowStyle Normal
                Write-TrayLog "Dashboard launched via launcher script" -Level DEBUG
            } else {
                throw "Dashboard script not found: $dashboardPath"
            }
        }
        catch {
            Write-TrayLog "Failed to open dashboard: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard: $($_.Exception.Message)", "Error")
        }
    })

    $exitMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $exitMenuItem.Text = "Exit"
    $exitMenuItem.Add_Click({
        try {
            Write-TrayLog "Starting exit process..." -Level DEBUG
            
            # Show console window during cleanup
            $consolePtr = [Console.Window]::GetConsoleWindow()
            [void][Console.Window]::ShowWindow($consolePtr, 1)
            
            # Remove tray icon immediately
            $script:trayIcon.Visible = $false
            $script:trayIcon.Dispose()
            
            # Get script paths from registry
            $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
            $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
            $stopScript = Join-Path $serverManagerDir "Scripts\kill-webserver.ps1"

            if (Test-Path $stopScript) {
                Write-TrayLog "Running kill-webserver script..." -Level DEBUG
                # Start kill-webserver.ps1 as administrator without waiting
                Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$stopScript`"" -Verb RunAs -WindowStyle Normal
            }

            Write-TrayLog "Exit process complete" -Level DEBUG
            [System.Windows.Forms.Application]::Exit()

            # Force exit this script
            Stop-Process $pid -Force
        }
        catch {
            Write-TrayLog "Error during exit: $($_.Exception.Message)" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Error during shutdown: $($_.Exception.Message)", "Error")
            exit 1
        }
    })

    $contextMenu.Items.AddRange(@($openDashboardMenuItem, $openPSFormItem, $exitMenuItem))
    $script:trayIcon.ContextMenuStrip = $contextMenu
    $script:trayIcon.Visible = $true

    Write-TrayLog "Tray icon initialized successfully" -Level DEBUG

    # Create a dummy form to keep the application running
    $dummyForm = New-Object System.Windows.Forms.Form
    $dummyForm.WindowState = [System.Windows.Forms.FormWindowState]::Minimized
    $dummyForm.ShowInTaskbar = $false
    
    # Run the application
    [System.Windows.Forms.Application]::Run($dummyForm)
}
catch {
    Write-TrayLog "Critical error in tray icon: $($_.Exception.Message)" -Level ERROR
    Write-TrayLog $_.ScriptStackTrace -Level ERROR
    throw
}
finally {
    if ($script:trayIcon) {
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose()
    }
}
