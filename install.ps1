Add-Type -AssemblyName System.Windows.Forms

# Define global variables first
$global:logMemory = @()
$global:logFilePath = $null
$CurrentVersion = "0.2"
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

# Add this right after the initial variable definitions
function Get-InstallationOptions {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Server Manager Installation Options"
    $form.Size = New-Object System.Drawing.Size(400,200)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $serviceCheckbox = New-Object System.Windows.Forms.CheckBox
    $serviceCheckbox.Text = "Install as Windows Service"
    $serviceCheckbox.Location = New-Object System.Drawing.Point(20,20)
    $serviceCheckbox.Size = New-Object System.Drawing.Size(350,20)
    $form.Controls.Add($serviceCheckbox)

    $infoLabel = New-Object System.Windows.Forms.Label
    $infoLabel.Text = "Running as a service allows Server Manager to start automatically with Windows."
    $infoLabel.Location = New-Object System.Drawing.Point(20,50)
    $infoLabel.Size = New-Object System.Drawing.Size(350,40)
    $form.Controls.Add($infoLabel)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = "Continue"
    $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $okButton.Location = New-Object System.Drawing.Point(150,100)
    $form.Controls.Add($okButton)
    $form.AcceptButton = $okButton

    $result = $form.ShowDialog()
    
    return @{
        InstallService = ($result -eq [System.Windows.Forms.DialogResult]::OK -and $serviceCheckbox.Checked)
    }
}

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

# Modify Install-RequiredModules function to match actual repository structure
function Install-RequiredModules {
    param([string]$ServerManagerDir)
    
    Write-Host "Installing required PowerShell modules..." -ForegroundColor Cyan
    
    try {
        $modulesPath = Join-Path $ServerManagerDir "Modules"
        
        if (-not (Test-Path $modulesPath)) {
            throw "Modules directory not found at: $modulesPath"
        }

        # Install SecretManagement if needed
        if (-not (Get-Module -ListAvailable -Name "Microsoft.PowerShell.SecretManagement")) {
            Install-Module -Name "Microsoft.PowerShell.SecretManagement" -Force -Scope CurrentUser
        }

        # Only load modules needed for installation
        $installModules = @(
            "Security"     # Needed for encryption and authentication setup
            "Logging"      # Needed for installation logging
        )

        $successCount = 0
        foreach ($moduleName in $installModules) {
            $modulePath = Join-Path $modulesPath "$moduleName.psm1"
            if (Test-Path $modulePath) {
                try {
                    Write-Host "Importing installation module: $moduleName"
                    Import-Module -Name $modulePath -Force -Global -ErrorAction Stop
                    $successCount++
                } catch {
                    Write-Host "Error importing module $moduleName : $($_.Exception.Message)" -ForegroundColor Red
                    Write-Host "Full Error: $($_)" -ForegroundColor Red
                }
            } else {
                Write-Host "Critical module not found: $modulePath" -ForegroundColor Red
                return $false
            }
        }

        # Verify core modules were loaded
        if ($successCount -ne $installModules.Count) {
            Write-Host "Not all required installation modules were loaded." -ForegroundColor Red
            return $false
        }

        Write-Host "Successfully loaded installation modules." -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "Module installation error: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Add this function after Install-RequiredModules and before Set-InitialAuthConfig
function Initialize-EncryptionKey {
    # Keep encryption key in ProgramData for security
    $encryptionKeyPath = "C:\ProgramData\ServerManager"
    $keyFile = Join-Path $encryptionKeyPath "encryption.key"

    try {
        # Create directory if it doesn't exist
        if (-not (Test-Path $encryptionKeyPath)) {
            New-Item -Path $encryptionKeyPath -ItemType Directory -Force | Out-Null
            
            # Set appropriate permissions
            $acl = Get-Acl $encryptionKeyPath
            $acl.SetAccessRuleProtection($true, $false)
            
            # Add SYSTEM with full control
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
            $acl.AddAccessRule($rule)
            
            # Add Administrators with full control
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
            $acl.AddAccessRule($rule)
            
            Set-Acl $encryptionKeyPath $acl
        }

        # Generate and save encryption key if it doesn't exist
        if (-not (Test-Path $keyFile)) {
            $key = New-Object byte[] 32
            $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
            $rng.GetBytes($key)
            $key | Set-Content -Path $keyFile -Encoding Byte
            
            # Set restrictive permissions on the key file
            $acl = Get-Acl $keyFile
            $acl.SetAccessRuleProtection($true, $false)
            
            # Only SYSTEM and Administrators should have access
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "SYSTEM", "FullControl", "Allow")
            $acl.AddAccessRule($rule)
            
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "Administrators", "FullControl", "Allow")
            $acl.AddAccessRule($rule)
            
            Set-Acl $keyFile $acl
        }
        
        Write-Host "Encryption key setup completed successfully" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "Failed to initialize encryption key: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Modify Set-InitialAuthConfig function
function Set-InitialAuthConfig {
    param([string]$ServerManagerDir)
    
    Write-Log "Starting authentication configuration setup"
    
    try {
        # Initialize encryption key before proceeding
        if (-not (Initialize-EncryptionKey)) {
            throw "Failed to initialize encryption key"
        }
        
        # Update security module path
        Import-Module (Join-Path $ServerManagerDir "Modules\Security.psm1") -Force
        
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
        
        # Modified user object structure
        $users = @(
            @{
                Username = $adminUser
                PasswordHash = $hash
                Salt = $salt
                IsAdmin = $true  # Explicitly set to true
                Created = Get-Date -Format "o"
                LastModified = Get-Date -Format "o"
                Type = "Admin"   # Add explicit type
                Enabled = $true  # Add enabled status
                Permissions = @{  # Add detailed permissions
                    IsAdmin = $true
                    CanManageUsers = $true
                    CanManageServers = $true
                }
            }
        )
        
        # Create config directory if it doesn't exist
        $configDir = Join-Path $ServerManagerDir "config"
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }

        # Export with specific encoding and format
        $usersFile = Join-Path $configDir "users.xml"
        $users | Export-Clixml -Path $usersFile -Force

        # Also create an admin config file to ensure admin status is preserved
        $adminConfig = @{
            AdminUsers = @($adminUser)
            LastModified = Get-Date -Format "o"
        }
        
        $adminConfigFile = Join-Path $configDir "admin.xml"
        $adminConfig | Export-Clixml -Path $adminConfigFile -Force

        # Protect both files
        Protect-ConfigFile -FilePath $usersFile
        Protect-ConfigFile -FilePath $adminConfigFile
        
        Write-Log "Authentication configuration completed successfully"
        Write-Host "`nAdmin account created successfully with username: $adminUser" -ForegroundColor Green
        
        return $true
    }
    catch {
        Write-Log "Failed to configure authentication: $($_.Exception.Message)"
        throw
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

# Function to show completion dialog
function Show-CompletionDialog {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Server Manager Installer"
    $form.Width = 350
    $form.Height = 150
    $form.FormBorderStyle = 'FixedDialog'
    $form.StartPosition = 'CenterScreen'

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "SteamCMD successfully installed and set up!"
    $label.AutoSize = $true
    $label.TextAlign = 'MiddleCenter'
    $label.Location = New-Object System.Drawing.Point(
        [math]::Max(0, ($form.ClientSize.Width - $label.PreferredWidth) / 2), 
        30
    )

    $button = New-Object System.Windows.Forms.Button
    $button.Text = "OK"
    $button.Width = 80
    $button.Height = 30
    $button.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $button.Location = New-Object System.Drawing.Point(
        [math]::Max(0, ($form.ClientSize.Width - $button.Width) / 2),
        70
    )

    $form.Controls.AddRange(@($label, $button))
    $form.AcceptButton = $button
    $form.ShowDialog()
}

# Add this function before Install-RequiredModules
function Install-ExternalModules {
    param([string]$RequirementsPath)
    
    Write-Host "Installing external PowerShell modules..." -ForegroundColor Cyan
    
    if (-not (Test-Path $RequirementsPath)) {
        Write-Host "Requirements file not found at: $RequirementsPath" -ForegroundColor Yellow
        return $false
    }
    
    try {
        $modules = Get-Content $RequirementsPath | Where-Object { $_ -match '\S' } | ForEach-Object { $_.Trim() }
        
        foreach ($module in $modules) {
            Write-Host "Installing module: $module"
            try {
                Install-Module -Name $module -Force -AllowClobber -Scope CurrentUser -ErrorAction Stop
                Write-Host "Successfully installed $module" -ForegroundColor Green
            }
            catch {
                Write-Host "Failed to install module $module : $($_.Exception.Message)" -ForegroundColor Red
                return $false
            }
        }
        
        return $true
    }
    catch {
        Write-Host "Error reading requirements file: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# MAIN SCRIPT FLOW
try {
    Test-AdminPrivileges

    # Get installation options first
    $installOptions = Get-InstallationOptions
    
    $SteamCMDPath = Select-FolderDialog
    if (-Not $SteamCMDPath -or -not (Test-ValidPath $SteamCMDPath)) {
        throw "Invalid or no directory selected"
    }

    # Create base directories first
    New-Servermanager -dir $SteamCMDPath
    $ServerManagerDir = Join-Path $SteamCMDPath "Servermanager"
    New-Item -ItemType Directory -Force -Path $ServerManagerDir | Out-Null
    
    # Set up logging
    $global:logFilePath = Join-Path $ServerManagerDir "Install-Log.txt"
    Write-Log "Installation started"
    Write-Log "Selected installation directory: $SteamCMDPath"
    Write-Log "Installation options selected: Service install = $($installOptions.InstallService)"

    # Create registry structure
    if (-not (Test-RegistryAccess)) {
        throw "Insufficient registry access"
    }

    $registryValues = @{
        'CurrentVersion' = $CurrentVersion
        'SteamCMDPath' = $SteamCMDPath
        'Servermanagerdir' = $ServerManagerDir
        'InstallDate' = (Get-Date).ToString('o')
        'LastUpdate' = (Get-Date).ToString('o')
        'WebPort' = '8080'
        'ModulePath' = "$ServerManagerDir\Modules"
        'LogPath' = "$ServerManagerDir\logs"
    }

    New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
    New-Item -Path $registryPath -Force | Out-Null
    foreach ($key in $registryValues.Keys) {
        Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
    }

    # Git operations first to get repository content
    Install-Git
    Update-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir

    # Now that we have the repository, we can install external modules
    $requirementsPath = Join-Path $ServerManagerDir "requirements.txt"
    if (-not (Install-ExternalModules -RequirementsPath $requirementsPath)) {
        throw "Failed to install required external modules"
    }

    # After external modules, install internal modules
    if (-not (Install-RequiredModules -ServerManagerDir $ServerManagerDir)) {
        throw "Module installation failed"
    }

    # SteamCMD installation
    $steamCmdExe = Join-Path $SteamCMDPath "steamcmd.exe"
    if (-Not (Test-Path $steamCmdExe)) {
        $steamCmdZip = Join-Path $SteamCMDPath "steamcmd.zip"
        Invoke-WebRequest -Uri $steamCmdUrl -OutFile $steamCmdZip
        Expand-Archive -Path $steamCmdZip -DestinationPath $SteamCMDPath -Force
        Remove-Item -Path $steamCmdZip -Force
    }

    Update-SteamCmd -steamCmdPath $steamCmdExe
    New-AppIDFile -serverManagerDir $ServerManagerDir
    Set-InitialAuthConfig -ServerManagerDir $ServerManagerDir

    # Service installation last
    if ($installOptions.InstallService) {
        Write-Log "Setting up Windows Service..."
        try {
            # Create service script
            $serviceScript = @"
#Requires -RunAsAdministrator
`$PSScriptRoot = Split-Path -Parent `$MyInvocation.MyCommand.Path
`$launcherPath = Join-Path `$PSScriptRoot "Scripts\launcher.ps1"
& `$launcherPath -AsService
"@
            $serviceScriptPath = Join-Path $ServerManagerDir "service.ps1"
            $serviceScript | Set-Content -Path $serviceScriptPath -Force

            # Create service
            $serviceName = "ServerManagerService"
            $displayName = "Server Manager Service"
            $binPath = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$serviceScriptPath`""

            if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
                Write-Log "Removing existing service..."
                Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
                $null = sc.exe delete $serviceName
                Start-Sleep -Seconds 2
            }

            Write-Log "Creating new service..."
            $null = New-Service -Name $serviceName `
                              -DisplayName $displayName `
                              -Description "Manages game servers and provides web interface" `
                              -BinaryPathName $binPath `
                              -StartupType Automatic

            Write-Log "Service installation completed"
            
            # Start the service
            Write-Log "Starting service..."
            Start-Service -Name $serviceName
            Write-Log "Service started successfully"
        }
        catch {
            Write-Log "Failed to install service: $($_.Exception.Message)"
            throw
        }
    }

    Write-Log "Installation completed successfully"
    Write-LogToFile -logFilePath $global:logFilePath

    Show-CompletionDialog
}
catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Log "Installation failed: $($_.Exception.Message)"
    if (Test-Path (Split-Path $global:logFilePath -Parent)) {
        Write-LogToFile -logFilePath $global:logFilePath
    }
    exit 1
}

exit 0