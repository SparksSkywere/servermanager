function New-ServerOperation {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName,
        [Parameter(Mandatory = $true)]
        [string]$Operation,
        [hashtable]$Parameters = @{}
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $operationsLog = Join-Path $serverManagerDir "operations.log"

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = @{
        Timestamp = $timestamp
        Server = $ServerName
        Operation = $Operation
        Parameters = $Parameters
        Status = "Pending"
    }

    # Log the operation
    $logEntry | ConvertTo-Json | Add-Content -Path $operationsLog

    # Return operation ID for tracking
    return [PSCustomObject]@{
        Id = [Guid]::NewGuid().ToString()
        Timestamp = $timestamp
        Server = $ServerName
        Operation = $Operation
        Status = "Pending"
    }
}

function Get-ServerOperation {
    param (
        [Parameter(Mandatory = $true)]
        [string]$OperationId
    )

    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $operationsLog = Join-Path $serverManagerDir "operations.log"

    # Read and parse operations log
    $operations = Get-Content -Path $operationsLog | ConvertFrom-Json
    return $operations | Where-Object { $_.Id -eq $OperationId }
}

# Export all functions
Export-ModuleMember -Function *
