# Set process name
$host.ui.RawUI.WindowTitle = "Steam Game App Updater"

# Path to configuration file (inside SteamCMD's servermanager folder)
$InstallSteamCMDPath = "C:\SteamCMD"  # Adjust this if the install directory for SteamCMD is different
$serverManagerDir = Join-Path $InstallSteamCMDPath "servermanager"
$configFilePath = Join-Path $serverManagerDir "config.json"

# Check if configuration file exists
if (-not (Test-Path -Path $configFilePath)) {
    Write-Host "Configuration file not found at $configFilePath. Exiting script."
    exit 1
}

# Load and parse the configuration file
try {
    $configContent = Get-Content -Path $configFilePath -Raw | ConvertFrom-Json
    $SteamCMDPath = $configContent.SteamCmdPath
} catch {
    Write-Host "Error loading or parsing configuration file: $_"
    exit 1
}

# Ensure SteamCMDPath is defined
if (-not $SteamCMDPath) {
    Write-Host "SteamCMDPath is not defined in the configuration file. Exiting script."
    exit 1
}

# Path to log file (inside SteamCMD's servermanager folder)
$LogFilePath = Join-Path $serverManagerDir "log-autoupdater.log"
$log = $true  # Set this to $false to disable logging

# Define a function to log messages if logging is enabled
function Logging {
    param (
        [string]$Message,
        [string]$Type = "INFO"
    )
    
    if ($log) {
        $timestamp = Get-Date -Format "dd-MM-yyyy HH:mm:ss"
        $logEntry = "$timestamp [$Type] $Message"
        Add-Content -Path $LogFilePath -Value $logEntry
    }
    
    Write-Host $Message
}

# Define a function to recursively stop a process and its children
function Stop-ProcessTree {
    param (
        [int]$ParentId
    )

    $childProcesses = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ParentId }

    foreach ($childProcess in $childProcesses) {
        Stop-ProcessTree -ParentId $childProcess.ProcessId
    }

    try {
        Stop-Process -Id $ParentId -Force
        Logging "Stopped process (PID: $ParentId) and its child processes."
    } catch {
        Logging "Failed to stop process (PID: $ParentId): $_" -Type "ERROR"
    }
}

# Define a function to check if a process is running by PID
function ServerProcessRunning {
    param (
        [int]$ProcessId
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Logging "Process $ProcessId is running."
        return $true
    } else {
        Logging "Process $ProcessId is not running."
        return $false
    }
}

# Define a function to notify players about the server shutdown before stopping it
function Send-Shutdown {
    param (
        [string]$ServerName,
        [int]$ProcessId,
        [int]$ShutdownTime = 60
    )

    $message = "Server will shut down in $ShutdownTime seconds for updates!"
    Logging "Sending shutdown message to $ServerName..."

    # Define the shutdown folder (inside SteamCMD's servermanager folder)
    $shutdownDir = $serverManagerDir
    if (-not (Test-Path -Path $shutdownDir)) {
        New-Item -Path $shutdownDir -ItemType Directory | Out-Null
        Logging "Created directory: $shutdownDir"
    }

    # Create VBS script to send shutdown messages
    $vbsScript = @"
    Set objShell = CreateObject("WScript.Shell")
    objShell.SendKeys "$message {ENTER}"
"@
    try {
        $vbsScript | Out-File "$shutdownDir\shutdown_$ServerName.vbs" -Force
        Start-Process -FilePath "$shutdownDir\shutdown_$ServerName.vbs"
        Start-Sleep -Seconds $ShutdownTime
        Remove-Item -Path "$shutdownDir\shutdown_$ServerName.vbs"
        Logging "Shutdown script executed and removed for $ServerName."
    } catch {
        Logging "Failed to create or run shutdown script for $ServerName : $_" -Type "ERROR"
    }
}

# Ensure stopFilePath is initialized
$stopFilePath = Join-Path $serverManagerDir "stop.txt"
Logging "Stop file path was initialized to: $stopFilePath."

# Define a function to stop a server process based on PID from the PIDS.txt file
function Stop-Server {
    param (
        [string]$ServerName
    )

    Logging "Stopping server: $ServerName..."

    $pidFilePath = Join-Path $serverManagerDir "PIDS.txt"

    if (Test-Path -Path $pidFilePath) {
        $pidEntries = Get-Content -Path $pidFilePath
        $pidEntry = $pidEntries | Where-Object { $_ -like "* - $ServerName" }

        if ($pidEntry) {
            $processId = [int]($pidEntry -split ' - ')[0]

            # Check if the process is running before stopping it
            if (ServerProcessRunning -ProcessId $processId) {
                # Notify users before shutdown
                Send-Shutdown -ServerName $ServerName -ProcessId $processId -ShutdownTime 60

                Stop-ProcessTree -ParentId $processId

                # Remove the PID entry from PIDS.txt
                $updatedEntries = $pidEntries | Where-Object { $_ -ne $pidEntry }
                Set-Content -Path $pidFilePath -Value $updatedEntries
                Logging "PID entry for $ServerName removed from PIDS.txt."
            } else {
                Logging "$ServerName is not running."
            }
        } else {
            Logging "No PID found for $ServerName in PIDS.txt. Assuming server is already off."
        }
    } else {
        Logging "PIDS.txt file not found at $pidFilePath."
    }
}

# Define a function to check if an update is available for a game using SteamCMD
function AnyUpdatesAvailable {
    param (
        [string]$AppID,
        [string]$AppName
    )

    Logging "Checking for updates: $AppName..."

    $arguments = "+login anonymous +app_info_update 1 +app_update $AppID validate +exit"

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $SteamCMDPath
    $processInfo.Arguments = $arguments
    $processInfo.RedirectStandardOutput = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($processInfo)

    # Wait for the process to finish or timeout
    if (-not $process.WaitForExit(240000)) {
        Logging "SteamCMD process for $AppName timed out. Killing process..." -Type "ERROR"
        $process.Kill()
        $process.WaitForExit()
        return $false
    }

    $output = $process.StandardOutput.ReadToEnd()
    Logging "SteamCMD Output for $AppName $output"

    # Check for multiple possible update messages in the output
    if ($output -match "(?i)(update\s+required|reconfiguring|validating|downloading)") {
        Logging "Update available for $AppName."
        return $true
    } else {
        Logging "No update available for $AppName."
        return $false
    }
}

# Define a function to update a game using SteamCMD
function Update-Game {
    param (
        [string]$AppName,
        [string]$AppID,
        [string]$InstallDir = ""
    )

    # Ensure stopFilePath is initialized before use
    $stopFilePath = Join-Path $serverManagerDir "stop.txt"  # Default stop file path

    # Check if the game is running by looking for its PID
    $pidFilePath = Join-Path $serverManagerDir "PIDS.txt"
    $isRunning = $false

    if (Test-Path -Path $pidFilePath) {
        $pidEntries = Get-Content -Path $pidFilePath
        $pidEntry = $pidEntries | Where-Object { $_ -like "* - $AppName" }

        if ($pidEntry) {
            $isRunning = $true
            Logging "$AppName is currently running. Proceeding with shutdown for update."
        } else {
            Logging "No PID found for $AppName in PIDS.txt. Assuming server is already off."
        }
    }

    # Check if an update is available
    $updateAvailable = AnyUpdatesAvailable -AppID $AppID -AppName $AppName

    # Exit the function if no update is available
    if (-not $updateAvailable) {
        Logging "No update available for $AppName. Skipping update."
        return
    }

    # Check if the installation directory exists
    if ($InstallDir -and -not (Test-Path -Path $InstallDir)) {
        Logging "Directory for $AppName not found at $InstallDir. Installing..."
        $InstallDir = ""  # Reset to default if the specified directory does not exist
    }

    # Only stop the server if it is running
    if ($isRunning) {
        # Create stop file to notify the watchdog script to halt server restarts
        Set-Content -Path $stopFilePath -Value $AppName
        Logging "Stop file created for $AppName. Waiting for server shutdown..."

        # Stop the server if running
        Stop-Server -ServerName $AppName

        # Optionally, wait for some time to ensure the server shuts down before updating
        Start-Sleep -Seconds 60 # Adjust based on how long your server takes to shut down
    }

    Logging "Updating $AppName..."

    # Construct the SteamCMD arguments
    $arguments = "+login anonymous +app_update $AppID +exit"
    
    # If an install directory is provided, include it in the arguments
    if ($InstallDir) {
        $arguments = "+force_install_dir $InstallDir $arguments"
    }

    # Start the update process and capture the output
    try {
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $SteamCMDPath
        $processInfo.Arguments = $arguments
        $processInfo.RedirectStandardOutput = $true
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true

        $process = [System.Diagnostics.Process]::Start($processInfo)
        $output = $process.StandardOutput.ReadToEnd()
        $process.WaitForExit()

        Logging "SteamCMD Output: $output"

        if ($output -match "progress: \d+\.\d+") {
            Logging "$AppName update completed successfully."
        } else {
            Logging "No update detected or already up-to-date for $AppName."
        }
    } catch {
        Logging "Error detected in SteamCMD output: $output" -Type "ERROR"
        return $false
    } finally {
        # Remove the stop file to allow the server to restart, if it was created
        if (Test-Path -Path $stopFilePath) {
            Remove-Item -Path $stopFilePath -Force
            Logging "Update complete for $AppName. Stop file removed. Server can restart."
        }
    }
}

# List of games with their corresponding App IDs and optional install directories
$games = @(
    @{ Name = "Factorio"; AppID = "427520" }
)

# Loop through each game and update it
foreach ($game in $games) {
    Update-Game -AppName $game.Name -AppID $game.AppID -InstallDir $game.InstallDir
}

Logging "All games updated! Exiting in 10 seconds..."
Start-Sleep -Seconds 10