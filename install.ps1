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
$CurrentVersion = "0.2"

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

# Function to check and install Git if missing
function Install-Git {
    if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "Git is not installed. Installing Git..."
        try {
            $installerUrl = "https://github.com/git-for-windows/git/releases/latest/download/Git-2.43.0-64-bit.exe"
            $installerPath = Join-Path $env:TEMP "git-installer.exe"

            Write-Host "Downloading Git installer..."
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Host "Running Git installer..."
            Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART" -Wait

            Write-Host "Git installation completed."
            Remove-Item -Path $installerPath -Force
        } catch {
            Write-Host "Failed to install Git: $($_.Exception.Message)"
            exit
        }
    } else {
        Write-Host "Git is already installed."
    }
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

# Create AppID.txt file | Future fixes planned for this file
function Create-AppIDFile {
    param (
        [string]$serverManagerDir
    )
    $appIDFile = Join-Path $serverManagerDir "AppID.txt"
    if (-Not (Test-Path $appIDFile)) {
        New-Item -Path $appIDFile -ItemType File
        Write-Host "Created AppID.txt file."
    } else {
        Write-Host "AppID.txt file already exists."
    }
}

# Function to add delay between requests
function Add-Delay {
    Start-Sleep -Seconds 2
}

# Function to update AppID.txt with all Steam AppIDs from SteamDB (games only)
function Update-AppIDFile {
    param (
        [string]$serverManagerDir
    )
    
    $appIDFile = Join-Path $serverManagerDir "AppID.txt"
    $maxRetries = 3
    $retryCount = 0

    if (Test-Path $appIDFile) {
        do {
            try {
                # Fetch data from SteamDB API for games only
                Add-Delay
                $apiUrl = "https://steamdb.info/api/GetAppList/"
                # Add header for Cloudflare verification
                $headers = @{
                    'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36'
                }
                $response = Invoke-RestMethod -Uri $apiUrl -Method Get -Headers $headers
                
                # Filter for games only (assuming 'type' field exists and 'game' is one of the values)
                $appIDs = $response.applist.apps | Where-Object { $_.type -eq "game" } | Select-Object -ExpandProperty appid
                
                # Clear the file content before writing new data
                Clear-Content -Path $appIDFile
                
                # Write each AppID on a new line
                foreach ($appID in $appIDs) {
                    Add-Content -Path $appIDFile -Value $appID
                }
                Write-Host "Updated AppID.txt with AppIDs from SteamDB."
                break # This will exit the loop if successful
            }
            catch {
                Write-Host "Failed to fetch or process app IDs from SteamDB (Attempt $($retryCount + 1)/$maxRetries). Error: $_"
                $retryCount++
                if ($retryCount -ge $maxRetries) {
                    throw "Exceeded maximum retries attempting to fetch app IDs."
                }
                Add-Delay # Add a delay before next try
            }
        } while ($retryCount -lt $maxRetries)
    } else {
        Write-Host "AppID.txt does not exist, please create it first."
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

# Create the AppID.txt file
Create-AppIDFile -serverManagerDir $ServerManagerDir

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
        Set-ItemProperty -Path '$($registryPath)' -Name 'CurrentVersion' -Value '$($CurrentVersion)' -Force
        if (-Not (Test-Path -Path '$($registryPath)')) {
            New-Item -Path '$($registryPath)' -Force
            Set-ItemProperty -Path '$($registryPath)' -Name 'SteamCMDPath' -Value '$($SteamCMDPath)' -Force
            Set-ItemProperty -Path '$($registryPath)' -Name 'Servermanagerdir' -Value '$($ServerManagerDir)' -Force
            Write-Host 'Registry keys created.'
        } else {
            Write-Host 'Registry keys already exist, skipping creation.'
        }
    } catch {
        Write-Host 'Failed to manage registry: ' + $_.Exception.Message
        exit
    }
"@

# Run the registry creation after PATH has been selected
Start-ElevatedProcess -scriptBlock $scriptBlock

# Install Git
Install-Git

# Run the SteamCMD update (non-admin)
Update-SteamCmd -steamCmdPath $steamCmdExe

# Update the AppID.txt file with example AppIDs - Disabled for now as cloudflare security setup by SteamDB
#Update-AppIDFile -serverManagerDir $ServerManagerDir

# Finalise and exit
Write-Log "SteamCMD successfully installed to $SteamCMDPath"
Flush-LogToFile -logFilePath $global:logFilePath

Add-Type -AssemblyName System.Windows.Forms

# Create the pop-up window
$form = New-Object System.Windows.Forms.Form
$form.Text = "Server Manager Installer"
$form.Width = 350
$form.Height = 150
$form.FormBorderStyle = 'FixedDialog'
$form.StartPosition = 'CenterScreen'

# Create a label
$label = New-Object System.Windows.Forms.Label
$label.Text = "SteamCMD successfully installed and set up!"
$label.AutoSize = $true
$label.TextAlign = 'MiddleCenter'

# Calculate position to center the label horizontally
[int]$labelX = [math]::Max(0, (($form.ClientSize.Width - $label.PreferredWidth) / 2))
[int]$labelY = 30
$label.Location = New-Object System.Drawing.Point($labelX, $labelY)

# Create a close button
$button = New-Object System.Windows.Forms.Button
$button.Text = "OK"
$button.Width = 80
$button.Height = 30
$button.DialogResult = [System.Windows.Forms.DialogResult]::OK

# Calculate position to center the button horizontally
[int]$buttonX = [math]::Max(0, (($form.ClientSize.Width - $button.Width) / 2))
[int]$buttonY = 70
$button.Location = New-Object System.Drawing.Point($buttonX, $buttonY)

# Add controls to the form
$form.Controls.Add($label)
$form.Controls.Add($button)

# Show the form as a dialog box
$form.AcceptButton = $button
$form.ShowDialog()

Exit