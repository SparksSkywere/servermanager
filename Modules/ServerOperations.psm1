# ServerOperations Module
# This module handles core server management operations like start, stop, and status monitoring

# Define paths based on registry settings
$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"
$script:ServerManagerDir = $null

try {
    # Get server manager directory from registry
    $script:ServerManagerDir = (Get-ItemProperty -Path $script:RegPath -ErrorAction Stop).servermanagerdir
    $script:ServerManagerDir = $script:ServerManagerDir.Trim('"', ' ', '\')
}
catch {
    # Fallback to module parent directory if registry access fails
    Write-Warning "Failed to get ServerManagerDir from registry: $($_.Exception.Message)"
    $script:ServerManagerDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

# Initialize basic paths
$script:Paths = @{
    Root = $script:ServerManagerDir
    Logs = Join-Path $script:ServerManagerDir "logs"
    Config = Join-Path $script:ServerManagerDir "config"
    Servers = Join-Path $script:ServerManagerDir "servers"
    Cache = Join-Path $script:ServerManagerDir "cache"
    Temp = Join-Path $script:ServerManagerDir "temp"
}

# Create directories if they don't exist
foreach ($path in $script:Paths.Values) {
    if (-not (Test-Path -Path $path)) {
        try {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
        catch {
            Write-Warning "Failed to create directory: $path - $($_.Exception.Message)"
        }
    }
}

# Initialize logging
function Write-ServerLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [ValidateSet('INFO', 'WARN', 'ERROR', 'DEBUG')]
        [string]$Level = 'INFO',
        
        [Parameter(Mandatory=$false)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [string]$LogFilePath
    )
    
    try {
        # Generate timestamp
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        
        # Format log message
        $logMessage = "[$timestamp] [$Level]"
        if ($ServerName) {
            $logMessage += " [$ServerName]"
        }
        $logMessage += " $Message"
        
        # Determine log file path
        if (-not $LogFilePath) {
            if ($ServerName) {
                $logDir = Join-Path $script:Paths.Logs $ServerName
                if (-not (Test-Path -Path $logDir)) {
                    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
                }
                $LogFilePath = Join-Path $logDir "operations.log"
            }
            else {
                $LogFilePath = Join-Path $script:Paths.Logs "server-operations.log"
            }
        }
        
        # Write to log file
        Add-Content -Path $LogFilePath -Value $logMessage -ErrorAction Stop
        
        # Output to console for debugging if verbose
        if ($VerbosePreference -eq 'Continue' -or $DebugPreference -eq 'Continue' -or $Level -eq 'ERROR') {
            $foregroundColor = switch ($Level) {
                'INFO' { 'White' }
                'WARN' { 'Yellow' }
                'ERROR' { 'Red' }
                'DEBUG' { 'Cyan' }
                default { 'Gray' }
            }
            Write-Host $logMessage -ForegroundColor $foregroundColor
        }
    }
    catch {
        # Fallback to console output if logging fails
        Write-Warning "Failed to write to log: $Message"
    }
}

# Function to get server configuration
function Get-ServerConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName
    )
    
    try {
        # Check for server configuration file
        $configPath = Join-Path $script:Paths.Servers "$ServerName.json"
        
        if (Test-Path $configPath) {
            # Load and parse server configuration
            $configContent = Get-Content -Path $configPath -Raw -ErrorAction Stop
            $config = $configContent | ConvertFrom-Json -ErrorAction Stop
            
            # Validate configuration
            if (-not $config.name -or -not $config.installPath) {
                Write-ServerLog "Invalid configuration for server: $ServerName" -Level ERROR -ServerName $ServerName
                Write-ServerLog "Config doesn't contain required properties: name=$($config.name), installPath=$($config.installPath)" -Level ERROR -ServerName $ServerName
                return $null
            }
            
            # Ensure config is a PSCustomObject with the correct properties
            $serverConfig = [PSCustomObject]@{
                Name = $config.name
                InstallPath = $config.installPath
                AppId = $config.appId
                ExecutablePath = $config.executablePath
                LaunchParameters = $config.launchParameters
                LogPath = $config.logPath
                UseSteamCmd = $config.useSteamCmd -eq $true
                RestartOnCrash = $config.restartOnCrash -eq $true
                AutoUpdate = $config.autoUpdate -eq $true
                MaxPlayers = [int]($config.maxPlayers)
                Port = [int]($config.port)
                QueryPort = [int]($config.queryPort)
                LastStartTime = $config.lastStartTime
                LastUpdateTime = $config.lastUpdateTime
                Status = $config.status
                PID = $config.pid
                MonitorInterval = [int]($config.monitorInterval)
                Version = $config.version
                CustomProperties = $config.customProperties
            }
            
            # Handle defaults for missing properties
            if (-not $serverConfig.MonitorInterval -or $serverConfig.MonitorInterval -lt 10) {
                $serverConfig.MonitorInterval = 30
            }
            
            return $serverConfig
        }
        else {
            Write-ServerLog "Configuration not found for server: $ServerName" -Level ERROR -ServerName $ServerName
            return $null
        }
    }
    catch {
        Write-ServerLog "Error retrieving server configuration: $_" -Level ERROR -ServerName $ServerName
        return $null
    }
}

# Function to save server configuration
function Save-ServerConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [PSCustomObject]$ServerConfig
    )
    
    try {
        # Validate server config
        if (-not $ServerConfig.Name) {
            Write-ServerLog "Cannot save server configuration: Missing server name" -Level ERROR
            return $false
        }
        
        # Update timestamps
        $ServerConfig.LastUpdateTime = Get-Date -Format o
        
        # Convert configuration to JSON
        $configJson = $ServerConfig | ConvertTo-Json -Depth 10
        
        # Save to file
        $configPath = Join-Path $script:Paths.Servers "$($ServerConfig.Name).json"
        $configDir = Split-Path -Parent $configPath
        
        # Ensure directory exists
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }
        
        # Write configuration with backup strategy
        $backupPath = "$configPath.bak"
        if (Test-Path $configPath) {
            Copy-Item -Path $configPath -Destination $backupPath -Force
        }
        
        $configJson | Set-Content -Path $configPath -Encoding UTF8
        Write-ServerLog "Configuration saved for server: $($ServerConfig.Name)" -Level INFO -ServerName $ServerConfig.Name
        
        return $true
    }
    catch {
        Write-ServerLog "Error saving server configuration: $_" -Level ERROR -ServerName $ServerConfig.Name
        return $false
    }
}

# Function to list all game servers
function Get-GameServers {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [switch]$Refresh,
        
        [Parameter(Mandatory=$false)]
        [switch]$Status,
        
        [Parameter(Mandatory=$false)]
        [string]$Filter
    )
    
    try {
        # Check for server configuration directory
        $serversDir = $script:Paths.Servers
        if (-not (Test-Path $serversDir)) {
            Write-ServerLog "Servers directory not found: $serversDir" -Level WARN
            return @()
        }
        
        # Get all server configuration files
        $serverFiles = Get-ChildItem -Path $serversDir -Filter "*.json"
        if (-not $serverFiles -or $serverFiles.Count -eq 0) {
            Write-ServerLog "No server configurations found in: $serversDir" -Level INFO
            return @()
        }
        
        # Parse server configurations
        $servers = @()
        
        foreach ($file in $serverFiles) {
            try {
                $config = Get-Content -Path $file.FullName -Raw | ConvertFrom-Json
                
                # Apply filter if specified
                if ($Filter -and $config.name -notlike "*$Filter*") {
                    continue
                }
                
                # Create server info object
                $serverInfo = [PSCustomObject]@{
                    Name = $config.name
                    InstallPath = $config.installPath
                    AppId = $config.appId
                    Status = $config.status
                    Port = $config.port
                    LastStartTime = $config.lastStartTime
                    LastUpdateTime = $config.lastUpdateTime
                    PID = $config.pid
                    IsRunning = $false
                    Uptime = $null
                    ResourceUsage = $null
                }
                
                # Update status if requested
                if ($Status -or $Refresh) {
                    # Check if the server process is running
                    if ($config.pid) {
                        try {
                            $process = Get-Process -Id $config.pid -ErrorAction SilentlyContinue
                            if ($process) {
                                $serverInfo.IsRunning = -not $process.HasExited
                                
                                if ($serverInfo.IsRunning) {
                                    # Calculate uptime
                                    if ($process.StartTime) {
                                        $uptime = (Get-Date) - $process.StartTime
                                        $serverInfo.Uptime = [math]::Round($uptime.TotalHours, 2)
                                    }
                                    
                                    # Get resource usage
                                    $serverInfo.ResourceUsage = [PSCustomObject]@{
                                        CPU = [math]::Round($process.CPU, 2)
                                        Memory = [math]::Round($process.WorkingSet64 / 1MB, 2)
                                        Threads = $process.Threads.Count
                                    }
                                } else {
                                    $serverInfo.Status = "Stopped"
                                }
                            } else {
                                $serverInfo.Status = "Stopped"
                                $serverInfo.PID = $null
                            }
                        } catch {
                            $serverInfo.Status = "Unknown"
                            $serverInfo.PID = $null
                        }
                    } else {
                        $serverInfo.Status = "Stopped"
                    }
                    
                    # Update configuration if status changed
                    if ($Refresh -and $config.status -ne $serverInfo.Status) {
                        $config.status = $serverInfo.Status
                        $config | ConvertTo-Json -Depth 5 | Set-Content -Path $file.FullName
                    }
                }
                
                $servers += $serverInfo
            }
            catch {
                Write-ServerLog "Error loading server configuration from $($file.Name): $_" -Level ERROR
            }
        }
        
        return $servers
    }
    catch {
        Write-ServerLog "Error retrieving server list: $_" -Level ERROR
        return @()
    }
}

# Function to start a game server
function Start-GameServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$NoWindow,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$AdditionalParams = @{}
    )
    
    try {
        Write-ServerLog "Starting server: $ServerName" -Level INFO -ServerName $ServerName
        
        # Get server configuration
        $serverConfig = Get-ServerConfig -ServerName $ServerName
        if (-not $serverConfig) {
            throw "Failed to load configuration for server: $ServerName"
        }
        
        # Check if server is already running
        if ($serverConfig.PID) {
            try {
                $process = Get-Process -Id $serverConfig.PID -ErrorAction SilentlyContinue
                if ($process -and -not $process.HasExited) {
                    Write-ServerLog "Server is already running (PID: $($serverConfig.PID))" -Level WARN -ServerName $ServerName
                    return $false
                }
            }
            catch {
                # Process not running, continue with start
                Write-ServerLog "Previous process (PID: $($serverConfig.PID)) is no longer running" -Level INFO -ServerName $ServerName
            }
        }
        
        # Validate executable path
        $execPath = $serverConfig.ExecutablePath
        if (-not $execPath) {
            throw "Missing ExecutablePath in server configuration"
        }
        
        # Expand path if relative
        if (-not [System.IO.Path]::IsPathRooted($execPath)) {
            $execPath = Join-Path $serverConfig.InstallPath $execPath
        }
        
        # Check if executable exists
        if (-not (Test-Path $execPath)) {
            throw "Server executable not found: $execPath"
        }
        
        # Prepare launch parameters
        $launchParams = $serverConfig.LaunchParameters
        
        # Merge additional params if specified
        if ($AdditionalParams) {
            foreach ($key in $AdditionalParams.Keys) {
                $value = $AdditionalParams[$key]
                if ($launchParams -match "$key\s+[\w\d\-]+") {
                    # Replace existing parameter
                    $launchParams = $launchParams -replace "$key\s+[\w\d\-]+", "$key $value"
                } else {
                    # Add new parameter
                    $launchParams += " $key $value"
                }
            }
        }
        
        # Create log directory for this server if it doesn't exist
        $serverLogDir = Join-Path $script:Paths.Logs $ServerName
        if (-not (Test-Path $serverLogDir)) {
            New-Item -ItemType Directory -Path $serverLogDir -Force | Out-Null
        }
        
        # Define output log files
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $stdoutLogFile = Join-Path $serverLogDir "stdout_$timestamp.log"
        $stderrLogFile = Join-Path $serverLogDir "stderr_$timestamp.log"
        
        # Start the process
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $execPath
        $startInfo.Arguments = $launchParams
        $startInfo.WorkingDirectory = Split-Path -Parent $execPath
        $startInfo.CreateNoWindow = $NoWindow
        $startInfo.UseShellExecute = -not $NoWindow
        $startInfo.RedirectStandardOutput = $NoWindow
        $startInfo.RedirectStandardError = $NoWindow
        
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        
        # Setup output redirections if running without window
        if ($NoWindow) {
            # Capture output to log files
            $stdoutFile = [System.IO.File]::Create($stdoutLogFile)
            $stderrFile = [System.IO.File]::Create($stderrLogFile)
            
            $stdoutWriter = New-Object System.IO.StreamWriter($stdoutFile)
            $stderrWriter = New-Object System.IO.StreamWriter($stderrFile)
            $stdoutWriter.AutoFlush = $true
            $stderrWriter.AutoFlush = $true
            
            $process.OutputDataReceived += {
                param($sender, $e)
                if ($null -ne $e.Data) {
                    $stdoutWriter.WriteLine($e.Data)
                    Write-ServerLog $e.Data -Level INFO -ServerName $ServerName -LogFilePath $stdoutLogFile
                }
            }
            
            $process.ErrorDataReceived += {
                param($sender, $e)
                if ($null -ne $e.Data) {
                    $stderrWriter.WriteLine($e.Data)
                    Write-ServerLog $e.Data -Level ERROR -ServerName $ServerName -LogFilePath $stderrLogFile
                }
            }
        }
        
        # Start process
        $success = $process.Start()
        if (-not $success) {
            throw "Failed to start server process"
        }
        
        # Begin output redirection if needed
        if ($NoWindow) {
            $process.BeginOutputReadLine()
            $process.BeginErrorReadLine()
        }
        
        # Update server configuration
        $serverConfig.PID = $process.Id
        $serverConfig.Status = "Running"
        $serverConfig.LastStartTime = Get-Date -Format o
        
        # Save updated configuration
        $saved = Save-ServerConfig -ServerConfig $serverConfig
        if (-not $saved) {
            Write-ServerLog "Failed to save server configuration after start" -Level WARN -ServerName $ServerName
        }
        
        Write-ServerLog "Server started successfully (PID: $($process.Id))" -Level INFO -ServerName $ServerName
        
        # Return process object for further manipulation
        return $process
    }
    catch {
        Write-ServerLog "Error starting server: $_" -Level ERROR -ServerName $ServerName
        return $null
    }
}

# Function to stop a game server
function Stop-GameServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$Force,
        
        [Parameter(Mandatory=$false)]
        [int]$GracePeriodSeconds = 30
    )
    
    try {
        Write-ServerLog "Stopping server: $ServerName (Force: $Force)" -Level INFO -ServerName $ServerName
        
        # Get server configuration
        $serverConfig = Get-ServerConfig -ServerName $ServerName
        if (-not $serverConfig) {
            throw "Failed to load configuration for server: $ServerName"
        }
        
        # Check if server is running
        if (-not $serverConfig.PID) {
            Write-ServerLog "Server is not running (no PID found)" -Level WARN -ServerName $ServerName
            
            # Update status to reflect stopped state
            $serverConfig.Status = "Stopped"
            Save-ServerConfig -ServerConfig $serverConfig | Out-Null
            
            return $true
        }
        
        # Try to get process
        try {
            $process = Get-Process -Id $serverConfig.PID -ErrorAction SilentlyContinue
            if (-not $process -or $process.HasExited) {
                Write-ServerLog "Process (PID: $($serverConfig.PID)) is not running" -Level INFO -ServerName $ServerName
                
                # Update configuration with stopped status
                $serverConfig.Status = "Stopped"
                $serverConfig.PID = $null
                Save-ServerConfig -ServerConfig $serverConfig | Out-Null
                
                return $true
            }
        }
        catch {
            Write-ServerLog "Process (PID: $($serverConfig.PID)) is not accessible: $_" -Level WARN -ServerName $ServerName
            
            # Update configuration with stopped status
            $serverConfig.Status = "Stopped"
            $serverConfig.PID = $null
            Save-ServerConfig -ServerConfig $serverConfig | Out-Null
            
            return $true
        }
        
        # Try graceful shutdown first if not forced
        $stopped = $false
        if (-not $Force) {
            Write-ServerLog "Attempting graceful shutdown..." -Level INFO -ServerName $ServerName
            
            try {
                # Send close signal
                $process.CloseMainWindow() | Out-Null
                
                # Wait for process to exit
                $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
                while (-not $process.HasExited -and $stopwatch.Elapsed.TotalSeconds -lt $GracePeriodSeconds) {
                    Start-Sleep -Milliseconds 500
                    $process.Refresh()
                }
                
                $stopped = $process.HasExited
                
                if ($stopped) {
                    Write-ServerLog "Server stopped gracefully" -Level INFO -ServerName $ServerName
                } else {
                    Write-ServerLog "Server did not stop gracefully within $GracePeriodSeconds seconds" -Level WARN -ServerName $ServerName
                }
            }
            catch {
                Write-ServerLog "Error during graceful shutdown: $_" -Level WARN -ServerName $ServerName
            }
        }
        
        # Force kill if necessary
        if (-not $stopped) {
            Write-ServerLog "Forcing server termination..." -Level WARN -ServerName $ServerName
            
            try {
                Stop-Process -Id $serverConfig.PID -Force -ErrorAction Stop
                $stopped = $true
                Write-ServerLog "Server terminated forcefully" -Level INFO -ServerName $ServerName
            }
            catch {
                Write-ServerLog "Failed to terminate server process: $_" -Level ERROR -ServerName $ServerName
                $stopped = $false
            }
        }
        
        # Update server configuration regardless of outcome
        if ($stopped) {
            $serverConfig.Status = "Stopped"
            $serverConfig.PID = $null
            Save-ServerConfig -ServerConfig $serverConfig | Out-Null
        }
        
        return $stopped
    }
    catch {
        Write-ServerLog "Error stopping server: $_" -Level ERROR -ServerName $ServerName
        return $false
    }
}

# Function to restart a game server
function Restart-GameServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$Force,
        
        [Parameter(Mandatory=$false)]
        [int]$GracePeriodSeconds = 30,
        
        [Parameter(Mandatory=$false)]
        [switch]$NoWindow,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$AdditionalParams = @{}
    )
    
    try {
        Write-ServerLog "Restarting server: $ServerName (Force: $Force)" -Level INFO -ServerName $ServerName
        
        # Stop the server
        $stopped = Stop-GameServer -ServerName $ServerName -Force:$Force -GracePeriodSeconds $GracePeriodSeconds
        
        if (-not $stopped) {
            Write-ServerLog "Failed to stop server during restart" -Level ERROR -ServerName $ServerName
            return $false
        }
        
        # Give the system a moment to fully release resources
        Start-Sleep -Seconds 2
        
        # Start the server again
        $process = Start-GameServer -ServerName $ServerName -NoWindow:$NoWindow -AdditionalParams $AdditionalParams
        
        if ($null -eq $process) {
            Write-ServerLog "Failed to start server during restart" -Level ERROR -ServerName $ServerName
            return $false
        }
        
        Write-ServerLog "Server restarted successfully (PID: $($process.Id))" -Level INFO -ServerName $ServerName
        return $true
    }
    catch {
        Write-ServerLog "Error restarting server: $_" -Level ERROR -ServerName $ServerName
        return $false
    }
}

# Function to get server status
function Get-ServerStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$Detailed
    )
    
    try {
        # Get server configuration
        $serverConfig = Get-ServerConfig -ServerName $ServerName
        if (-not $serverConfig) {
            throw "Failed to load configuration for server: $ServerName"
        }
        
        # Create status object
        $status = [PSCustomObject]@{
            Name = $serverConfig.Name
            Status = $serverConfig.Status
            PID = $serverConfig.PID
            IsRunning = $false
            Port = $serverConfig.Port
            QueryPort = $serverConfig.QueryPort
            LastStartTime = $serverConfig.LastStartTime
            LastUpdateTime = $serverConfig.LastUpdateTime
            Uptime = $null
            ResourceUsage = $null
        }
        
        # Check if process is running
        if ($serverConfig.PID) {
            try {
                $process = Get-Process -Id $serverConfig.PID -ErrorAction SilentlyContinue
                if ($process -and -not $process.HasExited) {
                    $status.IsRunning = $true
                    
                    # Calculate uptime
                    if ($process.StartTime) {
                        $uptime = (Get-Date) - $process.StartTime
                        $status.Uptime = [PSCustomObject]@{
                            TotalSeconds = [math]::Round($uptime.TotalSeconds)
                            TotalMinutes = [math]::Round($uptime.TotalMinutes)
                            TotalHours = [math]::Round($uptime.TotalHours, 2)
                            Days = $uptime.Days
                            Hours = $uptime.Hours
                            Minutes = $uptime.Minutes
                            Seconds = $uptime.Seconds
                        }
                    }
                    
                    # Get basic resource usage
                    $status.ResourceUsage = [PSCustomObject]@{
                        CPU = [math]::Round($process.CPU, 2)
                        Memory = [math]::Round($process.WorkingSet64 / 1MB, 2)
                        PrivateMemory = [math]::Round($process.PrivateMemorySize64 / 1MB, 2)
                        Threads = $process.Threads.Count
                        Handles = $process.HandleCount
                    }
                    
                    # Update status if it's different from configuration
                    if ($status.Status -ne "Running") {
                        $serverConfig.Status = "Running"
                        Save-ServerConfig -ServerConfig $serverConfig | Out-Null
                        $status.Status = "Running"
                    }
                } else {
                    # Process not running, update status
                    $status.IsRunning = $false
                    $status.Status = "Stopped"
                    
                    # Update configuration if status has changed
                    if ($serverConfig.Status -ne "Stopped") {
                        $serverConfig.Status = "Stopped"
                        $serverConfig.PID = $null
                        Save-ServerConfig -ServerConfig $serverConfig | Out-Null
                    }
                }
            } catch {
                Write-ServerLog "Error checking process status: $_" -Level WARN -ServerName $ServerName
                $status.Status = "Unknown"
            }
        } else {
            $status.Status = "Stopped"
        }
        
        # Add detailed information if requested
        if ($Detailed) {
            $status | Add-Member -NotePropertyName InstallPath -NotePropertyValue $serverConfig.InstallPath
            $status | Add-Member -NotePropertyName ExecutablePath -NotePropertyValue $serverConfig.ExecutablePath
            $status | Add-Member -NotePropertyName LaunchParameters -NotePropertyValue $serverConfig.LaunchParameters
            $status | Add-Member -NotePropertyName AppId -NotePropertyValue $serverConfig.AppId
            $status | Add-Member -NotePropertyName Version -NotePropertyValue $serverConfig.Version
            $status | Add-Member -NotePropertyName MaxPlayers -NotePropertyValue $serverConfig.MaxPlayers
            
            # Get server log files
            $serverLogDir = Join-Path $script:Paths.Logs $ServerName
            if (Test-Path $serverLogDir) {
                $logFiles = Get-ChildItem -Path $serverLogDir -File | Select-Object -Last 5 | ForEach-Object { 
                    [PSCustomObject]@{
                        Name = $_.Name
                        Path = $_.FullName
                        SizeKB = [math]::Round($_.Length / 1KB, 2)
                        LastWriteTime = $_.LastWriteTime
                    } 
                }
                $status | Add-Member -NotePropertyName RecentLogs -NotePropertyValue $logFiles
            }
            
            # Add network information if server is running
            if ($status.IsRunning -and $status.Port -gt 0) {
                try {
                    $netStat = Get-NetTCPConnection -LocalPort $status.Port -ErrorAction SilentlyContinue | 
                               Where-Object { $_.State -eq "Listen" -or $_.State -eq "Established" } | 
                               Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, State
                    
                    $status | Add-Member -NotePropertyName NetworkConnections -NotePropertyValue $netStat
                } catch {
                    Write-ServerLog "Error retrieving network information: $_" -Level WARN -ServerName $ServerName
                }
            }
        }
        
        return $status
    }
    catch {
        Write-ServerLog "Error retrieving server status: $_" -Level ERROR -ServerName $ServerName
        return $null
    }
}

# Function to create a new server configuration
function New-ServerConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$true)]
        [string]$InstallPath,
        
        [Parameter(Mandatory=$true)]
        [string]$ExecutablePath,
        
        [Parameter(Mandatory=$false)]
        [string]$LaunchParameters = "",
        
        [Parameter(Mandatory=$false)]
        [string]$AppId = "",
        
        [Parameter(Mandatory=$false)]
        [int]$Port = 0,
        
        [Parameter(Mandatory=$false)]
        [int]$QueryPort = 0,
        
        [Parameter(Mandatory=$false)]
        [int]$MaxPlayers = 0,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$CustomProperties = @{},
        
        [Parameter(Mandatory=$false)]
        [switch]$UseSteamCmd,
        
        [Parameter(Mandatory=$false)]
        [switch]$RestartOnCrash,
        
        [Parameter(Mandatory=$false)]
        [switch]$AutoUpdate,
        
        [Parameter(Mandatory=$false)]
        [switch]$Force
    )
    
    try {
        # Validate server name - alphanumeric with hyphens and underscores only
        if ($ServerName -notmatch '^[a-zA-Z0-9_-]+$') {
            throw "Invalid server name. Use only alphanumeric characters, hyphens, and underscores."
        }
        
        # Check if server already exists
        $configPath = Join-Path $script:Paths.Servers "$ServerName.json"
        if ((Test-Path $configPath) -and -not $Force) {
            throw "Server configuration already exists. Use -Force to overwrite."
        }
        
        # Ensure install path exists
        if (-not (Test-Path $InstallPath)) {
            Write-ServerLog "Install path does not exist: $InstallPath" -Level WARN -ServerName $ServerName
        }
        
        # Check executable path
        $fullExecPath = $ExecutablePath
        if (-not [System.IO.Path]::IsPathRooted($ExecutablePath)) {
            $fullExecPath = Join-Path $InstallPath $ExecutablePath
        }
        
        if (-not (Test-Path $fullExecPath)) {
            Write-ServerLog "Executable path does not exist: $fullExecPath" -Level WARN -ServerName $ServerName
        }
        
        # Ensure servers directory exists
        if (-not (Test-Path $script:Paths.Servers)) {
            New-Item -ItemType Directory -Path $script:Paths.Servers -Force | Out-Null
        }
        
        # Create server log directory
        $serverLogDir = Join-Path $script:Paths.Logs $ServerName
        if (-not (Test-Path $serverLogDir)) {
            New-Item -ItemType Directory -Path $serverLogDir -Force | Out-Null
        }
        
        # Create server config object
        $serverConfig = [PSCustomObject]@{
            Name = $ServerName
            InstallPath = $InstallPath
            ExecutablePath = $ExecutablePath
            LaunchParameters = $LaunchParameters
            AppId = $AppId
            Port = $Port
            QueryPort = $QueryPort
            MaxPlayers = $MaxPlayers
            Status = "Stopped"
            PID = $null
            UseSteamCmd = $UseSteamCmd.IsPresent
            RestartOnCrash = $RestartOnCrash.IsPresent
            AutoUpdate = $AutoUpdate.IsPresent
            LastStartTime = $null
            LastUpdateTime = Get-Date -Format o
            LogPath = Join-Path $serverLogDir "server.log"
            MonitorInterval = 30
            Version = "1.0"
            CustomProperties = $CustomProperties
        }
        
        # Convert to JSON and save
        $configJson = $serverConfig | ConvertTo-Json -Depth 5
        Set-Content -Path $configPath -Value $configJson -Force
        
        Write-ServerLog "Created server configuration for: $ServerName" -Level INFO -ServerName $ServerName
        return $serverConfig
    }
    catch {
        Write-ServerLog "Error creating server configuration: $_" -Level ERROR -ServerName $ServerName
        return $null
    }
}

# Function to remove a server configuration
function Remove-ServerConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$StopServer,
        
        [Parameter(Mandatory=$false)]
        [switch]$RemoveInstallation,
        
        [Parameter(Mandatory=$false)]
        [switch]$Force
    )
    
    try {
        Write-ServerLog "Removing server: $ServerName (RemoveInstallation: $RemoveInstallation)" -Level INFO -ServerName $ServerName
        
        # Check if server configuration exists
        $configPath = Join-Path $script:Paths.Servers "$ServerName.json"
        if (-not (Test-Path $configPath)) {
            throw "Server configuration does not exist: $ServerName"
        }
        
        # Get server configuration
        $serverConfig = Get-ServerConfig -ServerName $ServerName
        if (-not $serverConfig -and -not $Force) {
            throw "Failed to load server configuration"
        }
        
        # Stop server if requested or force flag is set
        if (($StopServer -or $Force) -and $serverConfig) {
            Stop-GameServer -ServerName $ServerName -Force -GracePeriodSeconds 10
        }
        
        # Remove configuration file
        Remove-Item -Path $configPath -Force
        Write-ServerLog "Removed server configuration file" -Level INFO -ServerName $ServerName
        
        # Optionally remove installation directory
        if ($RemoveInstallation -and $serverConfig -and $serverConfig.InstallPath) {
            if (Test-Path $serverConfig.InstallPath) {
                Write-ServerLog "Removing installation directory: $($serverConfig.InstallPath)" -Level WARN -ServerName $ServerName
                
                # Safety check - don't delete system directories
                $systemPaths = @($env:ProgramFiles, $env:ProgramFiles, $env:SystemRoot, $env:windir)
                $isSystemPath = $false
                foreach ($path in $systemPaths) {
                    if ($serverConfig.InstallPath -eq $path) {
                        $isSystemPath = $true
                        break
                    }
                }
                
                if ($isSystemPath) {
                    Write-ServerLog "Refusing to delete system directory: $($serverConfig.InstallPath)" -Level ERROR -ServerName $ServerName
                } else {
                    # Proceed with deletion
                    try {
                        # Use the slower but safer Remove-Item cmdlet
                        Remove-Item -Path $serverConfig.InstallPath -Recurse -Force -ErrorAction Stop
                        Write-ServerLog "Installation directory removed" -Level INFO -ServerName $ServerName
                    } catch {
                        Write-ServerLog "Failed to remove installation directory: $_" -Level ERROR -ServerName $ServerName
                        
                        # Try alternative approach with robocopy (Empty + Delete)
                        try {
                            $tempEmptyDir = Join-Path $script:Paths.Temp "EmptyDir"
                            if (-not (Test-Path $tempEmptyDir)) {
                                New-Item -ItemType Directory -Path $tempEmptyDir -Force | Out-Null
                            }
                            
                            # Use robocopy to empty the directory (mirror empty to target)
                            $robocopyArgs = "`"$tempEmptyDir`" `"$($serverConfig.InstallPath)`" /MIR /R:1 /W:1"
                            Start-Process -FilePath "robocopy" -ArgumentList $robocopyArgs -Wait -NoNewWindow
                            
                            # Now remove the empty directory
                            Remove-Item -Path $serverConfig.InstallPath -Recurse -Force -ErrorAction Stop
                            
                            Write-ServerLog "Installation directory removed (using robocopy method)" -Level INFO -ServerName $ServerName
                        } catch {
                            Write-ServerLog "Failed to remove installation directory (alternative method): $_" -Level ERROR -ServerName $ServerName
                        }
                    }
                }
            } else {
                Write-ServerLog "Installation directory does not exist: $($serverConfig.InstallPath)" -Level WARN -ServerName $ServerName
            }
        }
        
        return $true
    }
    catch {
        Write-ServerLog "Error removing server: $_" -Level ERROR -ServerName $ServerName
        return $false
    }
}

# Function to update a server
function Update-GameServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ServerName,
        
        [Parameter(Mandatory=$false)]
        [switch]$Force,
        
        [Parameter(Mandatory=$false)]
        [switch]$RestartIfRunning,
        
        [Parameter(Mandatory=$false)]
        [string]$SteamCmdPath
    )
    
    try {
        Write-ServerLog "Updating server: $ServerName (Force: $Force)" -Level INFO -ServerName $ServerName
        
        # Get server configuration
        $serverConfig = Get-ServerConfig -ServerName $ServerName
        if (-not $serverConfig) {
            throw "Failed to load configuration for server: $ServerName"
        }
        
        # Check if we have an AppId for Steam updates
        if (-not $serverConfig.AppId -or $serverConfig.AppId -eq "0") {
            throw "Server doesn't have a valid AppId for updates"
        }
        
        # Check if SteamCMD is enabled and available
        if (-not $serverConfig.UseSteamCmd) {
            throw "Steam updates are not enabled for this server"
        }
        
        # Check if SteamCmd path is provided or available
        if (-not $SteamCmdPath) {
            # Try to get from registry
            try {
                $steamCmdPath = (Get-ItemProperty -Path $script:RegPath -ErrorAction Stop).SteamCMDPath
                if ($steamCmdPath) {
                    $SteamCmdPath = Join-Path $steamCmdPath "steamcmd.exe"
                }
            } catch {
                Write-ServerLog "Failed to get SteamCmdPath from registry: $_" -Level WARN -ServerName $ServerName
            }
            
            # If still not found, use default locations
            if (-not $SteamCmdPath -or -not (Test-Path $SteamCmdPath)) {
                $commonPaths = @(
                    (Join-Path $script:ServerManagerDir "steamcmd\steamcmd.exe"),
                    (Join-Path $env:ProgramFiles "SteamCMD\steamcmd.exe"),
                    (Join-Path ${env:ProgramFiles(x86)} "SteamCMD\steamcmd.exe")
                )
                
                foreach ($path in $commonPaths) {
                    if (Test-Path $path) {
                        $SteamCmdPath = $path
                        break
                    }
                }
            }
        }
        
        # Final check for SteamCmd
        if (-not $SteamCmdPath -or -not (Test-Path $SteamCmdPath)) {
            throw "SteamCmd not found. Please provide a valid -SteamCmdPath."
        }
        
        # Determine if we need to stop the server
        $isRunning = $false
        if ($serverConfig.PID) {
            try {
                $process = Get-Process -Id $serverConfig.PID -ErrorAction SilentlyContinue
                $isRunning = $process -and -not $process.HasExited
            } catch {
                Write-ServerLog "Error checking server process: $_" -Level WARN -ServerName $ServerName
                $isRunning = $false
            }
        }
        
        # Stop server if it's running and we need to
        if ($isRunning -and ($Force -or $RestartIfRunning)) {
            Write-ServerLog "Stopping server for update" -Level INFO -ServerName $ServerName
            
            $stopped = Stop-GameServer -ServerName $ServerName -Force:$Force -GracePeriodSeconds 30
            if (-not $stopped) {
                if (-not $Force) {
                    throw "Failed to stop server for update"
                } else {
                    Write-ServerLog "Failed to stop server gracefully, continuing with update anyway" -Level WARN -ServerName $ServerName
                }
            }
        } elseif ($isRunning) {
            throw "Server is running. Use -Force or -RestartIfRunning to stop it before updating."
        }
        
        # Run SteamCMD update
        Write-ServerLog "Running SteamCMD update (AppId: $($serverConfig.AppId))" -Level INFO -ServerName $ServerName
        
        # Create update log file
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $updateLogFile = Join-Path (Join-Path $script:Paths.Logs $ServerName) "update_$timestamp.log"
        
        # Build SteamCmd arguments
        $steamCmdArgs = "+login anonymous +force_install_dir `"$($serverConfig.InstallPath)`" +app_update $($serverConfig.AppId) validate +quit"
        
        # Start update process
        $updateProcess = Start-Process -FilePath $SteamCmdPath -ArgumentList $steamCmdArgs -NoNewWindow -PassThru -Wait -RedirectStandardOutput $updateLogFile -RedirectStandardError "${updateLogFile}.err"
        
        # Check exit code
        if ($updateProcess.ExitCode -ne 0) {
            Write-ServerLog "SteamCMD returned non-zero exit code: $($updateProcess.ExitCode)" -Level WARN -ServerName $ServerName
        }
        
        Write-ServerLog "Update completed with exit code: $($updateProcess.ExitCode)" -Level INFO -ServerName $ServerName
        
        # Update the server configuration
        $serverConfig.LastUpdateTime = Get-Date -Format o
        Save-ServerConfig -ServerConfig $serverConfig | Out-Null
        
        # Restart if it was running
        if ($isRunning -and $RestartIfRunning) {
            Write-ServerLog "Restarting server after update" -Level INFO -ServerName $ServerName
            
            Start-GameServer -ServerName $ServerName -NoWindow
        }
        
        return $updateProcess.ExitCode -eq 0
    }
    catch {
        Write-ServerLog "Error updating server: $_" -Level ERROR -ServerName $ServerName
        return $false
    }
}

# Export functions
Export-ModuleMember -Function @(
    'Write-ServerLog',
    'Get-ServerConfig',
    'Save-ServerConfig',
    'Get-GameServers',
    'Start-GameServer',
    'Stop-GameServer',
    'Restart-GameServer',
    'Get-ServerStatus',
    'New-ServerConfig',
    'Remove-ServerConfig',
    'Update-GameServer'
)
