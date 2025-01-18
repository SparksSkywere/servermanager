function New-ServerNetwork {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        [Parameter(Mandatory=$true)]
        [int]$Port
    )
    
    try {
        # First remove any existing rule
        Remove-NetFirewallRule -DisplayName "ServerManager_$ServerName" -ErrorAction SilentlyContinue
        
        # Create new rule
        $netRule = New-NetFirewallRule -DisplayName "ServerManager_$ServerName" `
                                     -Direction Inbound `
                                     -Action Allow `
                                     -Protocol TCP `
                                     -LocalPort $Port `
                                     -ErrorAction Stop
        
        Write-Host "Created firewall rule for $ServerName on port $Port"
        return $true
    } catch {
        Write-Error "Failed to create network rule: $($_.Exception.Message)"
        return $false
    }
}

function Remove-ServerNetwork {
    param (
        [string]$ServerName
    )
    
    try {
        Remove-NetFirewallRule -DisplayName "ServerManager_$ServerName" -ErrorAction SilentlyContinue
    } catch {
        Write-Error "Failed to remove network rule: $($_.Exception.Message)"
    }
}

Export-ModuleMember -Function New-ServerNetwork, Remove-ServerNetwork
