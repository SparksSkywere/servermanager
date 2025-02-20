# Common variables and functions for Server Manager

# Registry and paths
$script:RegistryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$script:ServerManagerDir = (Get-ItemProperty -Path $script:RegistryPath -ErrorAction Stop).servermanagerdir

# Directory structure
$script:Paths = @{
    Logs = Join-Path $script:ServerManagerDir "logs"
    Config = Join-Path $script:ServerManagerDir "config"
    Temp = Join-Path $script:ServerManagerDir "temp"
    Servers = Join-Path $script:ServerManagerDir "servers"
}

# Ready file paths
$script:ReadyFiles = @{
    WebServer = Join-Path $script:Paths.Temp "webserver.ready"
    WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
}

# Add PID file paths to existing paths structure
$script:PidFiles = @{
    Launcher = Join-Path $script:Paths.Temp "launcher.pid"
    WebServer = Join-Path $script:Paths.Temp "webserver.pid"
    TrayIcon = Join-Path $script:Paths.Temp "trayicon.pid"
    WebSocket = Join-Path $script:Paths.Temp "websocket.pid"
}

# Port configuration
$script:Ports = @{
    WebServer = 8080
    WebSocket = 8081
}

# Logging function
function Write-ServerLog {
    param (
        [string]$Message,
        [string]$Level = "INFO",
        [string]$Component = "System"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp [$Level] [$Component] $Message"
    
    # Ensure logs directory exists
    if (-not (Test-Path $script:Paths.Logs)) {
        New-Item -Path $script:Paths.Logs -ItemType Directory -Force | Out-Null
    }
    
    $logFile = Join-Path $script:Paths.Logs "$Component.log"
    Add-Content -Path $logFile -Value $logMessage
    
    # Also write to console for debugging
    Write-Host $logMessage
}

# Unified ready file management
function Write-ReadyFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type,
        [string]$Status = "ready",
        [int]$Port,
        [string]$Message = ""
    )
    
    try {
        $readyPath = $script:ReadyFiles[$Type]
        if (-not $readyPath) {
            throw "Invalid ready file type: $Type"
        }

        $content = @{
            status = $Status
            port = $Port
            timestamp = Get-Date -Format "o"
            message = $Message
        } | ConvertTo-Json

        Set-Content -Path $readyPath -Value $content -Force
        Write-ServerLog "Ready file updated: $Type = $Status" -Level INFO
        return $true
    }
    catch {
        Write-ServerLog "Failed to write ready file: $_" -Level ERROR
        return $false
    }
}

function Test-ReadyFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type,
        [int]$TimeoutSeconds = 30
    )
    
    try {
        $readyPath = $script:ReadyFiles[$Type]
        if (-not $readyPath) {
            throw "Invalid ready file type: $Type"
        }

        if (Test-Path $readyPath) {
            $content = Get-Content $readyPath -Raw | ConvertFrom-Json
            Write-ServerLog "Ready file status for $Type : $($content.status)" -Level DEBUG
            return $content.status -eq "ready"
        }
    }
    catch {
        Write-ServerLog "Error checking ready file: $_" -Level ERROR
    }
    return $false
}

# PID file management functions
function Write-PidFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type,
        [Parameter(Mandatory=$true)]
        [int]$ProcessId
    )
    
    try {
        $pidFile = $script:PidFiles[$Type]
        $pidInfo = @{
            ProcessId = $ProcessId
            StartTime = Get-Date -Format "o"
            ProcessPath = (Get-Process -Id $ProcessId).Path
            CommandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId").CommandLine
        }
        
        $pidInfo | ConvertTo-Json | Set-Content -Path $pidFile -Force
        Write-ServerLog "Created PID file for $Type (PID: $ProcessId)" -Level INFO -Component "PIDManager"
        return $true
    } catch {
        Write-ServerLog "Failed to write PID file for $Type : $_" -Level ERROR -Component "PIDManager"
        return $false
    }
}

function Get-ProcessFromPidFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type
    )
    
    try {
        $pidFile = $script:PidFiles[$Type]
        if (Test-Path $pidFile) {
            $pidInfo = Get-Content $pidFile -Raw | ConvertFrom-Json
            return Get-Process -Id $pidInfo.ProcessId -ErrorAction SilentlyContinue
        }
    } catch {
        Write-ServerLog "Failed to get process from PID file $Type : $_" -Level ERROR -Component "PIDManager"
    }
    return $null
}

function Test-ProcessAlive {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type
    )
    
    try {
        $process = Get-ProcessFromPidFile -Type $Type
        return ($null -ne $process -and -not $process.HasExited)
    } catch {
        Write-ServerLog "Failed to verify process $Type : $_" -Level ERROR -Component "PIDManager"
    }
    return $false
}

function Remove-PidFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Type
    )
    
    try {
        $pidFile = $script:PidFiles[$Type]
        if (Test-Path $pidFile) {
            Remove-Item -Path $pidFile -Force
            Write-ServerLog "Removed PID file for $Type" -Level INFO -Component "PIDManager"
            return $true
        }
    } catch {
        Write-ServerLog "Failed to remove PID file for $Type : $_" -Level ERROR -Component "PIDManager"
    }
    return $false
}

# Export members
Export-ModuleMember -Variable Paths, ReadyFiles, Ports, PidFiles
Export-ModuleMember -Function Write-ServerLog, Write-ReadyFile, Test-ReadyFile, 
                              Write-PidFile, Get-ProcessFromPidFile, 
                              Test-ProcessAlive, Remove-PidFile
