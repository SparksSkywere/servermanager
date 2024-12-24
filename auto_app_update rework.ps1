# Set process name
$host.ui.RawUI.WindowTitle = "Steam Game App Updater"

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
    
    # Set the working directory to the folder containing SteamCMD (excluding the .exe)
    $processInfo.WorkingDirectory = (Get-RegistryValue -keyPath $registryPath -propertyName "SteamCmdPath")    

    $process = [System.Diagnostics.Process]::Start($processInfo)

    # Check if the process started successfully
    if ($process -eq $null) {
    Logging "Failed to start SteamCMD process for $AppName." -Type "ERROR"
    return $false
    }

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
    @{ Name = "Team Fortress 2"; AppID = "232250"; InstallDir = "D:\SteamCMD\steamapps\common\TeamFortress2_DedicatedServer" },
    @{ Name = "Project Zomboid"; AppID = "108600" },
    @{ Name = "Space Engineers"; AppID = "298740" },
    @{ Name = "Starbound"; AppID = "211820" },
    @{ Name = "Rust"; AppID = "258550" },
    @{ Name = "Garry's Mod"; AppID = "4020" },
    @{ Name = "Stormworks"; AppID = "1247090" },
    @{ Name = "Factorio"; AppID = "427520" },
    @{ Name = "Satisfactory"; AppID = "1690800" },
    @{ Name = "Medieval Engineers"; AppID = "367970" },
    @{ Name = "The Forest"; AppID = "556450" },
    @{ Name = "Left 4 Dead 2"; AppID = "222860" },
    @{ Name = "7 Days to Die"; AppID = "251570" },
    @{ Name = "Unturned"; AppID = "1110390" },
    @{ Name = "Valheim"; AppID = "896660" },
    @{ Name = "Planet Explorers"; AppID = "237870" },
    @{ Name = "PalWorld"; AppID = "2394010" }
)

# Loop through each game and update it
foreach ($game in $games) {
    Update-Game -AppName $game.Name -AppID $game.AppID -InstallDir $game.InstallDir
}

Logging "All games updated! Exiting in 10 seconds..."
Start-Sleep -Seconds 10
