Add-Type -AssemblyName System.Windows.Forms

# Define the SteamCMD download URL
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# Define the registry path for configuration
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"

# Define the Git repository URL
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

# Variable to store log entries in RAM
$logMemory = @()

# Current Version of this script
$CurrentVersion = v0.1

# Function to check if the current user is an administrator
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adminRole = (New-Object Security.Principal.WindowsPrincipal $currentUser).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    return $adminRole
}

# Function to run a script block with elevated privileges (for registry changes)
function Start-ElevatedProcess {
    param (
        [string]$scriptBlock
    )

    $psExe = "$($env:SystemRoot)\System32\WindowsPowerShell\v1.0\powershell.exe"
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($scriptBlock))
    
    Start-Process -FilePath $psExe -ArgumentList "-NoProfile -EncodedCommand $encodedCommand" -Verb RunAs -Wait
}

# Function to create a directory if it doesn't exist (non-admin)
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

# Function to write messages to log (stored in memory first)
function Write-Log {
    param (
        [string]$message
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    
    # Store the log message in memory
    $global:logMemory += $logMessage
}

# Function to flush the log from memory to file
function Flush-LogToFile {
    param (
        [string]$logFilePath
    )

    if (-not $logFilePath) {
        Write-Host "Log file path is not set. Cannot write log."
        return
    }

    try {
        # Write each log entry stored in memory to the log file
        foreach ($logMessage in $global:logMemory) {
            Add-Content -Path $logFilePath -Value $logMessage
        }
        Write-Host "Log successfully written to file: $logFilePath"
    } catch {
        Write-Host "Failed to write to log file: $($_.Exception.Message)"
    }

    # Clear the in-memory log after flushing
    $global:logMemory = @()
}

# Function to open folder selection dialog (non-admin)
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

# Function to update and run SteamCMD (non-admin)
function Update-SteamCmd {
    param (
        [string]$steamCmdPath
    )
    Write-Host "Running SteamCMD update..."
    try {
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

# Function to update (pull) or clone Git repository (non-admin)
function Update-GitRepo {
    param (
        [string]$repoUrl,
        [string]$destination
    )
    
    Write-Host "Updating Git repository at $destination"
    try {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            if (Test-Path -Path (Join-Path $destination ".git")) {
                Write-Host "Performing git pull to update repository."
                Set-Location -Path $destination
                git pull
                Set-Location -Path $PSScriptRoot
                Write-Host "Git repository updated successfully."
            } else {
                if (Test-Path $destination) {
                    if ((Get-ChildItem $destination | Measure-Object).Count -gt 0) {
                        Write-Host "Directory is not a Git repository and is not empty. Deleting the existing directory."
                        Remove-Item -Recurse -Force -Path $destination
                    }
                }
                Write-Host "Cloning new repository."
                git clone $repoUrl $destination
                Write-Host "Git repository successfully cloned."
            }
        } else {
            Write-Host "Git is not installed or not found in the PATH."
            exit
        }
    } catch {
        Write-Host "Failed to update Git repository: $($_.Exception.Message)"
    }
}

# MAIN SCRIPT FLOW
$SteamCMDPath = Select-FolderDialog
if (-Not $SteamCMDPath) {
    Write-Host "No directory selected, exiting..."
    exit
}

Write-Log "Selected installation directory: $SteamCMDPath"

# Ensure the SteamCMD directory exists (non-admin)
$ServerManagerDir = Join-Path $SteamCMDPath "Servermanager"
Servermanager -dir $SteamCMDPath
Servermanager -dir $ServerManagerDir

# Update the Git repository into the Servermanager directory (either pull or clone)
Update-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir

# Set log file paths inside the Servermanager directory AFTER the Git repository is updated
$global:logFilePath = Join-Path $ServerManagerDir "Install-Log.txt"

# Ensure the log file is created before we start writing
if (-not (Test-Path $global:logFilePath)) {
    New-Item -ItemType File -Path $global:logFilePath -Force
}

Write-Log "Log file path set to: $global:logFilePath"

# Flush all logs from memory to the log file
Flush-LogToFile -logFilePath $global:logFilePath

# Download SteamCMD if steamcmd.exe does not exist (non-admin)
$steamCmdZip = Join-Path $SteamCMDPath "steamcmd.zip"
$steamCmdExe = Join-Path $SteamCMDPath "steamcmd.exe"

if (-Not (Test-Path $steamCmdExe)) {
    try {
        Write-Host "Downloading SteamCMD from $steamCmdUrl..."
        Invoke-WebRequest -Uri $steamCmdUrl -OutFile $steamCmdZip -ErrorAction Stop
        Write-Host "Successfully downloaded SteamCMD to $steamCmdZip"

        Write-Host "Unzipping SteamCMD to $SteamCMDPath..."
        Expand-Archive -Path $steamCmdZip -DestinationPath $SteamCMDPath -Force
        Write-Host "Successfully unzipped SteamCMD"
        Remove-Item -Path $steamCmdZip -Force
    } catch {
        Write-Log "Failed to download or unzip SteamCMD: $($_.Exception.Message)"
        exit
    }
} else {
    Write-Host "SteamCMD executable already exists."
}

# Combine registry-related admin-required tasks into a single elevated process
$scriptBlock = @"
    try {
        if (Test-Path -Path '$($registryPath)') {
            Remove-Item -Path '$($registryPath)' -Recurse -Force
            Start-Sleep -Seconds 2
        }
        New-Item -Path '$($registryPath)' -Force
        Set-ItemProperty -Path '$($registryPath)' -Name 'SteamCMDPath' -Value '$($SteamCMDPath)' -Force
        Set-ItemProperty -Path '$($registryPath)' -Name 'Servermanagerdir' -Value '$($ServerManagerDir)' -Force
        Set-ItemProperty -Path '$($registryPath)' -Name 'CurrentVersion' -Value '$($CurrentVersion)' -Force
    } catch {
        exit
    }
"@

# RUn the registry creation after PATH has been selected
Start-ElevatedProcess -scriptBlock $scriptBlock

# Run the SteamCMD update (non-admin)
Update-SteamCmd -steamCmdPath $steamCmdExe

# Finalise and exit
Write-Log "SteamCMD successfully installed to $SteamCMDPath"
Flush-LogToFile -logFilePath $global:logFilePath
Exit