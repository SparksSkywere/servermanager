# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "Modules\ServerManager\ServerManager.psm1"
Import-Module $serverManagerPath -Force

# Get registry path
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

# Configuration for servers to auto-update
$servers = Get-Content -Path (Join-Path $serverManagerDir "servers\*.json") | 
    ConvertFrom-Json |
    Where-Object { $_.AutoUpdate -eq $true }

foreach ($server in $servers) {
    Write-ServerLog -Message "Checking updates for $($server.Name)" -ServerName $server.Name
    
    # Check if update is available
    if (Test-AnyUpdatesAvailable -AppID $server.AppID -AppName $server.Name) {
        Write-ServerLog -Message "Update available for $($server.Name)" -ServerName $server.Name

        # Stop server if running
        if (Test-ServerInstance -ServerName $server.Name) {
            Stop-ServerInstance -ServerName $server.Name
        }

        # Update server
        Update-ServerInstance -ServerName $server.Name -AppID $server.AppID -InstallDir $server.InstallDir

        # Restart server if it was running
        Start-ServerInstance -ServerName $server.Name
    }
}

# Clean up old logs
Clear-OldLogs -DaysToKeep 30
