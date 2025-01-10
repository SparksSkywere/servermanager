function Get-ServerInstanceMetrics {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $pidFile = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "PIDS.txt"

    if (Test-Path $pidFile) {
        $pidEntry = Get-Content $pidFile | Where-Object { $_ -like "* - $ServerName" }
        if ($pidEntry) {
            $processId = [int]($pidEntry -split ' - ')[0]
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue

            if ($process) {
                return @{
                    Name = $ServerName
                    ProcessId = $processId
                    CPU = [math]::Round($process.CPU, 2)
                    Memory = [math]::Round($process.WorkingSet64 / 1MB, 2)
                    Threads = $process.Threads.Count
                    Uptime = (Get-Date) - $process.StartTime
                    Status = "Running"
                }
            }
        }
    }

    return @{
        Name = $ServerName
        Status = "Stopped"
        CPU = 0
        Memory = 0
        Threads = 0
        Uptime = [TimeSpan]::Zero
    }
}

function Test-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )

    $metrics = Get-ServerInstanceMetrics -ServerName $ServerName
    return $metrics.Status -eq "Running"
}

function New-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName,
        [Parameter(Mandatory = $true)]
        [string]$AppID,
        [Parameter(Mandatory = $false)]
        [string]$ServerPort,
        [Parameter(Mandatory = $false)]
        [string]$InstallPath
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $instancesDir = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "instances"
    
    # Create instances directory if it doesn't exist
    if (-not (Test-Path $instancesDir)) {
        New-Item -ItemType Directory -Path $instancesDir -Force | Out-Null
    }

    # Create instance metadata file
    $instanceConfig = @{
        Name = $ServerName
        AppID = $AppID
        Port = $ServerPort
        Status = "Stopped"
        InstallPath = $InstallPath  # This can be null if using default SteamCMD location
        Created = (Get-Date).ToString("o")
        LastStarted = $null
        LastStopped = $null
        UpdatedOn = $null
    }

    $configPath = Join-Path $instancesDir "$ServerName.json"
    $instanceConfig | ConvertTo-Json | Set-Content -Path $configPath

    Write-ServerLog -Message "Created new server instance metadata: $ServerName" -Level Info -ServerName $ServerName
    return $instanceConfig
}

function Get-ServerInstances {
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $instancesDir = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "instances"
    
    if (Test-Path $instancesDir) {
        Get-ChildItem -Path $instancesDir -Filter "*.json" | ForEach-Object {
            Get-Content $_.FullName | ConvertFrom-Json
        }
    }
}

function Remove-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $instancesDir = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "instances"
    $configPath = Join-Path $instancesDir "$ServerName.json"

    if (Test-Path $configPath) {
        Remove-Item -Path $configPath -Force
        Write-ServerLog -Message "Removed server instance metadata: $ServerName" -Level Info -ServerName $ServerName
        return $true
    }
    return $false
}

Export-ModuleMember -Function *
