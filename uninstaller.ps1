Add-Type -AssemblyName System.Windows.Forms

# Define the registry path for configuration
$registryPath = "HKCU:\Software\skywereindustries\servermanager"

# Function to remove directory if it exists
function Remove-Directory {
    param (
        [string]$dir
    )
    if (Test-Path -Path $dir) {
        Write-Log "Removing directory: $dir"
        Remove-Item -Recurse -Force -Path $dir
    } else {
        Write-Log "Directory does not exist: $dir"
    }
}

# Function to remove registry key if it exists
function Remove-RegistryKey {
    param (
        [string]$path
    )
    if (Test-Path $path) {
        Write-Log "Removing registry key: $path"
        Remove-Item -Path $path -Recurse -Force
    } else {
        Write-Log "Registry key does not exist: $path"
    }
}

# Function to write messages to log file
function Write-Log {
    param (
        [string]$message
    )

    # Ensure the log file path is set before writing
    if (-not $global:logFilePath) {
        Write-Host "Log file path is not set. Cannot write log."
        return
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    
    try {
        Add-Content -Path $global:logFilePath -Value $logMessage
    } catch {
        Write-Host "Failed to write to log file: $($_.Exception.Message)"
    }
}

# Function to open folder selection dialog
function Select-FolderDialog {
    [System.Windows.Forms.FolderBrowserDialog]$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select the directory where SteamCMD is installed"
    $dialog.ShowNewFolderButton = $false
    [void]$dialog.ShowDialog()
    if ($null -eq $dialog.SelectedPath) {
        Write-Host "No directory selected, exiting..."
        exit
    }
    return $dialog.SelectedPath
}

# Select the directory using Windows Folder Dialog
$installDir = Select-FolderDialog
if (-Not $installDir) {
    Write-Host "No directory selected, exiting..."
    exit
}

# Define the servermanager directory
$serverManagerDir = Join-Path $installDir "servermanager"

# Set log file path inside the servermanager directory
$global:logFilePath = Join-Path $serverManagerDir "Uninstall-Log.txt"

# Remove the servermanager directory
Remove-Directory -dir $serverManagerDir

# Remove the SteamCMD directory (you can choose to keep it or not, depending on your uninstallation strategy)
Write-Log "Removing SteamCMD directory: $installDir"
Remove-Directory -dir $installDir

# Remove registry entries
Remove-RegistryKey -path $registryPath

# Confirm success
Write-Log "SteamCMD successfully uninstalled from $installDir and registry keys removed."

# End of script
