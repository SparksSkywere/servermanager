Add-Type -AssemblyName System.Windows.Forms

# Define the SteamCMD download URL
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# Function to create directory if it doesn't exist
function Servermanager {
    param (
        [string]$dir
    )
    if (-Not (Test-Path -Path $dir)) {
        Write-Log "Directory does not exist, creating: $dir"
        New-Item -ItemType Directory -Force -Path $dir
    }
}

# Function to ensure the current user has full permissions to a directory
function Set-DirectoryPermissions {
    param (
        [string]$dir
    )

    $acl = Get-Acl $dir
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $permission = $currentUser, "FullControl", "ContainerInherit, ObjectInherit", "None", "Allow"
    $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule $permission
    $acl.SetAccessRule($accessRule)
    Set-Acl $dir $acl
    Write-Log "Set full control permissions for $currentUser on directory: $dir"
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
    $dialog.Description = "Select the directory where SteamCMD should be installed"
    $dialog.ShowNewFolderButton = $true
    [void]$dialog.ShowDialog()
    if ($dialog.SelectedPath -eq $null) {
        Write-Host "No directory selected, exiting..."
        exit
    }
    return $dialog.SelectedPath
}

# Function to update and run SteamCMD
function Update-SteamCmd {
    param (
        [string]$steamCmdPath
    )
    Write-Log "Running SteamCMD update..."
    Start-Process -FilePath $steamCmdPath -ArgumentList "+login anonymous +quit" -NoNewWindow -Wait
    Write-Log "SteamCMD updated successfully."
}

# Select the directory using Windows Folder Dialog
$installDir = Select-FolderDialog
if (-Not $installDir) {
    Write-Host "No directory selected, exiting..."
    exit
}

# Ensure the SteamCMD directory exists
Servermanager -dir $installDir

# Create the "servermanager" directory inside the selected SteamCMD directory
$serverManagerDir = Join-Path $installDir "servermanager"
Servermanager -dir $serverManagerDir

# Set log file and config paths inside the servermanager directory
$global:logFilePath = Join-Path $serverManagerDir "Install-Log.txt"
$configFilePath = Join-Path $serverManagerDir "config.json"

# Set permissions for the SteamCMD install directory and servermanager directory
Set-DirectoryPermissions -dir $installDir
Set-DirectoryPermissions -dir $serverManagerDir

# Define the full path for the SteamCMD zip file
$steamCmdZip = Join-Path $installDir "steamcmd.zip"

# Download SteamCMD
Write-Log "Downloading SteamCMD to $steamCmdZip..."
Invoke-WebRequest -Uri $steamCmdUrl -OutFile $steamCmdZip -ErrorAction Stop

# Unzip the SteamCMD zip file
Write-Log "Extracting SteamCMD..."
Expand-Archive -Path $steamCmdZip -DestinationPath $installDir -Force

# Remove the downloaded zip file after extraction
Remove-Item -Path $steamCmdZip -Force
Write-Log "SteamCMD zip file removed."

# Create or update the config.json file
# Add "steamcmd.exe" to the path for the SteamCmdPath
$configData = @{
    SteamCmdPath = Join-Path $installDir "steamcmd.exe"
}

$configJson = $configData | ConvertTo-Json -Depth 3

# Save the config.json file inside the servermanager directory
Write-Log "Saving SteamCMD path to $configFilePath..."
$configJson | Set-Content -Path $configFilePath -Encoding UTF8

# Confirm success
Write-Log "SteamCMD successfully installed to $installDir and path saved to $configFilePath."

# Run the SteamCMD update
Update-SteamCmd -steamCmdPath (Join-Path $installDir "steamcmd.exe")

# End of script
