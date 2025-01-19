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

# Start logging with verbose output
Start-Transcript -Path $LogPath -Force
Write-Host "Starting tray icon script at $(Get-Date)"

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

# Initialize variables in script scope with proper checks
Write-Host "Initializing variables..."
try {
    # Add required assemblies first
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $script:trayIcon = $null
    $script:contextMenu = $null
    $script:appContext = $null
    $script:exitRequested = $false

    # Create application context first
    $script:appContext = New-Object System.Windows.Forms.ApplicationContext
    if ($null -eq $script:appContext) {
        throw "Failed to create ApplicationContext"
    }

    # Create tray icon and verify
    $script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
    if ($null -eq $script:trayIcon) {
        throw "Failed to create NotifyIcon"
    }

    # Create context menu and verify
    $script:contextMenu = New-Object System.Windows.Forms.ContextMenuStrip
    if ($null -eq $script:contextMenu) {
        throw "Failed to create ContextMenuStrip"
    }

    Write-Host "Components initialized successfully"
}
catch {
    Write-Host "Failed to initialize components: $($_.Exception.Message)" -ForegroundColor Red
    if ($script:trayIcon) { $script:trayIcon.Dispose() }
    if ($script:contextMenu) { $script:contextMenu.Dispose() }
    if ($script:appContext) { $script:appContext.Dispose() }
    Stop-Transcript
    throw
}

trap {
    Write-Error "Critical error in tray icon: $($_.Exception.Message)"
    if ($script:trayIcon) {
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose()
    }
    throw
}

# Add registry access function
function Get-ServerManagerRegistry {
    $registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
    if (Test-Path $registryPath) {
        try {
            $properties = Get-ItemProperty -Path $registryPath
            return $properties
        }
        catch {
            Write-Host "Failed to read registry: $($_.Exception.Message)" -ForegroundColor Red
            return $null
        }
    }
    return $null
}

# Modified try block for the main logic
try {
    Write-Host "Creating tray icon components..."
    
    # Set up tray icon
    $script:trayIcon.Text = "Server Manager"
    
    # Load icon with verification using registry path
    $regInfo = Get-ServerManagerRegistry
    if ($null -eq $regInfo) {
        throw "Failed to read Server Manager registry settings"
    }

    $serverManagerDir = $regInfo.Servermanagerdir
    $iconPath = Join-Path $serverManagerDir "icons\servermanager.ico"
    Write-Host "Attempting to load icon from: $iconPath"
    
    $icon = if (Test-Path $iconPath) {
        try {
            [System.Drawing.Icon]::ExtractAssociatedIcon($iconPath)
        }
        catch {
            Write-Host "Failed to load custom icon, using default"
            [System.Drawing.Icon]::ExtractAssociatedIcon((Get-Process -Id $PID).MainModule.FileName)
        }
    }
    else {
        Write-Host "Icon not found at $iconPath, using default"
        [System.Drawing.Icon]::ExtractAssociatedIcon((Get-Process -Id $PID).MainModule.FileName)
    }
    
    if ($null -eq $icon) {
        throw "Failed to load any icon"
    }
    
    $script:trayIcon.Icon = $icon
    
    # Set up menu items with null checks
    if ($null -ne $script:contextMenu) {
        $openItem = $script:contextMenu.Items.Add("Open Web Dashboard")
        if ($null -ne $openItem) {
            $openItem.Add_Click({ 
                try {
                    Start-Process "http://localhost:8080"
                } catch {
                    Write-Host "Error opening web dashboard: $($_.Exception.Message)" -ForegroundColor Red
                }
            })
        }
        
        $openPSFormItem = $script:contextMenu.Items.Add("Open Admin Dashboard")
        if ($null -ne $openPSFormItem) {
            $openPSFormItem.Add_Click({
                $dashboardPath = Join-Path (Split-Path -Parent $PSScriptRoot) "Scripts\dashboard.ps1"
                if (Test-Path $dashboardPath) {
                    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$dashboardPath`"" -WindowStyle Normal
                } else {
                    [System.Windows.Forms.MessageBox]::Show("Dashboard script not found at: $dashboardPath", "Error", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
                }
            })
        }
        
        $script:contextMenu.Items.Add("-")
        
        $exitItem = $script:contextMenu.Items.Add("Close Server Manager")
        if ($null -ne $exitItem) {
            $exitItem.Add_Click({
                Write-Host "Closing Server Manager..."
                $script:trayIcon.Visible = $false
                $script:exitRequested = $true
                $processPath = Join-Path (Split-Path -Parent $PSScriptRoot) "Stop-ServerManager.cmd"
                Start-Process -FilePath $processPath -WindowStyle Hidden
                [System.Windows.Forms.Application]::Exit()
            })
        }
    }

    # Configure tray icon with null checks
    if ($null -ne $script:trayIcon -and $null -ne $script:contextMenu) {
        $script:trayIcon.ContextMenuStrip = $script:contextMenu
        $script:trayIcon.Visible = $true
        
        # Add double-click handler
        $script:trayIcon.Add_MouseDoubleClick({
            Start-Process "http://localhost:8080"
        })
        
        Write-Host "Starting application message loop..."
        [System.Windows.Forms.Application]::Run($script:appContext)
    }
    else {
        throw "Tray icon or context menu is null"
    }
}
catch {
    Write-Host "Critical error in tray icon setup: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Stack trace: $($_.ScriptStackTrace)" -ForegroundColor Red
    
    # Cleanup on error
    if ($null -ne $script:trayIcon) { 
        $script:trayIcon.Visible = $false
        $script:trayIcon.Dispose() 
    }
    if ($null -ne $script:contextMenu) { $script:contextMenu.Dispose() }
    if ($null -ne $script:appContext) { $script:appContext.Dispose() }
    
    Stop-Transcript
    throw
}
finally {
    if ($script:trayIcon) {
        $script:trayIcon.Dispose()
    }
    # Properly stop transcript if running
    if ([System.Management.Automation.Host.PSHost].GetProperty('IsTranscribing', [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Static)) {
        Stop-Transcript -ErrorAction SilentlyContinue
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
