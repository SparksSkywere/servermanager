function Write-ServerLog {
    param (
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [ValidateSet('Info', 'Warning', 'Error')]
        [string]$Level = 'Info',
        [string]$ServerName = ''
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $logDir = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "logs"
    
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "$timestamp [$Level] $ServerName - $Message"
    
    # Write to server-specific log if ServerName is provided
    if ($ServerName) {
        $serverLog = Join-Path $logDir "$ServerName.log"
        Add-Content -Path $serverLog -Value $logEntry
    }

    # Always write to main log
    $mainLog = Join-Path $logDir "servermanager.log"
    Add-Content -Path $mainLog -Value $logEntry

    # Output to console with color
    $color = switch ($Level) {
        'Info' { 'White' }
        'Warning' { 'Yellow' }
        'Error' { 'Red' }
    }
    Write-Host $logEntry -ForegroundColor $color
}

function Clear-OldLogs {
    param (
        [int]$DaysToKeep = 30
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $logDir = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "logs"

    if (Test-Path $logDir) {
        $cutoffDate = (Get-Date).AddDays(-$DaysToKeep)
        Get-ChildItem -Path $logDir -Filter "*.log" | 
            Where-Object { $_.LastWriteTime -lt $cutoffDate } |
            Remove-Item -Force
    }
}

Export-ModuleMember -Function *
