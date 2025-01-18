# Add module scope marker to ensure functions stay in scope
$script:ModuleLoaded = $true

# Add function to global scope explicitly
function Global:New-ServerNetwork {
    [CmdletBinding()]
    [OutputType([bool])]
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
        $null = New-NetFirewallRule -DisplayName "ServerManager_$ServerName" `
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

function Global:Remove-ServerNetwork {
    [CmdletBinding()]
    [OutputType([bool])]
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    try {
        Remove-NetFirewallRule -DisplayName "ServerManager_$ServerName" -ErrorAction SilentlyContinue
        return $true
    } catch {
        Write-Error "Failed to remove network rule: $($_.Exception.Message)"
        return $false
    }
}

# Export functions with explicit scope
Export-ModuleMember -Function New-ServerNetwork, Remove-ServerNetwork -Variable ModuleLoaded
