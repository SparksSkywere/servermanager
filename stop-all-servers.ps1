# Define the registry path where the Server Manager settings are stored
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

# Retrieve Server Manager directory path from registry
$ServerManagerDir = Get-RegistryValue -keyPath $registryPath -propertyName "Servermanagerdir"

# Define the path to the PID file using the registry-based directory
$pidFilePath = Join-Path $ServerManagerDir "PIDS.txt"

# Check if the PID file exists
if (Test-Path -Path $pidFilePath) {
    # Read all the PIDs from the file
    $pidEntries = Get-Content -Path $pidFilePath

    # Loop through each entry in the file
    foreach ($pidEntry in $pidEntries) {
        # Attempt to extract the PID (assumes PID is the first value in each line)
        $processId = [int]($pidEntry -split ' - ')[0]

        # Attempt to stop the process
        try {
            Stop-Process -Id $processId -Force
            Write-Host "Successfully stopped process (PID: $processId)."
        } catch {
            Write-Host "Failed to stop process (PID: $processId): $_" -ForegroundColor Red
        }
    }

    # Clear the contents of the PID file after processing
    Clear-Content -Path $pidFilePath
    Write-Host "All processes stopped and PID file cleared."
} else {
    Write-Host "PID file not found at $pidFilePath."
}
