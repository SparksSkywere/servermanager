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
function New-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName,
        [Parameter(Mandatory = $true)]
        [string]$AppID,
        [Parameter(Mandatory = $true)]
        [string]$InstallDir
    )
    
    try {
        # Validate inputs
        if ([string]::IsNullOrWhiteSpace($ServerName)) {
            throw "ServerName cannot be empty"
        }
        if (-not $AppID -match '^\d+$') {
            throw "AppID must be numeric"
        }
        
        # Create server directory
        if (-not (Test-Path $InstallDir)) {
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        }

        # Get SteamCMD path from registry
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $steamCmdPath = Join-Path (Get-ItemProperty -Path $registryPath).SteamCmdPath "steamcmd.exe"

        # Install/Update server files
        $arguments = "+login anonymous +force_install_dir `"$InstallDir`" +app_update $AppID validate +quit"
        Start-Process -FilePath $steamCmdPath -ArgumentList $arguments -NoNewWindow -Wait

        # Create server configuration
        $serverConfig = @{
            Name = $ServerName
            AppID = $AppID
            InstallDir = $InstallDir
            LastUpdate = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        }

        # Save configuration
        $configPath = Join-Path (Get-ItemProperty -Path $registryPath).servermanagerdir "servers"
        if (-not (Test-Path $configPath)) {
            New-Item -ItemType Directory -Path $configPath -Force | Out-Null
        }
        $serverConfig | ConvertTo-Json | Set-Content -Path (Join-Path $configPath "$ServerName.json")

        Write-Host "Server instance created successfully: $ServerName"
    }
    catch {
        Write-Error "Failed to create server instance: $_"
        throw
    }
}

function Remove-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )
    
    try {
        # Get registry paths
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
        $configPath = Join-Path $serverManagerDir "servers\$ServerName.json"

        # Stop server if running
        $container = [ServerContainer]::new($ServerName)
        $container.Stop()

        # Remove configuration file
        if (Test-Path $configPath) {
            Remove-Item -Path $configPath -Force
        }

        # Clean up installation directory if specified
        $config = Get-Content $configPath -ErrorAction SilentlyContinue | ConvertFrom-Json
        if ($config -and $config.InstallDir -and (Test-Path $config.InstallDir)) {
            Remove-Item -Path $config.InstallDir -Recurse -Force
        }

        Write-Host "Server instance removed successfully: $ServerName"
    }
    catch {
        Write-Error "Failed to remove server instance: $_"
        throw
    }
}

function Get-ServerInstances {
    try {
        # Get registry path
        $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
        $configPath = Join-Path $serverManagerDir "servers"

        # Get all server configurations
        $servers = @()
        if (Test-Path $configPath) {
            Get-ChildItem -Path $configPath -Filter "*.json" | ForEach-Object {
                $config = Get-Content $_.FullName | ConvertFrom-Json
                $container = [ServerContainer]::new($config.Name)
                $container.AppId = $config.AppID
                $container.InstallPath = $config.InstallDir
                $stats = $container.GetStats()
                $container.Status = $stats.Status
                $container.CpuUsage = $stats.CPU
                $container.MemoryUsage = $stats.Memory
                $container.Uptime = if ($stats.StartTime) {
                    (Get-Date) - $stats.StartTime
                } else { "0:00:00" }
                $servers += $container
            }
        }

        return $servers
    }
    catch {
        Write-Error "Failed to get server instances: $_"
        throw
    }
}

function Start-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )
    
    try {
        $container = [ServerContainer]::new($ServerName)
        $container.Start()
        Write-Host "Server instance started successfully: $ServerName"
    }
    catch {
        Write-Error "Failed to start server instance: $_"
        throw
    }
}

function Stop-ServerInstance {
    param (
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )
    
    try {
        $container = [ServerContainer]::new($ServerName)
        $container.Stop()
        Write-Host "Server instance stopped successfully: $ServerName"
    }
    catch {
        Write-Error "Failed to stop server instance: $_"
        throw
    }
}

# Export all functions directly
Export-ModuleMember -Function *-* -Class ServerContainer, ServerConnection, ServerManager
