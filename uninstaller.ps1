# Check for admin rights and self-elevate if needed
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

function Remove-DirectoryForcefully {
    param (
        [string]$Path
    )
    
    Write-Host "Attempting to remove directory: $Path" -ForegroundColor Yellow
    
    # Kill any processes that might be locking the directory
    Get-Process | Where-Object {
        try { $_.Path -like "*$Path*" } catch { $false }
    } | ForEach-Object {
        Write-Host "Stopping process: $($_.Name)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    
    # Take ownership and grant permissions
    $null = takeown /f "$Path" /r /d y 2>&1
    $null = icacls "$Path" /grant administrators:F /t 2>&1
    
    # Try removal methods
    try {
        if (Test-Path $Path) {
            # Method 1: Direct removal
            Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
        }
    } catch {
        try {
            # Method 2: CMD
            $null = cmd /c "rd /s /q `"$Path`"" 2>&1
        } catch {
            # Method 3: Robocopy
            $empty = New-Item -ItemType Directory -Path "$env:TEMP\empty" -Force
            $null = robocopy "$env:TEMP\empty" "$Path" /PURGE /NFL /NDL /NJH /NJS /NC /NS /NP
            Remove-Item -Path "$env:TEMP\empty" -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $Path -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# Get the installation path from registry
$regPath = "HKLM:\Software\SkywereIndustries\servermanager"
try {
    $steamCMDPath = (Get-ItemProperty -Path $regPath -ErrorAction Stop).SteamCMDPath
    if (-not $steamCMDPath) { throw "SteamCMDPath not found" }
} catch {
    Write-Host "Installation not found or registry key missing." -ForegroundColor Red
    exit 1
}

# Confirm uninstallation
Add-Type -AssemblyName PresentationFramework
$result = [System.Windows.MessageBox]::Show(
    "Do you want to uninstall Server Manager?`nSteamCMD directory: $steamCMDPath", 
    "Uninstall Confirmation", 
    "YesNo", 
    "Question"
)

if ($result -eq "No") {
    exit
}

# Additional confirmation for SteamCMD
$removeSteamCMD = [System.Windows.MessageBox]::Show(
    "Do you also want to remove SteamCMD and all game servers?", 
    "Remove SteamCMD", 
    "YesNo", 
    "Question"
) -eq "Yes"

Write-Host "Starting uninstallation..." -ForegroundColor Cyan

# Stop related processes
Write-Host "Stopping related processes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -like "*steam*" -or $_.ProcessName -like "*servermanager*" } | 
    Stop-Process -Force -ErrorAction SilentlyContinue

# Remove services
Write-Host "Removing services..." -ForegroundColor Yellow
if (Get-Service "ServerManagerService" -ErrorAction SilentlyContinue) {
    Stop-Service "ServerManagerService" -Force
    $null = sc.exe delete "ServerManagerService"
}

# Remove firewall rules
Write-Host "Removing firewall rules..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName "ServerManager_*" -ErrorAction SilentlyContinue | 
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

# Remove scheduled tasks
Write-Host "Removing scheduled tasks..." -ForegroundColor Yellow
Get-ScheduledTask -TaskPath "\ServerManager\*" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue

# Remove program data
$programDataPaths = @(
    "C:\ProgramData\ServerManager",
    "$env:LOCALAPPDATA\ServerManager",
    "$env:APPDATA\ServerManager"
)

foreach ($path in $programDataPaths) {
    Remove-DirectoryForcefully -Path $path
}

# Remove registry keys
Write-Host "Removing registry keys..." -ForegroundColor Yellow
Remove-Item -Path "HKLM:\Software\SkywereIndustries\servermanager" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "HKLM:\Software\SkywereIndustries" -Force -ErrorAction SilentlyContinue

# Remove installation directory
if ($removeSteamCMD) {
    Write-Host "Removing SteamCMD directory..." -ForegroundColor Yellow
    Remove-DirectoryForcefully -Path $steamCMDPath
} else {
    Write-Host "Removing Server Manager components..." -ForegroundColor Yellow
    Remove-DirectoryForcefully -Path (Join-Path $steamCMDPath "ServerManager")
}

Write-Host "`nUninstallation completed!" -ForegroundColor Green
if (-not $removeSteamCMD) {
    Write-Host "SteamCMD remains at: $steamCMDPath" -ForegroundColor Yellow
}

Read-Host "Press Enter to exit"