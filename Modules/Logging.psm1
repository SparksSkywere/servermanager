# Generic Logging Module - Can be used by any PowerShell script

# Load required assemblies
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

# Module scope variables with registry-based paths
$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"
$script:ServerManagerDir = if (Test-Path $script:RegPath) {
    try {
        (Get-ItemProperty -Path $script:RegPath -ErrorAction Stop).servermanagerdir.Trim('"', ' ', '\')
    } catch {
        $PSScriptRoot | Split-Path | Split-Path    # Fallback to script parent directory
    }
} else {
    $PSScriptRoot | Split-Path | Split-Path    # Fallback to script parent directory
}

# Initialize paths structure
$script:Paths = @{
    Root = $script:ServerManagerDir
    Logs = Join-Path $script:ServerManagerDir "logs"
    Config = Join-Path $script:ServerManagerDir "config"
    Temp = Join-Path $script:ServerManagerDir "temp"
    Modules = Join-Path $script:ServerManagerDir "Modules"
}

# Default log path is now under ServerManager logs directory
$script:DefaultLogPath = $script:Paths.Logs

# Rest of logging defaults
$script:LoggingDefaults = @{
    LogLevel = "INFO"  # Default minimum log level
    UseTimestamp = $true
    TimestampFormat = "yyyy-MM-dd HH:mm:ss"
    AppendToExisting = $true
    DefaultColors = @{
        "INFO"  = "White"
        "WARN"  = "Yellow"
        "ERROR" = "Red"
        "DEBUG"  = "Cyan"
        "FATAL" = "DarkRed"
        "TRACE" = "Gray"
    }
    DefaultRtbColors = @{
        "INFO"  = [System.Drawing.Color]::White
        "WARN"  = [System.Drawing.Color]::Orange
        "ERROR" = [System.Drawing.Color]::Red
        "DEBUG" = [System.Drawing.Color]::DarkCyan
        "FATAL" = [System.Drawing.Color]::DarkRed
        "TRACE" = [System.Drawing.Color]::Gray
    }
    ShowDebugOutput = $false
    EnableFileLogging = $true
    EventLogSource = "PowerShellLogging"
    EventLogName = "Application"
}

# Custom log level definition
enum LogLevel {
    TRACE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    FATAL = 5
}

# Initialize logging - can be called to customize defaults
function Initialize-Logging {
    param (
        [Parameter(Mandatory = $false)]
        [string]$DefaultLogDirectory,
        
        [Parameter(Mandatory = $false)]
        [string]$MinimumLogLevel = "INFO",
        
        [Parameter(Mandatory = $false)]
        [string]$TimestampFormat,
        
        [Parameter(Mandatory = $false)]
        [switch]$ShowDebugOutput,
        
        [Parameter(Mandatory = $false)]
        [switch]$DisableFileLogging,
        
        [Parameter(Mandatory = $false)]
        [string]$EventLogSource,
        
        [Parameter(Mandatory = $false)]
        [string]$EventLogName
    )
    
    # Set default log directory
    if ($DefaultLogDirectory) {
        $script:DefaultLogPath = $DefaultLogDirectory
        
        # Create directory if it doesn't exist
        if (-not (Test-Path -Path $DefaultLogDirectory)) {
            New-Item -Path $DefaultLogDirectory -ItemType Directory -Force | Out-Null
        }
    }
    
    # Update other defaults
    if ($MinimumLogLevel) {
        $script:LoggingDefaults.LogLevel = $MinimumLogLevel
    }
    
    if ($TimestampFormat) {
        $script:LoggingDefaults.TimestampFormat = $TimestampFormat
    }
    
    if ($PSBoundParameters.ContainsKey('ShowDebugOutput')) {
        $script:LoggingDefaults.ShowDebugOutput = $ShowDebugOutput.IsPresent
    }
    
    if ($PSBoundParameters.ContainsKey('DisableFileLogging')) {
        $script:LoggingDefaults.EnableFileLogging = -not $DisableFileLogging.IsPresent
    }
    
    if ($EventLogSource) {
        $script:LoggingDefaults.EventLogSource = $EventLogSource
    }
    
    if ($EventLogName) {
        $script:LoggingDefaults.EventLogName = $EventLogName
    }
    
    # Create an initial log entry
    Write-Log -Message "Logging initialized with settings: Default directory=$($script:DefaultLogPath), MinLevel=$($script:LoggingDefaults.LogLevel), FileLogging=$($script:LoggingDefaults.EnableFileLogging)" -Level DEBUG
    
    return $script:LoggingDefaults
}

# Helper function to determine calling script name
function Get-CallingScriptName {
    $callStack = Get-PSCallStack
    $callerInfo = $callStack | Where-Object { $_.ScriptName -and $_.ScriptName -ne $MyInvocation.ScriptName } | Select-Object -First 1
    
    if ($callerInfo -and $callerInfo.ScriptName) {
        return [System.IO.Path]::GetFileNameWithoutExtension($callerInfo.ScriptName)
    }
    elseif ($Host.Name -eq 'ConsoleHost') {
        return "ConsoleSession"
    }
    else {
        return "PowerShell"
    }
}

# Function to determine if a log level meets the minimum threshold
function Test-LogLevel {
    param (
        [string]$Level
    )
    
    try {
        $levelEnum = [LogLevel]$Level
        $minLevelEnum = [LogLevel]$script:LoggingDefaults.LogLevel
        return $levelEnum -ge $minLevelEnum
    }
    catch {
        # Default to allowing the message if parsing fails
        return $true
    }
}

# Main logging function
function Write-Log {
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [ValidateSet("INFO", "WARN", "ERROR", "DEBUG", "FATAL", "TRACE")]
        [string]$Level = "INFO",
        
        [Parameter(Mandatory=$false)]
        [string]$LogName,
        
        [Parameter(Mandatory=$false)]
        [string]$LogDirectory,
        
        [Parameter(Mandatory=$false)]
        [switch]$NoConsole,
        
        [Parameter(Mandatory=$false)]
        [switch]$NoFile,
        
        [Parameter(Mandatory=$false)]
        [switch]$NoTimestamp,
        
        [Parameter(Mandatory=$false)]
        [System.Windows.Forms.RichTextBox]$ConsoleOutput,
        
        [Parameter(Mandatory=$false)]
        [switch]$ForcePrint,
        
        [Parameter(Mandatory=$false)]
        [System.ConsoleColor]$ConsoleColor,
        
        [Parameter(Mandatory=$false)]
        [System.Drawing.Color]$RtbColor,
        
        [Parameter(Mandatory=$false)]
        [switch]$WriteToEventLog,
        
        [Parameter(Mandatory=$false)]
        [System.Diagnostics.EventLogEntryType]$EventLogEntryType = [System.Diagnostics.EventLogEntryType]::Information
    )
    
    # Skip message if it doesn't meet minimum level and not forced
    if (-not (Test-LogLevel -Level $Level) -and -not $ForcePrint) {
        return
    }
    
    try {
        # Determine log name (file name without extension) if not provided
        if (-not $LogName) {
            $LogName = Get-CallingScriptName
        }
        
        # Use provided directory or default
        $logDir = if ($LogDirectory) { $LogDirectory } else { $script:DefaultLogPath }
        
        # Format the timestamp
        $timestamp = ""
        if (-not $NoTimestamp -and $script:LoggingDefaults.UseTimestamp) {
            $timestamp = Get-Date -Format $script:LoggingDefaults.TimestampFormat
        }
        
        # Format the log message
        $formattedMessage = if ($timestamp) {
            "$timestamp [$Level] - $Message"
        } else {
            "[$Level] - $Message"
        }
        
        # Write to log file if enabled and not explicitly disabled for this message
        if ($script:LoggingDefaults.EnableFileLogging -and -not $NoFile) {
            try {
                # Construct log file path
                $logFilePath = Join-Path -Path $logDir -ChildPath "$LogName.log"
                
                # Create parent directory if it doesn't exist
                if (-not (Test-Path -Path $logDir)) {
                    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
                }
                
                # Write to file
                $formattedMessage | Add-Content -Path $logFilePath -ErrorAction Stop
            }
            catch {
                # Try writing to temp if original location fails
                try {
                    $fallbackPath = Join-Path -Path $env:TEMP -ChildPath "$LogName.log"
                    $formattedMessage | Add-Content -Path $fallbackPath -ErrorAction Stop
                }
                catch {
                    # If even that fails, we'll just continue without file logging
                }
            }
        }
        
        # Determine if we should write to console
        $shouldWriteConsole = $ForcePrint -or 
                             (-not $NoConsole) -and 
                             ($script:LoggingDefaults.ShowDebugOutput -or 
                              $Level -eq "ERROR" -or 
                              $Level -eq "FATAL" -or
                              $Level -eq "INFO" -or
                              $Level -eq "WARN" -or
                              ($Level -eq "DEBUG" -and $script:LoggingDefaults.ShowDebugOutput))
        
        # Write to host console
        if ($shouldWriteConsole) {
            # Determine console color
            $color = if ($ConsoleColor) {
                $ConsoleColor
            } else {
                $script:LoggingDefaults.DefaultColors[$Level]
            }
            
            # Write to console
            Write-Host $formattedMessage -ForegroundColor $color
        }
        
        # Write to UI console if provided
        if ($null -ne $ConsoleOutput -and -not $ConsoleOutput.IsDisposed) {
            # Determine color for rich text box
            $textColor = if ($RtbColor) {
                $RtbColor
            } else {
                $script:LoggingDefaults.DefaultRtbColors[$Level]
            }
            
            # Use Invoke if calling from a different thread
            if ($ConsoleOutput.InvokeRequired) {
                $ConsoleOutput.Invoke([Action]{
                    $currentColor = $ConsoleOutput.SelectionColor
                    $ConsoleOutput.SelectionColor = $textColor
                    $ConsoleOutput.AppendText("$formattedMessage`n")
                    $ConsoleOutput.SelectionColor = $currentColor
                    $ConsoleOutput.ScrollToCaret()
                })
            }
            else {
                $currentColor = $ConsoleOutput.SelectionColor
                $ConsoleOutput.SelectionColor = $textColor
                $ConsoleOutput.AppendText("$formattedMessage`n")
                $ConsoleOutput.SelectionColor = $currentColor
                $ConsoleOutput.ScrollToCaret()
            }
        }
        
        # Write to Windows Event Log if requested or if it's a FATAL error
        if ($WriteToEventLog -or $Level -eq "FATAL") {
            try {
                # Convert log level to event log entry type if not explicitly provided
                if (-not $PSBoundParameters.ContainsKey('EventLogEntryType')) {
                    $EventLogEntryType = switch ($Level) {
                        "ERROR" { [System.Diagnostics.EventLogEntryType]::Error }
                        "FATAL" { [System.Diagnostics.EventLogEntryType]::Error }
                        "WARN"  { [System.Diagnostics.EventLogEntryType]::Warning }
                        default { [System.Diagnostics.EventLogEntryType]::Information }
                    }
                }
                
                # Try to register the event source if it doesn't exist
                if (-not [System.Diagnostics.EventLog]::SourceExists($script:LoggingDefaults.EventLogSource)) {
                    try {
                        [System.Diagnostics.EventLog]::CreateEventSource(
                            $script:LoggingDefaults.EventLogSource, 
                            $script:LoggingDefaults.EventLogName
                        )
                    }
                    catch {
                        # Silently continue if we can't create the source (requires admin rights)
                    }
                }
                
                # Write to event log if source exists
                if ([System.Diagnostics.EventLog]::SourceExists($script:LoggingDefaults.EventLogSource)) {
                    [System.Diagnostics.EventLog]::WriteEntry(
                        $script:LoggingDefaults.EventLogSource,
                        $Message,
                        $EventLogEntryType,
                        1000  # Event ID
                    )
                }
            }
            catch {
                # Silently continue if event log writing fails
            }
        }
    }
    catch {
        # Last resort error handling
        try {
            Write-Warning "Failed to write to log: $Message - Error: $_"
        }
        catch {
            # If even that fails, we're out of options
        }
    }
}

# Convenience function aliases for different log levels
function Write-LogInfo {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "INFO"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    Write-Log @params
}

function Write-LogWarning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "WARN"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    Write-Log @params
}

function Write-LogError {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "ERROR"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    Write-Log @params
}

function Write-LogDebug {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "DEBUG"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    Write-Log @params
}

function Write-LogFatal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "FATAL"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    # Fatal always writes to event log by default
    Write-Log @params -WriteToEventLog
}

function Write-LogTrace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Message,
        
        [Parameter(ValueFromRemainingArguments=$true)]
        $RestArguments
    )
    
    $params = @{
        Message = $Message
        Level = "TRACE"
    }
    
    if ($RestArguments) {
        # Convert remaining arguments to a hashtable and merge
        $additionalParams = $PSBoundParameters
        $additionalParams.Remove("Message")
        foreach ($param in $additionalParams.Keys) {
            $params[$param] = $additionalParams[$param]
        }
    }
    
    Write-Log @params
}

# Helper function to clear old logs
function Clear-OldLogs {
    param (
        [Parameter(Mandatory=$false)]
        [string]$LogDirectory = $script:DefaultLogPath,
        
        [Parameter(Mandatory=$false)]
        [int]$DaysToKeep = 30,
        
        [Parameter(Mandatory=$false)]
        [string]$Filter = "*.log"
    )

    if (Test-Path $LogDirectory) {
        $cutoffDate = (Get-Date).AddDays(-$DaysToKeep)
        $oldLogs = Get-ChildItem -Path $LogDirectory -Filter $Filter | 
            Where-Object { $_.LastWriteTime -lt $cutoffDate }
            
        if ($oldLogs.Count -gt 0) {
            $oldLogs | Remove-Item -Force
            Write-Log "Removed $($oldLogs.Count) log files older than $DaysToKeep days" -Level INFO
            return $oldLogs.Count
        }
        else {
            Write-Log "No log files found older than $DaysToKeep days" -Level DEBUG
            return 0
        }
    }
    else {
        Write-Log "Log directory not found: $LogDirectory" -Level WARN
        return -1
    }
}

# Add backward compatibility for Write-ServerLog for existing scripts
function Write-ServerLog {
    param (
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [ValidateSet('Info', 'Warning', 'Error')]
        [string]$Level = 'Info',
        [string]$ServerName = ''
    )
    
    $logLevel = switch($Level) {
        'Info'    { 'INFO' }
        'Warning' { 'WARN' }
        'Error'   { 'ERROR' }
        default   { 'INFO' }
    }
    
    $logParams = @{
        Message = $Message
        Level = $logLevel
    }
    
    if ($ServerName) {
        $logParams.LogName = $ServerName
    }
    
    Write-Log @logParams
}

# Add backward compatibility for Write-DashboardLog for existing scripts
function Write-DashboardLog {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [Parameter()]
        [ValidateSet("INFO", "WARN", "ERROR", "DEBUG", "FATAL", "TRACE")]
        [string]$Level = "INFO",
        
        [Parameter()]
        [string]$LogFilePath,
        
        [Parameter()]
        [switch]$NoConsole,
        
        [Parameter()]
        [switch]$NoTimestamp,
        
        [Parameter()]
        [System.Windows.Forms.RichTextBox]$ConsoleOutput,
        
        [Parameter()]
        [switch]$ForcePrint,
        
        [Parameter()]
        [System.Drawing.Color]$Color
    )
    
    $logParams = @{
        Message = $Message
        Level = $Level
        NoConsole = $NoConsole
        NoTimestamp = $NoTimestamp
        ConsoleOutput = $ConsoleOutput
        ForcePrint = $ForcePrint
    }
    
    if ($LogFilePath) {
        $logParams.LogDirectory = [System.IO.Path]::GetDirectoryName($LogFilePath)
        $logParams.LogName = [System.IO.Path]::GetFileNameWithoutExtension($LogFilePath)
    }
    
    if ($Color) {
        $logParams.RtbColor = $Color
    }
    
    Write-Log @logParams
}

# Initialize with default settings when module is loaded
Initialize-Logging

# Export all public functions
Export-ModuleMember -Function Initialize-Logging, Write-Log, Write-LogInfo, Write-LogWarning, 
    Write-LogError, Write-LogDebug, Write-LogFatal, Write-LogTrace, Clear-OldLogs,
    Write-ServerLog, Write-DashboardLog
