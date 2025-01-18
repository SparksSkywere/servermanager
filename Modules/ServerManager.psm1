using namespace System.Management.Automation
using namespace System.Collections.Generic

# Initialize error handling
$ErrorActionPreference = 'Stop'

# Direct module imports
$requiredModules = @(
    "Network.psm1",
    "Authentication.psm1",
    "Logging.psm1",
    "Security.psm1",
    "ServerInstances.psm1",
    "ServerOperations.psm1",
    "WebSocketServer.psm1"
)

foreach ($module in $requiredModules) {
    $modulePath = Join-Path $PSScriptRoot $module
    if (Test-Path $modulePath) {
        Import-Module $modulePath -Force
    } else {
        Write-Warning "Required module not found: $module"
    }
}

# Server container class for managing individual server instances
class ServerContainer {
    [string]$Name
    [string]$AppId
    [string]$Status
    [double]$CpuUsage
    [double]$MemoryUsage
    [string]$Uptime
    [string]$InstallPath
    [hashtable]$Network
    [hashtable]$Resources
    [array]$Volumes
    
    ServerContainer([string]$name) {
        $this.Name = $name
        $this.Status = "Stopped"
        $this.Network = @{}
        $this.Resources = @{
            CpuLimit = 0
            MemoryLimit = 0
            DiskLimit = 0
        }
        $this.Volumes = @()
    }

    [void]Start() {
        try {
            # Get server config
            $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
            $configPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "servers\$($this.Name).json"
            $config = Get-Content $configPath | ConvertFrom-Json

            # Start server process
            $process = Start-Process -FilePath (Join-Path $config.InstallDir $config.ExecutablePath) `
                -ArgumentList $config.StartupArgs `
                -WorkingDirectory $config.InstallDir `
                -PassThru

            # Update status and store PID
            $this.Status = "Running"
            $pidPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "PIDS.txt"
            "$($process.Id) - $($this.Name)" | Add-Content -Path $pidPath
        }
        catch {
            Write-Error "Failed to start server: $_"
            throw
        }
    }

    [void]Stop() {
        try {
            # Get PID from PIDS.txt
            $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
            $pidPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "PIDS.txt"
            $pidEntry = Get-Content $pidPath | Where-Object { $_ -like "* - $($this.Name)" }
            
            if ($pidEntry) {
                $processId = [int]($pidEntry -split ' - ')[0]
                Stop-Process -Id $processId -Force
                
                # Update PIDS.txt
                $pids = Get-Content $pidPath | Where-Object { $_ -ne $pidEntry }
                Set-Content -Path $pidPath -Value $pids

                $this.Status = "Stopped"
            }
        }
        catch {
            Write-Error "Failed to stop server: $_"
            throw
        }
    }

    [void]Restart() {
        $this.Stop()
        Start-Sleep -Seconds 5  # Wait for cleanup
        $this.Start()
    }

    [hashtable]GetStats() {
        try {
            # Get PID from PIDS.txt
            $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
            $pidPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "PIDS.txt"
            $pidEntry = Get-Content $pidPath | Where-Object { $_ -like "* - $($this.Name)" }
            
            if ($pidEntry) {
                $processId = [int]($pidEntry -split ' - ')[0]
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                
                if ($process) {
                    return @{
                        CPU = $process.CPU
                        Memory = $process.WorkingSet64 / 1MB
                        Threads = $process.Threads.Count
                        Status = "Running"
                        StartTime = $process.StartTime
                    }
                }
            }
            
            return @{
                CPU = 0
                Memory = 0
                Threads = 0
                Status = "Stopped"
                StartTime = $null
            }
        }
        catch {
            Write-Error "Failed to get server stats: $_"
            return @{}
        }
    }
}

# Remote server connection management class
class ServerConnection {
    [string]$ServerName
    [string]$IPAddress
    [PSCredential]$Credential
    [bool]$Connected
    
    ServerConnection([string]$server, [PSCredential]$cred) {
        $this.ServerName = $server
        $this.Credential = $cred
        $this.Connected = $false
    }

    [bool]Connect() {
        try {
            $session = New-PSSession -ComputerName $this.ServerName -Credential $this.Credential
            if ($session) {
                $this.Connected = $true
                Remove-PSSession $session
                return $true
            }
        }
        catch {
            $this.Connected = $false
            return $false
        }
        return $false
    }
}

# Main server management class
class ServerManager {
    [List[ServerConnection]]$Servers
    [List[ServerContainer]]$Containers
    
    ServerManager() {
        $this.Servers = [List[ServerConnection]]::new()
        $this.Containers = [List[ServerContainer]]::new()
    }

    [void]AddServer([string]$serverName, [PSCredential]$credential) {
        $server = [ServerConnection]::new($serverName, $credential)
        $this.Servers.Add($server)
    }

    [void]AddContainer([string]$name) {
        $container = [ServerContainer]::new($name)
        $this.Containers.Add($container)
    }

    [hashtable]GetServerStats([string]$serverName) {
        $server = $this.Servers | Where-Object { $_.ServerName -eq $serverName }
        if ($server) {
            $session = New-PSSession -ComputerName $server.ServerName -Credential $server.Credential
            $stats = Invoke-Command -Session $session -ScriptBlock {
                @{
                    CPU = (Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
                    Memory = (Get-Counter '\Memory\% Committed Bytes In Use').CounterSamples.CookedValue
                    DiskSpace = Get-Volume | Select-Object DriveLetter, SizeRemaining, Size
                    Services = Get-Service | Where-Object { $_.Status -eq 'Running' } | Measure-Object | Select-Object -ExpandProperty Count
                    Uptime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
                }
            }
            Remove-PSSession $session
            return $stats
        }
        return $null
    }

    [hashtable]GetContainerStats([string]$containerName) {
        $container = $this.Containers | Where-Object { $_.Name -eq $containerName }
        if ($container) {
            return $container.GetStats()
        }
        return $null
    }
}

# Server management functions
# Script-level variables to store state
$script:Servers = @{}
$script:ServerInstances = @{}

function New-ServerInstance {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        [Parameter(Mandatory=$true)]
        [string]$AppID,
        [Parameter(Mandatory=$true)]
        [string]$InstallDir
    )
    
    try {
        if ([string]::IsNullOrWhiteSpace($ServerName)) {
            throw "ServerName cannot be empty"
        }
        if (-not $AppID -match '^\d+$') {
            throw "AppID must be numeric"
        }

        $script:ServerInstances[$ServerName] = @{
            Name = $ServerName
            AppID = $AppID
            InstallDir = $InstallDir
            Status = "Stopped"
            LastUpdate = Get-Date
            Process = $null
        }

        Write-Host "Server instance created: $ServerName"
        return $true
    }
    catch {
        Write-Error "Failed to create server instance: $($_.Exception.Message)"
        return $false
    }
}

function Start-ServerInstance {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    try {
        if (-not $script:ServerInstances.ContainsKey($ServerName)) {
            throw "Server instance not found: $ServerName"
        }

        $instance = $script:ServerInstances[$ServerName]
        if ($instance.Status -eq "Running") {
            Write-Warning "Server instance already running: $ServerName"
            return $true
        }

        # Start server process here
        $instance.Status = "Running"
        Write-Host "Server instance started: $ServerName"
        return $true
    }
    catch {
        Write-Error "Failed to start server instance: $($_.Exception.Message)"
        return $false
    }
}

function Stop-ServerInstance {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    try {
        if (-not $script:ServerInstances.ContainsKey($ServerName)) {
            throw "Server instance not found: $ServerName"
        }

        $instance = $script:ServerInstances[$ServerName]
        if ($instance.Status -eq "Stopped") {
            Write-Warning "Server instance already stopped: $ServerName"
            return $true
        }

        # Stop server process here
        $instance.Status = "Stopped"
        Write-Host "Server instance stopped: $ServerName"
        return $true
    }
    catch {
        Write-Error "Failed to stop server instance: $($_.Exception.Message)"
        return $false
    }
}

function Get-ServerInstances {
    return $script:ServerInstances.Clone()
}

function Get-ServerStatus {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    try {
        if (-not $script:ServerInstances.ContainsKey($ServerName)) {
            throw "Server instance not found: $ServerName"
        }

        return $script:ServerInstances[$ServerName].Clone()
    }
    catch {
        Write-Error "Failed to get server status: $($_.Exception.Message)"
        return $null
    }
}

# Store server state
$script:Servers = @{}

function New-GameServer {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        [Parameter(Mandatory=$true)]
        [string]$GameType,
        [Parameter(Mandatory=$true)]
        [string]$InstallPath
    )
    
    $script:Servers[$ServerName] = @{
        Name = $ServerName
        GameType = $GameType
        InstallPath = $InstallPath
        Status = "Stopped"
        LastUpdated = Get-Date
    }
    
    Write-Host "Created new server configuration for $ServerName"
}

function Start-GameServer {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    if ($script:Servers.ContainsKey($ServerName)) {
        $script:Servers[$ServerName].Status = "Running"
        Write-Host "Started server: $ServerName"
    } else {
        Write-Error "Server not found: $ServerName"
    }
}

function Stop-GameServer {
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    if ($script:Servers.ContainsKey($ServerName)) {
        $script:Servers[$ServerName].Status = "Stopped"
        Write-Host "Stopped server: $ServerName"
    } else {
        Write-Error "Server not found: $ServerName"
    }
}

# Replace the export section
function Get-ServerContainerClass {
    return [ServerContainer]
}

function Get-ServerConnectionClass {
    return [ServerConnection]
}

function Get-ServerManagerClass {
    return [ServerManager]
}

# Export all functions
Export-ModuleMember -Function New-ServerInstance, Start-ServerInstance, Stop-ServerInstance, Get-ServerInstances, Get-ServerStatus, New-GameServer, Start-GameServer, Stop-GameServer
