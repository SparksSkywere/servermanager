# Define the path to SteamCMD executable
$SteamCMDPath = "D:\SteamCMD\steamcmd.exe"

# Define a function to recursively stop a process and its children
function Stop-ProcessTree {
    param (
        [int]$ParentId
    )

    # Get all child processes of the given parent process
    $childProcesses = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ParentId }

    # Recursively stop all child processes
    foreach ($childProcess in $childProcesses) {
        Stop-ProcessTree -ParentId $childProcess.ProcessId
    }

    # Stop the parent process
    try {
        Stop-Process -Id $ParentId -Force
        Write-Host "Stopped process (PID: $ParentId) and its child processes."
    } catch {
        Write-Host "Failed to stop process (PID: $ParentId): $_" -ForegroundColor Red
    }
}

# Define a function to stop a server process based on PID from the PIDS.txt file
function Stop-Server {
    param (
        [string]$ServerName
    )

    Write-Host "Stopping server: $ServerName..."

    # Path to the PIDs file
    $pidFilePath = "C:\PIDS.txt"

    # Check if the PID file exists and read the PID associated with the server name
    if (Test-Path -Path $pidFilePath) {
        $pidEntries = Get-Content -Path $pidFilePath
        $pidEntry = $pidEntries | Where-Object { $_ -like "* - $ServerName" }

        if ($pidEntry) {
            $processId = [int]($pidEntry -split ' - ')[0] # Extract the process ID from the entry

            # Stop the server process tree
            Stop-ProcessTree -ParentId $processId

            # Remove the PID entry from the file
            $updatedEntries = $pidEntries | Where-Object { $_ -ne $pidEntry }
            Set-Content -Path $pidFilePath -Value $updatedEntries
            Write-Host "PID entry for $ServerName removed from PIDS.txt."
        } else {
            Write-Host "No PID found for $ServerName in PIDS.txt."
        }
    } else {
        Write-Host "PIDS.txt file not found at $pidFilePath."
    }
}

# Define a function to update a game using SteamCMD
function Update-Game {
    param (
        [string]$AppName,
        [string]$AppID,
        [string]$InstallDir = ""
    )

    Write-Host "Preparing to update $AppName..."

    # Create stop file to notify watchdog script to halt server restarts
    $stopFilePath = "C:\stop.txt"
    Set-Content -Path $stopFilePath -Value $AppName
    Write-Host "Stop file created for $AppName. Waiting for server shutdown..."
    # To make sure the server has received the stop command, default time for servers to pick up are 2 seconds
    Start-Sleep -Seconds 6

    # Stop the server if running
    Stop-Server -ServerName $AppName

    # Optionally, wait for some time to ensure the server shuts down before updating
    Start-Sleep -Seconds 10 # Adjust based on how long your server takes to shut down

    Write-Host "Updating $AppName..."

    # Construct the SteamCMD arguments
    $arguments = "+login anonymous +app_update $AppID +exit"
    
    # If an install directory is provided, include it in the arguments
    if ($InstallDir) {
        $arguments = "+force_install_dir `"$InstallDir`" $arguments"
    }

    # Start the update process
    try {
        Start-Process -FilePath $SteamCMDPath -ArgumentList $arguments -Wait -NoNewWindow
        Write-Host "$AppName update completed.`n"
    } catch {
        Write-Host "Failed to update $AppName $_" -ForegroundColor Red
    } finally {
        # Remove the stop file to allow the server to restart
        Remove-Item -Path $stopFilePath -Force
        Write-Host "Update complete for $AppName. Stop file removed. Server can restart."
    }
}

# List of games with their corresponding App IDs and optional install directories
$games = @(
    @{ Name = "Project Zomboid"; AppID = "108600" },
    @{ Name = "Space Engineers"; AppID = "298740" },
    @{ Name = "Team Fortress 2"; AppID = "232250"; InstallDir = "D:\SteamCMD\steamapps\common\TeamFortress2_DedicatedServer" },
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
    @{ Name = "Project Zomboid"; AppID = "108600" },
    @{ Name = "Valheim"; AppID = "896660" },
    @{ Name = "Planet Explorers"; AppID = "237870" },
    @{ Name = "PalWorld"; AppID = "2394010" }
)

# Loop through each game and update it
foreach ($game in $games) {
    Update-Game -AppName $game.Name -AppID $game.AppID -InstallDir $game.InstallDir
}

Write-Host "All games updated! Exiting in 10 seconds..."
Start-Sleep -Seconds 10
