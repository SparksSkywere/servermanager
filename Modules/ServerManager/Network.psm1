function New-ServerNetwork {
    param (
        [string]$ServerName,
        [int]$Port
    )
    
    try {
        $netRule = New-NetFirewallRule -DisplayName "ServerManager_$ServerName" `
                                     -Direction Inbound `
                                     -Action Allow `
                                     -Protocol TCP `
                                     -LocalPort $Port `
                                     -ErrorAction Stop
        return $netRule
    } catch {
        Write-Error "Failed to create network rule: $($_.Exception.Message)"
        return $null
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
