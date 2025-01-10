# Set title and clear screen
$host.ui.RawUI.WindowTitle = "Server Manager Launcher"
Clear-Host

# Store process IDs for cleanup
$Global:ProcessTracker = @{
    WebServer = $null
    TrayIcon = $null
}

# Function to cleanup processes
function Stop-AllComponents {
    Write-Host "Stopping all components..." -ForegroundColor Cyan
    
    $processes = @($Global:ProcessTracker.WebServer, $Global:ProcessTracker.TrayIcon)
    foreach ($pid in $processes) {
        if ($pid) {
            try {
                $process = Get-Process -Id $pid -ErrorAction Stop
                if (-not $process.HasExited) {
                    Stop-Process -Id $pid -Force
                    Wait-Process -Id $pid -Timeout 5 -ErrorAction SilentlyContinue
                }
            } catch { }
        }
    }
    
    # Ensure ports are released
    try {
        netsh http delete urlacl url=http://localhost:8080/ | Out-Null
    } catch { }
    
    # Kill any remaining processes using port 8080
    Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
        ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
}

# Register cleanup on script exit
trap {
    Stop-AllComponents
    exit
}

# Check for admin privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Get script directory and parent directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

# Get registry paths
try {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $steamCmdDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).SteamCmdPath
    
    # Validate server directory
    if ([string]::IsNullOrWhiteSpace($serverDir)) {
        throw "Server directory path is empty in registry"
    }
    
    # Clean up path (remove any trailing slashes and quotes)
    $serverDir = $serverDir.Trim('"', ' ', '\')
    
    Write-Host "Server Directory: $serverDir" -ForegroundColor Cyan
    
    if (-not (Test-Path $serverDir)) {
        throw "Server directory not found: $serverDir"
    }

    # Validate required subdirectories
    $requiredPaths = @(
        (Join-Path $rootDir "Modules\ServerManager"),
        (Join-Path $scriptDir "webserver.ps1")
    )

    foreach ($path in $requiredPaths) {
        if (-not (Test-Path $path)) {
            throw "Required path not found: $path"
        }
    }

} catch {
    Write-Host "Error accessing Server Manager installation: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Registry Path: $registryPath" -ForegroundColor Yellow
    Write-Host "Server Directory: $serverDir" -ForegroundColor Yellow
    Write-Host "Please ensure Server Manager is properly installed by running install.ps1"
    Read-Host "Press Enter to exit"
    exit 1
}

# Create required directories
@("$rootDir\logs", "$rootDir\instances") | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}

# Import module and start web server
try {
    # Simplified HTTP listener setup
    Write-Host "Setting up HTTP listener..." -ForegroundColor Cyan
    
    # Remove existing URL reservation
    $null = netsh http delete urlacl url=http://localhost:8080/ 2>$null
    
    # Add new URL reservation
    $result = netsh http add urlacl url=http://localhost:8080/ user=Everyone
    Write-Host "URL reservation result: $result" -ForegroundColor Yellow
    
    # Verify URL reservation
    Write-Host "Current URL reservations:" -ForegroundColor Cyan
    netsh http show urlacl | Select-String "8080"
    
    # Check port availability
    $portCheck = Test-NetConnection -ComputerName localhost -Port 8080 -WarningAction SilentlyContinue
    if ($portCheck.TcpTestSucceeded) {
        Write-Host "Warning: Port 8080 is already in use" -ForegroundColor Yellow
        Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
            ForEach-Object {
                $process = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                Write-Host "Process using port: $($process.ProcessName) (PID: $($process.Id))" -ForegroundColor Yellow
            }
    }

    # Continue with module import
    $modulePath = Join-Path -Path $serverDir -ChildPath "Modules\ServerManager"
    Write-Host "Looking for module at: $modulePath" -ForegroundColor Cyan
    
    if (-not (Test-Path $modulePath)) {
        throw "Module not found at: $modulePath"
    }
    
    Import-Module $modulePath -Force
    
    # Create firewall rule for the web server
    New-ServerNetwork -ServerName "WebInterface" -Port 8080 | Out-Null
    
    # Start web server in a new PowerShell process
    $webserverPath = Join-Path -Path $PSScriptRoot -ChildPath "webserver.ps1"
    $trayIconPath = Join-Path -Path $PSScriptRoot -ChildPath "trayicon.ps1"

    if (-not (Test-Path $webserverPath)) {
        throw "WebServer script not found at: $webserverPath"
    }

    if (-not (Test-Path $trayIconPath)) {
        throw "TrayIcon script not found at: $trayIconPath"
    }

    $webServerProcess = Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$webserverPath`"" -PassThru -WindowStyle Hidden
    $Global:ProcessTracker.WebServer = $webServerProcess.Id
    
    Write-Host "Web server started with PID: $($webServerProcess.Id)" -ForegroundColor Green
    
    # Wait for web server to be ready
    $maxAttempts = 10
    $attempts = 0
    $serverReady = $false
    
    while (-not $serverReady -and $attempts -lt $maxAttempts) {
        try {
            $test = New-Object Net.Sockets.TcpClient('localhost', 8080)
            $test.Close()
            $serverReady = $true
        } catch {
            Start-Sleep -Seconds 1
            $attempts++
        }
    }
    
    if (-not $serverReady) {
        throw "Web server failed to start after $maxAttempts attempts"
    }
    
    # Start tray icon in a new PowerShell process
    $trayIconStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $trayIconStartInfo.FileName = "powershell.exe"
    $trayIconStartInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$trayIconPath`""
    $trayIconStartInfo.UseShellExecute = $false
    $trayIconStartInfo.RedirectStandardOutput = $true
    $trayIconStartInfo.RedirectStandardError = $true
    $trayProcess = [System.Diagnostics.Process]::Start($trayIconStartInfo)
    $Global:ProcessTracker.TrayIcon = $trayProcess.Id
    
    Write-Host "Tray icon started with PID: $($trayProcess.Id)" -ForegroundColor Green
    
    # Allow some time for the tray icon to initialize
    Start-Sleep -Seconds 2
    
    # Verify tray icon process is still running
    $trayProcess.Refresh()
    if ($trayProcess.HasExited) {
        throw "TrayIcon process failed to start properly. Exit code: $($trayProcess.ExitCode)"
    }
    
    # Display connection information
    Write-Host "`n=================================" -ForegroundColor Green
    Write-Host "Server Manager is ready!" -ForegroundColor Green
    Write-Host "=================================" -ForegroundColor Green
    Write-Host "`nLocal Connection URL: http://localhost:8080/`n"
    Write-Host "The server manager is now running in the background" -ForegroundColor Cyan
    Write-Host "Use the tray icon to manage the server" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop all components`n"
    
    # Monitor child processes and keep script running
    while ($true) {
        Start-Sleep -Seconds 2
        
        $webServerProcess = Get-Process -Id $Global:ProcessTracker.WebServer -ErrorAction SilentlyContinue
        $trayIconProcess = Get-Process -Id $Global:ProcessTracker.TrayIcon -ErrorAction SilentlyContinue
        
        if (-not $webServerProcess -or -not $trayIconProcess) {
            $errorMsg = ""
            if (-not $webServerProcess) {
                $errorMsg += "WebServer process (PID: $($Global:ProcessTracker.WebServer)) has stopped unexpectedly. "
            }
            if (-not $trayIconProcess) {
                $errorMsg += "TrayIcon process (PID: $($Global:ProcessTracker.TrayIcon)) has stopped unexpectedly."
            }
            throw $errorMsg.Trim()
        }
    }
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    Stop-AllComponents
    Read-Host "Press Enter to exit"
    exit 1
}
