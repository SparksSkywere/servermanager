# Check for admin privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Stopping Server Manager..." -ForegroundColor Yellow

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

# Remove firewall rule
try {
    $firewallRule = Get-NetFirewallRule -DisplayName "WebInterface_TCP_8080" -ErrorAction SilentlyContinue
    if ($firewallRule) {
        Write-Host "Removing firewall rule..." -ForegroundColor Cyan
        Remove-NetFirewallRule -DisplayName "WebInterface_TCP_8080" -ErrorAction Stop
    }
} catch {
    Write-Host "Error removing firewall rule: $($_.Exception.Message)" -ForegroundColor Red
}

# Add netsh commands to clean up HTTP listener
Write-Host "Cleaning up HTTP listener..." -ForegroundColor Cyan
try {
    # Remove URL reservation
    $null = netsh http delete urlacl url=http://+:8080/
    $null = netsh http delete urlacl url=http://localhost:8080/
    
    # Delete SSL certificate bindings if they exist
    $null = netsh http delete sslcert ipport=0.0.0.0:8080
    $null = netsh http delete sslcert ipport=127.0.0.1:8080
} catch {
    Write-Host "Error cleaning up HTTP listener: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Enhanced HTTP listener cleanup
Write-Host "Performing thorough HTTP listener cleanup..." -ForegroundColor Cyan
try {
    # Force stop HTTP listener service
    Stop-Service -Name HTTP -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-Service -Name HTTP

    # Remove all possible URL reservations for port 8080
    $urls = @(
        "http://+:8080/",
        "http://localhost:8080/",
        "http://*:8080/",
        "http://0.0.0.0:8080/"
    )
    
    foreach ($url in $urls) {
        netsh http delete urlacl url=$url 2>$null
    }
    
    # Kill any process that might be holding port 8080
    $connections = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $process = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Killing process: $($process.ProcessName) (PID: $($process.Id))" -ForegroundColor Yellow
            Stop-Process -Id $process.Id -Force
        }
    }
    
    # Wait to ensure everything is cleaned up
    Start-Sleep -Seconds 3
} catch {
    Write-Host "Warning during cleanup: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Kill any process using port 8080
$processesUsingPort = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | 
    Select-Object -ExpandProperty OwningProcess | 
    ForEach-Object { Get-Process -Id $_ }

if ($processesUsingPort) {
    Write-Host "Found processes using port 8080. Stopping them..." -ForegroundColor Cyan
    $processesUsingPort | Stop-Process -Force
}

# Check if port 8080 is still in use
$portInUse = Test-NetConnection -ComputerName localhost -Port 8080 -WarningAction SilentlyContinue
if ($portInUse.TcpTestSucceeded) {
    Write-Host "Warning: Port 8080 is still in use by another process" -ForegroundColor Yellow
} else {
    Write-Host "Port 8080 is now free" -ForegroundColor Green
}

Write-Host "`nServer Manager has been stopped successfully" -ForegroundColor Green
Start-Sleep -Seconds 2
