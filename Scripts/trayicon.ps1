# Force STA thread model
if (-not [System.Threading.Thread]::CurrentThread.GetApartmentState() -eq 'STA') {
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`"" -WindowStyle Hidden
    exit
}

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

# Create tray icon
$script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
    $script:trayIcon.Text = "Server Manager"
    
    # Load icon with fallback
    $powershellPath = (Get-Process -Id $PID).MainModule.FileName
    $iconPaths = @(
        (Join-Path $PSScriptRoot "..\icons\servermanager.ico"),
        (Join-Path $PSScriptRoot "servermanager.ico"),
        $powershellPath
    )

    $iconLoaded = $false
    foreach ($path in $iconPaths) {
        try {
            if (Test-Path $path) {
                $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($path)
                $iconLoaded = $true
                break
            }
        } catch { continue }
    }

    if (-not $iconLoaded) {
        Write-Warning "Could not load any icons, using default PowerShell icon"
        $script:trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($powershellPath)
    }

    # Create context menu
    $script:contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

    # Open Website menu item
    $openWebsiteMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $openWebsiteMenuItem.Text = "Open Dashboard"
    $openWebsiteMenuItem.Add_Click({
        try {
            Start-Process "http://localhost:8080"
        } catch {
            [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard: $($_.Exception.Message)", "Error", 
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        }
    }.GetNewClosure())
    $script:contextMenu.Items.Add($openWebsiteMenuItem)

    # Add separator
    $script:contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

    # Exit menu item
    $exitMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
    $exitMenuItem.Text = "Exit"
    $exitMenuItem.Add_Click({
        $script:exitRequested = $true
        try {
            if ($null -ne $script:appContext) {
                $script:appContext.ExitThread()
            }
            if ($null -ne $script:trayIcon) {
                $script:trayIcon.Visible = $false
            }
            [System.Windows.Forms.Application]::Exit()
            # Give the application time to cleanup
            Start-Sleep -Milliseconds 500
            Stop-Process $PID -Force
        } catch {
            Write-Error "Failed to exit cleanly: $($_.Exception.Message)"
            Stop-Process $PID -Force
        }
    }.GetNewClosure())
    $script:contextMenu.Items.Add($exitMenuItem)

    # Set context menu and make tray icon visible
    $script:trayIcon.ContextMenuStrip = $script:contextMenu
    $script:trayIcon.Visible = $true

    # Add double-click handler
    $script:trayIcon.Add_MouseDoubleClick({
        if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
            try {
                Start-Process "http://localhost:8080"
            } catch {
                [System.Windows.Forms.MessageBox]::Show("Failed to open dashboard: $($_.Exception.Message)", "Error",
                    [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
            }
        }
    })

    # Show balloon tip on startup with error handling
    try {
        $script:trayIcon.ShowBalloonTip(
            5000,
            "Server Manager",
            "Server Manager is running in the background. Right-click the tray icon for options.",
            [System.Windows.Forms.ToolTipIcon]::Info
        )
    } catch {
        Write-Warning "Failed to show balloon tip: $($_.Exception.Message)"
    }

    # Register cleanup on application exit
    [System.Windows.Forms.Application]::ApplicationExit += {
        if ($script:trayIcon) {
            $script:trayIcon.Visible = $false
            $script:trayIcon.Dispose()
        }
        if ($script:contextMenu) {
            $script:contextMenu.Dispose()
        }
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
