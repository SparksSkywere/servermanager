Add-Type -AssemblyName System.Windows.Forms

# Define global variables first
$global:logMemory = @()
$global:logFilePath = $null
$CurrentVersion = "0.2"
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

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
function New-Servermanager {
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

# Function to write the log from memory to file
function Write-LogToFile {
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
            # Use a more reliable Git download URL
            $installerUrl = "https://api.github.com/repos/git-for-windows/git/releases/latest"
            $latestRelease = Invoke-RestMethod -Uri $installerUrl
            $installerUrl = ($latestRelease.assets | Where-Object { $_.name -like "*64-bit.exe" }).browser_download_url
            $installerPath = Join-Path $env:TEMP "git-installer.exe"

            Write-Host "Downloading Git installer..."
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Host "Running Git installer..."
            Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART" -Wait

            # Verify installation
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
                throw "Git installation failed verification"
            }

            Write-Host "Git installation completed."
            Remove-Item -Path $installerPath -Force
        } catch {
            Write-Host "Failed to install Git: $($_.Exception.Message)"
            exit 1
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
                Write-Host "Existing Git repository found."
                Set-Location -Path $destination
                
                # Stash any local changes
                Write-Host "Stashing local changes..."
                git stash push -m "Auto-stashed during update"
                
                # Get current branch name
                $currentBranch = git rev-parse --abbrev-ref HEAD
                
                # Fetch updates
                Write-Host "Fetching updates..."
                git fetch origin
                
                # Attempt to merge changes
                Write-Host "Merging changes..."
                git merge "origin/$currentBranch" --no-commit
                
                # Check for merge conflicts
                $hasConflicts = git diff --name-only --diff-filter=U
                if ($hasConflicts) {
                    Write-Host "Merge conflicts detected. Keeping local changes..."
                    git merge --abort
                    git stash pop
                } else {
                    # Complete the merge if no conflicts
                    git commit -m "Auto-merged updates"
                }
                
                Set-Location -Path $PSScriptRoot
                Write-Host "Git repository updated successfully."
            } else {
                if (Test-Path $destination) {
                    # Backup existing non-git files
                    $backupDir = "$destination-backup-$(Get-Date -Format 'yyyyMMddHHmmss')"
                    Write-Host "Creating backup of existing files to: $backupDir"
                    Copy-Item -Path $destination -Destination $backupDir -Recurse -Force
                    
                    # Clone new repository
                    Write-Host "Cloning new repository..."
                    git clone $repoUrl "$destination-temp"
                    
                    # Move existing config files back if they exist
                    $configsToPreserve = @(
                        "config/auth.xml",
                        "config/users.xml",
                        "config/admin.xml",
                        "AppID.txt"
                    )
                    
                    foreach ($config in $configsToPreserve) {
                        $sourcePath = Join-Path $backupDir $config
                        $destPath = Join-Path "$destination-temp" $config
                        if (Test-Path $sourcePath) {
                            Write-Host "Preserving existing config: $config"
                            $destDir = Split-Path $destPath -Parent
                            if (-not (Test-Path $destDir)) {
                                New-Item -ItemType Directory -Path $destDir -Force
                            }
                            Copy-Item -Path $sourcePath -Destination $destPath -Force
                        }
                    }
                    
                    # Remove original directory and move new one in place
                    Remove-Item -Path $destination -Recurse -Force
                    Move-Item -Path "$destination-temp" -Destination $destination
                }
                else {
                    Write-Host "Cloning new repository..."
                    git clone $repoUrl $destination
                }
                Write-Host "Git repository successfully cloned."
            }
        } else {
            Write-Host "Git is not installed or not found in the PATH."
            exit
        }
    } catch {
        Write-Host "Failed to update Git repository: $($_.Exception.Message)"
        if (Test-Path "$destination-temp") {
            Remove-Item -Path "$destination-temp" -Recurse -Force
        }
        throw
    }
}

# Create AppID.txt file | Future fixes planned for this file
function New-AppIDFile {
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

# Function to install required PowerShell modules
function Install-RequiredModules {
    Write-Host "Installing required PowerShell modules..."
    
    # Ensure TLS 1.2 is used
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    
    try {
        # List of required modules with their minimum versions
        $modules = @(
            @{
                Name = "Microsoft.PowerShell.SecretManagement"
                MinimumVersion = "1.1.0"
            }
        )

        # First ensure NuGet is installed as a package provider
        if (!(Get-PackageProvider -Name NuGet -ErrorAction SilentlyContinue)) {
            Write-Host "Installing NuGet package provider..."
            Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser
        }

        # Set PSGallery as trusted
        if ((Get-PSRepository -Name "PSGallery").InstallationPolicy -ne "Trusted") {
            Write-Host "Setting PSGallery as trusted..."
            Set-PSRepository -Name "PSGallery" -InstallationPolicy Trusted
        }

        foreach ($module in $modules) {
            try {
                if (-not (Get-Module -ListAvailable -Name $module.Name | 
                         Where-Object { $_.Version -ge $module.MinimumVersion })) {
                    Write-Host "Installing $($module.Name) module version $($module.MinimumVersion)..."
                    Install-Module -Name $module.Name -Force -AllowClobber -Scope CurrentUser -MinimumVersion $module.MinimumVersion -Repository PSGallery
                    Write-Host "$($module.Name) module installed successfully."
                } else {
                    Write-Host "$($module.Name) module is already installed with required version."
                }
            } catch {
                Write-Host "Failed to install $($module.Name) module: $($_.Exception.Message)" -ForegroundColor Red
            }
        }

        # Verify ServerManager module path exists before importing
        $serverManagerPath = Join-Path $ServerManagerDir "Modules\ServerManager\ServerManager.psm1"
        if (Test-Path $serverManagerPath) {
            Import-Module $serverManagerPath -Force -ErrorAction Stop
            Write-Host "ServerManager module imported successfully."
        } else {
            Write-Host "Warning: ServerManager.psm1 not found at: $serverManagerPath" -ForegroundColor Yellow
            # Create empty module file
            New-Item -ItemType File -Path $serverManagerPath -Force
        }
    } catch {
        Write-Host "Module installation error: $($_.Exception.Message)" -ForegroundColor Red
        # Continue installation despite module errors
    }
}

# Modify Set-InitialAuthConfig function
function Set-InitialAuthConfig {
    param([string]$ServerManagerDir)
    
    Write-Log "Starting authentication configuration setup"
    
    try {
        # Import security module
        Import-Module (Join-Path $ServerManagerDir "Modules\ServerManager\Security.psm1") -Force
        
        $configDir = Join-Path $ServerManagerDir "config"
        $usersFile = Join-Path $configDir "users.xml"
        
        # Create config directory with restricted access
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        $acl = Get-Acl $configDir
        $acl.SetAccessRuleProtection($true, $false)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "FullControl", "Allow")
        $acl.AddAccessRule($rule)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $env:USERNAME, "FullControl", "Allow")
        $acl.AddAccessRule($rule)
        Set-Acl $configDir $acl
        
        # Setup root admin account with enhanced security
        do {
            $adminUser = Read-Host "Enter root admin username (minimum 4 characters)"
            if ($adminUser.Length -lt 4) {
                Write-Host "Username must be at least 4 characters long" -ForegroundColor Red
            }
        } while ($adminUser.Length -lt 4)

        do {
            $adminPass = Read-Host "Enter root admin password (minimum 12 characters)" -AsSecureString
            $adminPassConfirm = Read-Host "Confirm root admin password" -AsSecureString
            
            $passPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPass))
            $passConfirmPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPassConfirm))
            
            if ($passPlain.Length -lt 12) {
                Write-Host "Password must be at least 12 characters long" -ForegroundColor Red
                continue
            }
            
            if ($passPlain -ne $passConfirmPlain) {
                Write-Host "Passwords do not match. Please try again." -ForegroundColor Red
            }
            
            # Clear sensitive data
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPass))
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPassConfirm))
            
        } while ($passPlain.Length -lt 12 -or $passPlain -ne $passConfirmPlain)

        # Generate unique salt and hash password
        $salt = New-Salt
        $hash = Get-SecureHash -SecurePassword $adminPass -Salt $salt
        
        # Create users file with encrypted credentials
        $users = @(
            @{
                Username = $adminUser
                PasswordHash = $hash
                Salt = $salt
                IsAdmin = $true
                Created = Get-Date -Format "o"
                LastModified = Get-Date -Format "o"
            }
        )
        
        $users | Export-Clixml -Path $usersFile
        
        # Protect the users file
        Protect-ConfigFile -FilePath $usersFile
        
        Write-Host "`nAuthentication setup completed successfully!" -ForegroundColor Green
        Write-Host "Root admin account created with enhanced security" -ForegroundColor Cyan
        Write-Log "Authentication configuration completed successfully"
        
    }
    catch {
        Write-Log "Failed to configure authentication: $($_.Exception.Message)" -Level "ERROR"
        throw "Failed to configure authentication. Error: $($_.Exception.Message)"
    }
    finally {
        # Clear sensitive data from memory
        if ($adminPass) { $adminPass.Dispose() }
        if ($adminPassConfirm) { $adminPassConfirm.Dispose() }
        if ($passPlain) { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR([System.Runtime.InteropServices.Marshal]::StringToBSTR($passPlain)) }
        if ($passConfirmPlain) { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR([System.Runtime.InteropServices.Marshal]::StringToBSTR($passConfirmPlain)) }
        if ($hash) { Clear-Variable hash }
        if ($salt) { Clear-Variable salt }
    }
}

function Get-HashString {
    param([string]$InputString)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($InputString)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return [Convert]::ToBase64String($hash)
}

# Add this function for path validation
function Test-ValidPath {
    param([string]$Path)
    
    try {
        $null = [System.IO.Path]::GetFullPath($Path)
        return $true
    } catch {
        return $false
    }
}

# Modify Test-RegistryAccess function to be more reliable
function Test-RegistryAccess {
    param([string]$Path)
    
    try {
        # Try to create a test key to verify write access
        $testPath = "HKLM:\Software\SkywereIndustries\Test"
        if (-not (Test-Path "HKLM:\Software\SkywereIndustries")) {
            New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
        }
        New-Item -Path $testPath -Force | Out-Null
        Remove-Item -Path $testPath -Force
        return $true
    } catch {
        Write-Host "Registry access test failed: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

# Add function to ensure admin elevation
function Test-AdminPrivileges {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "Requesting administrative privileges..." -ForegroundColor Yellow
        $arguments = "& '" + $MyInvocation.MyCommand.Path + "'"
        Start-Process powershell -Verb RunAs -ArgumentList $arguments
        exit
    }
}

# MAIN SCRIPT FLOW
Ensure-AdminPrivileges

$SteamCMDPath = Select-FolderDialog
if (-Not $SteamCMDPath) {
    Write-Host "No directory selected, exiting..."
    exit
}

Write-Log "Selected installation directory: $SteamCMDPath"

# Validate paths before proceeding
if (-not (Test-ValidPath $SteamCMDPath)) {
    Write-Host "Invalid SteamCMD path selected" -ForegroundColor Red
    exit 1
}

# Ensure the SteamCMD directory exists (non-admin)
$ServerManagerDir = Join-Path $SteamCMDPath "Servermanager"
New-Servermanager -dir $SteamCMDPath
New-Servermanager -dir $ServerManagerDir

# Create the Modules directory structure
$ModulesDir = Join-Path $ServerManagerDir "Modules\ServerManager"
New-Servermanager -dir $ModulesDir

# Update the Git repository into the Servermanager directory (either pull or clone)
Update-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir

# Install required PowerShell modules after Git repo is cloned
Install-RequiredModules

# Create the AppID.txt file
New-AppIDFile -serverManagerDir $ServerManagerDir

# Set log file paths inside the Servermanager directory AFTER the Git repository is updated
$global:logFilePath = Join-Path $ServerManagerDir "Install-Log.txt"

# Ensure the log file is created before we start writing
if (-not (Test-Path $global:logFilePath)) {
    New-Item -ItemType File -Path $global:logFilePath -Force
}

Write-Log "Log file path set to: $global:logFilePath"

# Write all logs from memory to the log file
Write-LogToFile -logFilePath $global:logFilePath

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

# Replace the registry validation and creation section
try {
    Write-Host "Creating registry entries..." -ForegroundColor Cyan
    if (-not (Test-Path "HKLM:\Software\SkywereIndustries")) {
        New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
    }
    if (-not (Test-Path $registryPath)) {
        New-Item -Path $registryPath -Force | Out-Null
    }
    
    # Create registry values directly instead of using a script block
    $registryValues = @{
        'CurrentVersion' = $CurrentVersion
        'SteamCMDPath' = $SteamCMDPath
        'Servermanagerdir' = $ServerManagerDir
        'InstallDate' = (Get-Date).ToString('o')
        'LastUpdate' = (Get-Date).ToString('o')
        'WebPort' = '8080'
        'ModulePath' = "$ServerManagerDir\Modules\ServerManager"
        'LogPath' = "$ServerManagerDir\logs"
    }

    foreach ($key in $registryValues.Keys) {
        Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
    }
    
    Write-Host "Registry entries created successfully." -ForegroundColor Green
} catch {
    Write-Host "Failed to create registry entries: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Please ensure you're running as administrator." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Install Git
Install-Git

# Run the SteamCMD update (non-admin)
Update-SteamCmd -steamCmdPath $steamCmdExe

# Add before the final success message
Write-Host "`nSetting up authentication..." -ForegroundColor Cyan
Set-InitialAuthConfig -ServerManagerDir $ServerManagerDir

# Finalise and exit
Write-Log "SteamCMD successfully installed to $SteamCMDPath"
Write-LogToFile -logFilePath $global:logFilePath

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