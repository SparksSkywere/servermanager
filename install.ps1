Add-Type -AssemblyName System.Windows.Forms

# Define the SteamCMD download URL
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# Define the registry path for configuration
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Function to check if the current user is an administrator
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adminRole = (New-Object Security.Principal.WindowsPrincipal $currentUser).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    return $adminRole
}

# Function to run a script block with elevated privileges
function Start-ElevatedProcess {
    param (
        [string]$scriptBlock
    )

    $psExe = "$($env:SystemRoot)\System32\WindowsPowerShell\v1.0\powershell.exe"
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($scriptBlock))
    
    Start-Process -FilePath $psExe -ArgumentList "-NoProfile -EncodedCommand $encodedCommand" -Verb RunAs -Wait
}

# Function to create a directory if it doesn't exist
function Servermanager {
    param (
        [string]$dir
    )
    if (-Not (Test-Path -Path $dir)) {
        try {
            Write-Host "Directory does not exist, creating: $dir"
            New-Item -ItemType Directory -Force -Path $dir
            Write-Host "Successfully created directory: $dir"
        } catch {
            Write-Host "Failed to create directory: $($_.Exception.Message)"
            throw
        }
    } else {
        Write-Host "Directory already exists: $dir"
    }
}

# Function to write messages to log file
function Write-Log {
    param (
        [string]$message
    )

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
    if ($null -eq $dialog.SelectedPath) {
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
    Write-Host "Running SteamCMD update..."
    try {
        # Check if steamcmd.exe exists before attempting to run it
        if (Test-Path $steamCmdPath) {
            Write-Host "SteamCMD executable found at $steamCmdPath"
            Start-Process -FilePath $steamCmdPath -ArgumentList "+login anonymous +quit" -NoNewWindow -Wait
            Write-Host "SteamCMD updated successfully."
        } else {
            Write-Host "SteamCMD executable not found. Cannot run update."
            exit
        }
    } catch {
        Write-Host "Failed to update SteamCMD: $($_.Exception.Message)"
    }
}

# MAIN SCRIPT FLOW
$SteamCMDPath = Select-FolderDialog
if (-Not $SteamCMDPath) {
    Write-Host "No directory selected, exiting..."
    exit
}

Write-Host "Selected installation directory: $SteamCMDPath"

# Ensure the SteamCMD directory exists
$serverManagerDir = Join-Path $SteamCMDPath "servermanager"
Servermanager -dir $SteamCMDPath
Servermanager -dir $serverManagerDir

# Set log file and config paths inside the servermanager directory AFTER the directory is confirmed to exist
$global:logFilePath = Join-Path $serverManagerDir "Install-Log.txt"
Write-Log "Log file path set to: $global:logFilePath"

# Prepare the paths and registry values
$steamCmdZip = Join-Path $SteamCMDPath "steamcmd.zip"
$steamCmdExe = Join-Path $SteamCMDPath "steamcmd.exe"

# Combine all admin-required tasks into a single elevated process
$scriptBlock = @"
    # Create or recreate registry key and properties
    try {
        Write-Host 'Attempting to create the registry key at path: $($registryPath)'

        # Remove existing registry key if found (to avoid old entries)
        if (Test-Path -Path '$($registryPath)') {
            Remove-Item -Path '$($registryPath)' -Recurse -Force
            Write-Host 'Removed existing registry key: $($registryPath)'
            Start-Sleep -Seconds 2
        }

        # Create new registry key
        New-Item -Path '$($registryPath)' -Force
        Write-Host 'Created new registry key: $($registryPath)'

        # Set registry properties
        Set-ItemProperty -Path '$($registryPath)' -Name 'SteamCMDPath' -Value '$($SteamCMDPath)' -Force
        Set-ItemProperty -Path '$($registryPath)' -Name 'servermanagerdir' -Value '$($servermanagerDir)' -Force
        Write-Host 'Updated registry with new SteamCMDPath and servermanagerdir values.'

    } catch {
        Write-Host 'Failed to recreate or set registry properties: $($_.Exception.Message)'
        exit
    }

    # Download SteamCMD if steamcmd.exe does not exist
    if (-Not (Test-Path '$($steamCmdExe)')) {
        try {
            Write-Host 'Downloading SteamCMD from $($steamCmdUrl)...'
            Invoke-WebRequest -Uri '$($steamCmdUrl)' -OutFile '$($steamCmdZip)' -ErrorAction Stop
            Write-Host 'Successfully downloaded SteamCMD to $($steamCmdZip)'

            # Unzip the SteamCMD zip file
            Write-Host 'Unzipping SteamCMD to $($SteamCMDPath)...'
            Expand-Archive -Path '$($steamCmdZip)' -DestinationPath '$($SteamCMDPath)' -Force
            Write-Host 'Successfully unzipped SteamCMD'

            # Verify if steamcmd.exe exists after extraction
            if (Test-Path '$($steamCmdExe)') {
                Write-Host 'SteamCMD executable found at $($steamCmdExe)'
            } else {
                Write-Host 'SteamCMD executable not found after extraction. Exiting...'
                exit
            }

            # Remove the downloaded zip file
            Remove-Item -Path '$($steamCmdZip)' -Force
            Write-Host 'Removed SteamCMD zip file: $($steamCmdZip)'
        } catch {
            Write-Host 'Failed to download or unzip SteamCMD: $($_.Exception.Message)'
            exit
        }
    } else {
        Write-Host 'SteamCMD executable already exists, skipping download and extraction.'
    }

    # Create config.json file
    try {
        \$configData = @{
            SteamCmdPath = '$($steamCmdExe)'
        }
        \$configJson = \$configData | ConvertTo-Json -Depth 3
        \$configJson | Set-Content -Path '$($serverManagerDir)' -Encoding UTF8
        Write-Host 'Created config.json file at $($serverManagerDir)'
    } catch {
        Write-Host 'Failed to create config.json: $($_.Exception.Message)'
    }

    Write-Host 'All admin-required tasks completed successfully.'
"@

# Run all admin tasks in one elevation request
Start-ElevatedProcess -scriptBlock $scriptBlock

# Run the SteamCMD update (does not require admin rights)
Update-SteamCmd -steamCmdPath $steamCmdExe

# End of script
Write-Log "SteamCMD successfully installed to $SteamCMDPath and path saved to $serverManagerDir."
