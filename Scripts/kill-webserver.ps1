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

# Kill all related processes
$processNames = @(
    "*webserver*",
    "*trayicon*",
    "*launcher*"
)

# Modify the process termination section
foreach ($processName in $processNames) {
    $processes = Get-Process -Name "powershell*" | 
        Where-Object { $_.MainWindowTitle -like $processName -or $_.CommandLine -like "*$processName*" }
    
    foreach ($process in $processes) {
        Write-Host "Attempting to stop process: $($process.Id)" -ForegroundColor Cyan
        
        $maxAttempts = 10
        $attempt = 0
        $stopped = $false
        
        while ($attempt -lt $maxAttempts -and -not $stopped) {
            try {
                Stop-Process -Id $process.Id -Force
                
                # Wait up to 1 second for process to exit
                $stopWatch = [System.Diagnostics.Stopwatch]::StartNew()
                while ($stopWatch.ElapsedMilliseconds -lt 1000) {
                    if ((Get-Process -Id $process.Id -ErrorAction SilentlyContinue) -eq $null) {
                        $stopped = $true
                        break
                    }
                    Start-Sleep -Milliseconds 100
                }
                $stopWatch.Stop()
            } catch {
                # Process already stopped
                $stopped = $true
            }
            
            if (-not $stopped) {
                $attempt++
                Write-Host "Attempt $attempt of $maxAttempts to stop process $($process.Id)..." -ForegroundColor Yellow
                Start-Sleep -Seconds 1
            }
        }
        
        # Force kill if still running
        if (-not $stopped) {
            Write-Host "Force terminating process $($process.Id) after $maxAttempts attempts..." -ForegroundColor Red
            $null = taskkill /F /PID $process.Id 2>$null
        }
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
$maxAttempts = 5
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

# Modify the port check section at the end
foreach ($port in $portsToCheck) {
    $maxAttempts = 5
    $attempt = 0
    $cleared = $false
    
    while ($attempt -lt $maxAttempts -and -not $cleared) {
        try {
            $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
            if ($connections) {
                foreach ($conn in $connections) {
                    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            } else {
                $cleared = $true
                break
            }
        } catch {
            $cleared = $true
            break
        }
        
        $attempt++
        if (-not $cleared) {
            Write-Host "Attempt $attempt of $maxAttempts to clear port $port..." -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }
    }
    
    # Force kill if still in use
    if (-not $cleared) {
        Write-Host "Force clearing port $port after $maxAttempts attempts..." -ForegroundColor Red
        $null = netstat -ano | Select-String ":$port" | ForEach-Object {
            if ($_ -match "\s+(\d+)$") {
                taskkill /F /PID $matches[1] 2>$null
            }
        }
    }
}

Write-Host "Performing final log cleanup..." -ForegroundColor Yellow

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

Write-Host "Server Manager stopped successfully" -ForegroundColor Green
Write-Host "Cleanup complete" -ForegroundColor Green
Start-Sleep -Seconds 2
Exit