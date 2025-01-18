# Check for admin privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Stopping Server Manager..." -ForegroundColor Yellow

# Kill the launcher process first
Get-Process -Name "powershell*" | 
    Where-Object { $_.MainWindowTitle -like "*launcher*" -or $_.CommandLine -like "*launcher.ps1*" } | 
    ForEach-Object {
        Write-Host "Stopping launcher process: $($_.Id)" -ForegroundColor Cyan
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

# Get root directory and log paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$logDir = Join-Path $rootDir "logs"

# Add function to safely stop transcripts
function Stop-TranscriptSafely {
    try {
        $transcribing = [System.Management.Automation.Host.PSHost].GetProperty(
            'IsTranscribing',
            [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Static
        )
        if ($transcribing) {
            Stop-Transcript -ErrorAction SilentlyContinue
        }
    } catch {
        # Ignore any errors
    }
}

# Stop any PowerShell transcripts first
Stop-TranscriptSafely

# Force close any open log files
$logFiles = @(
    "main.log",
    "webserver.log",
    "trayicon.log",
    "updates.log"
)

# More aggressive log file cleanup
foreach ($logFile in $logFiles) {
    $logPath = Join-Path $logDir $logFile
    if (Test-Path $logPath) {
        try {
            [System.GC]::Collect()
            [System.GC]::WaitForPendingFinalizers()
            
            # Stop any PowerShell transcripts
            Stop-TranscriptSafely
            
            # Force close file handles
            $handles = Get-Process | 
                Where-Object { $_.Modules.FileName -contains $logPath } | 
                ForEach-Object { $_.Handle }
            
            foreach ($handle in $handles) {
                $null = [System.Runtime.InteropServices.Marshal]::FreeHGlobal($handle)
            }
            
            Start-Sleep -Milliseconds 500
            
            # Delete and recreate file
            Remove-Item -Path $logPath -Force -ErrorAction Stop
            New-Item -Path $logPath -ItemType File -Force | Out-Null
        } catch {
            Write-Warning "Failed to cleanup log file $logFile : $_"
        }
    }
}

# Kill all related processes
$processNames = @(
    "*webserver*",
    "*trayicon*",
    "*launcher*"
)

foreach ($processName in $processNames) {
    Get-Process -Name "powershell*" | 
        Where-Object { $_.MainWindowTitle -like $processName -or $_.CommandLine -like "*$processName*" } | 
        ForEach-Object {
            Write-Host "Stopping process: $($_.Id)" -ForegroundColor Cyan
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
}

# Find and stop any running web server jobs
$webserverJobs = Get-Job | Where-Object { $_.Name -like "*webserver*" -or $_.Command -like "*webserver.ps1*" }
if ($webserverJobs) {
    Write-Host "Found running web server jobs. Stopping..." -ForegroundColor Cyan
    $webserverJobs | Stop-Job -PassThru | Remove-Job -Force
}

# Find and stop any PowerShell processes running webserver.ps1
$webserverProcesses = Get-Process -Name powershell* | Where-Object { $_.CommandLine -like "*webserver.ps1*" }
if ($webserverProcesses) {
    Write-Host "Found running web server processes. Stopping..." -ForegroundColor Cyan
    $webserverProcesses | Stop-Process -Force
}

# Remove firewall rule silently
Get-NetFirewallRule -DisplayName "WebInterface_TCP_8080" -ErrorAction SilentlyContinue | 
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

# Cleanup HTTP listener quietly
$urls = @(
    "http://+:8080/",
    "http://localhost:8080/",
    "http://*:8080/",
    "http://0.0.0.0:8080/"
)

foreach ($url in $urls) {
    $null = netsh http delete urlacl url=$url 2>$null
}

$null = netsh http delete sslcert ipport=0.0.0.0:8080 2>$null
$null = netsh http delete sslcert ipport=127.0.0.1:8080 2>$null

# Restart HTTP service quietly
$null = Stop-Service -Name HTTP -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$null = Start-Service -Name HTTP -ErrorAction SilentlyContinue

# Kill processes using port 8080 silently
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
    ForEach-Object { 
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue 
    }

# Additional cleanup: Remove any leftover PID files
Remove-Item -Path "$env:TEMP\servermanager_*.pid" -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1

# Final port check
$portInUse = Test-NetConnection -ComputerName localhost -Port 8080 -WarningAction SilentlyContinue
if (-not $portInUse.TcpTestSucceeded) {
    Write-Host "Server Manager stopped successfully" -ForegroundColor Green
} else {
    Write-Host "Warning: Port 8080 is still in use" -ForegroundColor Yellow
    
    # Force kill any remaining processes using port 8080
    Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
        ForEach-Object { 
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue 
        }
}

Write-Host "Cleanup complete" -ForegroundColor Green
Start-Sleep -Seconds 2
