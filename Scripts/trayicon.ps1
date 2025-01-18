param(
    [string]$LogPath
)

# Start logging
Start-Transcript -Path $LogPath -Force

# Ensure STA thread model
if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
    Write-Host "Current thread is not STA. Restarting in STA mode..."
    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-Sta",
        "-File", "`"$($MyInvocation.MyCommand.Path)`"",
        "-LogPath", "`"$LogPath`""
    )
    Start-Process powershell -ArgumentList $argList -WindowStyle Hidden
    Stop-Transcript
    exit 0
}

Write-Host "Running in STA mode, continuing with tray icon creation..."

# Add required assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Initialize variables in script scope
$script:trayIcon = $null
$script:contextMenu = $null
$script:appContext = $null
$script:exitRequested = $false

trap {
    Write-Error "Critical error in tray icon: $($_.Exception.Message)"
    if ($script:trayIcon) {
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose()
    }
    throw
}

# Create application context first
$script:appContext = New-Object System.Windows.Forms.ApplicationContext

try {
    # Create tray icon and context menu
    $script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
    $script:contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
    
    # Set up tray icon
    $script:trayIcon.Text = "Server Manager"
    
    # Load icon
    $iconPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "icons\servermanager.ico"
    if (Test-Path $iconPath) {
        Write-Host "Loading icon from: $iconPath"
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($iconPath)
    } else {
        Write-Host "Using default PowerShell icon"
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon((Get-Process -Id $PID).MainModule.FileName)
    }
    
    # Set up menu items
    $openItem = $script:contextMenu.Items.Add("Open Dashboard")
    $openItem.Add_Click({
        Start-Process "http://localhost:8080"
    })
    
    $script:contextMenu.Items.Add("-")
    
    $exitItem = $script:contextMenu.Items.Add("Exit")
    $exitItem.Add_Click({
        $script:trayIcon.Visible = $false
        Stop-Transcript
        [System.Windows.Forms.Application]::Exit()
    })
    
    # Configure tray icon
    $script:trayIcon.ContextMenuStrip = $script:contextMenu
    $script:trayIcon.Visible = $true
    
    # Show startup notification
    $script:trayIcon.ShowBalloonTip(
        2000,
        "Server Manager",
        "Server Manager is running. Click to open dashboard.",
        [System.Windows.Forms.ToolTipIcon]::Info
    )
    
    # Add double-click handler
    $script:trayIcon.Add_MouseDoubleClick({
        Start-Process "http://localhost:8080"
    })
    
    Write-Host "Tray icon initialized successfully"
    
    # Start message loop
    [System.Windows.Forms.Application]::Run()
}
catch {
    Write-Error "Error in tray icon: $($_.Exception.Message)"
    Write-Error $_.ScriptStackTrace
    if ($script:trayIcon) {
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose()
    }
    throw
}
finally {
    if ($script:trayIcon) {
        $script:trayIcon.Dispose()
    }
    Stop-Transcript
}

# Cleanup resources
if (-not $script:exitRequested) {
    if ($null -ne $script:contextMenu) {
        $script:contextMenu.Dispose()
    }
    if ($null -ne $script:trayIcon) {
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose()
    }
    if ($null -ne $script:appContext) {
        $script:appContext.Dispose()
    }
    # Cleanup event handlers
    Get-EventSubscriber | Unregister-Event
}
