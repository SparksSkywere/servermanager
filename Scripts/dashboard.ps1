# Set essential preferences and check for STA mode
$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -STA -File `"$($MyInvocation.MyCommand.Path)`"" -WindowStyle Normal
    exit
}

# Load required assemblies first to ensure types are available
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Centralized logging function
function Write-DashboardLog {
    param(
        [Parameter(Mandatory=$true)][string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR", "DEBUG", "FATAL", "TRACE")][string]$Level = "INFO",
        [string]$LogFilePath,
        [switch]$NoConsole,
        [switch]$NoTimestamp,
        [System.Windows.Forms.RichTextBox]$ConsoleOutput,
        [switch]$ForcePrint,
        [System.Drawing.Color]$Color
    )
    
    try {
        $LogFilePath = if ([string]::IsNullOrEmpty($LogFilePath)) { $script:LogPath } else { $LogFilePath }
        $logDir = Split-Path $LogFilePath -Parent
        if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }
        
        $timestamp = if (-not $NoTimestamp) { Get-Date -Format "yyyy-MM-dd HH:mm:ss" } else { "" }
        $formattedMessage = if ($NoTimestamp) { "[$Level] - $Message" } else { "$timestamp [$Level] - $Message" }
        
        try {
            $formattedMessage | Add-Content -Path $LogFilePath -ErrorAction Stop
        }
        catch {
            try {
                $logDir = Split-Path $LogFilePath -Parent
                if (-not (Test-Path $logDir)) { New-Item -Path $logDir -ItemType Directory -Force | Out-Null }
                $formattedMessage | Add-Content -Path $LogFilePath -ErrorAction Stop
            }
            catch {
                try {
                    $formattedMessage | Add-Content -Path (Join-Path $env:TEMP "dashboard_emergency.log") -ErrorAction Stop
                }
                catch { }
            }
        }
        
        $shouldWriteConsole = $ForcePrint -or $script:DebugLoggingEnabled -or $Level -in @("ERROR", "FATAL") -or
                             ($Level -eq "DEBUG" -and $script:debugMode)
        
        if ($shouldWriteConsole -and -not $NoConsole) {
            $consoleColor = switch ($Level) {
                "ERROR" { "Red" }
                "FATAL" { "DarkRed" }
                "WARN"  { "Yellow" }
                "DEBUG" { "Cyan" }
                "TRACE" { "Gray" }
                default { "White" }
            }
            Write-Host "[$Level] $Message" -ForegroundColor $consoleColor
        }
        
        if ($null -ne $ConsoleOutput -and -not $ConsoleOutput.IsDisposed) {
            $rtbColor = if ($Color) { $Color } else {
                switch ($Level) {
                    "ERROR" { [System.Drawing.Color]::Red }
                    "FATAL" { [System.Drawing.Color]::DarkRed }
                    "WARN"  { [System.Drawing.Color]::Orange }
                    "DEBUG" { [System.Drawing.Color]::DarkCyan }
                    "TRACE" { [System.Drawing.Color]::Gray }
                    default { [System.Drawing.Color]::White }
                }
            }
            
            if ($ConsoleOutput.InvokeRequired) {
                $ConsoleOutput.Invoke([Action]{
                    $ConsoleOutput.SelectionColor = $rtbColor
                    $ConsoleOutput.AppendText("$formattedMessage`n")
                    $ConsoleOutput.ScrollToCaret()
                })
            }
            else {
                $ConsoleOutput.SelectionColor = $rtbColor
                $ConsoleOutput.AppendText("$formattedMessage`n")
                $ConsoleOutput.ScrollToCaret()
            }
        }
        
        if ($Level -eq "FATAL") {
            try {
                if (-not [System.Diagnostics.EventLog]::SourceExists("ServerManager")) {
                    try { [System.Diagnostics.EventLog]::CreateEventSource("ServerManager", "Application") }
                    catch { }
                }
                if ([System.Diagnostics.EventLog]::SourceExists("ServerManager")) {
                    [System.Diagnostics.EventLog]::WriteEntry("ServerManager", $Message, [System.Diagnostics.EventLogEntryType]::Error, 1001)
                }
            }
            catch { }
        }
    }
    catch {
        try { Write-Warning "Failed to write to log: $Message - Error: $_" }
        catch { }
    }
}

# Initialize global variables
$script:Variables = @{
    previousNetworkStats = @{}
    previousNetworkTime = Get-Date
    webSocketClient = $null
    isWebSocketConnected = $false
    lastServerListUpdate = [DateTime]::MinValue
    lastFullUpdate = [DateTime]::MinValue
    DebugLoggingEnabled = $false
    defaultSteamPath = Join-Path $env:ProgramFiles "SteamCMD"
    jobSyncLock = New-Object System.Object
    offlineMode = $false
    formDisplayed = $false
    debugMode = $true
    verificationInProgress = $false
    networkAdapters = @()
    lastNetworkStats = @{}
    lastNetworkStatsTime = Get-Date
    systemInfo = @{}
    diskInfo = @()
    gpuInfo = $null
    systemRefreshInterval = 10
    webSocketErrorShown = $false
}

# Get base paths from registry consistently
$registryPath = $script:RegPath
if (-not (Test-Path $registryPath)) {
    throw "Server Manager registry path not found"
}

$serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
if (-not $serverManagerDir) {
    throw "Server Manager directory not found in registry"
}

# Get SteamCmd path from registry
try {
    $script:steamCmdPath = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).SteamCmdPath
    if (-not $script:steamCmdPath) {
        # This will be logged once LogPath is defined
    } else {
        # Validate the SteamCmd path exists
        if (Test-Path $script:steamCmdPath) {
        } else {
            # Replace hardcoded paths with better fallbacks
            $possiblePaths = @(
                (Join-Path $env:ProgramFiles "SteamCMD"),
                (Join-Path ${env:ProgramFiles(x86)} "SteamCMD"),
                (Join-Path $serverManagerDir "SteamCMD")
            )
            
            foreach ($path in $possiblePaths) {
                if (Test-Path (Join-Path $path "steamcmd.exe")) {
                    $script:steamCmdPath = $path
                    break
                }
            }
        }
    }
} catch {
    # Will log this after LogPath is defined
}

# Clean up path
$serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')

# Initialize essential script-scope paths
$script:Paths = @{
    Root = $serverManagerDir
    Logs = Join-Path $serverManagerDir "logs"
    Config = Join-Path $serverManagerDir "config"
    Temp = Join-Path $serverManagerDir "temp"
    Servers = Join-Path $serverManagerDir "servers"
    Modules = Join-Path $serverManagerDir "Modules"
}

# Set default install dir after paths are initialized using program files env variable
$script:defaultSteamPath = if ($script:steamCmdPath) { $script:steamCmdPath } else { Join-Path $env:ProgramFiles "SteamCMD" }
$script:defaultInstallDir = Join-Path $script:defaultSteamPath "steamapps\common"

# Ensure required directories exist
foreach ($path in $script:Paths.Values) {
    if (-not (Test-Path $path)) {
        New-Item -Path $path -ItemType Directory -Force | Out-Null
    }
}

# Ensure temp directory exists
if (-not (Test-Path $script:Paths.Temp)) {
    New-Item -Path $script:Paths.Temp -ItemType Directory -Force | Out-Null
}

# Define ready file paths
$script:ReadyFiles = @{
    WebServer = Join-Path $script:Paths.Temp "webserver.ready"
    WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
}

# Update log path to use the proper log directory - THIS IS THE SINGLE LOG FILE
$script:LogPath = Join-Path $script:Paths.Logs "dashboard.log"

# Now that LogPath is defined, we can log startup messages
Write-DashboardLog "Initialization starting..." -Level INFO

# Log any previous messages that were waiting for the log path to be defined
if (-not $script:steamCmdPath) {
    Write-DashboardLog "SteamCmd path not found in registry, server creation may fail" -Level WARN
} else {
    Write-DashboardLog "SteamCmd path loaded from registry: $($script:steamCmdPath)" -Level DEBUG
}

# Add Windows Forms assemblies before importing modules
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName PresentationFramework

# Define required modules
$moduleImports = @(
    "Common.psm1",
    "Network.psm1",
    "WebSocketServer.psm1",
    "ServerManager.psm1",
    "Authentication.psm1"
)

# Load all required modules - MOVED TO THE TOP
foreach ($module in $moduleImports) {
    $modulePath = Join-Path $script:Paths.Modules $module
    if (Test-Path $modulePath) {
        Import-Module $modulePath -Force -DisableNameChecking
        Write-DashboardLog "Successfully imported module: $module" -Level INFO
    } else {
        throw "Required module not found: $modulePath"
    }
}

# Add functions for job monitoring that can be reused
function Test-JobStatus {
    param (
        [Parameter(Mandatory=$true)]
        $Job,
        [Parameter(Mandatory=$true)]
        $ConsoleOutput,
        [Parameter(Mandatory=$true)]
        $StatusLabel
    )
    
    try {
        if ($null -eq $Job) {
            return @{
                Success = $false
                Message = "Job reference is null"
            }
        }
        
        $currentState = $Job.State
        if ($null -eq $currentState) {
            return @{
                Success = $false
                Message = "Job state is null"
            }
        }
        
        return @{
            Success = $true
            State = $currentState
        }
    }
    catch {
        $ConsoleOutput.AppendText("[ERROR] Failed to get job state: $($_.Exception.Message)`n")
        $StatusLabel.Text = "Job state error!"
        return @{
            Success = $false
            Message = $_.Exception.Message
        }
    }
}

function Receive-JobOutput {
    param (
        [Parameter(Mandatory=$true)]
        $Job,
        [Parameter(Mandatory=$true)]
        $ConsoleOutput,
        [switch]$KeepOutput
    )
    
    try {
        if ($null -eq $Job) {
            return $null
        }
        
        $output = $null
        if ($KeepOutput) {
            $output = $Job | Receive-Job -Keep -ErrorAction SilentlyContinue
        } else {
            $output = $Job | Receive-Job -ErrorAction SilentlyContinue
        }
        
        if ($null -ne $output -and $output.Count -gt 0) {
            foreach ($line in $output) {
                if ($null -ne $line) {
                    $ConsoleOutput.AppendText("$line`n")
                    
                    # Track verification progress
                    if ($line -match "Verifying installation" -or 
                        $line -match "\[\s*\d+%\]\s*Verifying" -or 
                        $line -match "Update state.*verifying" -or
                        $line -match "\[----\] Verifying installation") {
                        
                        $script:verificationInProgress = $true
                        
                        # Extract progress percentage if available
                        if ($line -match "Update state.*verifying install, progress:? (\d+)") {
                            $progressPct = $matches[1]
                            $StatusLabel.Text = "Verifying installation: $progressPct%"
                        } else {
                            $StatusLabel.Text = "Verifying installation..."
                        }
                    }
                    # Better detection for successful installation completion
                    elseif ($line -match "Success! App.*fully installed") {
                        $script:successDetected = $true
                        $script:verificationInProgress = $false
                        $StatusLabel.Text = "Installation complete!"
                        $ConsoleOutput.AppendText("[INFO] Detected successful installation completion`n")
                    }
                    elseif ($line -match "SteamCMD process completed with exit code: 0" -and $script:verificationInProgress) {
                        # Exit code 0 means success when we're in verification
                        $script:successDetected = $true
                        $script:verificationInProgress = $false
                        $StatusLabel.Text = "Installation complete!"
                        $ConsoleOutput.AppendText("[INFO] Installation completed successfully with exit code 0`n")
                    }
                    elseif ($line -eq "[RESULT-OBJECT-BEGIN]") {
                        # Definitive marker of completion
                        $script:successDetected = $true
                        $script:verificationInProgress = $false
                        $StatusLabel.Text = "Installation complete!"
                        $ConsoleOutput.AppendText("[INFO] Detected result object - installation completed`n")
                    }
                }
            }
            $ConsoleOutput.ScrollToCaret()
        }
        
        return $output
    }
    catch {
        $ConsoleOutput.AppendText("[WARN] Error receiving job output: $($_.Exception.Message)`n")
        return $null
    }
}

function Clean-Job {
    param (
        [Parameter(Mandatory=$true)]
        $Job,
        [Parameter(Mandatory=$false)]
        $JobInfo
    )
    
    try {
        if ($null -ne $Job) {
            Remove-Job -Job $Job -ErrorAction SilentlyContinue
        }
        if ($null -ne $JobInfo) {
            $JobInfo.Job = $null
            $JobInfo.IsJobCompleted = $true
        }
        return $true
    }
    catch {
        Write-DashboardLog "Failed to clean up job: $($_.Exception.Message)" -Level WARN
        return $false
    }
}

# Fix the Initialize-JobMonitorTimer function to properly handle the OnSuccess callback
function Initialize-JobMonitorTimer {
    param (
        [Parameter(Mandatory=$true)]
        $Timer,
        [Parameter(Mandatory=$true)]
        $JobInfo,
        [Parameter(Mandatory=$true)]
        $ConsoleOutput,
        [Parameter(Mandatory=$true)]
        $StatusLabel,
        [Parameter(Mandatory=$true)]
        $ProgressBar,
        [Parameter(Mandatory=$true)]
        $EnableButton,
        [scriptblock]$OnSuccess,
        [scriptblock]$OnFailure
    )
    
    # Create a completion flag for checking result in output
    $script:successDetected = $false
    
    # Store references to callback handlers in the JobInfo for better preservation
    $JobInfo.OnSuccess = $OnSuccess
    $JobInfo.OnFailure = $OnFailure
    
    $Timer.Add_Tick({
        try {
            # Early exit if jobInfo is null
            if ($null -eq $JobInfo) {
                $Timer.Stop()
                $ConsoleOutput.AppendText("[ERROR] Job tracking information has been lost`n")
                $StatusLabel.Text = "Job tracking error!"
                $EnableButton.Enabled = $true
                $ProgressBar.MarqueeAnimationSpeed = 0
                return
            }
            
            # Make sure the jobSyncLock exists
            if ($null -eq $script:jobSyncLock) {
                $script:jobSyncLock = New-Object System.Object
                $ConsoleOutput.AppendText("[WARN] Job sync lock was null, recreated`n")
            }
            
            # Use try/finally without monitor.enter to avoid potential null reference
            [bool]$lockTaken = $false
            try {
                # Make sure jobInfo is still not null before trying to lock
                if ($null -eq $JobInfo) {
                    $Timer.Stop()
                    $ConsoleOutput.AppendText("[ERROR] Job tracking information was lost while attempting to lock`n")
                    $StatusLabel.Text = "Job tracking error!"
                    $EnableButton.Enabled = $true
                    $ProgressBar.MarqueeAnimationSpeed = 0
                    return
                }
                
                # Add an extra null check on jobSyncLock before using it
                if ($null -eq $script:jobSyncLock) {
                    $script:jobSyncLock = New-Object System.Object
                    $ConsoleOutput.AppendText("[WARN] Job sync lock was null right before TryEnter, recreated`n")
                }
                
                # Try to enter the lock with a specific timeout and use a try-catch block for better error handling
                try {
                    if ($null -eq $script:jobSyncLock) {
                        $ConsoleOutput.AppendText("[ERROR] Cannot acquire lock: jobSyncLock is null`n")
                        return
                    }
                    
                    [System.Threading.Monitor]::TryEnter($script:jobSyncLock, 100, [ref]$lockTaken)
                }
                catch {
                    $ConsoleOutput.AppendText("[ERROR] Failed to acquire lock: $($_.Exception.Message)`n")
                    # Continue without lock as fallback
                    $lockTaken = $false
                }
                
                if (-not $lockTaken) {
                    # If we couldn't get the lock, just return and try again next time
                    return
                }
                
                # If job is already marked as completed, stop timer and return
                if ($null -ne $JobInfo.IsJobCompleted -and $JobInfo.IsJobCompleted) {
                    $Timer.Stop()
                    return
                }
                
                # Make a local copy of the job reference to use safely throughout this tick
                $localJobRef = $JobInfo.Job
                
                # Check for null job reference before proceeding
                if ($null -eq $localJobRef) {
                    $ConsoleOutput.AppendText("[INFO] Job reference is null - already processed or removed`n")
                    $Timer.Stop()
                    $EnableButton.Enabled = $true
                    $ProgressBar.MarqueeAnimationSpeed = 0
                    return
                }
                
                # Check job status with null checks
                $jobStatus = Test-JobStatus -Job $localJobRef -ConsoleOutput $ConsoleOutput -StatusLabel $StatusLabel
                if ($null -eq $jobStatus -or -not $jobStatus.Success) {
                    $Timer.Stop()
                    $StatusLabel.Text = "Job status error!"
                    $EnableButton.Enabled = $true
                    $ProgressBar.MarqueeAnimationSpeed = 0
                    return
                }
                
                # Check the current job output regardless of verification status - add null checks
                $jobOutput = $null
                try {
                    $jobOutput = $localJobRef | Receive-Job -Keep -ErrorAction SilentlyContinue
                } catch {
                    $ConsoleOutput.AppendText("[ERROR] Failed to receive job output: $($_.Exception.Message)`n")
                }
                
                $newOutput = $null
                try {
                    $newOutput = Receive-JobOutput -Job $localJobRef -ConsoleOutput $ConsoleOutput
                } catch {
                    $ConsoleOutput.AppendText("[ERROR] Failed in Receive-JobOutput: $($_.Exception.Message)`n")
                }
                
                # Look for success patterns in job output - more aggressive detection - with null check
                if ($null -ne $jobOutput) {
                    foreach ($line in $jobOutput) {
                        # Skip null lines
                        if ($null -eq $line) { continue }
                        
                        # Detect success patterns and mark for completion
                        if ($line -match "Success! App.*fully installed" -or 
                            $line -match "\[SUCCESS\] Configuration saved successfully" -or
                            $line -match "\[RESULT-OBJECT-BEGIN\]") {
                            
                            $script:successDetected = $true
                            $ConsoleOutput.AppendText("[INFO] Detected successful completion marker`n")
                            
                            # If in verification, mark it as complete
                            if ($script:verificationInProgress) {
                                $script:verificationInProgress = $false
                                $StatusLabel.Text = "Installation complete!"
                            }
                        }
                        
                        # Also look for RESULT-OBJECT-BEGIN/END blocks which indicate job completion
                        if ($line -eq "[RESULT-OBJECT-BEGIN]") {
                            $resultStartFound = $true
                            $ConsoleOutput.AppendText("[INFO] Found result object marker - installation completed`n")
                            $script:verificationInProgress = $false
                            $StatusLabel.Text = "Installation complete!"
                        }
                    }
                }
                
                # If success detected and still in verification, force completion
                if ($script:successDetected -and $script:verificationInProgress) {
                    $ConsoleOutput.AppendText("[INFO] Success detected but still in verification state - proceeding to completion`n")
                    $script:verificationInProgress = $false
                    $StatusLabel.Text = "Installation complete!"
                }
                
                # Special detection for process completion with successful exit code (0) - with null checks
                if ($null -ne $jobOutput -and $jobOutput -match "SteamCMD process completed with exit code: 0" -and $script:verificationInProgress) {
                    $ConsoleOutput.AppendText("[INFO] SteamCMD completed successfully - finishing verification`n")
                    $script:verificationInProgress = $false
                    $StatusLabel.Text = "Installation complete!"
                }
                
                # If we're still in verification but the job is completed, force it to finish
                if ($script:verificationInProgress -and $jobStatus.State -eq 'Completed') {
                    $ConsoleOutput.AppendText("[INFO] Job completed but still in verification state - forcing completion`n")
                    $script:verificationInProgress = $false
                    $StatusLabel.Text = "Installation complete!"
                }
                
                # We need to add a timeout for verification to prevent it getting stuck indefinitely
                if ($script:verificationInProgress -and $null -ne $JobInfo.VerificationStartTime) {
                    $verificationTimeout = 300  # 5 minutes timeout
                    $elapsedTime = [math]::Round(((Get-Date) - $JobInfo.VerificationStartTime).TotalSeconds)
                    
                    if ($elapsedTime -gt $verificationTimeout) {
                        $ConsoleOutput.AppendText("[WARN] Verification timed out after $elapsedTime seconds - forcing completion`n")
                        $script:verificationInProgress = $false
                        $StatusLabel.Text = "Installation complete (timeout)"
                    }
                }
                
                # If we're no longer in verification mode or the job has completed, process the results
                if ((-not $script:verificationInProgress) -and 
                    ($jobStatus.State -eq 'Completed' -or $script:successDetected)) {
                    
                    $ConsoleOutput.AppendText("[INFO] Processing job completion`n")
                    
                    # Mark job as completed to prevent multiple processing attempts
                    $JobInfo.IsJobCompleted = $true
                    
                    # Get the final job result with comprehensive error handling
                    try {
                        # First make sure the job reference is still valid
                        if ($null -eq $localJobRef) {
                            $ConsoleOutput.AppendText("[WARN] Job reference is null, but completion was detected`n")
                            # Create a synthetic success result since we know we have completion markers
                            $result = @{
                                Success = $true
                                Message = "Server created successfully (result inferred from completed state)"
                            }
                        }
                        else {
                            # Try to receive job output safely
                            try {
                                $jobOutput = $localJobRef | Receive-Job -Keep -ErrorAction Stop
                                $ConsoleOutput.AppendText("[INFO] Successfully received job output`n")
                            }
                            catch {
                                $ConsoleOutput.AppendText("[WARN] Error receiving job output: $($_.Exception.Message)`n")
                                # Continue with whatever output we may already have
                                $jobOutput = $null
                            }
                            
                            # Search for result markers and process output
                            $result = $null
                            $resultFound = $false
                            
                            # Extract result from JSON block if present
                            $resultStartIdx = -1
                            $resultEndIdx = -1
                            
                            if ($null -ne $jobOutput -and ($jobOutput -is [array] -or $jobOutput -is [System.Collections.ICollection])) {
                                for ($i = 0; $i -lt $jobOutput.Count; $i++) {
                                    if ($null -eq $jobOutput[$i]) { continue }
                                    if ($jobOutput[$i] -eq "[RESULT-OBJECT-BEGIN]") {
                                        $resultStartIdx = $i
                                    }
                                    if ($jobOutput[$i] -eq "[RESULT-OBJECT-END]") {
                                        $resultEndIdx = $i
                                        break
                                    }
                                }
                                
                                if ($resultStartIdx -ge 0 -and $resultEndIdx -gt $resultStartIdx) {
                                    # Extract the JSON result between markers
                                    $jsonText = $jobOutput[($resultStartIdx+1)..($resultEndIdx-1)] -join "`n"
                                    try {
                                        $result = $jsonText | ConvertFrom-Json
                                        $resultFound = $true
                                        $ConsoleOutput.AppendText("[INFO] JSON result parsed successfully`n")
                                    }
                                    catch {
                                        $ConsoleOutput.AppendText("[ERROR] Failed to parse JSON result: $($_.Exception.Message)`n")
                                        # Continue with alternative result extraction
                                    }
                                }
                            }
                            
                            # If no JSON result found, look for success based on output patterns
                            if (-not $resultFound) {
                                if ($script:successDetected) {
                                    # Create a success result since we detected success markers
                                    $ConsoleOutput.AppendText("[INFO] Creating success result based on output markers`n")
                                    $result = @{
                                        Success = $true
                                        Message = "Server created successfully"
                                    }
                                }
                                else {
                                    # Try to find any hashtable or PSObject that might be our result
                                    $possibleResult = $null
                                    if ($null -ne $jobOutput) {
                                        try {
                                            $possibleResult = $jobOutput | Where-Object { 
                                                $null -ne $_ -and
                                                ($_ -is [hashtable] -or $_ -is [PSCustomObject]) -and 
                                                (($_ | Get-Member -Name "Success" -MemberType NoteProperty -ErrorAction SilentlyContinue) -or 
                                                 ($_ -is [hashtable] -and $_.ContainsKey("Success")))
                                            } | Select-Object -Last 1
                                        }
                                        catch {
                                            $ConsoleOutput.AppendText("[WARN] Error looking for result object: $($_.Exception.Message)`n")
                                        }
                                    }
                                    
                                    if ($possibleResult) {
                                        $ConsoleOutput.AppendText("[INFO] Found result object in job output`n")
                                        $result = $possibleResult
                                    }
                                    else {
                                        # If SteamCMD was successful (exit code 0), create a success result
                                        if ($null -ne $jobOutput -and 
                                            ($jobOutput -match "SteamCMD process completed with exit code: 0" -or 
                                             $jobOutput -contains "SteamCMD process completed with exit code: 0")) {
                                            $ConsoleOutput.AppendText("[INFO] Creating success result based on exit code 0`n")
                                            $result = @{
                                                Success = $true
                                                Message = "Server created successfully (based on exit code)"
                                            }
                                        }
                                        else {
                                            # Create a basic result as last resort
                                            $ConsoleOutput.AppendText("[INFO] Creating default success result`n")
                                            $result = @{
                                                Success = $true
                                                Message = "Job completed successfully"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        # First check if we need to restore the timer reference
                        if ($null -eq $Timer -and $null -ne $script:jobInfo.Timer) {
                            $ConsoleOutput.AppendText("[INFO] Restoring timer reference from script scope`n")
                            $timerFromScriptScope = $script:jobInfo.Timer
                            # Use the script scope timer since the local one is null
                            $timerFromScriptScope.Stop()
                        }
                        else {
                            # Store a reference to the timer before potentially losing it
                            $timerRef = $Timer
                            
                            # Stop timer BEFORE removing job to prevent race condition
                            # Test if Timer is still available
                            if ($null -ne $timerRef) {
                                $ConsoleOutput.AppendText("[INFO] Stopping timer`n")
                                $timerRef.Stop()
                            }
                            else {
                                $ConsoleOutput.AppendText("[WARN] Timer object is null, can't stop it`n")
                                # Try to use the script-level timer as fallback
                                if ($null -ne $script:jobInfo -and $null -ne $script:jobInfo.Timer) {
                                    $ConsoleOutput.AppendText("[INFO] Using script-level timer as fallback`n")
                                    $script:jobInfo.Timer.Stop()
                                }
                            }
                        }
                        
                        # Update progress bar if it's available
                        if ($null -ne $ProgressBar) {
                            $ProgressBar.MarqueeAnimationSpeed = 0
                        }
                        
                        # Clean up the job - but first check if it's not null
                        if ($null -ne $localJobRef) {
                            $ConsoleOutput.AppendText("[INFO] Cleaning up job resources`n")
                            Clean-Job -Job $localJobRef -JobInfo $JobInfo
                        }
                        
                        # Update UI with success status
                        if ($null -ne $StatusLabel) {
                            $StatusLabel.Text = "Installation complete!"
                        }
                        
                        # Enable the button if it exists
                        if ($null -ne $EnableButton) {
                            $EnableButton.Enabled = $true
                        }
                        
                        # Call success handler if provided
                        # FIXED: First check JobInfo.OnSuccess, then fall back to the parameter
                        $successHandler = if ($null -ne $JobInfo.OnSuccess) { $JobInfo.OnSuccess } else { $OnSuccess }
                        
                        if ($null -ne $successHandler) {
                            $ConsoleOutput.AppendText("[INFO] Calling OnSuccess handler`n")
                            try {
                                # Explicitly invoke the script block with the result parameter
                                & $successHandler $result
                            }
                            catch {
                                $ConsoleOutput.AppendText("[ERROR] Error in OnSuccess handler: $($_.Exception.Message)`n")
                                $ConsoleOutput.AppendText("[ERROR] Stack trace: $($_.ScriptStackTrace)`n")
                            }
                        }
                        else {
                            $ConsoleOutput.AppendText("[INFO] No OnSuccess handler provided`n")
                        }
                    }
                    catch {
                        $ConsoleOutput.AppendText("[ERROR] Failed to get final job result: $($_.Exception.Message)`n")
                        $ConsoleOutput.AppendText("[ERROR] Stack trace: $($_.ScriptStackTrace)`n")
                        
                        # Safely stop timer with enhanced error handling
                        try {
                            if ($null -ne $Timer) {
                                $Timer.Stop()
                            }
                            elseif ($null -ne $script:jobInfo -and $null -ne $script:jobInfo.Timer) {
                                # Fallback to script scope timer
                                $script:jobInfo.Timer.Stop()
                            }
                        }
                        catch {
                            $ConsoleOutput.AppendText("[ERROR] Failed to stop timer: $($_.Exception.Message)`n")
                        }
                        
                        # Update UI safely
                        if ($null -ne $ProgressBar) {
                            $ProgressBar.MarqueeAnimationSpeed = 0
                        }
                        
                        if ($null -ne $StatusLabel) {
                            $StatusLabel.Text = "Error processing results!"
                        }
                        
                        if ($null -ne $EnableButton) {
                            $EnableButton.Enabled = $true
                        }
                        
                        # Still try to clean up job resources
                        if ($null -ne $localJobRef -and $null -ne $JobInfo) {
                            Clean-Job -Job $localJobRef -JobInfo $JobInfo
                        }
                        
                        # Call failure handler with the error if available
                        if ($null -ne $OnFailure) {
                            try {
                                & $OnFailure $_
                            }
                            catch {
                                $ConsoleOutput.AppendText("[ERROR] Error in OnFailure handler: $($_.Exception.Message)`n")
                            }
                        }
                    }
                }
                # Handle job failed state
                elseif ($jobStatus.State -eq 'Failed') {
                    $Timer.Stop()
                    $ProgressBar.MarqueeAnimationSpeed = 0
                    $StatusLabel.Text = "Job failed!"
                    $EnableButton.Enabled = $true
                    $script:verificationInProgress = $false
                    
                    # Get error details if available
                    try {
                        if ($null -ne $localJobRef.ChildJobs -and $localJobRef.ChildJobs.Count -gt 0) {
                            $jobError = $localJobRef.ChildJobs[0].Error
                            if ($jobError) {
                                $ConsoleOutput.AppendText("[ERROR] $jobError`n")
                            }
                        }
                    }
                    catch {
                        $ConsoleOutput.AppendText("[ERROR] Could not retrieve job error details`n")
                    }
                    
                    # Clean up the job
                    Clean-Job -Job $localJobRef -JobInfo $JobInfo
                    
                    if ($null -ne $OnFailure) {
                        & $OnFailure "Job failed"
                    }
                }
            }
            finally {
                # Only exit the lock if we actually entered it AND jobSyncLock isn't null
                if ($lockTaken -and $null -ne $script:jobSyncLock) {
                    try {
                        [System.Threading.Monitor]::Exit($script:jobSyncLock)
                    }
                    catch {
                        $ConsoleOutput.AppendText("[WARN] Error exiting lock: $($_.Exception.Message)`n")
                        # Can't do much if Exit fails, but at least log it
                    }
                }
            }
        }
        catch {
            Write-DashboardLog "Error in job monitoring timer: $($_.Exception.Message)" -Level ERROR
            if ($_.ScriptStackTrace) {
                Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level DEBUG
            }
            
            # Store the error for debugging
            $script:lastJobError = $_
            
            # Stop timer and release resources - Add null checks before accessing objects
            try {
                # First try with local timer
                if ($null -ne $Timer) {
                    $Timer.Stop()
                }
                # Fallback to script scope timer
                elseif ($null -ne $script:jobInfo -and $null -ne $script:jobInfo.Timer) {
                    $script:jobInfo.Timer.Stop()
                }
                
                if ($null -ne $ProgressBar) {
                    $ProgressBar.MarqueeAnimationSpeed = 0
                }
                
                if ($null -ne $StatusLabel) {
                    $StatusLabel.Text = "Error monitoring job!"
                }
                
                if ($null -ne $EnableButton) {
                    $EnableButton.Enabled = $true
                }
                
                $script:verificationInProgress = $false
            } 
            catch {
                # Log error but don't throw to avoid endless loop
                Write-DashboardLog "Error during cleanup after timer error: $($_.Exception.Message)" -Level ERROR
            }
            
            # Clean up job resources with proper null checks
            try {
                if ($null -ne $JobInfo -and $null -ne $JobInfo.Job) {
                    Clean-Job -Job $JobInfo.Job -JobInfo $JobInfo
                }
            }
            catch {
                # Just log but ignore any errors during cleanup
                if ($null -ne $ConsoleOutput) {
                    $ConsoleOutput.AppendText("[WARN] Error during job cleanup: $($_.Exception.Message)`n")
                }
                Write-DashboardLog "Error during job cleanup: $($_.Exception.Message)" -Level WARN
            }
            
            if ($null -ne $OnFailure) {
                try {
                    & $OnFailure $_
                }
                catch {
                    Write-DashboardLog "Error calling OnFailure handler: $($_.Exception.Message)" -Level ERROR
                }
            }
        }
    })
    
    # Ensure the timer reference is stored in both the script scope and the job info
    $script:jobInfo.Timer = $Timer
    
    return $Timer
}

# Console window handling function (unified version)
function Show-Console {
    param ([Switch]$Show, [Switch]$Hide)
    if (-not ("Console.Window" -as [type])) {
        Add-Type -Name Window -Namespace Console -MemberDefinition '
        [DllImport("Kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        '
    }
    $consolePtr = [Console.Window]::GetConsoleWindow()
    $nCmdShow = if ($Show) { 5 } elseif ($Hide) { 0 } else { return }
    [Console.Window]::ShowWindow($consolePtr, $nCmdShow) | Out-Null
    $script:DebugLoggingEnabled = $Show.IsPresent
    Write-DashboardLog "Console visibility set to: $($Show.IsPresent)" -Level DEBUG
}

# Hide Console
Show-Console -Hide

# Add verification before WebSocket connection
function Test-WebSocketServer {
    param (
        [int]$TimeoutSeconds = 5,
        [switch]$Silent
    )
    
    if (-not $Silent) {
        Write-DashboardLog "Checking server connection..." -Level DEBUG
    }
    
    # Define the ports to check
    $webServerPort = 8080
    $webSocketPort = 8081
    $serverIsRunning = $false
    $limitedConnection = $false
    $connectionDetails = ""
    
    # Check for WebSocket ready file first to get correct ports
    try {
        $tempDir = $script:Paths.Temp
        $wsReadyFile = $script:ReadyFiles.WebSocket
        $webReadyFile = $script:ReadyFiles.WebServer
        
        # If WebSocket ready file exists, get the actual port
        if (Test-Path $wsReadyFile) {
            try {
                $wsConfig = Get-Content $wsReadyFile -Raw | ConvertFrom-Json
                if ($wsConfig.port) {
                    $webSocketPort = $wsConfig.port
                    if (-not $Silent) {
                        Write-DashboardLog "WebSocket ready file found, using port: $webSocketPort" -Level DEBUG
                    }
                }
            }
            catch {
                if (-not $Silent) {
                    Write-DashboardLog "Failed to parse WebSocket ready file: $($_.Exception.Message)" -Level DEBUG
                }
            }
        }
        
        # If web server ready file exists, get the actual port
        if (Test-Path $webReadyFile) {
            try {
                $webConfig = Get-Content $webReadyFile -Raw | ConvertFrom-Json
                if ($webConfig.port) {
                    $webServerPort = $webConfig.port
                    if (-not $Silent) {
                        Write-DashboardLog "Web server ready file found, using port: $webServerPort" -Level DEBUG
                    }
                }
            }
            catch {
                if (-not $Silent) {
                    Write-DashboardLog "Failed to parse web server ready file: $($_.Exception.Message)" -Level DEBUG
                }
            }
        }
    }
    catch {
        if (-not $Silent) {
            Write-DashboardLog "Error checking ready files: $($_.Exception.Message)" -Level DEBUG
        }
    }
    
    # Try the TCP connection approach first as it's more reliable
    try {
        # Try WebSocket port first (usually more reliable)
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        try {
            # Use BeginConnect with a shorter timeout (1 second)
            $connectionResult = $tcpClient.BeginConnect("localhost", $webSocketPort, $null, $null)
            $wsSuccess = $connectionResult.AsyncWaitHandle.WaitOne(1000, $false)
            
            if ($wsSuccess) {
                try {
                    $tcpClient.EndConnect($connectionResult)
                    $serverIsRunning = $true
                    $limitedConnection = $true
                    $connectionDetails = "WebSocket Connection OK"
                    
                    if (-not $Silent) {
                        Write-DashboardLog "WebSocket port $webSocketPort is accessible" -Level DEBUG
                    }
                }
                catch {
                    if (-not $Silent) {
                        Write-DashboardLog "WebSocket connection attempt failed: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
        }
        finally {
            $tcpClient.Close()
        }
        
        # Now try HTTP port 
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        try {
            $connectionResult = $tcpClient.BeginConnect("localhost", $webServerPort, $null, $null)
            $httpSuccess = $connectionResult.AsyncWaitHandle.WaitOne(1000, $false)
            
            if ($httpSuccess) {
                try {
                    $tcpClient.EndConnect($connectionResult)
                    $serverIsRunning = $true
                    
                    if ($limitedConnection) {
                        # Both WebSocket and HTTP ports are accessible
                        $connectionDetails = "HTTP + WebSocket OK"
                        $limitedConnection = $false
                    } else {
                        # Only HTTP port is accessible
                        $connectionDetails = "HTTP Connection OK"
                    }
                    
                    if (-not $Silent) {
                        Write-DashboardLog "HTTP port $webServerPort is accessible" -Level DEBUG
                    }
                }
                catch {
                    if (-not $Silent) {
                        Write-DashboardLog "HTTP connection attempt failed: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
        }
        finally {
            $tcpClient.Close()
        }
    }
    catch {
        if (-not $Silent) {
            Write-DashboardLog "TCP connection check failed: $($_.Exception.Message)" -Level DEBUG
        }
        # Continue to HTTP request check
    }
    
    # If TCP checks didn't succeed, try the HTTP request with stricter timeout
    if (-not $serverIsRunning) {
        try {
            # Use HttpWebRequest with a very short timeout
            $url = "http://localhost:$webServerPort/health"
            $request = [System.Net.HttpWebRequest]::Create($url)
            $request.Timeout = 1000  # 1 second timeout
            $request.ReadWriteTimeout = 1000
            $request.Method = "GET"
            
            try {
                # Get response with timeout protection
                $response = $request.GetResponse()
                
                try {
                    $stream = $response.GetResponseStream()
                    $reader = New-Object System.IO.StreamReader($stream)
                    $content = $reader.ReadToEnd()
                    
                    if ($content -match '"status":"ok"') {
                        $serverIsRunning = $true
                        $connectionDetails = "HTTP API OK"
                        
                        if (-not $Silent) {
                            Write-DashboardLog "HTTP health check successful" -Level DEBUG
                        }
                    }
                }
                finally {
                    if ($reader) { $reader.Close() }
                    if ($response) { $response.Close() }
                }
            }
            catch [System.Net.WebException] {
                if (-not $Silent) {
                    Write-DashboardLog "Web request failed: $($_.Exception.Message)" -Level DEBUG
                }
                # Continue to the next check
            }
        }
        catch {
            if (-not $Silent) {
                Write-DashboardLog "HTTP health check failed: $($_.Exception.Message)" -Level DEBUG
            }
            # Continue to the next check
        }
    }
    
    # Final check: Look for specific server processes as a last resort
    if (-not $serverIsRunning) {
        try {
            # Check for processes with PIDs from PID files
            $pidFileHttp = Join-Path $script:Paths.Temp "webserver.pid"
            $pidFileWs = Join-Path $script:Paths.Temp "websocket.pid" 
            
            $httpPid = $null
            $wsPid = $null
            
            if (Test-Path $pidFileHttp) {
                try {
                    $pidContent = Get-Content $pidFileHttp -Raw | ConvertFrom-Json
                    $httpPid = $pidContent.ProcessId
                }
                catch {
                    if (-not $Silent) {
                        Write-DashboardLog "Failed to read HTTP PID file: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
            
            if (Test-Path $pidFileWs) {
                try {
                    $pidContent = Get-Content $pidFileWs -Raw | ConvertFrom-Json
                    $wsPid = $pidContent.ProcessId
                }
                catch {
                    if (-not $Silent) {
                        Write-DashboardLog "Failed to read WebSocket PID file: $($_.Exception.Message)" -Level DEBUG
                    }
                }
            }
            
            # Check if processes are running
            $httpRunning = $false
            $wsRunning = $false
            
            if ($httpPid) {
                try {
                    $process = Get-Process -Id $httpPid -ErrorAction SilentlyContinue
                    if ($process -and -not $process.HasExited) {
                        $httpRunning = $true
                    }
                }
                catch {
                    # Process not found, ignore error
                }
            }
            
            if ($wsPid) {
                try {
                    $process = Get-Process -Id $wsPid -ErrorAction SilentlyContinue
                    if ($process -and -not $process.HasExited) {
                        $wsRunning = $true
                    }
                }
                catch {
                    # Process not found, ignore error
                }
            }
            
            # If any of the processes are running, mark as running
            if ($httpRunning -or $wsRunning) {
                $serverIsRunning = $true
                $limitedConnection = $true
                
                $connectionDetails = if ($httpRunning -and $wsRunning) {
                    "Processes Running (Both)"
                } elseif ($httpRunning) {
                    "HTTP Process Running"
                } else {
                    "WebSocket Process Running"
                }
                
                if (-not $Silent) {
                    Write-DashboardLog "Server processes found running: HTTP=$httpRunning, WebSocket=$wsRunning" -Level DEBUG
                }
            }
        }
        catch {
            if (-not $Silent) {
                Write-DashboardLog "Process check failed: $($_.Exception.Message)" -Level DEBUG
            }
        }
    }
    
    if (-not $Silent) {
        Write-DashboardLog "Server connection status: Running=$serverIsRunning, Details=$connectionDetails" -Level DEBUG
    }
    
    # Return true if WebSocket server is available
    return $serverIsRunning
}

# Initialize performance counter
try {
    $script:cpuCounter = New-Object System.Diagnostics.PerformanceCounter("Processor", "% Processor Time", "_Total")
    $script:cpuCounter.NextValue() # First call to initialize
} catch {
    Write-DashboardLog "Failed to initialize CPU counter: $($_.Exception.Message)" -Level ERROR
    $script:cpuCounter = $null
}

# Add credential handling functions
function Get-SecureCredentials {
    param (
        [Parameter(Mandatory=$true)][string]$credentialName,
        [string]$keyFile = (Join-Path $env:ProgramData "ServerManager\encryption.key")
    )
    try {
        if (-not (Test-Path $keyFile)) {
            Write-DashboardLog "Encryption key not found at: $keyFile" -Level WARN
            return $null
        }

        $key = Get-Content $keyFile -Encoding Byte -ErrorAction Stop
        if ($null -eq $key -or $key.Length -eq 0) {
            Write-DashboardLog "Encryption key is empty or corrupted" -Level ERROR
            return $null
        }

        $credPath = Join-Path $env:ProgramData "ServerManager\Credentials"
        $credFile = Join-Path $credPath "$credentialName.cred"
        
        if (Test-Path $credFile) {
            try {
                $encrypted = Get-Content $credFile -ErrorAction Stop | ConvertTo-SecureString -Key $key -ErrorAction Stop
                $cred = [PSCredential]::new("steam", $encrypted)
                Write-DashboardLog "Successfully retrieved credentials for: $credentialName" -Level DEBUG
                return $cred
            }
            catch {
                Write-DashboardLog "Failed to decrypt credential file: $($_.Exception.Message)" -Level ERROR
                return $null
            }
        }
        else {
            Write-DashboardLog "No credential file found for: $credentialName" -Level DEBUG
            return $null
        }
    }
    catch {
        Write-DashboardLog "Failed to get secure credentials: $($_.Exception.Message)" -Level ERROR
        if ($_.ScriptStackTrace) {
            Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level DEBUG
        }
        return $null
    }
}

function Save-SecureCredentials {
    param (
        [Parameter(Mandatory=$true)][string]$credentialName,
        [Parameter(Mandatory=$true)][SecureString]$password,
        [string]$keyFile = (Join-Path $env:ProgramData "ServerManager\encryption.key"),
        [switch]$Force
    )
    try {
        if (-not (Test-Path $keyFile)) {
            # Try to create encryption key if it doesn't exist
            if ($Force) {
                try {
                    $keyDir = Split-Path $keyFile -Parent
                    if (-not (Test-Path $keyDir)) {
                        New-Item -Path $keyDir -ItemType Directory -Force -ErrorAction Stop | Out-Null
                    }
                    
                    # Generate a new random key
                    $newKey = New-Object Byte[] 32
                    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
                    $rng.GetBytes($newKey)
                    $newKey | Set-Content $keyFile -Encoding Byte -ErrorAction Stop
                    Write-DashboardLog "Created new encryption key at: $keyFile" -Level INFO
                    $key = $newKey
                }
                catch {
                    Write-DashboardLog "Failed to create encryption key: $($_.Exception.Message)" -Level ERROR
                    return $false
                }
            }
            else {
                Write-DashboardLog "Encryption key not found and -Force not specified" -Level ERROR
                return $false
            }
        }
        else {
            # Read existing key
            $key = Get-Content $keyFile -Encoding Byte -ErrorAction Stop
        }

        # Validate key
        if ($null -eq $key -or $key.Length -eq 0) {
            Write-DashboardLog "Encryption key is empty or corrupted" -Level ERROR
            return $false
        }

        # Create credentials directory if needed
        $credPath = Join-Path $env:ProgramData "ServerManager\Credentials"
        if (-not (Test-Path $credPath)) {
            New-Item -Path $credPath -ItemType Directory -Force -ErrorAction Stop | Out-Null
            Write-DashboardLog "Created credentials directory: $credPath" -Level DEBUG
        }

        # Save encrypted credentials
        $credFile = Join-Path $credPath "$credentialName.cred"
        $password | ConvertFrom-SecureString -Key $key | Set-Content $credFile -ErrorAction Stop
        Write-DashboardLog "Credentials saved successfully for: $credentialName" -Level INFO
        return $true
    }
    catch {
        Write-DashboardLog "Failed to save secure credentials: $($_.Exception.Message)" -Level ERROR
        if ($_.ScriptStackTrace) {
            Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level DEBUG
        }
        return $false
    }
}

# Establish connection to the websocket server
function Connect-WebSocketServer {
    param (
        [int]$TimeoutSeconds = 5,
        [switch]$Silent
    )
    
    if (-not $Silent) {
        Write-DashboardLog "Attempting to establish WebSocket connection..." -Level INFO
    }
    
    try {
        # First check if server is available using our test function
        if (-not (Test-WebSocketServer -TimeoutSeconds $TimeoutSeconds -Silent:$Silent)) {
            if (-not $Silent) {
                Write-DashboardLog "WebSocket server not available" -Level WARN
            }
            return $false
        }
        
        # Get port from ready file
        $webSocketPort = 8081  # Default port
        $wsReadyFile = $script:ReadyFiles.WebSocket
        
        if (Test-Path $wsReadyFile) {
            try {
                $wsConfig = Get-Content $wsReadyFile -Raw | ConvertFrom-Json
                if ($wsConfig.port) {
                    $webSocketPort = $wsConfig.port
                    if (-not $Silent) {
                        Write-DashboardLog "Using WebSocket port from ready file: $webSocketPort" -Level DEBUG
                    }
                }
            } catch {
                if (-not $Silent) {
                    Write-DashboardLog "Error reading WebSocket port from ready file: $_" -Level WARN
                }
            }
        }
        
        # Initialize WebSocket client
        $uri = New-Object System.Uri("ws://localhost:$webSocketPort/ws")
        $client = New-Object System.Net.WebSockets.ClientWebSocket
        $cts = New-Object System.Threading.CancellationTokenSource
        $cts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
        
        # Connect with timeout
        try {
            $connectionTask = $client.ConnectAsync($uri, $cts.Token)
            
            # Wait for connection or timeout
            $connectionTask.Wait($cts.Token)
            if ($connectionTask.IsCompleted -and -not $connectionTask.IsFaulted) {
                $script:webSocketClient = $client
                $script:isWebSocketConnected = $true
                if (-not $Silent) {
                    Write-DashboardLog "WebSocket connection established successfully" -Level INFO
                }
                return $true
            }
        } catch {
            if (-not $Silent) {
                Write-DashboardLog "Error connecting to WebSocket: $_" -Level ERROR
            }
            if ($client) {
                $client.Dispose()
            }
            $script:isWebSocketConnected = $false
            return $false
        }
    } catch {
        if (-not $Silent) {
            Write-DashboardLog "Failed to initialize WebSocket connection: $_" -Level ERROR
        }
        $script:isWebSocketConnected = $false
        return $false
    }
    
    $script:isWebSocketConnected = $false
    return $false
}


# Job script block for server installation - fixing the steamCmdPath issue and null result handling
$script:jobScriptBlock = {
    param($name, $appId, $installDir, $serverManagerDir, $credentials, $steamCmdPath)
    
    $output = New-Object System.Text.StringBuilder
    $errorOutput = $null
    $process = $null
    
    try {
        Write-Output "[DEBUG] Job started with parameters:"
        Write-Output "[DEBUG] - Name: $name"
        Write-Output "[DEBUG] - AppID: $appId"
        Write-Output "[DEBUG] - Install Directory: $installDir"
        Write-Output "[DEBUG] - Server Manager Directory: $serverManagerDir"
        Write-Output "[DEBUG] - SteamCmd Path: $steamCmdPath"
        
        # Verify SteamCmd path directly instead of trying to read from registry again
        Write-Output "[DEBUG] Checking SteamCmd path: $steamCmdPath"
        if ([string]::IsNullOrEmpty($steamCmdPath)) {
            throw "SteamCmd path is empty or null"
        }
        
        $steamCmdExe = Join-Path $steamCmdPath "steamcmd.exe"
        Write-Output "[DEBUG] SteamCmd executable path: $steamCmdExe"
        
        if (-not (Test-Path $steamCmdExe)) {
            throw "SteamCMD executable not found at: $steamCmdExe"
        }
        
        # If installDir is empty, create a directory directly in steamapps/common folder
        # Important fix to avoid nested paths
        if ([string]::IsNullOrWhiteSpace($installDir)) {
            # Create a path in steamapps/common without duplicating the structure
            $steamAppsCommon = Join-Path $steamCmdPath "steamapps\common"
            $installDir = Join-Path $steamAppsCommon $name
            Write-Output "[INFO] Using default installation path: $installDir"
            
            # Create the default directory if it doesn't exist
            if (-not (Test-Path $installDir)) {
                Write-Output "[INFO] Creating default install directory: $installDir"
                New-Item -ItemType Directory -Path $installDir -Force | Out-Null
            }
        }
        
        # Only create directory if path is specified and doesn't exist
        elseif (-not (Test-Path $installDir)) {
            Write-Output "[INFO] Creating custom install directory: $installDir"
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
        }

        Write-Output "[INFO] Starting server installation..."
        
        # Build SteamCMD command
        $steamCmdArgs = if ($credentials.Anonymous) {
            "+login anonymous"
        } else {
            "+login `"$($credentials.Username)`" `"$($credentials.Password)`""
        }

        $steamCmdArgs += " +force_install_dir `"$installDir`""
        $steamCmdArgs += " +app_update $appId validate +quit"
        
        Write-Output "[INFO] Running SteamCMD with command: $steamCmdExe $steamCmdArgs"

        # Start SteamCMD process
        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $steamCmdExe
        $pinfo.Arguments = $steamCmdArgs
        $pinfo.UseShellExecute = $false
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true
        $pinfo.RedirectStandardInput = $false
        $pinfo.CreateNoWindow = $true

        Write-Output "[DEBUG] Created process info object"
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $pinfo
        
        Write-Output "[INFO] Starting SteamCMD process..."
        try {
            $started = $process.Start()
            
            if (-not $started) {
                throw "Process.Start() returned false"
            }
            Write-Output "[DEBUG] Process started successfully: PID $($process.Id)"
        }
        catch {
            throw "Failed to start SteamCMD process: $($_.Exception.Message)"
        }

        # Capture output in real-time
        Write-Output "[DEBUG] Beginning output capture"
        $installSuccessDetected = $false
        
        while (!$process.StandardOutput.EndOfStream) {
            $line = $process.StandardOutput.ReadLine()
            $output.AppendLine($line)
            Write-Output $line
            
            # Detect success line as it comes through in real-time
            if ($line -match "Success! App.*fully installed") {
                $installSuccessDetected = $true
                Write-Output "[INFO] Detected successful installation completion"
            }
        }

        $errorOutput = $process.StandardError.ReadToEnd()
        Write-Output "[DEBUG] Waiting for process to exit"
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        Write-Output "[INFO] SteamCMD process completed with exit code: $exitCode"
        
        if ($errorOutput) {
            Write-Output "[WARN] SteamCMD Errors:"
            Write-Output $errorOutput
        }

        if ($exitCode -ne 0 -and -not $installSuccessDetected) {
            throw "SteamCMD failed with exit code: $exitCode"
        }
        
        # Even if exit code is non-zero, if we detected a successful installation message,
        # consider the installation successful
        if ($installSuccessDetected) {
            Write-Output "[INFO] Installation considered successful based on output markers"
        }

        # Verify installation
        if (-not (Test-Path $installDir)) {
            throw "Installation directory not created: $installDir"
        }

        $installedFiles = Get-ChildItem -Path $installDir -Recurse
        if (-not $installedFiles) {
            Write-Output "[WARN] No files detected in installation directory - this may indicate a problem"
        } else {
            Write-Output "[INFO] Installation directory contains $(($installedFiles | Measure-Object).Count) files/directories"
        }

        # Create server configuration
        Write-Output "[INFO] Creating server configuration..."
        $serverConfig = @{
            Name = $name
            AppID = $appId
            InstallDir = $installDir
            Created = Get-Date -Format "o"
            LastUpdate = Get-Date -Format "o"
        }

        $configPath = Join-Path $serverManagerDir "servers"
        Write-Output "[DEBUG] Config path: $configPath"
        
        if (-not (Test-Path $configPath)) {
            Write-Output "[INFO] Creating servers directory: $configPath"
            try {
                $createdDir = New-Item -ItemType Directory -Path $configPath -Force -ErrorAction Stop
                Write-Output "[DEBUG] Directory created: $($createdDir.FullName)"
            }
            catch {
                throw "Failed to create config directory: $configPath - $($_.Exception.Message)"
            }
        }

        $configFile = Join-Path $configPath "$name.json"
        Write-Output "[INFO] Saving configuration to: $configFile"
        try {
            $serverConfig | ConvertTo-Json | Set-Content $configFile -Force -ErrorAction Stop
            
            if (Test-Path $configFile) {
                Write-Output "[DEBUG] Config file created successfully: $configFile"
            } else {
                throw "Config file wasn't created despite no errors"
            }
        }
        catch {
            throw "Failed to save server config: $($_.Exception.Message)"
        }

        # Save installation log to a file in the Game_Logs directory
        try {
            # Create Game_Logs directory under the main logs folder
            $gameLogsPath = Join-Path $serverManagerDir "logs\Game_Logs"
            if (-not (Test-Path $gameLogsPath)) {
                Write-Output "[INFO] Creating Game_Logs directory: $gameLogsPath"
                New-Item -ItemType Directory -Path $gameLogsPath -Force | Out-Null
            }
            
            # Save the complete output to Game_Install.log named with server name
            $logFilePath = Join-Path $gameLogsPath "${name}_install.log"
            Write-Output "[INFO] Saving installation log to: $logFilePath"
            
            # Combine all output into a timestamped log file
            $logContent = @"
# Server Installation Log
# Server Name: $name
# App ID: $appId
# Installation Directory: $installDir
# Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

$($output.ToString())

"@
            
            # Add error output if there was any
            if (-not [string]::IsNullOrEmpty($errorOutput)) {
                $logContent += @"
# Error Output:
$errorOutput
"@
            }
            
            # Save the log file
            $logContent | Out-File -FilePath $logFilePath -Encoding utf8 -Force
            Write-Output "[INFO] Installation log saved successfully to central logs"
            
            # Also save a copy in the server directory for convenience
            $serverLogsPath = Join-Path $installDir "logs"
            if (-not (Test-Path $serverLogsPath)) {
                Write-Output "[INFO] Creating server logs directory: $serverLogsPath"
                New-Item -ItemType Directory -Path $serverLogsPath -Force | Out-Null
            }
            
            $serverLogFile = Join-Path $serverLogsPath "Game_Install.log"
            $logContent | Out-File -FilePath $serverLogFile -Encoding utf8 -Force
            Write-Output "[INFO] Installation log copy saved in server directory"
        }
        catch {
            Write-Output "[WARN] Failed to save installation log: $($_.Exception.Message)"
            # Log but continue - this shouldn't fail the whole installation
        }

        Write-Output "[SUCCESS] Configuration saved successfully"

        # Return an explicit PSCustomObject - Adding Write-Output to ensure it gets returned
        $returnObject = [PSCustomObject]@{
            Success = $true
            Message = "Server created successfully at $installDir"
            InstallPath = $installDir
        }
        
        # Explicitly write the return object to the output stream
        Write-Output "[RESULT-OBJECT-BEGIN]"
        Write-Output ($returnObject | ConvertTo-Json)
        Write-Output "[RESULT-OBJECT-END]"
        
        return $returnObject
    }
    catch {
        Write-Output "[ERROR] Error occurred: $($_.Exception.Message)"
        Write-Output "[ERROR] Stack trace: $($_.ScriptStackTrace)"
        Write-Output "[ERROR] Exception type: $($_.Exception.GetType().Name)"
        
        # Create an explicit error result object and ensure it's output properly
        $errorObject = [PSCustomObject]@{
            Success = $false
            Message = $_.Exception.Message
            StackTrace = $_.ScriptStackTrace
            ExceptionType = $_.Exception.GetType().Name
        }
        
        # Explicitly write the error object to the output stream
        Write-Output "[ERROR-OBJECT-BEGIN]"
        Write-Output ($errorObject | ConvertTo-Json)
        Write-Output "[ERROR-OBJECT-END]"
        
        return $errorObject
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

function Get-SteamCredentials {
    $loginForm = New-Object System.Windows.Forms.Form
    $loginForm.Text = "Steam Login"
    $loginForm.Size = New-Object System.Drawing.Size(300,250)
    $loginForm.StartPosition = "CenterScreen"
    $loginForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $loginForm.MaximizeBox = $false

    $usernameLabel = New-Object System.Windows.Forms.Label
    $usernameLabel.Text = "Username:"
    $usernameLabel.Location = New-Object System.Drawing.Point(10,20)
    $usernameLabel.Size = New-Object System.Drawing.Size(100,20)

    $usernameBox = New-Object System.Windows.Forms.TextBox
    $usernameBox.Location = New-Object System.Drawing.Point(110,20)
    $usernameBox.Size = New-Object System.Drawing.Size(150,20)

    $passwordLabel = New-Object System.Windows.Forms.Label
    $passwordLabel.Text = "Password:"
    $passwordLabel.Location = New-Object System.Drawing.Point(10,50)
    $passwordLabel.Size = New-Object System.Drawing.Size(100,20)

    $passwordBox = New-Object System.Windows.Forms.TextBox
    $passwordBox.Location = New-Object System.Drawing.Point(110,50)
    $passwordBox.Size = New-Object System.Drawing.Size(150,20)
    $passwordBox.PasswordChar = '*'

    $guardLabel = New-Object System.Windows.Forms.Label
    $guardLabel.Text = "Steam Guard Code:"
    $guardLabel.Location = New-Object System.Drawing.Point(10,80)
    $guardLabel.Size = New-Object System.Drawing.Size(100,20)
    $guardLabel.Visible = $false

    $guardBox = New-Object System.Windows.Forms.TextBox
    $guardBox.Location = New-Object System.Drawing.Point(110,80)
    $guardBox.Size = New-Object System.Drawing.Size(150,20)
    $guardBox.MaxLength = 5
    $guardBox.Visible = $false

    $loginButton = New-Object System.Windows.Forms.Button
    $loginButton.Text = "Login"
    $loginButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $loginButton.Location = New-Object System.Drawing.Point(110,120)

    $anonButton = New-Object System.Windows.Forms.Button
    $anonButton.Text = "Anonymous"
    $anonButton.DialogResult = [System.Windows.Forms.DialogResult]::Ignore
    $anonButton.Location = New-Object System.Drawing.Point(110,150)

    $loginForm.Controls.AddRange(@(
        $usernameLabel, $usernameBox, 
        $passwordLabel, $passwordBox,
        $guardLabel, $guardBox,
        $loginButton, $anonButton
    ))

    $result = $loginForm.ShowDialog()
    
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return @{
            Username = $usernameBox.Text
            Password = $passwordBox.Text
            GuardCode = $guardBox.Text
            Anonymous = $false
        }
    }
    elseif ($result -eq [System.Windows.Forms.DialogResult]::Ignore) {
        return @{
            Anonymous = $true
        }
    }
    else {
        return $null
    }
}

# Create the main form - make sure there's only ONE form initialization section
$form = New-Object System.Windows.Forms.Form
$form.Text = "Server Manager Dashboard"
$form.Size = New-Object System.Drawing.Size(1200,700)
$form.StartPosition = "CenterScreen"
$form.MinimumSize = New-Object System.Drawing.Size(800,600)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.AutoSize = $false
$form.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink

# Create the main container for all controls to maintain proper layout
$containerPanel = New-Object System.Windows.Forms.TableLayoutPanel
$containerPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$containerPanel.RowCount = 3
$containerPanel.ColumnCount = 1
$containerPanel.Padding = New-Object System.Windows.Forms.Padding(10)

# Set row styles for container panel
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$containerPanel.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))

# Create main layout panel for servers and info
$mainPanel = New-Object System.Windows.Forms.TableLayoutPanel
$mainPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$mainPanel.ColumnCount = 2
$mainPanel.RowCount = 1
$mainPanel.AutoSize = $false
$mainPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))
$mainPanel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 30)))
$mainPanel.CellBorderStyle = [System.Windows.Forms.TableLayoutPanelCellBorderStyle]::Single

# Create ListView for servers
$listView = New-Object System.Windows.Forms.ListView
$listView.View = [System.Windows.Forms.View]::Details
$listView.FullRowSelect = $true
$listView.GridLines = $true
$listView.Dock = [System.Windows.Forms.DockStyle]::Fill

# Add context menu to listView
$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

# Create "Add Server" menu item (always visible)
$addServerMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
$addServerMenuItem.Text = "Add Server"
$addServerMenuItem.Add_Click({
    # Get Steam credentials first
    $credentials = Get-SteamCredentials
    if ($credentials -eq $null) {
        Write-DashboardLog "User cancelled Steam login" -Level DEBUG
        return
    }

    Write-DashboardLog "Steam login type: $(if ($credentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG
    New-IntegratedGameServer -SteamCredentials $credentials
})

# Create "Open Folder Directory" menu item (only when server selected)
$openFolderMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
$openFolderMenuItem.Text = "Open Folder Directory"
$openFolderMenuItem.Add_Click({
    # Get selected server
    if ($listView.SelectedItems.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show("Please select a server first.", "No Selection", 
            [System.Windows.Forms.MessageBoxButtons]::OK, 
            [System.Windows.Forms.MessageBoxIcon]::Information)
        return
    }
    
    $serverName = $listView.SelectedItems[0].Text
    Write-DashboardLog "Opening folder for server: $serverName" -Level DEBUG
    
    # Get server config path
    $configPath = Join-Path $script:Paths.Root "servers\$serverName.json"
    if (-not (Test-Path $configPath)) {
        [System.Windows.Forms.MessageBox]::Show("Server configuration file not found: $configPath", "Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error)
        return
    }
    
    # Read server config
    try {
        $serverConfig = Get-Content $configPath -Raw | ConvertFrom-Json
        
        # Get installation directory
        if (-not $serverConfig.InstallDir) {
            [System.Windows.Forms.MessageBox]::Show("Installation directory not specified in server configuration.", "Error",
                [System.Windows.Forms.MessageBoxButtons]::OK, 
                [System.Windows.Forms.MessageBoxIcon]::Error)
            return
        }
        
        $installDir = $serverConfig.InstallDir
        
        # Check if directory exists
        if (-not (Test-Path $installDir)) {
            $result = [System.Windows.Forms.MessageBox]::Show(
                "The installation directory does not exist: $installDir`n`nDo you want to create it?", 
                "Directory Not Found",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning)
            
            if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
                try {
                    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
                } catch {
                    [System.Windows.Forms.MessageBox]::Show("Failed to create directory: $($_.Exception.Message)", "Error",
                        [System.Windows.Forms.MessageBoxButtons]::OK,
                        [System.Windows.Forms.MessageBoxIcon]::Error)
                    return
                }
            } else {
                return
            }
        }
        
        # Open the directory
        try {
            Write-DashboardLog "Opening directory: $installDir" -Level DEBUG
            Start-Process "explorer.exe" -ArgumentList "`"$installDir`"" -ErrorAction Stop
        } catch {
            [System.Windows.Forms.MessageBox]::Show("Failed to open directory: $($_.Exception.Message)", "Error",
                [System.Windows.Forms.MessageBoxButtons]::OK, 
                [System.Windows.Forms.MessageBoxIcon]::Error)
        }
    } catch {
        [System.Windows.Forms.MessageBox]::Show("Failed to read server configuration: $($_.Exception.Message)", "Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error)
    }
})

# Add Remove Server menu item
$removeServerMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem
$removeServerMenuItem.Text = "Remove Server"
$removeServerMenuItem.Add_Click({
    # Get selected server
    if ($listView.SelectedItems.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show("Please select a server first.", "No Selection", 
            [System.Windows.Forms.MessageBoxButtons]::OK, 
            [System.Windows.Forms.MessageBoxIcon]::Information)
        return
    }
    
    $serverName = $listView.SelectedItems[0].Text
    Write-DashboardLog "Removing server from context menu: $serverName" -Level DEBUG
    
    # Create removal form with pre-selected server
    $removeForm = New-Object System.Windows.Forms.Form
    $removeForm.Text = "Remove Game Server"
    $removeForm.Size = New-Object System.Drawing.Size(400,200)
    $removeForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $serverComboBox = New-Object System.Windows.Forms.ComboBox
    $serverComboBox.Location = New-Object System.Drawing.Point(120,20)
    $serverComboBox.Size = New-Object System.Drawing.Size(250,20)
    $serverComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList

    # Populate server list
    $configPath = Join-Path $script:Paths.Root "servers"
    if (Test-Path $configPath) {
        Get-ChildItem -Path $configPath -Filter "*.json" | ForEach-Object {
            $serverComboBox.Items.Add($_.BaseName)
        }
    }
    
    # Pre-select the server
    if ($serverComboBox.Items.Contains($serverName)) {
        $serverComboBox.SelectedItem = $serverName
    }

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(120,80)
    $progressBar.Size = New-Object System.Drawing.Size(250,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(120,60)
    $statusLabel.Size = New-Object System.Drawing.Size(250,20)
    $statusLabel.Text = ""

    # Create a hidden console output for job monitoring
    $consoleOutput = New-Object System.Windows.Forms.RichTextBox
    $consoleOutput.Location = New-Object System.Drawing.Point(-2000,-2000)
    $consoleOutput.Size = New-Object System.Drawing.Size(10,10)
    $consoleOutput.Visible = $false

    $removeButton = New-Object System.Windows.Forms.Button
    $removeButton.Text = "Remove"
    $removeButton.Location = New-Object System.Drawing.Point(120,110)
    $removeButton.Add_Click({
    })

    $removeForm.Controls.AddRange(@(
        $nameLabel, $serverComboBox,
        $removeButton, $progressBar, $statusLabel, 
        $consoleOutput
    ))

    $removeForm.ShowDialog()
})

# Configure context menu opening event to dynamically adjust menu items
$contextMenu.Add_Opening({
    param($sender, $e)
    
    # Clear existing items first
    $contextMenu.Items.Clear()
    
    # Add Server is always available
    $contextMenu.Items.Add($addServerMenuItem)
    
    # If a server is selected, add the server-specific options
    if ($listView.SelectedItems.Count -gt 0) {
        $contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
        $contextMenu.Items.Add($openFolderMenuItem)
        $contextMenu.Items.Add($removeServerMenuItem)
    }
})

# Assign context menu to listView
$listView.ContextMenuStrip = $contextMenu

# Add columns to match web dashboard
$listView.Columns.Add("Server Name", 150)
$listView.Columns.Add("Status", 100)
$listView.Columns.Add("CPU Usage", 100)
$listView.Columns.Add("Memory Usage", 100)
$listView.Columns.Add("Uptime", 150)

# Create left panel for server list
$serversPanel = New-Object System.Windows.Forms.Panel
$serversPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$serversPanel.Controls.Add($listView)

# Create host information panel
$HostNamePanel = New-Object System.Windows.Forms.TableLayoutPanel
$HostNamePanel.ColumnCount = 1
$HostNamePanel.RowCount = 2
$HostNamePanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$HostNamePanel.Padding = New-Object System.Windows.Forms.Padding(10)

# Create container for system info header
$systemHeaderPanel = New-Object System.Windows.Forms.TableLayoutPanel
$systemHeaderPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$systemHeaderPanel.ColumnCount = 1
$systemHeaderPanel.RowCount = 2
$systemHeaderPanel.AutoSize = $true
$systemHeaderPanel.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 10)

# System name header
$systemNameLabel = New-Object System.Windows.Forms.Label
$systemNameLabel.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$systemNameLabel.Text = "Loading system info..."
$systemNameLabel.AutoSize = $true
$systemNameLabel.Dock = [System.Windows.Forms.DockStyle]::Fill
$systemNameLabel.Name = "lblSystemName"

# OS version info
$osInfoLabel = New-Object System.Windows.Forms.Label
$osInfoLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$osInfoLabel.Text = "Loading OS info..."
$osInfoLabel.AutoSize = $true
$osInfoLabel.Dock = [System.Windows.Forms.DockStyle]::Fill
$osInfoLabel.Name = "lblOsInfo"
$osInfoLabel.ForeColor = [System.Drawing.Color]::Gray

# Add to header panel
$systemHeaderPanel.Controls.Add($systemNameLabel, 0, 0)
$systemHeaderPanel.Controls.Add($osInfoLabel, 0, 1)

# Create system metrics grid
$metricsPanel = New-Object System.Windows.Forms.TableLayoutPanel
$metricsPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$metricsPanel.ColumnCount = 2
$metricsPanel.RowCount = 6
$metricsPanel.CellBorderStyle = [System.Windows.Forms.TableLayoutPanelCellBorderStyle]::None
$metricsPanel.Padding = New-Object System.Windows.Forms.Padding(0)

# Function to create formatted metric panels with titles and values
function New-MetricPanel {
    param(
        [string]$Title,
        [string]$Value,
        [string]$Name,
        [string]$IconText = ""
    )
    
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Dock = [System.Windows.Forms.DockStyle]::Fill
    $panel.Padding = New-Object System.Windows.Forms.Padding(0)
    $panel.Margin = New-Object System.Windows.Forms.Padding(5)
    
    # Title label
    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = if ($IconText) { "$IconText $Title" } else { $Title }
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $titleLabel.AutoSize = $true
    $titleLabel.Location = New-Object System.Drawing.Point(0, 0)
    $titleLabel.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 3)
    
    # Value label
    $valueLabel = New-Object System.Windows.Forms.Label
    $valueLabel.Text = $Value
    $valueLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11)
    $valueLabel.AutoSize = $true
    $valueLabel.Location = New-Object System.Drawing.Point(0, 20)
    $valueLabel.Name = $Name
    
    $panel.Controls.Add($titleLabel)
    $panel.Controls.Add($valueLabel)
    
    return $panel
}

# Create metric panels with plain text icons instead of emojis
$metrics = @(
    @{Title="CPU"; Value="Loading..."; Name="lblCPU"; Icon="(CPU)"},
    @{Title="Memory"; Value="Loading..."; Name="lblMemory"; Icon="(MEM)"},
    @{Title="Disk Space"; Value="Loading..."; Name="lblDisk"; Icon="(DSK)"},
    @{Title="Network"; Value="Loading..."; Name="lblNetwork"; Icon="(NET)"},
    @{Title="GPU"; Value="Loading..."; Name="lblGPU"; Icon="(GPU)"},
    @{Title="System Uptime"; Value="Loading..."; Name="lblUptime"; Icon="(UP)"}
)

$row = 0
$col = 0
$metrics | ForEach-Object {
    $metricPanel = New-MetricPanel -Title $_.Title -Value $_.Value -Name $_.Name -IconText $_.Icon
    $metricsPanel.Controls.Add($metricPanel, $col, $row)
    $col++
    if ($col -ge 2) {
        $col = 0
        $row++
    }
}

# Add panels to host info panel
$HostNamePanel.Controls.Add($systemHeaderPanel, 0, 0)
$HostNamePanel.Controls.Add($metricsPanel, 0, 1)

# Add the panels to the main panel
$mainPanel.Controls.Add($serversPanel, 0, 0)
$mainPanel.Controls.Add($HostNamePanel, 1, 0)

# Improved version of the Get-SystemUptime function
function Get-SystemUptime {
    try {
        $os = Get-WmiObject -Class Win32_OperatingSystem -ErrorAction Stop
        $uptime = (Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime)
        
        # Format uptime nicely
        if ($uptime.Days -gt 0) {
            $uptimeString = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
        }
        elseif ($uptime.Hours -gt 0) {
            $uptimeString = "$($uptime.Hours)h $($uptime.Minutes)m"
        }
        else {
            $uptimeString = "$($uptime.Minutes)m"
        }
        
        return $uptimeString
    }
    catch {
        Write-DashboardLog "Error getting system uptime: $($_.Exception.Message)" -Level WARN
        return "Unknown"
    }
}

# Update-HostInformation function to refresh system metrics
function Update-HostInformation {
    try {
        # Initialize systemInfo hashtable if it's null or empty
        if ($null -eq $script:systemInfo) {
            $script:systemInfo = @{}
        }

        # Initialize WMI queries if needed
        if ($script:systemInfo.Count -eq 0) {
            Write-DashboardLog "Initializing system information" -Level DEBUG
            
            # System name and OS info
            try {
                $computerSystem = Get-WmiObject -Class Win32_ComputerSystem -ErrorAction Stop
                $osInfo = Get-WmiObject -Class Win32_OperatingSystem -ErrorAction Stop
                
                # Use hashtable syntax for assignment instead of property syntax
                $script:systemInfo["ComputerName"] = $computerSystem.Name
                if ($computerSystem.Model) {
                    $script:systemInfo["ComputerName"] += " ($($computerSystem.Model))" 
                }
                
                $script:systemInfo["OSName"] = $osInfo.Caption
                $script:systemInfo["OSVersion"] = "$($osInfo.Version) Build $($osInfo.BuildNumber)"
                
                $form.Invoke([Action]{
                    try {
                        $systemNameLabel.Text = $script:systemInfo["ComputerName"]
                        $osInfoLabel.Text = "$($script:systemInfo["OSName"]) ($($script:systemInfo["OSVersion"]))"
                    }
                    catch {
                        Write-DashboardLog "Error updating system header: $($_.Exception.Message)" -Level ERROR
                    }
                })
            }
            catch {
                Write-DashboardLog "Error getting basic system info: $($_.Exception.Message)" -Level WARN
                $script:systemInfo["ComputerName"] = $env:COMPUTERNAME
                $script:systemInfo["OSName"] = "Windows"
                $script:systemInfo["OSVersion"] = "Unknown"
                
                $form.Invoke([Action]{
                    try {
                        $systemNameLabel.Text = $script:systemInfo["ComputerName"]
                        $osInfoLabel.Text = $script:systemInfo["OSName"]
                    }
                    catch {
                        Write-DashboardLog "Error updating system header: $($_.Exception.Message)" -Level ERROR
                    }
                })
            }
            
            # Get available network adapters (only once)
            try {
                $adapters = Get-WmiObject -Class Win32_NetworkAdapter | Where-Object { 
                    $_.NetConnectionStatus -eq 2 -and $null -ne $_.NetConnectionID -and $_.NetConnectionID -ne "" 
                }
                $script:networkAdapters = $adapters | ForEach-Object { $_.DeviceID }
                
                # Get initial network stats
                if ($script:networkAdapters.Count -gt 0) {
                    $script:lastNetworkStats = @{
                        In = 0
                        Out = 0
                    }
                    $script:networkAdapters | ForEach-Object {
                        $adapterID = $_
                        try {
                            $adapterName = (Get-WmiObject -Class Win32_NetworkAdapter | Where-Object { $_.DeviceID -eq $adapterID }).NetConnectionID
                            if ($adapterName) {
                                $perfCounterIN = New-Object System.Diagnostics.PerformanceCounter("Network Interface", "Bytes Received/sec", $adapterName, $true)
                                $perfCounterOUT = New-Object System.Diagnostics.PerformanceCounter("Network Interface", "Bytes Sent/sec", $adapterName, $true)
                                $script:lastNetworkStats[$adapterID] = @{
                                    In = $perfCounterIN.NextValue()
                                    Out = $perfCounterOUT.NextValue()
                                }
                            }
                        } catch {
                            Write-DashboardLog "Error initializing network counter for adapter ${adapterID}: $($_.Exception.Message)" -Level DEBUG
                        }
                    }
                    $script:lastNetworkStatsTime = Get-Date
                }
            }
            catch {
                Write-DashboardLog "Error initializing network adapters: $($_.Exception.Message)" -Level WARN
                $script:networkAdapters = @()
            }
            
            # Look for GPU info
            try {
                $gpus = Get-WmiObject -Class Win32_VideoController -ErrorAction Stop
                if ($gpus -and $gpus.Count -gt 0) {
                    $primaryGpu = $gpus | Where-Object { $_.CurrentHorizontalResolution -gt 0 } | Select-Object -First 1
                    if (-not $primaryGpu) { $primaryGpu = $gpus | Select-Object -First 1 }
                    
                    $script:gpuInfo = @{
                        Name = $primaryGpu.Name
                        DriverVersion = $primaryGpu.DriverVersion
                        Memory = if ($primaryGpu.AdapterRAM -gt 0) { [math]::Round($primaryGpu.AdapterRAM / 1MB, 0) } else { 0 }
                    }
                }
            }
            catch {
                Write-DashboardLog "Error getting GPU info: $($_.Exception.Message)" -Level WARN
                $script:gpuInfo = $null
            }
        }
        
        # Update CPU usage (using performance counter)
        try {
            if (-not $script:cpuCounter) {
                $script:cpuCounter = New-Object System.Diagnostics.PerformanceCounter("Processor", "% Processor Time", "_Total")
                $script:cpuCounter.NextValue()
                Start-Sleep -Milliseconds 100
            }
            
            $cpuUsage = [math]::Round($script:cpuCounter.NextValue(), 1)
            $cpuCores = (Get-WmiObject -Class Win32_Processor).NumberOfLogicalProcessors
            
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblCPU"]) {
                    $metricsPanel.Controls["lblCPU"].Text = "$cpuUsage% ($cpuCores cores)"
                } else {
                    Write-DashboardLog "CPU label control not found in metricsPanel" -Level WARN
                }
            })
        }
        catch {
            Write-DashboardLog "Error updating CPU usage: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblCPU"]) {
                    $metricsPanel.Controls["lblCPU"].Text = "Error measuring CPU"
                }
            })
        }
        
        # Update memory usage
        try {
            $os = Get-WmiObject -Class Win32_OperatingSystem
            $totalMemoryGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
            $freeMemoryGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
            $usedMemoryGB = [math]::Round($totalMemoryGB - $freeMemoryGB, 1)
            $memoryPercent = [math]::Round(($usedMemoryGB / $totalMemoryGB) * 100, 0)
            
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblMemory"]) {
                    $metricsPanel.Controls["lblMemory"].Text = "$usedMemoryGB GB / $totalMemoryGB GB ($memoryPercent%)"
                }
            })
        }
        catch {
            Write-DashboardLog "Error updating memory usage: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblMemory"]) {
                    $metricsPanel.Controls["lblMemory"].Text = "Error measuring memory"
                }
            })
        }
        
        # Update disk usage (only local fixed disks)
        try {
            $drives = Get-WmiObject -Class Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 }
            if ($drives) {
                $totalSizeGB = [math]::Round(($drives | Measure-Object -Property Size -Sum).Sum / 1GB, 0)
                $freeSpaceGB = [math]::Round(($drives | Measure-Object -Property FreeSpace -Sum).Sum / 1GB, 0)
                $usedSpaceGB = $totalSizeGB - $freeSpaceGB
                $diskPercent = [math]::Round(($usedSpaceGB / $totalSizeGB) * 100, 0)
                
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblDisk"]) {
                        $metricsPanel.Controls["lblDisk"].Text = "$usedSpaceGB GB / $totalSizeGB GB ($diskPercent%)"
                    }
                })
            }
            else {
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblDisk"]) {
                        $metricsPanel.Controls["lblDisk"].Text = "No fixed disks found"
                    }
                })
            }
        }
        catch {
            Write-DashboardLog "Error updating disk usage: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblDisk"]) {
                    $metricsPanel.Controls["lblDisk"].Text = "Error measuring disk usage"
                }
            })
        }
        
        # Update network usage (calculate real-time bandwidth)
        try {
            if ($script:networkAdapters.Count -gt 0) {
                $currentNetworkStats = @{}
                $totalBpsIn = 0
                $totalBpsOut = 0
                
                foreach ($adapterID in $script:networkAdapters) {
                    try {
                        $adapterName = (Get-WmiObject -Class Win32_NetworkAdapter | Where-Object { $_.DeviceID -eq $adapterID }).NetConnectionID
                        if ($adapterName) {
                            $perfCounterIN = New-Object System.Diagnostics.PerformanceCounter("Network Interface", "Bytes Received/sec", $adapterName, $true)
                            $perfCounterOUT = New-Object System.Diagnostics.PerformanceCounter("Network Interface", "Bytes Sent/sec", $adapterName, $true)
                            
                            # Get current values
                            $currentNetworkStats[$adapterID] = @{
                                In = $perfCounterIN.NextValue()
                                Out = $perfCounterOUT.NextValue()
                            }
                            
                            # Add to total
                            $totalBpsIn += $currentNetworkStats[$adapterID].In
                            $totalBpsOut += $currentNetworkStats[$adapterID].Out
                        }
                    }
                    catch {
                        Write-DashboardLog "Error measuring network adapter $($adapterID): $($_.Exception.Message)" -Level DEBUG
                    }
                }
                
                # Format network speed in appropriate units
                $inUnit = "Bps"
                $outUnit = "Bps"
                
                if ($totalBpsIn -gt 1024 * 1024) {
                    $totalBpsIn = [math]::Round($totalBpsIn / 1MB, 1)
                    $inUnit = "MBps"
                } 
                elseif ($totalBpsIn -gt 1024) {
                    $totalBpsIn = [math]::Round($totalBpsIn / 1KB, 1)
                    $inUnit = "KBps"
                }
                
                if ($totalBpsOut -gt 1024 * 1024) {
                    $totalBpsOut = [math]::Round($totalBpsOut / 1MB, 1)
                    $outUnit = "MBps"
                }
                elseif ($totalBpsOut -gt 1024) {
                    $totalBpsOut = [math]::Round($totalBpsOut / 1KB, 1)
                    $outUnit = "KBps"
                }
                
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblNetwork"]) {
                        $metricsPanel.Controls["lblNetwork"].Text = "Down: $totalBpsIn $inUnit / Up: $totalBpsOut $outUnit"
                    }
                })
                
                # Store values for next time
                $script:lastNetworkStats = $currentNetworkStats
                $script:lastNetworkStatsTime = Get-Date
            }
            else {
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblNetwork"]) {
                        $metricsPanel.Controls["lblNetwork"].Text = "No active network adapters"
                    }
                })
            }
        }
        catch {
            Write-DashboardLog "Error updating network usage: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblNetwork"]) {
                    $metricsPanel.Controls["lblNetwork"].Text = "Error measuring network"
                }
            })
        }
        
        # Update GPU info
        try {
            if ($script:gpuInfo) {
                # Get current GPU utilization if available (WMI doesn't provide this natively)
                $gpuText = "$($script:gpuInfo.Name)"
                if ($script:gpuInfo.Memory -gt 0) {
                    $gpuText += " ($($script:gpuInfo.Memory) MB)"
                }
                
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblGPU"]) {
                        $metricsPanel.Controls["lblGPU"].Text = $gpuText
                    }
                })
            }
            else {
                $form.Invoke([Action]{
                    if ($metricsPanel.Controls["lblGPU"]) {
                        $metricsPanel.Controls["lblGPU"].Text = "No GPU detected"
                    }
                })
            }
        }
        catch {
            Write-DashboardLog "Error updating GPU info: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblGPU"]) {
                    $metricsPanel.Controls["lblGPU"].Text = "Error detecting GPU"
                }
            })
        }
        
        # Update uptime
        try {
            $uptimeString = Get-SystemUptime
            
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblUptime"]) {
                    $metricsPanel.Controls["lblUptime"].Text = $uptimeString
                }
            })
        }
        catch {
            Write-DashboardLog "Error updating system uptime: $($_.Exception.Message)" -Level WARN
            $form.Invoke([Action]{
                if ($metricsPanel.Controls["lblUptime"]) {
                    $metricsPanel.Controls["lblUptime"].Text = "Error measuring uptime"
                }
            })
        }

        # Only broadcast update if WebSocket is connected or we can connect
        if (-not $script:offlineMode) {
            # First check availability
            if ($script:isWebSocketConnected -or (Test-WebSocketServer -Silent)) {
                # If server is available but we're not connected, try to connect
                if (-not $script:isWebSocketConnected) {
                    Connect-WebSocketServer -Silent
                }
                
                # Now check if we have a valid connection
                if ($script:isWebSocketConnected -and $script:webSocketClient -and 
                    $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                    
                    try {
                        # Create host data to send - use safe access with default values if properties don't exist
                        $hostData = @{
                            CPU = if ($metricsPanel.Controls["lblCPU"]) { $metricsPanel.Controls["lblCPU"].Text } else { "N/A" }
                            Memory = if ($metricsPanel.Controls["lblMemory"]) { $metricsPanel.Controls["lblMemory"].Text } else { "N/A" }
                            Disk = if ($metricsPanel.Controls["lblDisk"]) { $metricsPanel.Controls["lblDisk"].Text } else { "N/A" }
                            Network = if ($metricsPanel.Controls["lblNetwork"]) { $metricsPanel.Controls["lblNetwork"].Text } else { "N/A" }
                            GPU = if ($metricsPanel.Controls["lblGPU"]) { $metricsPanel.Controls["lblGPU"].Text } else { "N/A" }
                            Uptime = if ($metricsPanel.Controls["lblUptime"]) { $metricsPanel.Controls["lblUptime"].Text } else { "N/A" }
                            SystemName = if ($systemNameLabel -and -not $systemNameLabel.IsDisposed) { $systemNameLabel.Text } else { $env:COMPUTERNAME }
                            OSInfo = if ($osInfoLabel -and -not $osInfoLabel.IsDisposed) { $osInfoLabel.Text } else { "Windows" }
                        }
                        
                        $updateMessage = @{
                            Type = "HostInfoUpdate"
                            HostInfo = $hostData
                            Timestamp = Get-Date -Format "o"
                        } | ConvertTo-Json
                        
                        $buffer = [System.Text.Encoding]::UTF8.GetBytes($updateMessage)
                        $segment = [ArraySegment[byte]]::new($buffer)
                        
                        $script:webSocketClient.SendAsync(
                            $segment,
                            [System.Net.WebSockets.WebSocketMessageType]::Text,
                            $true,
                            [System.Threading.CancellationToken]::None
                        ).Wait(1000)
                    } 
                    catch {
                        Write-DashboardLog "Failed to send host info update: $_" -Level ERROR
                    }
                }
            }
        }
        
        # Mark the time when the full update was completed
        $script:lastFullUpdate = Get-Date
    }
    catch {
        Write-DashboardLog "Failed to update host information: $_" -Level ERROR
        Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level DEBUG
    }
}

# Create buttons panel
$buttonPanel = New-Object System.Windows.Forms.Panel
$buttonPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$buttonPanel.Height = 50

# Create a flow layout for buttons to ensure proper spacing
$buttonFlowPanel = New-Object System.Windows.Forms.FlowLayoutPanel
$buttonFlowPanel.Dock = [System.Windows.Forms.DockStyle]::Fill
$buttonFlowPanel.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$buttonFlowPanel.WrapContents = $false
$buttonFlowPanel.AutoSize = $true

# Add these functions before creating the buttons
function New-IntegratedGameServer {
    param (
        [Parameter(Mandatory=$true)]
        [hashtable]$SteamCredentials
    )
    
    $createForm = New-Object System.Windows.Forms.Form
    $createForm.Text = "Create Game Server"
    $createForm.Size = New-Object System.Drawing.Size(600,500)
    $createForm.StartPosition = "CenterScreen"

    # Keep existing input controls but adjust their positions
    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $nameTextBox = New-Object System.Windows.Forms.TextBox
    $nameTextBox.Location = New-Object System.Drawing.Point(120,20)
    $nameTextBox.Size = New-Object System.Drawing.Size(250,20)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "App ID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10,50)
    $appIdLabel.Size = New-Object System.Drawing.Size(100,20)

    $appIdTextBox = New-Object System.Windows.Forms.TextBox
    $appIdTextBox.Location = New-Object System.Drawing.Point(120,50)
    $appIdTextBox.Size = New-Object System.Drawing.Size(250,20)

    $installDirLabel = New-Object System.Windows.Forms.Label
    $installDirLabel.Text = "Install Directory:"
    $installDirLabel.Location = New-Object System.Drawing.Point(10,80)
    $installDirLabel.Size = New-Object System.Drawing.Size(100,20)

    $installDirTextBox = New-Object System.Windows.Forms.TextBox
    $installDirTextBox.Location = New-Object System.Drawing.Point(120,80)
    $installDirTextBox.Size = New-Object System.Drawing.Size(200,20)
    $installDirInfo = New-Object System.Windows.Forms.Label
    $installDirInfo.Text = "(Leave blank for default location)"
    $installDirInfo.Location = New-Object System.Drawing.Point(120,102)
    $installDirInfo.Size = New-Object System.Drawing.Size(200,18)
    $installDirInfo.ForeColor = [System.Drawing.Color]::DarkGray
    $installDirInfo.Font = New-Object System.Drawing.Font($installDirInfo.Font.FontFamily, ($installDirInfo.Font.Size - 1))

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse"
    $browseButton.Location = New-Object System.Drawing.Point(330,78)
    $browseButton.Size = New-Object System.Drawing.Size(60,22)
    $browseButton.Add_Click({
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "Select Installation Directory"
        if ($folderBrowser.ShowDialog() -eq 'OK') {
            $installDirTextBox.Text = $folderBrowser.SelectedPath
        }
    })

    # Add console output window
    $consoleOutput = New-Object System.Windows.Forms.RichTextBox
    $consoleOutput.Location = New-Object System.Drawing.Point(10,120)
    $consoleOutput.Size = New-Object System.Drawing.Size(560,250)  # Wide console window
    $consoleOutput.MultiLine = $true
    $consoleOutput.ScrollBars = "Vertical"
    $consoleOutput.BackColor = [System.Drawing.Color]::Black
    $consoleOutput.ForeColor = [System.Drawing.Color]::White
    $consoleOutput.Font = New-Object System.Drawing.Font("Consolas", 9)
    $consoleOutput.ReadOnly = $true

    # Move progress elements below console
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(10,390)
    $progressBar.Size = New-Object System.Drawing.Size(560,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(10,370)
    $statusLabel.Size = New-Object System.Drawing.Size(560,20)
    $statusLabel.Text = ""

    $createButton = New-Object System.Windows.Forms.Button
    $createButton.Text = "Create"
    $createButton.Location = New-Object System.Drawing.Point(10,420)
    $createButton.Size = New-Object System.Drawing.Size(100,30)
    
    # Add cancel button
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.Location = New-Object System.Drawing.Point(120,420)
    $cancelButton.Size = New-Object System.Drawing.Size(100,30)
    $cancelButton.Enabled = $false
    
    # Add cancellation flag to track if user requested cancellation
    $script:installCancelled = $false
    
    # Define the cancel button click handler
    $cancelButton.Add_Click({
        try {
            # Confirm cancellation with the user
            $confirmResult = [System.Windows.Forms.MessageBox]::Show(
                "Are you sure you want to cancel the installation? Partial files will be cleaned up but logs will be preserved.",
                "Confirm Cancellation", 
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )
            
            if ($confirmResult -eq [System.Windows.Forms.DialogResult]::No) {
                return
            }
            
            # Set cancellation flag
            $script:installCancelled = $true
            
            # Update UI to show cancellation in progress
            if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                $statusLabel.Text = "Cancelling installation..."
            }
            
            if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                $cancelButton.Enabled = $false
            }
            
            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                $consoleOutput.AppendText("[INFO] Cancellation requested, stopping installation process...`n")
            }
            
            Write-DashboardLog "User requested cancellation of server installation" -Level INFO
            
            # Stop the job if it's running - add comprehensive null checks
            if ($null -ne $script:jobInfo) {
                if ($null -ne $script:jobInfo.Job) {
                    try {
                        Write-DashboardLog "Stopping job with ID $($script:jobInfo.Job.Id)" -Level DEBUG
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[INFO] Stopping installation job...`n")
                        }
                        Stop-Job -Job $script:jobInfo.Job -ErrorAction SilentlyContinue
                        
                        # Process job output to get installation directory info
                        $jobOutput = Receive-Job -Job $script:jobInfo.Job -Keep -ErrorAction SilentlyContinue
                        $installDir = $null
                        
                        # Try to extract install directory from job output
                        if ($null -ne $jobOutput) {
                            foreach ($line in $jobOutput) {
                                if ($null -ne $line -and $line -match "Using default installation path: (.+)") {
                                    $installDir = $matches[1]
                                    break
                                }
                            }
                        }
                        
                        # If no path found in output, use the one from the form
                        if (-not $installDir -and $null -ne $installDirTextBox -and -not $installDirTextBox.IsDisposed -and 
                            -not [string]::IsNullOrWhiteSpace($installDirTextBox.Text)) {
                            $installDir = $installDirTextBox.Text
                        }
                        
                        # Clean up the job
                        Remove-Job -Job $script:jobInfo.Job -Force -ErrorAction SilentlyContinue
                        
                        # Create cleanup script block to run separately
                        if ($installDir -and (Test-Path $installDir)) {
                            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                $consoleOutput.AppendText("[INFO] Cleaning up installation directory: $installDir`n")
                            }
                            Write-DashboardLog "Cleaning up cancelled installation at: $installDir" -Level INFO
                            
                            # Preserve logs by copying them if they exist
                            $serverLogsPath = Join-Path $installDir "logs"
                            if (Test-Path $serverLogsPath) {
                                try {
                                    $preserveLogsPath = Join-Path $script:Paths.Logs "CancelledInstalls"
                                    if (-not (Test-Path $preserveLogsPath)) {
                                        New-Item -Path $preserveLogsPath -ItemType Directory -Force | Out-Null
                                    }
                                    
                                    # Generate a unique timestamp for the preserved logs
                                    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
                                    $serverName = if ($null -ne $nameTextBox -and -not $nameTextBox.IsDisposed) { $nameTextBox.Text } else { "Unknown" }
                                    $preserveDir = Join-Path $preserveLogsPath "${serverName}_$timestamp"
                                    
                                    # Copy logs before deletion
                                    Copy-Item -Path $serverLogsPath -Destination $preserveDir -Recurse -Force
                                    if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                        $consoleOutput.AppendText("[INFO] Installation logs preserved at: $preserveDir`n")
                                    }
                                }
                                catch {
                                    if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                        $consoleOutput.AppendText("[WARN] Failed to preserve logs: $($_.Exception.Message)`n")
                                    }
                                }
                            }
                            
                            # Now attempt to clean up the installation directory
                            try {
                                # Use Stop-Process on any processes that might have locks on files
                                $processes = Get-Process | Where-Object { $_.Path -like "$installDir*" }
                                foreach ($process in $processes) {
                                    try {
                                        $process | Stop-Process -Force -ErrorAction SilentlyContinue
                                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                            $consoleOutput.AppendText("[INFO] Stopped process: $($process.Name) (ID: $($process.Id))`n")
                                        }
                                    }
                                    catch {
                                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                            $consoleOutput.AppendText("[WARN] Failed to stop process: $($process.Name)`n")
                                        }
                                    }
                                }
                                
                                # Wait a moment for handles to be released
                                Start-Sleep -Milliseconds 500
                                
                                # Try to remove the directory
                                Remove-Item -Path $installDir -Recurse -Force -ErrorAction Stop
                                if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                    $consoleOutput.AppendText("[INFO] Installation directory removed successfully`n")
                                }
                            }
                            catch {
                                if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                    $consoleOutput.AppendText("[ERROR] Failed to clean up directory: $($_.Exception.Message)`n")
                                    $consoleOutput.AppendText("[INFO] You may need to manually remove: $installDir`n")
                                }
                                Write-DashboardLog "Failed to clean up directory: $($_.Exception.Message)" -Level ERROR
                            }
                        }
                        else {
                            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                $consoleOutput.AppendText("[INFO] No installation directory found to clean up`n")
                            }
                            Write-DashboardLog "No installation directory identified for cleanup" -Level INFO
                        }
                    }
                    catch {
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[ERROR] Error during cancellation: $($_.Exception.Message)`n")
                        }
                        Write-DashboardLog "Error during installation cancellation: $($_.Exception.Message)" -Level ERROR
                    }
                }
            }
            
            # Clean up server config file if it was created
            if ($null -ne $nameTextBox -and -not $nameTextBox.IsDisposed -and -not [string]::IsNullOrWhiteSpace($nameTextBox.Text)) {
                $configPath = Join-Path $script:Paths.Root "servers"
                $configFile = Join-Path $configPath "$($nameTextBox.Text).json"
                if (Test-Path $configFile) {
                    try {
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[INFO] Removing server configuration file`n")
                        }
                        Remove-Item -Path $configFile -Force -ErrorAction Stop
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[INFO] Server configuration file removed`n")
                        }
                    }
                    catch {
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[ERROR] Failed to remove configuration: $($_.Exception.Message)`n")
                        }
                    }
                }
            }
            
            # Stop timer if running - with enhanced null checks
            if ($null -ne $script:jobInfo) {
                if ($null -ne $script:jobInfo.Timer) {
                    try {
                        $script:jobInfo.Timer.Stop()
                    }
                    catch {
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[WARN] Error stopping timer: $($_.Exception.Message)`n")
                        }
                    }
                }
            }
            
            # Reset UI state with null checks
            if ($null -ne $progressBar -and -not $progressBar.IsDisposed) {
                $progressBar.MarqueeAnimationSpeed = 0
            }
            
            if ($null -ne $createButton -and -not $createButton.IsDisposed) {
                $createButton.Enabled = $true
            }
            
            if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                $statusLabel.Text = "Installation cancelled"
            }
            
            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                $consoleOutput.AppendText("[INFO] Installation cancelled successfully`n")
            }
            
            Write-DashboardLog "Server installation cancelled by user" -Level INFO
        }
        catch {
            # Ensure we handle errors gracefully
            $errorMessage = $_.Exception.Message
            Write-DashboardLog "Error in cancellation handler: $errorMessage" -Level ERROR
            
            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                $consoleOutput.AppendText("[ERROR] Error in cancellation handler: $errorMessage`n")
            }
            
            if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                $statusLabel.Text = "Cancellation error"
            }
            
            # Try to recover the UI state
            if ($null -ne $createButton -and -not $createButton.IsDisposed) {
                $createButton.Enabled = $true
            }
            
            if ($null -ne $progressBar -and -not $progressBar.IsDisposed) {
                $progressBar.MarqueeAnimationSpeed = 0
            }
        }
    })

    # Modify the create button click handler to enable the cancel button when installation starts
    $createButton.Add_Click({
        try {
            Write-DashboardLog "Starting server creation process" -Level DEBUG
            
            # Verify SteamCmd path exists in script variable
            if (-not $script:steamCmdPath) {
                # Try to get it from registry again
                try {
                    $regPath = "HKLM:\Software\SkywereIndustries\servermanager"
                    if (Test-Path $regPath) {
                        $script:steamCmdPath = (Get-ItemProperty -Path $regPath -ErrorAction Stop).SteamCmdPath
                    }
                } catch {
                    # Silently handle registry error
                }
                
                if (-not $script:steamCmdPath) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "SteamCmd path not found in system registry. Please make sure SteamCmd is properly installed.",
                        "Configuration Error",
                        [System.Windows.Forms.MessageBoxButtons]::OK,
                        [System.Windows.Forms.MessageBoxIcon]::Error
                    )
                    Write-DashboardLog "SteamCmd path not found in registry" -Level ERROR
                    $consoleOutput.AppendText("[ERROR] SteamCmd path not found in registry. Server creation cannot continue.`n")
                    return
                }
            }
            
            # Validate that SteamCmd executable exists
            $steamCmdExe = Join-Path $script:steamCmdPath "steamcmd.exe"
            if (-not (Test-Path $steamCmdExe)) {
                [System.Windows.Forms.MessageBox]::Show(
                    "SteamCmd executable not found at: $steamCmdExe`nPlease make sure SteamCmd is properly installed.",
                    "Configuration Error",
                    [System.Windows.Forms.MessageBoxButtons]::OK,
                    [System.Windows.Forms.MessageBoxIcon]::Error
                )
                Write-DashboardLog "SteamCmd executable not found at: $steamCmdExe" -Level ERROR
                $consoleOutput.AppendText("[ERROR] SteamCmd executable not found at: $steamCmdExe`n")
                return
            }
            
            # Validate required fields
            if ([string]::IsNullOrWhiteSpace($nameTextBox.Text)) {
                [System.Windows.Forms.MessageBox]::Show("Server name is required.", "Validation Error")
                Write-DashboardLog "Validation failed: Server name missing" -Level ERROR
                return
            }

            if ([string]::IsNullOrWhiteSpace($appIdTextBox.Text)) {
                [System.Windows.Forms.MessageBox]::Show("Steam App ID is required.", "Validation Error")
                Write-DashboardLog "Validation failed: App ID missing" -Level ERROR
                return
            }

            # Validate App ID is numeric
            if (-not [int]::TryParse($appIdTextBox.Text, [ref]$null)) {
                [System.Windows.Forms.MessageBox]::Show("Steam App ID must be a number.", "Validation Error")
                Write-DashboardLog "Validation failed: Invalid App ID format" -Level ERROR
                return
            }

            # Validate server name doesn't already exist
            $existingConfigPath = Join-Path $script:Paths.Root "servers\$($nameTextBox.Text).json"
            if (Test-Path $existingConfigPath) {
                [System.Windows.Forms.MessageBox]::Show("A server with this name already exists.", "Validation Error")
                Write-DashboardLog "Validation failed: Server name already exists" -Level ERROR
                return
            }

            # Validate install directory if specified
            if (-not [string]::IsNullOrWhiteSpace($installDirTextBox.Text)) {
                $installPath = $installDirTextBox.Text
                Write-DashboardLog "Validating install path: $installPath" -Level DEBUG
                
                # Check if path is valid
                try {
                    $null = [System.IO.Path]::GetFullPath($installPath)
                }
                catch {
                    [System.Windows.Forms.MessageBox]::Show("Invalid installation path specified.", "Validation Error")
                    Write-DashboardLog "Validation failed: Invalid install path - $($_.Exception.Message)" -Level ERROR
                    return
                }

                # Check if path exists and is empty, or can be created
                if (Test-Path $installPath) {
                    if ((Get-ChildItem $installPath -Force).Count -gt 0) {
                        $result = [System.Windows.Forms.MessageBox]::Show(
                            "The specified installation directory is not empty. Continue anyway?",
                            "Warning",
                            [System.Windows.Forms.MessageBoxButtons]::YesNo,
                            [System.Windows.Forms.MessageBoxIcon]::Warning
                        )
                        if ($result -eq [System.Windows.Forms.DialogResult]::No) {
                            Write-DashboardLog "User cancelled due to non-empty directory" -Level DEBUG
                            return
                        }
                    }
                }
                else {
                    try {
                        $null = New-Item -ItemType Directory -Path $installPath -Force -ErrorAction Stop
                        Remove-Item $installPath -Force
                        Write-DashboardLog "Test directory creation successful: $installPath" -Level DEBUG
                    }
                    catch {
                        [System.Windows.Forms.MessageBox]::Show("Cannot create installation directory. Please check permissions.", "Validation Error")
                        Write-DashboardLog "Validation failed: Cannot create install directory - $($_.Exception.Message)" -Level ERROR
                        return
                    }
                }
            }

            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Installing server..."
            $createButton.Enabled = $false
            
            # Enable cancel button when installation starts
            $cancelButton.Enabled = $true
            
            # Reset cancellation flag
            $script:installCancelled = $false

            # Clear console output
            $consoleOutput.Clear()
            $consoleOutput.AppendText("Starting server installation...`n")
            $consoleOutput.AppendText("[INFO] SteamCmd path: $script:steamCmdPath`n")
            $consoleOutput.AppendText("[INFO] Server name: $($nameTextBox.Text)`n")
            $consoleOutput.AppendText("[INFO] App ID: $($appIdTextBox.Text)`n")
            
            # Show the appropriate install directory message
            if ([string]::IsNullOrWhiteSpace($installDirTextBox.Text)) {
                $defaultPath = Join-Path (Join-Path $script:steamCmdPath "steamapps\common") $nameTextBox.Text
                $consoleOutput.AppendText("[INFO] Using default install directory: $defaultPath`n")
            } else {
                $consoleOutput.AppendText("[INFO] Install directory: $($installDirTextBox.Text)`n")
            }

            # Log steam credentials type (anonymously to not expose credentials)
            Write-DashboardLog "Steam login type: $(if ($SteamCredentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG
            
            # Log job parameters (except credentials)
            Write-DashboardLog "Job parameters - Name: $($nameTextBox.Text), AppID: $($appIdTextBox.Text), Install Dir: $($installDirTextBox.Text), Root: $($script:Paths.Root)" -Level DEBUG

            # Create a hashtable to store job info - add this line to create a proper script-scope variable
            $script:jobInfo = @{
                Job = $null
                Timer = $null
                SteamCmdPath = $script:steamCmdPath
            }

            # Modify job scriptblock to include output
            Write-DashboardLog "Starting background job for server installation" -Level INFO
            try {
                # Create a job with explicit parameter handling
                $jobParams = @{
                    ScriptBlock = $script:jobScriptBlock
                    ArgumentList = @(
                        $nameTextBox.Text,
                        $appIdTextBox.Text,
                        $installDirTextBox.Text,
                        $script:Paths.Root,
                        $SteamCredentials,
                        $script:steamCmdPath
                    )
                    Name = "ServerCreation_$($nameTextBox.Text)"
                }
                
                # Start the job with proper error handling
                $job = $null
                try {
                    $job = Start-Job @jobParams -ErrorAction Stop
                } 
                catch {
                    throw "Failed to start job: $($_.Exception.Message)"
                }
                
                # Check if job was created successfully
                if ($null -eq $job) {
                    throw "Start-Job returned null. Job creation failed."
                }
                
                # Store job reference immediately in script scope with verification
                $script:jobInfo = @{
                    Job = $job
                    Timer = $null
                    SteamCmdPath = $script:steamCmdPath
                }
                
                # Double-check job is accessible before proceeding
                if ($null -eq $script:jobInfo.Job) {
                    throw "Job reference could not be stored in script scope."
                }
                
                Write-DashboardLog "Job started successfully with ID: $($job.Id)" -Level DEBUG
            }
            catch {
                Write-DashboardLog "Failed to start job: $($_.Exception.Message)" -Level ERROR
                $consoleOutput.AppendText("[ERROR] Failed to start server creation job: $($_.Exception.Message)`n")
                $statusLabel.Text = "Job creation failed!"
                $createButton.Enabled = $true
                return
            }

            # Create timer to monitor job and update console
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 100
            
            # Store timer at script scope for safety
            $script:currentJobTimer = $timer
            
            # Define success callback as a script block OUTSIDE the Initialize-JobMonitorTimer call
            $successCallback = {
                param($result)
                
                try {
                    # Add explicit debug logging
                    Write-DashboardLog "OnSuccess handler triggered with result: $($result | ConvertTo-Json -Depth 1)" -Level DEBUG
                    
                    # Check if installation was cancelled
                    if ($script:installCancelled) {
                        # Just reset the UI elements since cleanup is handled in cancel button click
                        if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                            $cancelButton.Enabled = $false
                        }
                        return
                    }
                    
                    # Process results with null-safe property access
                    $isSuccess = if ($result -is [hashtable]) { 
                        $result.ContainsKey('Success') -and $result.Success -eq $true 
                    } else { 
                        $null -ne $result -and $null -ne $result.PSObject.Properties['Success'] -and $result.Success -eq $true 
                    }
                    
                    $resultMessage = if ($result -is [hashtable]) { 
                        if($result.ContainsKey('Message')) { $result.Message } else { "No message provided" }
                    } else { 
                        if($null -ne $result -and $null -ne $result.PSObject.Properties['Message']) { $result.Message } else { "No message provided" }
                    }
                    
                    $resultPath = if ($result -is [hashtable]) { 
                        if($result.ContainsKey('InstallPath')) { $result.InstallPath } else { $null }
                    } else { 
                        if($null -ne $result -and $null -ne $result.PSObject.Properties['InstallPath']) { $result.InstallPath } else { $null }
                    }
                    
                    if ($isSuccess) {
                        # Always check UI element state before accessing
                        if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                            $statusLabel.Text = "Installation complete!"
                        }
                        
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[SUCCESS] Server created successfully.`n")
                        }
                        
                        # Disable cancel button on completion
                        if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                            $cancelButton.Enabled = $false
                        }
                        
                        # Log differently based on whether path is available
                        if ($resultPath) {
                            Write-DashboardLog "Server created successfully at $resultPath" -Level INFO
                            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                $consoleOutput.AppendText("[INFO] Installation path: $resultPath`n")
                            }
                        } else {
                            Write-DashboardLog "Server created successfully" -Level INFO
                        }
                        
                        # Update server list first
                        try {
                            Update-ServerList -ForceRefresh
                        }
                        catch {
                            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                $consoleOutput.AppendText("[WARN] Failed to update server list: $($_.Exception.Message)`n")
                            }
                        }
                        
                        # Show a simple message box first before trying to close the form
                        [System.Windows.Forms.MessageBox]::Show("Server created successfully!", "Success")
                        
                        # Now close the form directly with proper error handling
                        try {
                            if ($null -ne $createForm -and -not $createForm.IsDisposed) {
                                if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                    $consoleOutput.AppendText("[INFO] Closing creation form...`n")
                                }
                                
                                $createForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                                $createForm.Close()
                            }
                        }
                        catch {
                            Write-DashboardLog "Error closing form: $($_.Exception.Message)" -Level ERROR
                        }
                    } else {
                        if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                            $statusLabel.Text = "Installation failed!"
                        }
                        
                        $errorMsg = if ($resultMessage) { $resultMessage } else { "Unknown error" }
                        
                        if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                            $consoleOutput.AppendText("[ERROR] Failed to create server: $errorMsg`n")
                        }
                        
                        # Disable cancel button on failure
                        if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                            $cancelButton.Enabled = $false
                        }
                        
                        if ($result -and $null -ne $result.PSObject.Properties['StackTrace']) {
                            if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                                $consoleOutput.AppendText("[ERROR] Stack trace: $($result.StackTrace)`n")
                            }
                        }
                        
                        Write-DashboardLog "Server creation failed: $errorMsg" -Level ERROR
                        
                        if ($null -ne $createButton -and -not $createButton.IsDisposed) {
                            $createButton.Enabled = $true
                        }
                    }
                }
                catch {
                    Write-DashboardLog "Error in success handler: $($_.Exception.Message)" -Level ERROR
                    Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level ERROR
                    
                    if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                        $consoleOutput.AppendText("[ERROR] Error in success handler: $($_.Exception.Message)`n")
                    }
                    
                    # Try one more time to close the form
                    try {
                        if ($null -ne $createForm -and -not $createForm.IsDisposed) {
                            $createForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                            $createForm.Close()
                        }
                    }
                    catch {
                        # Just log, can't do much more
                        Write-DashboardLog "Final attempt to close form failed: $($_.Exception.Message)" -Level ERROR
                    }
                }
            }
            
            # Define failure callback as a script block
            $failureCallback = {
                param($errorMessage)
                
                if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                    $statusLabel.Text = "Installation failed!"
                }
                
                if ($null -ne $consoleOutput -and -not $consoleOutput.IsDisposed) {
                    $consoleOutput.AppendText("[ERROR] $errorMessage`n")
                }
                
                if ($null -ne $createButton -and -not $createButton.IsDisposed) {
                    $createButton.Enabled = $true
                }
                
                # Disable cancel button on error
                if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                    $cancelButton.Enabled = $false
                }
            }
            
            # Ensure we maintain references to all objects to prevent garbage collection
            $script:jobInfo = @{
                Job = $job
                Timer = $timer
                IsJobCompleted = $false
                VerificationStartTime = Get-Date
                OnSuccess = $successCallback
                OnFailure = $failureCallback
                ConsoleOutput = $consoleOutput
                StatusLabel = $statusLabel
                ProgressBar = $progressBar
                EnableButton = $createButton
                FormReference = $createForm
            }
            
            # Update timer tick event handler with proper null checks
            Initialize-JobMonitorTimer -Timer $timer -JobInfo $script:jobInfo `
                -ConsoleOutput $consoleOutput -StatusLabel $statusLabel `
                -ProgressBar $progressBar -EnableButton $createButton `
                -OnSuccess $successCallback `
                -OnFailure $failureCallback
            
            Write-DashboardLog "Starting job monitoring timer" -Level DEBUG
            $timer.Start()
        }
        catch {
            Write-DashboardLog "Critical error in server creation: $($_.Exception.Message)" -Level ERROR
            Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level ERROR
            $consoleOutput.AppendText("[ERROR] Critical error: $($_.Exception.Message)`n")
            $consoleOutput.AppendText("[ERROR] Stack trace: $($_.ScriptStackTrace)`n")
            $statusLabel.Text = "Critical error!"
            $createButton.Enabled = $true
            $cancelButton.Enabled = $false
        }
    })

    # Add all controls to form
    $createForm.Controls.AddRange(@(
        $nameLabel, $nameTextBox,
        $appIdLabel, $appIdTextBox,
        $installDirLabel, $installDirTextBox, $installDirInfo,
        $browseButton, $consoleOutput,
        $statusLabel, $progressBar,
        $createButton, $cancelButton
    ))

    # Add form closing handler to clean up properly
    $createForm.Add_FormClosing({
        param($sender, $e)
        
        # If the dialog result is OK, allow the form to close without prompting
        if ($sender.DialogResult -eq [System.Windows.Forms.DialogResult]::OK) {
            Write-DashboardLog "Form closing with DialogResult OK - allowing close" -Level DEBUG
            return
        }
        
        # Confirm cancellation if an installation is in progress
        $shouldCancel = $false
        if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
            $shouldCancel = $cancelButton.Enabled
        }
        
        if ($shouldCancel) {
            $result = [System.Windows.Forms.MessageBox]::Show(
                "An installation is in progress. Do you want to cancel it?",
                "Confirm Exit",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Question
            )
            
            if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
                # Trigger cancel button click to clean up
                if ($null -ne $cancelButton -and -not $cancelButton.IsDisposed) {
                    $cancelButton.PerformClick()
                }
                
                # Delay closing to allow cleanup to start
                $e.Cancel = $true
                $script:pendingFormClose = $true
                
                # Set a timer to close the form after a short delay
                $closeTimer = New-Object System.Windows.Forms.Timer
                $closeTimer.Interval = 1000
                $closeTimer.Add_Tick({
                    $closeTimer.Stop()
                    
                    # Use try/catch in case the form was already closed
                    try {
                        if ($null -ne $createForm -and -not $createForm.IsDisposed) {
                            $createForm.Close()
                        }
                    } 
                    catch {
                        # Ignore errors during forced close
                    }
                    finally {
                        # Clean up the timer
                        $closeTimer.Dispose()
                    }
                })
                $closeTimer.Start()
            }
            else {
                # Cancel the form closing
                $e.Cancel = $true
            }
        }
    })

    $createForm.ShowDialog()
}

function Remove-IntegratedGameServer {
    $removeForm = New-Object System.Windows.Forms.Form
    $removeForm.Text = "Remove Game Server"
    $removeForm.Size = New-Object System.Drawing.Size(400,200)
    $removeForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)

    $serverComboBox = New-Object System.Windows.Forms.ComboBox
    $serverComboBox.Location = New-Object System.Drawing.Point(120,20)
    $serverComboBox.Size = New-Object System.Drawing.Size(250,20)
    $serverComboBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList

    # Populate server list
    $configPath = Join-Path $serverManagerDir "servers"
    if (Test-Path $configPath) {
        Get-ChildItem -Path $configPath -Filter "*.json" | ForEach-Object {
            $serverComboBox.Items.Add($_.BaseName)
        }
    }

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(120,80)
    $progressBar.Size = New-Object System.Drawing.Size(250,20)
    $progressBar.Style = 'Marquee'
    $progressBar.MarqueeAnimationSpeed = 0

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(120,60)
    $statusLabel.Size = New-Object System.Drawing.Size(250,20)
    $statusLabel.Text = ""

    # Create a hidden console output for job monitoring
    $consoleOutput = New-Object System.Windows.Forms.RichTextBox
    $consoleOutput.Location = New-Object System.Drawing.Point(-2000,-2000)
    $consoleOutput.Size = New-Object System.Drawing.Size(10,10)
    $consoleOutput.Visible = $false

    $removeButton = New-Object System.Windows.Forms.Button
    $removeButton.Text = "Remove"
    $removeButton.Location = New-Object System.Drawing.Point(120,110)
    $removeButton.Add_Click({
        $serverName = $serverComboBox.SelectedItem

        if ([string]::IsNullOrEmpty($serverName)) {
            [System.Windows.Forms.MessageBox]::Show("Please select a server.", "Error")
            Write-DashboardLog "No server selected for removal" -Level WARN
            return
        }

        Write-DashboardLog "Preparing to remove server: $serverName" -Level INFO

        $confirmResult = [System.Windows.Forms.MessageBox]::Show(
            "Are you sure you want to remove the server '$serverName'?",
            "Confirm Removal",
            [System.Windows.Forms.MessageBoxButtons]::YesNo
        )

        if ($confirmResult -eq [System.Windows.Forms.DialogResult]::Yes) {
            $progressBar.MarqueeAnimationSpeed = 30
            $statusLabel.Text = "Removing server..."
            $removeButton.Enabled = $false
            
            Write-DashboardLog "Starting server removal job for: $serverName" -Level DEBUG

            # Create a dedicated script-level variable specifically for removal
            # to avoid conflicts with other operations
            $script:removalJobInfo = @{
                Job = $null
                Timer = $null
                IsJobCompleted = $false
                OnSuccess = $null
                OnFailure = $null
                ConsoleOutput = $consoleOutput
                StatusLabel = $statusLabel
                ProgressBar = $progressBar
                EnableButton = $removeButton
                FormReference = $removeForm
                VerificationStartTime = Get-Date
                SteamCmdPath = $script:steamCmdPath
                ServerName = $serverName
            }
            
            # Start removal in background job
            try {
                $job = Start-Job -ScriptBlock {
                    param($serverName, $serverManagerDir)
                    
                    try {
                        Write-Output "[INFO] Starting server removal: $serverName"
                        # Stop server if running
                        $configFile = Join-Path $serverManagerDir "servers\$serverName.json"
                        Write-Output "[DEBUG] Config file path: $configFile"
                        
                        if (Test-Path $configFile) {
                            Write-Output "[DEBUG] Reading server configuration"
                            try {
                                $serverConfig = Get-Content $configFile -Raw -ErrorAction Stop | ConvertFrom-Json
                                Write-Output "[DEBUG] Server config loaded: InstallDir=$($serverConfig.InstallDir)"
                                
                                # Check if server has a process ID registered
                                if ($serverConfig.ProcessId) {
                                    Write-Output "[INFO] Server has process ID registered: $($serverConfig.ProcessId)"
                                    try {
                                        $process = Get-Process -Id $serverConfig.ProcessId -ErrorAction SilentlyContinue
                                        if ($process) {
                                            Write-Output "[INFO] Found running server process, attempting to stop"
                                            $process.Kill()
                                            Write-Output "[INFO] Process terminated successfully"
                                        } else {
                                            Write-Output "[INFO] No running process found with ID $($serverConfig.ProcessId)"
                                        }
                                    } catch {
                                        Write-Output "[WARN] Failed to stop server process: $($_.Exception.Message)"
                                    }
                                }
                            } catch {
                                Write-Output "[WARN] Failed to read server config: $($_.Exception.Message)"
                            }
                            
                            Write-Output "[INFO] Removing server configuration file"
                            try {
                                Remove-Item $configFile -Force -ErrorAction Stop
                                Write-Output "[INFO] Server configuration file removed successfully"
                            }
                            catch {
                                throw "Failed to remove configuration file: $($_.Exception.Message)"
                            }
                        } else {
                            Write-Output "[WARN] Server configuration file not found: $configFile"
                            
                            # Even if file is not found, we'll consider it a success
                            # since the goal was to remove the server and it's no longer there
                            Write-Output "[RESULT-OBJECT-BEGIN]"
                            Write-Output (@{
                                Success = $true
                                Message = "Server configuration file not found - server is already removed"
                                ServerName = $serverName
                            } | ConvertTo-Json)
                            Write-Output "[RESULT-OBJECT-END]"
                            
                            return @{
                                Success = $true
                                Message = "Server configuration file not found - server is already removed"
                                ServerName = $serverName
                            }
                        }
                        
                        Write-Output "[RESULT-OBJECT-BEGIN]"
                        Write-Output (@{
                            Success = $true
                            Message = "Server removed successfully"
                            ServerName = $serverName
                        } | ConvertTo-Json)
                        Write-Output "[RESULT-OBJECT-END]"
                        
                        return @{
                            Success = $true
                            Message = "Server removed successfully"
                            ServerName = $serverName
                        }
                    }
                    catch {
                        Write-Output "[ERROR] Server removal failed: $($_.Exception.Message)"
                        Write-Output "[ERROR] Stack trace: $($_.ScriptStackTrace)"
                        
                        Write-Output "[RESULT-OBJECT-BEGIN]"
                        Write-Output (@{
                            Success = $false
                            Message = $_.Exception.Message
                            StackTrace = $_.ScriptStackTrace
                        } | ConvertTo-Json)
                        Write-Output "[RESULT-OBJECT-END]"
                        
                        return @{
                            Success = $false
                            Message = $_.Exception.Message
                            StackTrace = $_.ScriptStackTrace
                        }
                    }
                } -ArgumentList $serverName, $script:Paths.Root
                
                # Better job null check with message
                if ($null -eq $job) {
                    throw "Failed to create server removal job - Start-Job returned null"
                }
                
                Write-DashboardLog "Server removal job started with ID: $($job.Id)" -Level DEBUG
                $script:removalJobInfo.Job = $job
            }
            catch {
                Write-DashboardLog "Failed to start server removal job: $($_.Exception.Message)" -Level ERROR
                $statusLabel.Text = "Failed to start removal job!"
                $removeButton.Enabled = $true
                [System.Windows.Forms.MessageBox]::Show("Failed to start server removal: $($_.Exception.Message)", "Error")
                return
            }

            # Define success and failure callbacks BEFORE initializing the timer
            $successCallback = {
                param($result)
                
                try {
                    # Check for null result and provide fallback
                    if ($null -eq $result) {
                        $result = @{
                            Success = $true
                            Message = "Server removed successfully (no details returned)"
                            ServerName = $script:removalJobInfo.ServerName
                        }
                    }
                    
                    Write-DashboardLog "Server removal job completed: $($result | ConvertTo-Json -Depth 1 -ErrorAction SilentlyContinue)" -Level DEBUG
                    
                    # Handle both hashtable and object formats with safe checks
                    $isSuccess = $true
                    $serverName = $script:removalJobInfo.ServerName
                    
                    # Extract server name from result safely
                    if ($result -is [hashtable]) {
                        if ($result.ContainsKey('ServerName')) { 
                            $serverName = $result.ServerName 
                        }
                        if ($result.ContainsKey('Success')) { 
                            $isSuccess = $result.Success -eq $true 
                        }
                    } elseif ($null -ne $result -and $null -ne $result.PSObject -and $null -ne $result.PSObject.Properties) {
                        if ($null -ne $result.PSObject.Properties['ServerName']) { 
                            $serverName = $result.ServerName 
                        }
                        if ($null -ne $result.PSObject.Properties['Success']) { 
                            $isSuccess = $result.Success -eq $true 
                        }
                    }
                    
                    # Get message with fallback
                    $resultMessage = if ($result -is [hashtable]) { 
                        if($result.ContainsKey('Message')) { $result.Message } else { "Server removed successfully" }
                    } else { 
                        if($null -ne $result -and $null -ne $result.PSObject.Properties['Message']) { 
                            $result.Message 
                        } else { 
                            "Server removed successfully" 
                        }
                    }
                    
                    if ($isSuccess) {
                        # Only display UI updates if controls still exist
                        if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                            $statusLabel.Text = "Server removed successfully!"
                        }
                        
                       
                        Write-DashboardLog "Server removal completed successfully: $serverName" -Level INFO
                        
                        try {
                            [System.Windows.Forms.MessageBox]::Show("Server removed successfully.", "Success")
                            
                            # Update server list to reflect changes
                            if ($null -ne $serverComboBox -and -not $serverComboBox.IsDisposed) {
                                $serverComboBox.Items.Remove($serverName)
                            }
                            
                            # Update the global server list
                            Update-ServerList
                            
                            # Close form with proper error handling
                            if ($null -ne $removeForm -and -not $removeForm.IsDisposed) {
                                try {
                                    $removeForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
                                    $removeForm.Close()
                                }
                                catch {
                                    Write-DashboardLog "Error closing form: $($_.Exception.Message)" -Level ERROR
                                    # Try alternative closing method
                                    try { $removeForm.Dispose() } catch { }
                                }
                            }
                        }
                        catch {
                            Write-DashboardLog "Error during form completion: $($_.Exception.Message)" -Level ERROR
                        }
                    } else {
                        $errorMsg = if ([string]::IsNullOrEmpty($resultMessage)) { "Unknown error" } else { $resultMessage }
                        
                        if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                            $statusLabel.Text = "Failed to remove server!"
                        }
                        
                        Write-DashboardLog "Server removal failed: $errorMsg" -Level ERROR
                        [System.Windows.Forms.MessageBox]::Show("Failed to remove server: $errorMsg", "Error")
                        
                        if ($null -ne $removeButton -and -not $removeButton.IsDisposed) {
                            $removeButton.Enabled = $true
                        }
                    }
                }
                catch {
                    Write-DashboardLog "Error in server removal success handler: $($_.Exception.Message)" -Level ERROR
                    Write-DashboardLog "Stack trace: $($_.ScriptStackTrace)" -Level ERROR
                    
                    # Fallback - ensure controls are reset
                    if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                        $statusLabel.Text = "Error processing results!"
                    }
                    
                    if ($null -ne $removeButton -and -not $removeButton.IsDisposed) {
                        $removeButton.Enabled = $true
                    }
                    
                    if ($null -ne $progressBar -and -not $progressBar.IsDisposed) {
                        $progressBar.MarqueeAnimationSpeed = 0
                    }
                }
            }
            
            $failureCallback = {
                param($errorMessage)
                
                # Log error and display message
                Write-DashboardLog "Remove server error: $errorMessage" -Level ERROR
                
                # Update UI if components still exist
                if ($null -ne $statusLabel -and -not $statusLabel.IsDisposed) {
                    $statusLabel.Text = "Failed to remove server!"
                }
                
                if ($null -ne $removeButton -and -not $removeButton.IsDisposed) {
                    $removeButton.Enabled = $true
                }
                
                if ($null -ne $progressBar -and -not $progressBar.IsDisposed) {
                    $progressBar.MarqueeAnimationSpeed = 0
                }
                
                [System.Windows.Forms.MessageBox]::Show("Failed to remove server: $errorMessage", "Error")
            }
            
            # Store callbacks in the job info
            $script:removalJobInfo.OnSuccess = $successCallback
            $script:removalJobInfo.OnFailure = $failureCallback

            # Monitor the job with improved thread safety
            $timer = New-Object System.Windows.Forms.Timer
            $timer.Interval = 500
            $script:removalJobInfo.Timer = $timer
            
            # When initializing timer, use explicit script:removalJobInfo instead of JobInfo to avoid potential override
            Initialize-JobMonitorTimer -Timer $timer -JobInfo $script:removalJobInfo `
                -ConsoleOutput $consoleOutput -StatusLabel $statusLabel `
                -ProgressBar $progressBar -EnableButton $removeButton `
                -OnSuccess $successCallback `
                -OnFailure $failureCallback

            Write-DashboardLog "Starting server removal job monitoring timer" -Level DEBUG
            $timer.Start()
        } else {
            Write-DashboardLog "User cancelled server removal for: $serverName" -Level DEBUG
        }
    })

    $removeForm.Controls.AddRange(@(
        $nameLabel, $serverComboBox,
        $removeButton, $progressBar, $statusLabel, 
        $consoleOutput
    ))

    $removeForm.ShowDialog()
}

function New-IntegratedAgent {
    $agentForm = New-Object System.Windows.Forms.Form
    $agentForm.Text = "Add Agent"
    $agentForm.Size = New-Object System.Drawing.Size(400,300)
    $agentForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Agent Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)
    
    $nameBox = New-Object System.Windows.Forms.TextBox
    $nameBox.Location = New-Object System.Drawing.Point(120,20)
    $nameBox.Size = New-Object System.Drawing.Size(250,20)

    $ipLabel = New-Object System.Windows.Forms.Label
    $ipLabel.Text = "IP Address:"
    $ipLabel.Location = New-Object System.Drawing.Point(10,50)
    $ipLabel.Size = New-Object System.Drawing.Size(100,20)

    $ipBox = New-Object System.Windows.Forms.TextBox
    $ipBox.Location = New-Object System.Drawing.Point(120,50)
    $ipBox.Size = New-Object System.Drawing.Size(250,20)

    $portLabel = New-Object System.Windows.Forms.Label
    $portLabel.Text = "Port:"
    $portLabel.Location = New-Object System.Drawing.Point(10,80)
    $portLabel.Size = New-Object System.Drawing.Size(100,20)

    $portBox = New-Object System.Windows.Forms.TextBox
    $portBox.Location = New-Object System.Drawing.Point(120,80)
    $portBox.Size = New-Object System.Drawing.Size(250,20)
    $portBox.Text = "8080"

    $addButton = New-Object System.Windows.Forms.Button
    $addButton.Text = "Add Agent"
    $addButton.Location = New-Object System.Drawing.Point(120,120)
    $addButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text) -or 
            [string]::IsNullOrWhiteSpace($ipBox.Text) -or 
            [string]::IsNullOrWhiteSpace($portBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("Please fill in all fields.", "Error")
            return
        }

        try {
            $agentConfig = @{
                Name = $nameBox.Text
                IP = $ipBox.Text
                Port = $portBox.Text
                Added = Get-Date -Format "o"
            }

            $agentsPath = Join-Path $serverManagerDir "agents"
            if (-not (Test-Path $agentsPath)) {
                New-Item -ItemType Directory -Path $agentsPath -Force | Out-Null
            }

            $agentConfig | ConvertTo-Json | Set-Content -Path (Join-Path $agentsPath "$($nameBox.Text).json")
            [System.Windows.Forms.MessageBox]::Show("Agent added successfully!", "Success")
            $agentForm.Close()
        }
        catch {
            [System.Windows.Forms.MessageBox]::Show("Failed to add agent: $($_.Exception.Message)", "Error")
        }
    })

    $agentForm.Controls.AddRange(@(
        $nameLabel, $nameBox,
        $ipLabel, $ipBox,
        $portLabel, $portBox,
        $addButton
    ))

    $agentForm.ShowDialog()
}

# Create buttons with similar functionality to web dashboard
$addButton = New-Object System.Windows.Forms.Button
$addButton.Location = New-Object System.Drawing.Point(0,0)
$addButton.Size = New-Object System.Drawing.Size(100,30)
$addButton.Text = "Add Server"
$addButton.Add_Click({
    # Get Steam credentials first
    $credentials = Get-SteamCredentials
    if ($credentials -eq $null) {
        Write-DashboardLog "User cancelled Steam login" -Level DEBUG
        return
    }

    Write-DashboardLog "Steam login type: $(if ($credentials.Anonymous) { 'Anonymous' } else { 'Account' })" -Level DEBUG
    New-IntegratedGameServer -SteamCredentials $credentials
})

$removeButton = New-Object System.Windows.Forms.Button
$removeButton.Location = New-Object System.Drawing.Point(110,0)
$removeButton.Size = New-Object System.Drawing.Size(100,30)
$removeButton.Text = "Remove Server"
$removeButton.Add_Click({
    Remove-IntegratedGameServer
})

$importButton = New-Object System.Windows.Forms.Button
$importButton.Location = New-Object System.Drawing.Point(220,0)
$importButton.Size = New-Object System.Drawing.Size(100,30)
$importButton.Text = "Import Server"
$importButton.Add_Click({
    Import-ExistingServer
})

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Location = New-Object System.Drawing.Point(330,0)
$refreshButton.Size = New-Object System.Drawing.Size(100,30)
$refreshButton.Text = "Refresh"
$refreshButton.Add_Click({
    Update-ServerList -ForceRefresh
    Update-SystemInfoNow
})

# Fix the Size property for the sync button
$syncButton = New-Object System.Windows.Forms.Button
$syncButton.Location = New-Object System.Drawing.Point(440, 0)
$syncButton.Size = New-Object System.Drawing.Size(100, 30)
$syncButton.Text = "Sync All"
$syncButton.Add_Click({
    Sync-AllDashboards
})

# Add new agent button next to sync button
$agentButton = New-Object System.Windows.Forms.Button
$agentButton.Location = New-Object System.Drawing.Point(550,0)
$agentButton.Size = New-Object System.Drawing.Size(100,30)
$agentButton.Text = "Add Agent"
$agentButton.Add_Click({
    New-IntegratedAgent
})

# Create status label for WebSocket connection
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Dock = [System.Windows.Forms.DockStyle]::Fill
$statusLabel.Height = 25
$statusLabel.Padding = New-Object System.Windows.Forms.Padding(10, 0, 10, 5)
$statusLabel.Text = "WebSocket: Disconnected"
$statusLabel.ForeColor = [System.Drawing.Color]::Red

# Add buttons to flow panel
@($addButton, $removeButton, $importButton, $refreshButton, $syncButton, $agentButton) | ForEach-Object {
    $_.AutoSize = $true
    $_.Margin = New-Object System.Windows.Forms.Padding(5)
    $buttonFlowPanel.Controls.Add($_)
}
$buttonPanel.Controls.Add($buttonFlowPanel)

# Assemble all UI components into container
$containerPanel.Controls.Add($mainPanel, 0, 0)
$containerPanel.Controls.Add($buttonPanel, 0, 1)
$containerPanel.Controls.Add($statusLabel, 0, 2)

# CRITICAL FIX: Add the container panel to the form - this was missing!
$form.Controls.Add($containerPanel)

# Refactored function to update the server list with parameters for customization
function Update-ServerList {
    param (
        [Parameter(Mandatory=$false)]
        [switch]$SkipWebSocketBroadcast,
        
        [Parameter(Mandatory=$false)]
        [switch]$ForceRefresh
    )
    
    # Skip update if it's been less than 5 seconds since the last update and ForceRefresh isn't specified
    if (-not $ForceRefresh -and 
        ($null -ne $script:lastServerListUpdate) -and 
        ((Get-Date) - $script:lastServerListUpdate).TotalSeconds -lt 5) {
        Write-DashboardLog "Skipping server list update - last update was less than 5 seconds ago" -Level DEBUG
        return
    }
    
    $listView.Items.Clear()
    
    # Get the servers directory from registry
    $serversPath = Join-Path $script:Paths.Root "servers"
    
    if (Test-Path $serversPath) {
        $serverConfigs = Get-ChildItem -Path $serversPath -Filter "*.json"
        foreach ($configFile in $serverConfigs) {
            try {
                $serverConfig = Get-Content $configFile.FullName -Raw | ConvertFrom-Json
                
                $item = New-Object System.Windows.Forms.ListViewItem($serverConfig.Name)
                
                # Check if server is running
                $status = "Offline"
                $cpuUsage = "N/A"
                $memoryUsage = "N/A"
                $uptime = "N/A"
                
                # Get process if running
                if ($serverConfig.ProcessId) {
                    $process = Get-Process -Id $serverConfig.ProcessId -ErrorAction SilentlyContinue
                    if ($process) {
                        $status = "Running"
                        $cpuUsage = "Checking..."
                        $memoryUsage = [Math]::Round($process.WorkingSet64 / 1MB, 2) + " MB"
                        $uptime = "Checking..."
                    }
                }
                
                $item.SubItems.Add($status)
                $item.SubItems.Add($cpuUsage)
                $item.SubItems.Add($memoryUsage)
                $item.SubItems.Add($uptime)
                
                $listView.Items.Add($item)
            }
            catch {
                Write-DashboardLog "Failed to process server config $($configFile.Name): $_" -Level ERROR
            }
        }
    }
    
    # Only try to broadcast update if we're not in offline mode and not explicitly skipped
    if (-not $SkipWebSocketBroadcast -and -not $script:offlineMode) {
        # First verify WebSocket server is available and we're connected
        if ($script:isWebSocketConnected -or (Test-WebSocketServer -Silent)) {
            # If server is available but we're not connected, try to connect
            if (-not $script:isWebSocketConnected) {
                Connect-WebSocketServer -Silent
            }
            
            # Now check if we have a valid connection
            if ($script:isWebSocketConnected -and $script:webSocketClient -and 
                $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                
                try {
                    $serverData = $listView.Items | ForEach-Object {
                        @{
                            Name = $_.Text
                            Status = $_.SubItems[1].Text
                            CPU = $_.SubItems[2].Text
                            Memory = $_.SubItems[3].Text
                            Uptime = $_.SubItems[4].Text
                        }
                    }
                    
                    $updateMessage = @{
                        Type = "ServerListUpdate"
                        Servers = $serverData
                        Timestamp = Get-Date -Format "o"
                    } | ConvertTo-Json
                    
                    $buffer = [System.Text.Encoding]::UTF8.GetBytes($updateMessage)
                    $segment = [ArraySegment[byte]]::new($buffer)
                    
                    $script:webSocketClient.SendAsync(
                        $segment,
                        [System.Net.WebSockets.WebSocketMessageType]::Text,
                        $true,
                        [System.Threading.CancellationToken]::None
                    ).Wait(1000)
                    
                    Write-DashboardLog "Server list update broadcast to WebSocket clients" -Level DEBUG
                } catch {
                    Write-DashboardLog "Failed to send server list update: $_" -Level ERROR
                }
            }
        }
    }
}

# Add the Import Server function
function Import-ExistingServer {
    $importForm = New-Object System.Windows.Forms.Form
    $importForm.Text = "Import Existing Server"
    $importForm.Size = New-Object System.Drawing.Size(450,250)
    $importForm.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10,20)
    $nameLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($nameLabel)

    $nameBox = New-Object System.Windows.Forms.TextBox
    $nameBox.Location = New-Object System.Drawing.Point(120,20)
    $nameBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($nameBox)

    $pathLabel = New-Object System.Windows.Forms.Label
    $pathLabel.Text = "Server Path:"
    $pathLabel.Location = New-Object System.Drawing.Point(10,50)
    $pathLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($pathLabel)

    $pathBox = New-Object System.Windows.Forms.TextBox
    $pathBox.Location = New-Object System.Drawing.Point(120,50)
    $pathBox.Size = New-Object System.Drawing.Size(250,20)
    $importForm.Controls.Add($pathBox)

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse"
    $browseButton.Location = New-Object System.Drawing.Point(380,48)
    $browseButton.Size = New-Object System.Drawing.Size(40,24)
    $browseButton.Add_Click({
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "Select Server Directory"
        if ($folderBrowser.ShowDialog() -eq 'OK') {
            $pathBox.Text = $folderBrowser.SelectedPath
        }
    })
    $importForm.Controls.Add($browseButton)

    $appIdLabel = New-Object System.Windows.Forms.Label
    $appIdLabel.Text = "Steam AppID:"
    $appIdLabel.Location = New-Object System.Drawing.Point(10,80)
    $appIdLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($appIdLabel)

    $appIdBox = New-Object System.Windows.Forms.TextBox
    $appIdBox.Location = New-Object System.Drawing.Point(120,80)
    $appIdBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($appIdBox)

    $execPathLabel = New-Object System.Windows.Forms.Label
    $execPathLabel.Text = "Executable Path:"
    $execPathLabel.Location = New-Object System.Drawing.Point(10,110)
    $execPathLabel.Size = New-Object System.Drawing.Size(100,20)
    $importForm.Controls.Add($execPathLabel)

    $execPathBox = New-Object System.Windows.Forms.TextBox
    $execPathBox.Location = New-Object System.Drawing.Point(120,110)
    $execPathBox.Size = New-Object System.Drawing.Size(300,20)
    $importForm.Controls.Add($execPathBox)

    $importButton = New-Object System.Windows.Forms.Button
    $importButton.Text = "Import"
    $importButton.Location = New-Object System.Drawing.Point(180,170)
    $importButton.Size = New-Object System.Drawing.Size(90,30)
    $importButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text) -or 
            [string]::IsNullOrWhiteSpace($pathBox.Text) -or 
            [string]::IsNullOrWhiteSpace($appIdBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("Server name, path and AppID are required fields.", "Error")
            return
        }

        # Validate if the path exists
        if (-not (Test-Path $pathBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show("The specified server path does not exist.", "Error")
            return
        }

        try {
            # Create server configuration
            $serverConfig = @{
                Name = $nameBox.Text
                InstallDir = $pathBox.Text
                AppID = $appIdBox.Text
                ExecutablePath = $execPathBox.Text
                Created = Get-Date -Format "o"
                LastUpdate = Get-Date -Format "o"
                Imported = $true
            }

            # Save server configuration
            $configPath = Join-Path $script:Paths.Root "servers"
            if (-not (Test-Path $configPath)) {
                New-Item -ItemType Directory -Path $configPath -Force | Out-Null
            }

            $configFile = Join-Path $configPath "$($nameBox.Text).json"
            if (Test-Path $configFile) {
                $result = [System.Windows.Forms.MessageBox]::Show(
                    "A server with this name already exists. Do you want to overwrite it?",
                    "Warning",
                    [System.Windows.Forms.MessageBoxButtons]::YesNo,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                if ($result -eq [System.Windows.Forms.DialogResult]::No) {
                    return
                }
            }

            $serverConfig | ConvertTo-Json | Set-Content $configFile -Force

            [System.Windows.Forms.MessageBox]::Show("Server imported successfully!", "Success")
            $importForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $importForm.Close()
            
            # Update server list
            Update-ServerList -ForceRefresh
        }
        catch {
            Write-DashboardLog "Failed to import server: $_" -Level ERROR
            [System.Windows.Forms.MessageBox]::Show("Failed to import server: $($_.Exception.Message)", "Error")
        }
    })
    $importForm.Controls.Add($importButton)

    $importForm.ShowDialog()
}

# Add refresh timer
$script:refreshTimer = New-Object System.Windows.Forms.Timer
$script:refreshTimer.Interval = 10000 # Change from 60000 (1 min) to 10000 (10 seconds) for more responsive updates
$script:refreshTimer.Add_Tick({
    # Check if WebSocket server is available and maintain connection
    if (-not $script:offlineMode) {
        # Only check every few cycles to avoid constant checking
        $checkInterval = 30 # seconds
        if ($null -eq $script:lastConnectionCheck -or
            ((Get-Date) - $script:lastConnectionCheck).TotalSeconds -ge $checkInterval) {
            
            # Update last check time
            $script:lastConnectionCheck = Get-Date
            
            # If server is available but we're disconnected, try to reconnect
            if (-not $script:isWebSocketConnected -and (Test-WebSocketServer -Silent)) {
                if (Connect-WebSocketServer -Silent) {
                    # Connection successful, update UI
                    $statusLabel.Text = "WebSocket: Connected"
                    $statusLabel.ForeColor = [System.Drawing.Color]::Green
                    $script:offlineMode = $false
                }
            }
            # If we think we're connected but can't reach the server, mark as disconnected
            elseif ($script:isWebSocketConnected -and -not (Test-WebSocketServer -Silent)) {
                $script:isWebSocketConnected = $false
                $statusLabel.Text = "WebSocket: Connection Lost"
                $statusLabel.ForeColor = [System.Drawing.Color]::Red
            }
        }
    }
    
    # Regular update tasks
    Update-ServerList
    Update-HostInformation
})

# Function to sync all dashboards - fixed implementation
function Sync-AllDashboards {
    # First check if WebSocket server is available
    if (-not (Test-WebSocketServer -Silent)) {
        Write-DashboardLog "Cannot sync - WebSocket server not available" -Level WARN
        [System.Windows.Forms.MessageBox]::Show(
            "Cannot synchronize dashboards - WebSocket server not available.",
            "Sync Failed",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        return $false
    }
    
    # Now check if we're connected, and connect if needed
    if (-not $script:isWebSocketConnected) {
        Write-DashboardLog "WebSocket not connected, attempting to connect before sync..." -Level INFO
        if (Connect-WebSocketServer -Silent) {
            Write-DashboardLog "WebSocket connection established, starting services..." -Level INFO
            $statusLabel.Text = "WebSocket: Connected"
            $statusLabel.ForeColor = [System.Drawing.Color]::Green
            # Start the refresh timer directly
            $script:refreshTimer.Start()
        } 
        else {
            Write-DashboardLog "Failed to establish WebSocket connection, switching to offline mode" -Level WARN
            $script:offlineMode = $true
            $statusLabel.Text = "WebSocket: Offline Mode"
            $statusLabel.ForeColor = [System.Drawing.Color]::Orange
            $refreshTimer.Start()
        }
    }
    
    # If we're connected now, send the sync request
    if ($script:isWebSocketConnected -and $script:webSocketClient -and 
        $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        
        try {
            $syncMessage = @{
                Type = "SyncRequest"
                Timestamp = Get-Date -Format "o"
            } | ConvertTo-Json

            $buffer = [System.Text.Encoding]::UTF8.GetBytes($syncMessage)
            $segment = [ArraySegment[byte]]::new($buffer)

            $script:webSocketClient.SendAsync(
                $segment,
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait(1000)
            
            Write-DashboardLog "Sync request sent successfully" -Level INFO
            return $true
        } catch {
            Write-DashboardLog "Failed to send sync request: $($_.Exception.Message)" -Level ERROR
            return $false
        }
    } else {
        Write-DashboardLog "Cannot sync - WebSocket connection lost" -Level WARN
        [System.Windows.Forms.MessageBox]::Show(
            "Cannot synchronize dashboards - WebSocket connection lost.",
            "Sync Failed",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        return $false
    }
}

# Implement a function to force update system information now
function Update-SystemInfoNow {
    try {
        Write-DashboardLog "Forcing immediate system info update" -Level DEBUG
        Update-HostInformation
        
        # Only show message if we're in debug mode
        if ($script:debugMode) {
            [System.Windows.Forms.MessageBox]::Show(
                "System information updated successfully.",
                "Update Complete",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            )
        }
        return $true
    }
    catch {
        Write-DashboardLog "Error updating system info: $($_.Exception.Message)" -Level ERROR
        return $false
    }
}

# Main form for the dashboard
$form.Add_Shown({
    Write-DashboardLog "Dashboard form shown, initializing components..." -Level DEBUG
    
    # Set the form displayed flag
    $script:formDisplayed = $true
    
    # Load initial data regardless of connectivity - this ensures we have data in offline mode
    try {
        Write-DashboardLog "Loading initial server data..." -Level DEBUG
        Update-ServerList -SkipWebSocketBroadcast
        Update-HostInformation
    }
    catch {
        Write-DashboardLog "Error loading initial data: $($_.Exception.Message)" -Level ERROR
    }
    
    # First verify WebSocket server is running
    if (-not (Test-WebSocketServer -TimeoutSeconds 3)) {
        Write-DashboardLog "WebSocket server not available, switching to offline mode" -Level WARN
        $script:offlineMode = $true
        $statusLabel.Text = "WebSocket: Offline Mode"
        $statusLabel.ForeColor = [System.Drawing.Color]::Orange
        
        # Show notification about offline mode - Only if not shown yet
        if (-not $script:webSocketErrorShown) {
            $script:webSocketErrorShown = $true
            [System.Windows.Forms.MessageBox]::Show(
                "WebSocket server is not running or not accessible. The dashboard will run in offline mode with limited functionality.",
                "Limited Functionality",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )
        }
        
        # Start refresh timer anyway to update local data
        $refreshTimer.Start()
        return
    }

    # Try to establish WebSocket connection
    try {
        Write-DashboardLog "WebSocket server available, attempting connection..." -Level DEBUG
        
        if (Connect-WebSocketServer) {
            Write-DashboardLog "WebSocket connection established, starting services..." -Level INFO
            $statusLabel.Text = "WebSocket: Connected"
            $statusLabel.ForeColor = [System.Drawing.Color]::Green
            # Start the refresh timer directly
            $script:refreshTimer.Start()
        } 
        else {
            Write-DashboardLog "Failed to establish WebSocket connection, switching to offline mode" -Level WARN
            $script:offlineMode = $true
            $statusLabel.Text = "WebSocket: Offline Mode"
            $statusLabel.ForeColor = [System.Drawing.Color]::Orange
            $refreshTimer.Start()
        }
    }
    catch {
        Write-DashboardLog "Error during WebSocket connection attempt: $($_.Exception.Message)" -Level ERROR
        $script:offlineMode = $true
        $statusLabel.Text = "WebSocket: Offline Mode (Error)"
        $statusLabel.ForeColor = [System.Drawing.Color]::Red
        $refreshTimer.Start()
    }
})

# Add form closing event to ensure proper cleanup
$form.Add_FormClosing({
    param($sender, $e)
    
    Write-DashboardLog "Dashboard form closing, cleaning up resources..." -Level INFO
    
    # Stop the refresh timer if running
    if ($script:refreshTimer -and $script:refreshTimer.Enabled) {
        $script:refreshTimer.Stop()
        Write-DashboardLog "Refresh timer stopped" -Level DEBUG
    }
    
    # Clean up WebSocket client if connected
    if ($script:webSocketClient -and $script:webSocketClient.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        try {
            # Send disconnection message
            $disconnectMessage = @{
                Type = "Disconnect"
                Message = "Dashboard closing"
                Timestamp = Get-Date -Format "o"
            } | ConvertTo-Json
            
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($disconnectMessage)
            $segment = [ArraySegment[byte]]::new($buffer)
            
            $script:webSocketClient.SendAsync(
                $segment,
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                [System.Threading.CancellationToken]::None
            ).Wait(1000)
            
            # Close WebSocket connection
            $script:webSocketClient.CloseAsync(
                [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                "Dashboard closing",
                [System.Threading.CancellationToken]::None
            ).Wait(1000)
            
            Write-DashboardLog "WebSocket connection closed gracefully" -Level DEBUG
        }
        catch {
            Write-DashboardLog "Error closing WebSocket connection: $($_.Exception.Message)" -Level WARN
        }
    }
    
    # Final cleanup message
    Write-DashboardLog "Dashboard closed" -Level INFO
})

# This is critical: Instead of just showing the form, we need to run an application loop
$form.Show()

# Keep the PowerShell script running until the form is closed
# Using Application.Run() to create a message pump to process Windows messages
[System.Windows.Forms.Application]::Run($form)