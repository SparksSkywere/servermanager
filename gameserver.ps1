Clear-Host
$host.UI.RawUI.WindowTitle = "*** Server Watchdog"

# Define the name of this server
$ServerName = "***"

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

# Retrieve Server Manager directory path from the registry
$ServerManagerDir = Get-RegistryValue -keyPath $registryPath -propertyName "Servermanagerdir"

# Path to the PIDs file
$pidFilePath = Join-Path $ServerManagerDir "PIDS.txt"

# Define the arguments for the process
$arguments = 
'
ENTER YOUR ARGUMENTS HERE
'

# Path to the stop file
$stopFilePath = Join-Path $ServerManagerDir "stop.txt"

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
        $process = Start-Process "***" -ArgumentList $arguments -PassThru -ErrorAction Stop
        if ($null -eq $process) {
            throw "Failed to start the process."
        }

        # Append the PID to the file
        $pidEntry = "$($process.Id) - $ServerName"
        Add-Content -Path $pidFilePath -Value $pidEntry

        Write-Output "PID $($process.Id) recorded for $ServerName."

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
