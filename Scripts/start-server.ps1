# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "Modules\ServerManager\ServerManager.psm1"
Import-Module $serverManagerPath -Force

function Start-GameServer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )

    # Get registry path
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $configPath = Join-Path $serverManagerDir "servers\$ServerName.json"

    if (Test-Path $configPath) {
        $config = Get-Content $configPath | ConvertFrom-Json
        
        # Start the server process
        try {
            $process = Start-Process -FilePath "$($config.InstallDir)\$($config.ExecutablePath)" `
                                   -ArgumentList $config.StartupArgs `
                                   -WorkingDirectory $config.InstallDir `
                                   -PassThru

            # Log the PID
            $pidFile = Join-Path $serverManagerDir "PIDS.txt"
            Add-Content -Path $pidFile -Value "$($process.Id) - $ServerName"
            
            Write-Host "Server started successfully: $ServerName (PID: $($process.Id))"
        }
        catch {
            Write-Host "Failed to start server $ServerName : $_"
        }
    }
    else {
        Write-Host "Server configuration not found: $ServerName"
    }
}

# Execute the function if ServerName is provided
if ($args.Count -gt 0) {
    Start-GameServer -ServerName $args[0]
}
else {
    Write-Host "Please provide a server name."
}
