using namespace System.Net
using namespace System.Net.Sockets

# Add module scope marker to ensure functions stay in scope
$script:ModuleLoaded = $true

# Add function to global scope explicitly
function Global:New-ServerNetwork {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [int]$Port = 8080,
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost"
    )
    
    try {
        # Test if port is already in use
        $inUse = Test-NetConnection -ComputerName localhost -Port $Port -ErrorAction SilentlyContinue -WarningAction SilentlyContinue
        if ($inUse.TcpTestSucceeded) {
            Write-Warning "Port $Port is already in use. Attempting to release..."
            Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | 
                ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        }

        # Configure URL ACL
        $null = Start-Process netsh -ArgumentList "http delete urlacl url=http://+:$Port/" -WindowStyle Hidden -Wait
        $null = Start-Process netsh -ArgumentList "http add urlacl url=http://+:$Port/ user=Everyone" -WindowStyle Hidden -Wait

        return @{
            Port = $Port
            HostName = $HostName
            Status = "Ready"
        }
    }
    catch {
        Write-Error "Failed to initialize network: $($_.Exception.Message)"
        throw
    }
}

function Global:Remove-ServerNetwork {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [int]$Port
    )
    
    try {
        Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | 
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        
        $null = Start-Process netsh -ArgumentList "http delete urlacl url=http://+:$Port/" -WindowStyle Hidden -Wait
        
        return $true
    }
    catch {
        Write-Error "Failed to cleanup network: $($_.Exception.Message)"
        return $false
    }
}

# Export functions with explicit scope
Export-ModuleMember -Function New-ServerNetwork, Remove-ServerNetwork -Variable ModuleLoaded
