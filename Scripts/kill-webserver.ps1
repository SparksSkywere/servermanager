# Verify admin privileges first
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this script as Administrator" -ForegroundColor Red
    exit 1
}

# Get paths from registry
try {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
    
    $paths = @{
        Root = $serverManagerDir
        Logs = Join-Path $serverManagerDir "logs"
        Config = Join-Path $serverManagerDir "config"
        Temp = Join-Path $serverManagerDir "temp"
        Scripts = Join-Path $serverManagerDir "Scripts"
    }

    $readyFiles = @{
        WebSocket = Join-Path $paths.Temp "websocket.ready"
        WebServer = Join-Path $paths.Temp "webserver.ready"
    }

    $pidFiles = @{
        Launcher = Join-Path $paths.Temp "launcher.pid"
        WebServer = Join-Path $paths.Temp "webserver.pid"
        TrayIcon = Join-Path $paths.Temp "trayicon.pid"
        WebSocket = Join-Path $paths.Temp "websocket.pid"
    }
} catch {
    Write-Host "Failed to get paths from registry: $_" -ForegroundColor Red
    exit 1
}

# Add URL cleanup function
function Remove-UrlReservation {
    param([string]$Port)
    
    $urls = @(
        "http://+:$Port/",
        "http://localhost:$Port/",
        "http://*:$Port/"
    )
    
    foreach ($url in $urls) {
        Write-Host "Removing URL reservation: $url" -ForegroundColor Cyan
        $null = netsh http delete urlacl url=$url 2>&1
    }
}

# Add firewall rule cleanup
function Remove-FirewallRules {
    param([string]$Port)
    
    $ruleNames = @(
        "ServerManager_http_$Port",
        "ServerManager_WebSocket_$Port"
    )
    
    foreach ($ruleName in $ruleNames) {
        Write-Host "Removing firewall rule: $ruleName" -ForegroundColor Cyan
        Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    }
}

# Enhanced port cleanup
function Clear-TCPPort {
    param(
        [Parameter(Mandatory=$true)]
        [int]$Port
    )
    
    Write-Host "Clearing port $Port..." -ForegroundColor Cyan
    
    # Get all processes using the port
    $connections = @()
    $connections += netstat -ano | Where-Object { $_ -match ":$Port\s+.*(?:LISTENING|ESTABLISHED)" }
    
    try {
        $connections += Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop
    } catch {
        Write-Host "Note: Get-NetTCPConnection unavailable" -ForegroundColor Yellow
    }
    
    # Extract process IDs
    $processIds = $connections | ForEach-Object {
        if ($_ -match ".*:$Port.*\s+(\d+)\s*$") {
            $matches[1]
        } elseif ($_.OwningProcess) {
            $_.OwningProcess
        }
    } | Select-Object -Unique
    
    foreach ($pid in $processIds) {
        if ($pid -in @(0, 4)) { continue } # Skip system processes
        
        try {
            $process = Get-Process -Id $pid -ErrorAction Stop
            Write-Host "Stopping process $($process.Name) (PID: $pid) using port $Port" -ForegroundColor Yellow
            Stop-Process -Id $pid -Force
        } catch {
            Write-Host "Could not stop process $pid : $_" -ForegroundColor Red
        }
    }
    
    # Reset networking components
    Write-Host "Resetting network configuration for port $Port..." -ForegroundColor Cyan
    Remove-UrlReservation -Port $Port
    Remove-FirewallRules -Port $Port
}

# Enhanced cleanup of ready files
Write-Host "Removing ready files..." -ForegroundColor Cyan
foreach ($file in $readyFiles.Values) {
    if (Test-Path $file) {
        Remove-Item -Path $file -Force
    }
}

# Stop all server manager processes
$processTypes = @("WebSocket", "WebServer", "TrayIcon", "Launcher")
foreach ($type in $processTypes) {
    $pidFile = $pidFiles[$type]
    if (Test-Path $pidFile) {
        try {
            $pidInfo = Get-Content $pidFile -Raw | ConvertFrom-Json
            $process = Get-Process -Id $pidInfo.ProcessId -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "Stopping $type process (PID: $($process.Id))" -ForegroundColor Cyan
                Stop-Process -Id $process.Id -Force
            }
            Remove-Item $pidFile -Force
        } catch {
            Write-Host "Error stopping $type process: $_" -ForegroundColor Red
        }
    }
}

# Clean up ports
@(8080, 8081) | ForEach-Object {
    Clear-TCPPort -Port $_
}

# Clean temp directory
Write-Host "Cleaning temporary files..." -ForegroundColor Cyan
Get-ChildItem -Path $paths.Temp -File | Remove-Item -Force

# Clear logs
Write-Host "Clearing log files..." -ForegroundColor Cyan
$logFiles = @("launcher.log", "webserver.log", "trayicon.log", "websocket.log")
foreach ($logFile in $logFiles) {
    $logPath = Join-Path $paths.Logs $logFile
    if (Test-Path $logPath) {
        try {
            Clear-Content -Path $logPath -Force
        } catch {
            Write-Host "Could not clear $logFile : $_" -ForegroundColor Red
        }
    }
}

# Final cleanup
[System.GC]::Collect()
[System.GC]::WaitForPendingFinalizers()

Write-Host "Cleanup complete" -ForegroundColor Green
Start-Sleep -Seconds 1