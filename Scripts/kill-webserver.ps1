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

# Restart HTTP service with retry mechanism
$maxAttempts = 10
$attempt = 0
$stopped = $false

Write-Host "Stopping HTTP Service..." -ForegroundColor Yellow
Stop-Service -Name HTTP -Force -ErrorAction SilentlyContinue

while ($attempt -lt $maxAttempts) {
    $service = Get-Service -Name HTTP
    if ($service.Status -eq 'Stopped') {
        $stopped = $true
        break
    }
    $attempt++
    Write-Host "Attempt ${attempt} of ${maxAttempts}: Waiting for HTTP Service to stop..." -ForegroundColor Cyan
    Start-Sleep -Seconds 1
}

if (-not $stopped) {
    Write-Host "Force terminating HTTP Service after $maxAttempts attempts..." -ForegroundColor Red
    # Use more aggressive methods to stop the service
    $null = taskkill /F /FI "SERVICES eq HTTP" 2>$null
}

# Wait a moment before starting the service again
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

# Replace the final port check section with this more aggressive version
# Kill any processes using port 8080 or 8081
$portsToCheck = @(8080, 8081)
foreach ($port in $portsToCheck) {
    try {
        $processes = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | 
            Select-Object -ExpandProperty OwningProcess
        
        if ($processes) {
            Write-Host "Found processes using port $port. Forcefully terminating..." -ForegroundColor Yellow
            foreach ($processId in $processes) {
                try {
                    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    if ($process) {
                        Write-Host "Terminating process: $($process.Name) (PID: $processId)" -ForegroundColor Cyan
                        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                    }
                } catch {
                    # If normal termination fails, use taskkill
                    $null = taskkill /F /PID $processId 2>$null
                }
            }
            
            # Wait briefly for processes to terminate
            Start-Sleep -Seconds 1
            
            # Double-check if port is still in use
            $stillInUse = Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue
            if ($stillInUse.TcpTestSucceeded) {
                # Use netstat to find any remaining processes
                $netstatOutput = netstat -ano | Select-String ":$port"
                foreach ($line in $netstatOutput) {
                    if ($line -match "\s+(\d+)$") {
                        $processId = $matches[1]
                        $null = taskkill /F /PID $processId 2>$null
                    }
                }
            }
        }
    } catch {
        # Ignore any errors and continue
    }
}

Write-Host "Server Manager stopped successfully" -ForegroundColor Green
Write-Host "Cleanup complete" -ForegroundColor Green
Start-Sleep -Seconds 2
