Clear-Host
# Define the name of this server (this is just a name)
$ServerName = "***"
# Define the name of the process to start
$ProcessName = "***"

# Set the window title to the server name
$host.UI.RawUI.WindowTitle = "$ServerName Server Watchdog"

# Define the registry path where SteamCMD is installed
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"

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

# Function to create a new server instance
function Create-ServerInstance {
    param (
        [string]$ServerName,
        [string]$ProcessName,
        [string]$Arguments
    )
    
    try {
        $process = Start-Process -FilePath $ProcessName -ArgumentList $Arguments -PassThru
        if ($process) {
            # Record PID
            $pidEntry = "$($process.Id) - $ServerName"
            Add-Content -Path $pidFilePath -Value $pidEntry
            Write-Output "Server instance created: $ServerName (PID: $($process.Id))"
            return $process
        }
    }
    catch {
        Write-Output "Failed to create server instance: $_"
        return $null
    }
}

# Function to remove a server instance
function Remove-ServerInstance {
    param (
        [string]$ServerName
    )
    
    try {
        # Get PID from file
        $pidEntry = Get-Content $pidFilePath | Where-Object { $_ -like "* - $ServerName" }
        if ($pidEntry) {
            $processId = [int]($pidEntry -split ' - ')[0]
            Stop-Process -Id $processId -Force
            
            # Remove PID entry
            $pids = Get-Content $pidFilePath | Where-Object { $_ -ne $pidEntry }
            Set-Content -Path $pidFilePath -Value $pids
            
            Write-Output "Server instance removed: $ServerName"
        }
    }
    catch {
        Write-Output "Failed to remove server instance: $_"
    }
}

# Retrieve Server Manager directory path from the registry
$ServerManagerDir = Get-RegistryValue -keyPath $registryPath -propertyName "Servermanagerdir"

# Path to the PIDs file
$pidFilePath = Join-Path $ServerManagerDir "PIDS.txt"

# Define the arguments for the process
$arguments = '
ENTER YOUR ARGUMENTS HERE'

# Path to the stop file
$stopFilePath = Join-Path $ServerManagerDir "stop.txt"

# Main loop to start and monitor the process
while ($true) {
    # Check if the stop file exists and read its content
    if (Test-Path -Path $stopFilePath) {
        $stopFileContent = Get-Content -Path $stopFilePath
        if ($stopFileContent.Trim() -eq $ServerName) {
            Write-Output "$ServerName update in progress. Waiting for the update to finish at: $(Get-Date)"
            Start-Sleep -Seconds 5
            continue
        }
    }

    Write-Output "$ServerName server starting at: $(Get-Date)"

    try {
        # Start the server and capture its PID with arguments
        $process = Start-Process "$ProcessName" -ArgumentList $arguments -PassThru -ErrorAction Stop
        if ($null -eq $process) {
            throw "Failed to start the process."
        }

        # Read the current contents of the PID file
        $pidFileContent = Get-Content -Path $pidFilePath

        # Filter out any lines that contain the server name
        $filteredContent = $pidFileContent | Where-Object { $_ -notmatch "$ServerName" }

        # Write the filtered content back to the PID file
        Set-Content -Path $pidFilePath -Value $filteredContent

        # Append the new PID entry to the file
        $pidEntry = "$($process.Id) - $ServerName"
        Add-Content -Path $pidFilePath -Value $pidEntry

        Write-Output "PID $($process.Id) recorded for $ServerName."

        # Connect to the PID console
        Connect-PIDConsole -ProcessId $process.Id

    } catch {
        Write-Output "Error starting process or writing PID: $_"
        Start-Sleep -Seconds 5
        continue
    }

    # Wait for the server process to exit (crash or shutdown)
    $process | Wait-Process

    Write-Output "$ServerName server crashed or shutdown at: $(Get-Date)"

    # Remove the PID from the file after the server stops
    try {
        # Read all lines, filter out the current process PID, and write back
        $pids = Get-Content -Path $pidFilePath | Where-Object { $_ -notmatch "^\s*$($process.Id)\s*-\s*$ServerName\s*$" }
        Set-Content -Path $pidFilePath -Value $pids

        Write-Output "PID $($process.Id) removed for $ServerName."

    } catch {
        Write-Output "Error removing PID from the file: $_"
    }
}
