# Update module import path
$serverManagerPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "Modules\ServerManager\ServerManager.psm1"
Import-Module $serverManagerPath -Force

# Set process name
$host.ui.RawUI.WindowTitle = "Steam Game Server Updater"

# Define the registry path where SteamCMD is installed
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Function to retrieve registry value
function Get-RegistryValue {
    param (
        [string]$keyPath,
        [string]$propertyName
    )
    try {
        $value = Get-ItemProperty -Path $keyPath -Name $propertyName -ErrorAction Stop
        return $value.$propertyName
    } catch {
        Write-Host "Failed to retrieve registry value: $($_.Exception.Message)"
        exit 1
    }
}

# Retrieve SteamCMD installation path from registry and append 'steamcmd.exe'
$SteamCMDPath = Join-Path (Get-RegistryValue -keyPath $registryPath -propertyName "SteamCmdPath") "steamcmd.exe"
# Retrieve Server Manager directory path from registry
$serverManagerDir = Get-RegistryValue -keyPath $registryPath -propertyName "servermanagerdir"

# Check if SteamCMDPath was retrieved successfully
if (-not $SteamCMDPath) {
    Write-Host "SteamCMD path not found in the registry. Exiting script."
    exit 1
}

# Path to log file (inside SteamCMD's servermanager folder)
$LogFilePath = Join-Path $serverManagerDir "log-updateserver.log"
$log = $true  # Set this to $false to disable logging

# Define a function to log messages if logging is enabled
function Write-Log {
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
        Write-Log "Stopped process (PID: $ParentId) and its child processes."
    } catch {
        Write-Log "Failed to stop process (PID: $ParentId): $_" -Type "ERROR"
    }
}

# Define a function to check if a process is running by PID
function Test-ServerProcessRunning {
    param (
        [int]$ProcessId
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Write-Log "Process $ProcessId is running."
        return $true
    } else {
        Write-Log "Process $ProcessId is not running."
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
    Write-Log "Sending shutdown message to $ServerName..."

    # Define the shutdown folder (inside SteamCMD's servermanager folder)
    $shutdownDir = $serverManagerDir
    if (-not (Test-Path -Path $shutdownDir)) {
        New-Item -Path $shutdownDir -ItemType Directory | Out-Null
        Write-Log "Created directory: $shutdownDir"
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
        Write-Log "Shutdown script executed and removed for $ServerName."
    } catch {
        Write-Log "Failed to create or run shutdown script for $ServerName : $_" -Type "ERROR"
    }
}

# Ensure stopFilePath is initialized
$stopFilePath = Join-Path $serverManagerDir "stop.txt"
Write-Log "Stop file path was initialized to: $stopFilePath."

# Define a function to stop a server process based on PID from the PIDS.txt file
function Stop-Server {
    param (
        [string]$ServerName
    )

    Write-Log "Stopping server: $ServerName..."

    $pidFilePath = Join-Path $serverManagerDir "PIDS.txt"

    if (Test-Path -Path $pidFilePath) {
        $pidEntries = Get-Content -Path $pidFilePath
        $pidEntry = $pidEntries | Where-Object { $_ -like "* - $ServerName" }

        if ($pidEntry) {
            $processId = [int]($pidEntry -split ' - ')[0]

            # Check if the process is running before stopping it
            if (Test-ServerProcessRunning -ProcessId $processId) {
                # Notify users before shutdown
                Send-Shutdown -ServerName $ServerName -ProcessId $processId -ShutdownTime 60

                Stop-ProcessTree -ParentId $processId

                # Remove the PID entry from PIDS.txt
                $updatedEntries = $pidEntries | Where-Object { $_ -ne $pidEntry }
                Set-Content -Path $pidFilePath -Value $updatedEntries
                Write-Log "PID entry for $ServerName removed from PIDS.txt."
            } else {
                Write-Log "$ServerName is not running."
            }
        } else {
            Write-Log "No PID found for $ServerName in PIDS.txt. Assuming server is already off."
        }
    } else {
        Write-Log "PIDS.txt file not found at $pidFilePath."
    }
}

# Define a function to check if an update is available for a game using SteamCMD
function Test-AnyUpdatesAvailable {
    param (
        [string]$AppID,
        [string]$AppName
    )

    Write-Log "Checking for updates: $AppName..."

    $arguments = "+login anonymous +app_info_update 1 +app_update $AppID validate +exit"

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $SteamCMDPath
    $processInfo.Arguments = $arguments
    $processInfo.RedirectStandardOutput = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    
    # Set the working directory to the folder containing SteamCMD (excluding the .exe)
    $processInfo.WorkingDirectory = (Get-RegistryValue -keyPath $registryPath -propertyName "SteamCmdPath")    

    $process = [System.Diagnostics.Process]::Start($processInfo)

    # Wait for the process to finish or timeout
    if (-not $process.WaitForExit(240000)) {
        Write-Log "SteamCMD process for $AppName timed out. Killing process..." -Type "ERROR"
        $process.Kill()
        $process.WaitForExit()
        return $false
    }

    $output = $process.StandardOutput.ReadToEnd()
    Write-Log "SteamCMD Output for $AppName $output"

    # Check for multiple possible update messages in the output
    if ($output -match "(?i)(update\s+required|reconfiguring|validating|downloading)") {
        Write-Log "Update available for $AppName."
        return $true
    } else {
        Write-Log "No update available for $AppName."
        return $false
    }
}

# Define a function to update or install a game using SteamCMD
function Update-Game {
    param (
        [string]$AppName,
        [string]$AppID,
        [string]$InstallDir = ""
    )

    # Ensure stopFilePath is initialized before use
    $stopFilePath = Join-Path $serverManagerDir "stop.txt"
    $appIDFilePath = Join-Path $serverManagerDir "AppID.txt"

    # Update AppID file
    Set-Content -Path $appIDFilePath -Value $AppID
    Write-Log "AppID file updated with $AppID for $AppName."

    # Check if the game is running by looking for its PID
    $pidFilePath = Join-Path $serverManagerDir "PIDS.txt"
    $isRunning = $false

    if (Test-Path -Path $pidFilePath) {
        $pidEntries = Get-Content -Path $pidFilePath
        $pidEntry = $pidEntries | Where-Object { $_ -like "* - $AppName" }

        if ($pidEntry) {
            $isRunning = $true
            Write-Log "$AppName is currently running. Proceeding with shutdown for update."
        } else {
            Write-Log "No PID found for $AppName in PIDS.txt. Assuming server is already off."
        }
    }

    # Check if an update is available
    $updateAvailable = Test-AnyUpdatesAvailable -AppID $AppID -AppName $AppName

    # Exit the function if no update is available
    if (-not $updateAvailable) {
        Write-Log "No update available for $AppName. Skipping update."
        return
    }

    # Determine if this is a new installation or an update
    if ($InstallDir -and -not (Test-Path -Path $InstallDir)) {
        Write-Log "Directory for $AppName not found at $InstallDir. Installing..."
        $InstallDir = ""  # Reset to default if the specified directory does not exist
        $installMode = "INSTALLING"
    } else {
        $installMode = "UPDATING"
    }

    # Only stop the server if it is running
    if ($isRunning) {
        # Create stop file to notify the watchdog script to halt server restarts
        Set-Content -Path $stopFilePath -Value $AppName
        Write-Log "Stop file created for $AppName. Waiting for server shutdown..."

        # Stop the server if running
        Stop-Server -ServerName $AppName

        # Optionally, wait for some time to ensure the server shuts down before updating
        Start-Sleep -Seconds 60 # Adjust based on how long your server takes to shut down
    }

    Write-Log "$installMode $AppName..."

    # Construct the SteamCMD arguments
    $arguments = "+login anonymous +app_update $AppID +exit"
    
    # If an install directory is provided, include it in the arguments
    if ($InstallDir) {
        $arguments = "+force_install_dir $InstallDir $arguments"
    }

    # Start the update/install process and capture the output
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

        Write-Log "SteamCMD Output: $output"

        if ($output -match "progress: \d+\.\d+") {
            Write-Log "$AppName $installMode completed successfully."
        } else {
            Write-Log "No update detected or already up-to-date for $AppName."
        }
    } catch {
        Write-Log "Error detected in SteamCMD output: $output" -Type "ERROR"
        return $false
    } finally {
        # Remove the stop file to allow the server to restart, if it was created
        if (Test-Path -Path $stopFilePath) {
            Remove-Item -Path $stopFilePath -Force
            Write-Log "$installMode complete for $AppName. Stop file removed. Server can restart."
        }
    }
}

# Function to connect to the PID console
function Connect-PIDConsole {
    param (
        [int]$ProcessId
    )
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $process | Out-Host
    } catch {
        Write-Host "Failed to connect to process (PID: $ProcessId): $_" -ForegroundColor Red
    }
}

# Define a function to create a new server instance
function New-ServerInstance {
    param (
        [string]$ServerName,
        [string]$AppID,
        [string]$InstallDir
    )
    Write-Log "Creating server instance: $ServerName..."
    # ...existing code...
}

# Define a function to remove a server instance
function Remove-ServerInstance {
    param (
        [string]$ServerName
    )
    Write-Log "Removing server instance: $ServerName..."
    # ...existing code...
}

# Define a function to list all server instances
function Get-ServerInstances {
    Write-Log "Listing all server instances..."
    # ...existing code...
}

# Define a function to start a server instance
function Start-ServerInstance {
    param (
        [string]$ServerName
    )
    Write-Log "Starting server instance: $ServerName..."
    # ...existing code...
}

# Define a function to stop a server instance
function Stop-ServerInstance {
    param (
        [string]$ServerName
    )
    Write-Log "Stopping server instance: $ServerName..."
    # ...existing code...
}

# Define a function to restart a server instance
function Restart-ServerInstance {
    param (
        [string]$ServerName
    )
    Write-Log "Restarting server instance: $ServerName..."
    Stop-ServerInstance -ServerName $ServerName
    Start-ServerInstance -ServerName $ServerName
}

# Define a function to update a server instance
function Update-ServerInstance {
    param (
        [string]$ServerName,
        [string]$AppID,
        [string]$InstallDir
    )
    Write-Log "Updating server instance: $ServerName..."
    Stop-ServerInstance -ServerName $ServerName
    Update-Game -AppName $ServerName -AppID $AppID -InstallDir $InstallDir
    Start-ServerInstance -ServerName $ServerName
}

# Update AppID file at the start of the script - Disabled for now as cloudflare security setup by SteamDB, the function has been removed, though Install.ps1 contains a copy
#Update-AppIDFile -serverManagerDir $serverManagerDir

# List of games with their corresponding App IDs and optional install directories
$games = @(
    #EXAMPLE WITHOUT DIR: @{ Name = "Project Zomboid"; AppID = "108600" },
    #EXAMPLE WITH DIR @{ Name = "Team Fortress 2"; AppID = "232250"; InstallDir = "D:\SteamCMD\steamapps\common\TeamFortress2_DedicatedServer" }
)

# Loop through each game and update/install it
foreach ($game in $games) {
    Update-Game -AppName $game.Name -AppID $game.AppID -InstallDir $game.InstallDir
}

Write-Log "All games updated/installed! Exiting in 10 seconds..."
Start-Sleep -Seconds 10
