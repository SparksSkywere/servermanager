# Check for admin rights and self-elevate if needed
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

# First stop the service for incase it is running in the background before uninstalling
$stopScript = Join-Path $PSScriptRoot "Modules\stop_servermanager.py"
if (Test-Path $stopScript) {
    Write-Host "Stopping Server Manager service..." -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -NoProfile -File $stopScript
    Start-Sleep -Seconds 2
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
try {
    # Try to use the service wrapper to properly uninstall the service
    $serviceWrapperPath = Join-Path $serverManagerDir "Modules\service_wrapper.py"
    if (Test-Path $serviceWrapperPath) {
        Write-Host "Using service wrapper to uninstall service..." -ForegroundColor Cyan
        $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($pythonPath) {
            & $pythonPath $serviceWrapperPath uninstall 2>&1 | Out-Null
        }
    }
    
    # Fallback - use sc.exe if service still exists
    if (Get-Service "ServerManagerService" -ErrorAction SilentlyContinue) {
        Write-Host "Stopping Server Manager service..." -ForegroundColor Yellow
        Stop-Service "ServerManagerService" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        
        Write-Host "Removing service registration..." -ForegroundColor Yellow
        $null = sc.exe delete "ServerManagerService"
    }
    
    Write-Host "Service removal completed" -ForegroundColor Green
} catch {
    Write-Host "Warning: Error during service removal: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Remove firewall rules
Write-Host "Removing firewall rules..." -ForegroundColor Yellow
try {
    $firewallRulesRemoved = 0
    $rulesToRemove = @(
        # New rule names with direction suffixes
        "ServerManager_WebInterface_In",
        "ServerManager_WebInterface_Out",
        "ServerManager_ClusterAPI_In",
        "ServerManager_ClusterAPI_Out",
        "ServerManager_GameServers_In",
        "ServerManager_GameServers_Out",
        "ServerManager_GameServers_UDP_In",
        "ServerManager_GameServers_UDP_Out",
        "ServerManager_SteamQuery_In",
        "ServerManager_SteamQuery_Out",
        # Legacy rule names for backward compatibility
        "ServerManager_WebInterface",
        "ServerManager_ClusterAPI", 
        "ServerManager_GameServers",
        "ServerManager_GameServers_UDP",
        "ServerManager_SteamQuery"
    )
    
    foreach ($ruleName in $rulesToRemove) {
        try {
            $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            if ($existingRule) {
                Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction Stop
                Write-Host "  ✓ Removed: $ruleName" -ForegroundColor Green
                $firewallRulesRemoved++
            }
        } catch {
            Write-Host "  ⚠ Could not remove: $ruleName" -ForegroundColor Yellow
        }
    }
    
    # Also remove any remaining rules with ServerManager_ prefix (cleanup)
    $remainingRules = Get-NetFirewallRule -DisplayName "ServerManager_*" -ErrorAction SilentlyContinue
    if ($remainingRules) {
        $remainingRules | Remove-NetFirewallRule -ErrorAction SilentlyContinue
        $firewallRulesRemoved += $remainingRules.Count
        Write-Host "  ✓ Removed $($remainingRules.Count) additional ServerManager firewall rules" -ForegroundColor Green
    }
    
    if ($firewallRulesRemoved -eq 0) {
        Write-Host "  No ServerManager firewall rules found to remove" -ForegroundColor Cyan
    } else {
        Write-Host "  Successfully removed $firewallRulesRemoved firewall rule(s)" -ForegroundColor Green
    }
} catch {
    Write-Host "Warning: Error during firewall rules removal: $($_.Exception.Message)" -ForegroundColor Yellow
}

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