Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Script parameters for both installation and service management
param(
    [Parameter()]
    [ValidateSet("Install", "Uninstall", "Start", "Stop", "Restart", "Status")]
    [string]$ServiceAction,
    
    [Parameter()]
    [switch]$ServiceOnly,
    
    [Parameter()]
    [switch]$Help
)

# Show help if requested
if ($Help) {
    Show-Help
    exit
}

# Check if this is a service management call
if ($ServiceAction -or $ServiceOnly) {
    # Service management mode
    Invoke-ServiceManagement -Action $ServiceAction
    exit
}

# Log function
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "$timestamp - $message"
    $global:logMemory += $logMessage
}

function Write-LogToFile {
    param (
        [string]$logFilePath
    )
    if (-not $logFilePath) { return }
    try {
        foreach ($logMessage in $global:logMemory) {
            Add-Content -Path $logFilePath -Value $logMessage
        }
    } catch {}
    $global:logMemory = @()
}

# Console window handling function (unified version)
function Show-Console {
    param ([Switch]$Show, [Switch]$Hide)
    if (-not ("Console.Window" -as [type])) {
        Add-Type -Name Window -Namespace Console -MemberDefinition '
        [DllImport("Kernel32.dll")]
        public static extern IntPtr GetConsoleWindow();

        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
        '
    }
    $consolePtr = [Console.Window]::GetConsoleWindow()
    $nCmdShow = if ($Show) { 5 } elseif ($Hide) { 0 } else { return }
    [Console.Window]::ShowWindow($consolePtr, $nCmdShow) | Out-Null
    $script:DebugLoggingEnabled = $Show.IsPresent
    Write-Log -Message "Console visibility set to: $($Show.IsPresent)" -Level DEBUG
}

# Hide Console
Show-Console -Hide

# Service Management Functions
function Invoke-ServiceManagement {
    param([string]$Action)
    
    # Check for admin rights and self-elevate if needed
    if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "Administrator rights required. Attempting to restart with elevated privileges..." -ForegroundColor Yellow
        Start-Process PowerShell -Verb RunAs -ArgumentList ("-ExecutionPolicy Bypass -File `"{0}`" -ServiceAction {1} -ServiceOnly" -f $PSCommandPath, $Action)
        exit
    }

    Write-Host "Server Manager Service Manager" -ForegroundColor Cyan
    Write-Host "================================" -ForegroundColor Cyan

    # Get Server Manager directory from registry
    try {
        $regPath = "HKLM:\Software\SkywereIndustries\Servermanager"
        $serverManagerDir = (Get-ItemProperty -Path $regPath -Name "ServerManagerPath").ServerManagerPath
        Write-Host "Server Manager directory: $serverManagerDir" -ForegroundColor Green
    } catch {
        Write-Host "Error: Server Manager installation not found in registry." -ForegroundColor Red
        Write-Host "Please run the installer first." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    # Check if service helper exists
    $serviceHelperPath = Join-Path $serverManagerDir "service_helper.py"
    if (-not (Test-Path $serviceHelperPath)) {
        Write-Host "Error: Service helper script not found at: $serviceHelperPath" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    # Find Python executable
    $pythonPath = Find-PythonExecutable
    if (-not $pythonPath) {
        Write-Host "Error: Python executable not found." -ForegroundColor Red
        Write-Host "Please ensure Python is installed and added to PATH." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Host "Using Python: $pythonPath" -ForegroundColor Green

    # Execute the requested action
    try {
        Write-Host "Executing action: $Action" -ForegroundColor Yellow
        
        $result = & $pythonPath $serviceHelperPath $Action.ToLower() 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Action completed successfully!" -ForegroundColor Green
            Write-Host $result -ForegroundColor White
        } else {
            Write-Host "Action failed!" -ForegroundColor Red
            Write-Host $result -ForegroundColor Red
        }
    } catch {
        Write-Host "Error executing action: $($_.Exception.Message)" -ForegroundColor Red
    }

    # Additional information based on action
    switch ($Action.ToLower()) {
        "install" {
            Write-Host ""
            Write-Host "If installation was successful:" -ForegroundColor Cyan
            Write-Host "- The service is now installed and running" -ForegroundColor White
            Write-Host "- Server Manager will start automatically with Windows" -ForegroundColor White
            Write-Host "- You can access the web interface at http://localhost:8080" -ForegroundColor White
        }
        "uninstall" {
            Write-Host ""
            Write-Host "If uninstallation was successful:" -ForegroundColor Cyan
            Write-Host "- The service has been removed" -ForegroundColor White
            Write-Host "- Server Manager will no longer start automatically" -ForegroundColor White
            Write-Host "- You can still start it manually using Start-ServerManager.pyw" -ForegroundColor White
        }
        "status" {
            Write-Host ""
            Write-Host "Service management commands:" -ForegroundColor Cyan
            Write-Host "- To start:   .\install.ps1 -ServiceAction Start" -ForegroundColor White
            Write-Host "- To stop:    .\install.ps1 -ServiceAction Stop" -ForegroundColor White
            Write-Host "- To restart: .\install.ps1 -ServiceAction Restart" -ForegroundColor White
        }
    }

    Write-Host ""
    Read-Host "Press Enter to exit"
}

function Find-PythonExecutable {
    $pythonPaths = @(
        (Get-Command python -ErrorAction SilentlyContinue).Source,
        (Get-Command python3 -ErrorAction SilentlyContinue).Source,
        "C:\Python\python.exe",
        "C:\Python39\python.exe",
        "C:\Python310\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe"
    )

    foreach ($path in $pythonPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    return $null
}

function Show-Help {
    Write-Host "Server Manager Installer and Service Manager" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  install.ps1                           # Run the installation wizard"
    Write-Host "  install.ps1 -Help                     # Show this help"
    Write-Host ""
    Write-Host "Service Management:" -ForegroundColor Yellow
    Write-Host "  install.ps1 -ServiceAction Install    # Install and start the service"
    Write-Host "  install.ps1 -ServiceAction Uninstall  # Uninstall the service"
    Write-Host "  install.ps1 -ServiceAction Start      # Start the service"
    Write-Host "  install.ps1 -ServiceAction Stop       # Stop the service"
    Write-Host "  install.ps1 -ServiceAction Restart    # Restart the service"
    Write-Host "  install.ps1 -ServiceAction Status     # Show service status"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Green
    Write-Host "  # Install Server Manager (GUI wizard)"
    Write-Host "  .\install.ps1"
    Write-Host ""
    Write-Host "  # Install as Windows service after installation"
    Write-Host "  .\install.ps1 -ServiceAction Install"
    Write-Host ""
    Write-Host "  # Check service status"
    Write-Host "  .\install.ps1 -ServiceAction Status"
    Write-Host ""
    Write-Host "Notes:" -ForegroundColor Cyan
    Write-Host "  - Admin privileges are required for installation and service management"
    Write-Host "  - The installer will automatically elevate if needed"
    Write-Host "  - Service actions require an existing Server Manager installation"
    Write-Host ""
}

# --- Main installer script ---
# Define global variables first
$global:logMemory = @()
$global:logFilePath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Install-Log.txt"
$CurrentVersion = "0.4"
$steamCmdUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

# Add this function after global variable definitions
function Test-ExistingInstallation {
    param([string]$RegPath)
    return Test-Path $RegPath
}

function Prompt-Reinstall {
    $result = [System.Windows.Forms.MessageBox]::Show(
        "An existing Server Manager installation was detected. Do you want to reinstall (this will overwrite previous settings)?",
        "Reinstall Server Manager",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

# Add missing New-EnvironmentFile function
function New-EnvironmentFile {
    param(
        [string]$ServerManagerDir,
        [hashtable]$SQLOptions,
        [string]$SQLDatabasePath,
        [hashtable]$HostTypeOptions
    )
    
    Write-Log "Creating environment configuration file..."
    
    try {
        $envFilePath = Join-Path $ServerManagerDir ".env"
        
        $envContent = @"
# Server Manager Configuration
FLASK_ENV=production
SECRET_KEY=$(New-Salt -Length 64)
DATABASE_TYPE=$($SQLOptions.SQLType)
DATABASE_PATH=$SQLDatabasePath
WEB_PORT=8080
LOG_LEVEL=INFO
HOST_TYPE=$($HostTypeOptions.HostType)
"@

        if ($HostTypeOptions.HostType -eq "Subhost" -and $HostTypeOptions.HostAddress) {
            $envContent += "`nHOST_ADDRESS=$($HostTypeOptions.HostAddress)"
        }

        Set-Content -Path $envFilePath -Value $envContent -Force
        Protect-ConfigFile -FilePath $envFilePath
        
        Write-Log "Environment file created successfully at: $envFilePath"
        return $true
    }
    catch {
        Write-Log "Failed to create environment file: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Add all missing functions from original script
function Get-InstalledSQLServers {
    $detected = @()
    # Always add SQLite (Python built-in)
    $detected += @{
        Type = "SQLite"
        Version = "3"
        Location = ""
        Display = "SQLite (local file, recommended for most users)"
    }

    # Detect MSSQL (Express or full)
    try {
        $mssqlRegPaths = @(
            "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL"
        )
        foreach ($regPath in $mssqlRegPaths) {
            if (Test-Path $regPath) {
                $props = Get-ItemProperty -Path $regPath
                $instanceNames = @()
                foreach ($prop in $props.PSObject.Properties) {
                    if ($prop.Name -notlike "PS*") {
                        $instanceNames += $prop.Name
                    }
                }
                foreach ($instance in $instanceNames) {
                    $ver = ""
                    try {
                        $verKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$($instance)\MSSQLServer\CurrentVersion"
                        if (Test-Path $verKey) {
                            $ver = (Get-ItemProperty -Path $verKey).CurrentVersion
                        }
                    } catch {}
                    $loc = ".\$instance"
                    $detected += @{
                        Type = $instance
                        Version = $ver
                        Location = $loc
                        Display = "$instance $ver"
                    }
                }
            }
        }
    } catch {}

    # Detect MySQL/MariaDB (look for service)
    try {
        $mysqlService = Get-Service | Where-Object { $_.Name -like "mysql*" -or $_.Name -like "mariadb*" }
        foreach ($svc in $mysqlService) {
            $type = if ($svc.Name -like "mariadb*") { "MariaDB" } else { "MySQL" }
            $ver = ""
            try {
                $exe = (Get-WmiObject Win32_Service -Filter "Name='$($svc.Name)'").PathName
                if ($exe -and (Test-Path $exe)) {
                    $ver = (& "$exe" --version 2>&1 | Select-String -Pattern "\d+\.\d+\.\d+" | Select-Object -First 1).Matches.Value
                }
            } catch {}
            $detected += @{
                Type = $type
                Version = $ver
                Location = "localhost"
                Display = "$type ($svc.Name) $ver"
            }
        }
    } catch {}

    return $detected
}

function Initialize-SQLDatabase {
    param(
        [string]$SQLType,
        [string]$SQLVersion,
        [string]$SQLLocation,
        [string]$DataFolder
    )
    Write-Log "Setting up SQL database..."

    if ($SQLType -eq "SQLite") {
        $dbFile = Join-Path $DataFolder "users.db"
        $global:SQLDatabaseFile = $dbFile
        if (-not (Test-Path $dbFile)) {
            Write-Log "Creating SQLite database at $dbFile"
            $pythonScript = @"
import sqlite3
import sys
dbfile = sys.argv[1]
conn = sqlite3.connect(dbfile)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    email TEXT,
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    two_factor_enabled INTEGER DEFAULT 0,
    two_factor_secret TEXT
)
''')
conn.commit()
conn.close()
"@
            $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
            Set-Content -Path $tempPy -Value $pythonScript
            python $tempPy $dbFile
            Remove-Item $tempPy -Force
        }
        return $dbFile
    }
    # Add other SQL types handling here if needed
    return $SQLLocation
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $adminRole = (New-Object Security.Principal.WindowsPrincipal $currentUser).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    return $adminRole
}

function Test-AdminPrivileges {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "Administrative privileges required. Requesting elevation..."
        
        # Show message to user
        [System.Windows.Forms.MessageBox]::Show(
            "This installer requires administrative privileges to install Server Manager.`n`nClick OK to restart with administrator rights.",
            "Administrator Rights Required",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
        
        try {
            # Get the current script path
            $scriptPath = $MyInvocation.MyCommand.Path
            if (-not $scriptPath) {
                $scriptPath = $PSCommandPath
            }
            
            # Create elevated process
            $processInfo = New-Object System.Diagnostics.ProcessStartInfo
            $processInfo.FileName = "powershell.exe"
            $processInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
            $processInfo.UseShellExecute = $true
            $processInfo.Verb = "runas"
            $processInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            
            Write-Log "Starting elevated process: $($processInfo.FileName) $($processInfo.Arguments)"
            
            $process = [System.Diagnostics.Process]::Start($processInfo)
            
            if ($process) {
                Write-Log "Elevated process started successfully. Exiting current instance."
                exit 0
            } else {
                throw "Failed to start elevated process"
            }
        }
        catch {
            Write-Log "Failed to restart with administrator privileges: $($_.Exception.Message)"
            [System.Windows.Forms.MessageBox]::Show(
                "Failed to restart with administrator privileges. Please run this installer as an administrator manually.`n`nError: $($_.Exception.Message)",
                "Elevation Failed",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            )
            exit 1
        }
    } else {
        Write-Log "Running with administrative privileges confirmed."
    }
}

function New-Servermanager {
    param ([string]$dir)
    if (-Not (Test-Path -Path $dir)) {
        try {
            Write-Log "Directory does not exist, creating: $dir"
            New-Item -ItemType Directory -Force -Path $dir
            Write-Log "Successfully created directory: $dir"
        } catch {
            Write-Log "Failed to create directory: $($_.Exception.Message)"
            throw
        }
    } else {
        Write-Log "Directory already exists: $dir"
    }
}

function Install-Git {
    if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Log "Git is not installed. Installing Git..."
        try {
            $installerUrl = "https://api.github.com/repos/git-for-windows/git/releases/latest"
            $latestRelease = Invoke-RestMethod -Uri $installerUrl
            $installerUrl = ($latestRelease.assets | Where-Object { $_.name -like "*64-bit.exe" }).browser_download_url
            $installerPath = Join-Path $env:TEMP "git-installer.exe"

            Write-Log "Downloading Git installer..."
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Log "Running Git installer..."
            Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART" -Wait

            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
                throw "Git installation failed verification"
            }

            Write-Log "Git installation completed."
            Remove-Item -Path $installerPath -Force
        } catch {
            Write-Log "Failed to install Git: $($_.Exception.Message)"
            exit 1
        }
    } else {
        Write-Log "Git is already installed."
    }
}

function Update-SteamCmd {
    param ([string]$steamCmdPath)
    Write-Log "Running SteamCMD update..."
    try {
        if (Test-Path $steamCmdPath) {
            Write-Log "SteamCMD executable found at $steamCmdPath"
            Start-Process -FilePath $steamCmdPath -ArgumentList "+login anonymous +quit" -NoNewWindow -Wait
            Write-Log "SteamCMD updated successfully."
        } else {
            Write-Log "SteamCMD executable not found. Cannot run update."
            exit
        }
    } catch {
        Write-Log "Failed to update SteamCMD: $($_.Exception.Message)"
    }
}

function Initialize-GitRepo {
    param ([string]$repoUrl, [string]$destination, [System.Windows.Forms.Label]$StatusLabel = $null, [System.Windows.Forms.Form]$Form = $null)
    
    Write-Log "Initializing Git repository at $destination"
    $maxAttempts = 3
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            if (Get-Command git -ErrorAction SilentlyContinue) {
                if (Test-Path $destination) {
                    Write-Log "Removing existing directory..."
                    Remove-Item -Path $destination -Recurse -Force
                }
                
                Write-Log "Cloning repository (attempt $attempt of $maxAttempts)..."
                
                # Update status label if provided
                if ($StatusLabel -and $Form) {
                    $StatusLabel.Text = "Git download attempt $attempt of $maxAttempts..."
                    $Form.Refresh()
                }
                
                # Use Start-Process with timeout for better control
                $gitProcess = Start-Process -FilePath "git" -ArgumentList "clone", "--depth", "1", "--single-branch", $repoUrl, $destination -NoNewWindow -PassThru
                
                # Wait for the process to complete with timeout (60 seconds)
                $timeoutReached = $false
                if (-not $gitProcess.WaitForExit(60000)) {
                    Write-Log "Git clone timeout reached (60 seconds), killing process..."
                    try {
                        $gitProcess.Kill()
                        $gitProcess.WaitForExit(5000)
                    } catch {
                        Write-Log "Failed to kill git process: $($_.Exception.Message)"
                    }
                    $timeoutReached = $true
                }
                
                if ($timeoutReached) {
                    throw "Git clone operation timed out after 60 seconds"
                }
                
                if ($gitProcess.ExitCode -ne 0) {
                    throw "Git clone failed with exit code: $($gitProcess.ExitCode)"
                }
                
                # Verify the clone was successful
                if (Test-Path $destination) {
                    Write-Log "Git repository successfully cloned."
                    return
                } else {
                    throw "Repository directory not created after clone"
                }
            } else {
                throw "Git is not installed or not found in the PATH"
            }
        } catch {
            Write-Log "Git clone attempt $attempt failed: $($_.Exception.Message)"
            
            # Clean up failed attempt
            if (Test-Path $destination) {
                try {
                    Remove-Item -Path $destination -Recurse -Force -ErrorAction SilentlyContinue
                } catch {
                    Write-Log "Warning: Failed to clean up failed clone directory: $($_.Exception.Message)"
                }
            }
            
            if ($attempt -eq $maxAttempts) {
                Write-Log "All Git clone attempts failed. Trying fallback download from website..."
                
                # Update status for website fallback
                if ($StatusLabel -and $Form) {
                    $StatusLabel.Text = "Git failed, trying website download..."
                    $Form.Refresh()
                }
                
                try {
                    Download-FromWebsite -destination $destination -StatusLabel $StatusLabel -Form $Form
                    return
                } catch {
                    Write-Log "Website download also failed: $($_.Exception.Message)"
                    throw "Both Git clone and website download failed. Git error: $($_.Exception.Message)"
                }
            } else {
                Write-Log "Retrying in 2 seconds..."
                
                # Update status for retry
                if ($StatusLabel -and $Form) {
                    $StatusLabel.Text = "Git attempt $attempt failed, retrying in 2 seconds..."
                    $Form.Refresh()
                }
                
                Start-Sleep -Seconds 2
            }
        }
    }
}

function Download-FromWebsite {
    param ([string]$destination, [System.Windows.Forms.Label]$StatusLabel = $null, [System.Windows.Forms.Form]$Form = $null)
    
    Write-Log "Attempting to download Server Manager from website..."
    $websiteUrl = "https://www.skywereindustries.com/servermanager/releases/latest.zip"
    $tempZip = Join-Path $env:TEMP "servermanager-latest.zip"
    $maxAttempts = 3
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            # Clean up destination if it exists
            if (Test-Path $destination) {
                Remove-Item -Path $destination -Recurse -Force
            }
            
            Write-Log "Website download attempt $attempt of $maxAttempts..."
            
            # Update status label if provided
            if ($StatusLabel -and $Form) {
                $StatusLabel.Text = "Website download attempt $attempt of $maxAttempts..."
                $Form.Refresh()
            }
            
            # Use Invoke-WebRequest with timeout instead of WebClient
            Write-Log "Downloading from $websiteUrl..."
            Invoke-WebRequest -Uri $websiteUrl -OutFile $tempZip -TimeoutSec 120 -UseBasicParsing
            
            if (-not (Test-Path $tempZip)) {
                throw "Download file was not created"
            }
            
            $fileSize = (Get-Item $tempZip).Length
            if ($fileSize -lt 1024) {
                throw "Downloaded file is too small ($fileSize bytes), probably an error page"
            }
            
            Write-Log "Downloaded $fileSize bytes successfully"
            
            # Update status for extraction
            if ($StatusLabel -and $Form) {
                $StatusLabel.Text = "Extracting downloaded files..."
                $Form.Refresh()
            }
            
            Write-Log "Extracting files..."
            
            # Create destination directory
            New-Item -ItemType Directory -Force -Path $destination | Out-Null
            
            # Extract with error handling using Add-Type for System.IO.Compression
            try {
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                [System.IO.Compression.ZipFile]::ExtractToDirectory($tempZip, $destination)
            } catch {
                # Fallback to Expand-Archive if ZipFile fails
                Write-Log "ZipFile extraction failed, trying Expand-Archive..."
                Expand-Archive -Path $tempZip -DestinationPath $destination -Force
            }
            
            # Check if files were extracted to a subdirectory and move them up if needed
            $extractedItems = Get-ChildItem -Path $destination -ErrorAction SilentlyContinue
            if ($extractedItems.Count -eq 1 -and $extractedItems[0].PSIsContainer) {
                $subDir = $extractedItems[0].FullName
                $tempDir = "$destination-temp"
                
                Write-Log "Moving files from subdirectory to main directory..."
                
                # Move subdirectory contents to temp location
                Move-Item -Path $subDir -Destination $tempDir
                
                # Remove original destination and move temp to destination
                Remove-Item -Path $destination -Recurse -Force
                Move-Item -Path $tempDir -Destination $destination
            }
            
            # Verify extraction
            $finalItems = Get-ChildItem -Path $destination -ErrorAction SilentlyContinue
            if ($finalItems.Count -eq 0) {
                throw "No files were extracted from the archive"
            }
            
            Write-Log "Successfully downloaded and extracted Server Manager files from website ($($finalItems.Count) items)"
            
            # Clean up
            if (Test-Path $tempZip) {
                Remove-Item -Path $tempZip -Force
            }
            
            return
            
        } catch {
            Write-Log "Website download attempt $attempt failed: $($_.Exception.Message)"
            
            # Clean up on failure
            if (Test-Path $tempZip) {
                Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue
            }
            if (Test-Path $destination) {
                Remove-Item -Path $destination -Recurse -Force -ErrorAction SilentlyContinue
            }
            
            if ($attempt -eq $maxAttempts) {
                throw "Website download failed after $maxAttempts attempts: $($_.Exception.Message)"
            } else {
                Write-Log "Retrying website download in 2 seconds..."
                
                # Update status for retry
                if ($StatusLabel -and $Form) {
                    $StatusLabel.Text = "Website attempt $attempt failed, retrying in 2 seconds..."
                    $Form.Refresh()
                }
                
                Start-Sleep -Seconds 2
            }
        }
    }
}

# --- Main installer script (continued) ---

# Unified installer form
function Show-InstallerWizard {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Server Manager Installer v$CurrentVersion"
    $form.Size = New-Object System.Drawing.Size(650, 550)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon("$env:SystemRoot\System32\msiexec.exe")

    # Header panel
    $headerPanel = New-Object System.Windows.Forms.Panel
    $headerPanel.Location = New-Object System.Drawing.Point(0, 0)
    $headerPanel.Size = New-Object System.Drawing.Size(650, 60)
    $headerPanel.BackColor = [System.Drawing.Color]::White
    $form.Controls.Add($headerPanel)

    # Header title
    $headerTitle = New-Object System.Windows.Forms.Label
    $headerTitle.Text = "Server Manager Setup Wizard"
    $headerTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $headerTitle.Location = New-Object System.Drawing.Point(20, 10)
    $headerTitle.Size = New-Object System.Drawing.Size(400, 25)
    $headerPanel.Controls.Add($headerTitle)

    # Header subtitle
    $headerSubtitle = New-Object System.Windows.Forms.Label
    $headerSubtitle.Text = "This wizard will guide you through the installation of Server Manager"
    $headerSubtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $headerSubtitle.Location = New-Object System.Drawing.Point(20, 35)
    $headerSubtitle.Size = New-Object System.Drawing.Size(500, 20)
    $headerPanel.Controls.Add($headerSubtitle)

    # Main content panel
    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(0, 60)
    $contentPanel.Size = New-Object System.Drawing.Size(650, 380)
    $contentPanel.BackColor = [System.Drawing.Color]::White
    $form.Controls.Add($contentPanel)

    # Bottom panel for buttons and progress
    $bottomPanel = New-Object System.Windows.Forms.Panel
    $bottomPanel.Location = New-Object System.Drawing.Point(0, 440)
    $bottomPanel.Size = New-Object System.Drawing.Size(650, 80)
    $bottomPanel.BackColor = [System.Drawing.SystemColors]::Control
    $form.Controls.Add($bottomPanel)

    # Separator line
    $separator = New-Object System.Windows.Forms.Label
    $separator.BorderStyle = [System.Windows.Forms.BorderStyle]::Fixed3D
    $separator.Location = New-Object System.Drawing.Point(0, 0)
    $separator.Size = New-Object System.Drawing.Size(650, 2)
    $bottomPanel.Controls.Add($separator)

    # Progress bar
    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(20, 15)
    $progressBar.Size = New-Object System.Drawing.Size(610, 20)
    $progressBar.Style = 'Continuous'
    $progressBar.Visible = $false
    $bottomPanel.Controls.Add($progressBar)

    # Status label
    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Text = ""
    $statusLabel.Location = New-Object System.Drawing.Point(20, 40)
    $statusLabel.Size = New-Object System.Drawing.Size(500, 20)
    $statusLabel.Visible = $false
    $bottomPanel.Controls.Add($statusLabel)

    # Navigation buttons
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.Location = New-Object System.Drawing.Point(390, 45)
    $cancelButton.Size = New-Object System.Drawing.Size(75, 25)
    $bottomPanel.Controls.Add($cancelButton)

    $backButton = New-Object System.Windows.Forms.Button
    $backButton.Text = "< Back"
    $backButton.Location = New-Object System.Drawing.Point(470, 45)
    $backButton.Size = New-Object System.Drawing.Size(75, 25)
    $backButton.Enabled = $false
    $bottomPanel.Controls.Add($backButton)

    $nextButton = New-Object System.Windows.Forms.Button
    $nextButton.Text = "Next >"
    $nextButton.Location = New-Object System.Drawing.Point(550, 45)
    $nextButton.Size = New-Object System.Drawing.Size(75, 25)
    $bottomPanel.Controls.Add($nextButton)

    # Create wizard pages
    $pages = @()
    $currentPageIndex = 0

    # Page 1: Welcome
    $welcomePage = New-Object System.Windows.Forms.Panel
    $welcomePage.Location = New-Object System.Drawing.Point(20, 20)
    $welcomePage.Size = New-Object System.Drawing.Size(610, 340)
    $welcomePage.Visible = $true
    $contentPanel.Controls.Add($welcomePage)

    $welcomeTitle = New-Object System.Windows.Forms.Label
    $welcomeTitle.Text = "Welcome to Server Manager Setup"
    $welcomeTitle.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
    $welcomeTitle.Location = New-Object System.Drawing.Point(20, 20)
    $welcomeTitle.Size = New-Object System.Drawing.Size(400, 30)
    $welcomePage.Controls.Add($welcomeTitle)

    $welcomeText = New-Object System.Windows.Forms.Label
    $welcomeText.Text = @"
This wizard will install Server Manager on your computer.

Server Manager is a comprehensive tool for managing game servers, providing an easy-to-use web interface for server administration, user management, and automated server deployment.

Click Next to continue, or Cancel to exit Setup.
"@
    $welcomeText.Location = New-Object System.Drawing.Point(20, 70)
    $welcomeText.Size = New-Object System.Drawing.Size(550, 150)
    $welcomePage.Controls.Add($welcomeText)

    $pages += $welcomePage

    # Page 2: Installation Options
    $optionsPage = New-Object System.Windows.Forms.Panel
    $optionsPage.Location = New-Object System.Drawing.Point(20, 20)
    $optionsPage.Size = New-Object System.Drawing.Size(610, 340)
    $optionsPage.Visible = $false
    $contentPanel.Controls.Add($optionsPage)

    $optionsTitle = New-Object System.Windows.Forms.Label
    $optionsTitle.Text = "Installation Options"
    $optionsTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $optionsTitle.Location = New-Object System.Drawing.Point(20, 20)
    $optionsTitle.Size = New-Object System.Drawing.Size(300, 25)
    $optionsPage.Controls.Add($optionsTitle)

    # SteamCMD Path
    $steamCmdLabel = New-Object System.Windows.Forms.Label
    $steamCmdLabel.Text = "SteamCMD Installation Directory:"
    $steamCmdLabel.Location = New-Object System.Drawing.Point(20, 60)
    $steamCmdLabel.Size = New-Object System.Drawing.Size(200, 20)
    $optionsPage.Controls.Add($steamCmdLabel)

    $steamCmdBox = New-Object System.Windows.Forms.TextBox
    $steamCmdBox.Location = New-Object System.Drawing.Point(20, 85)
    $steamCmdBox.Size = New-Object System.Drawing.Size(450, 20)
    $steamCmdBox.Text = "C:\SteamCMD"
    $optionsPage.Controls.Add($steamCmdBox)

    $steamCmdBrowse = New-Object System.Windows.Forms.Button
    $steamCmdBrowse.Text = "Browse..."
    $steamCmdBrowse.Location = New-Object System.Drawing.Point(480, 85)
    $steamCmdBrowse.Size = New-Object System.Drawing.Size(80, 23)
    $optionsPage.Controls.Add($steamCmdBrowse)

    # User Workspace Path
    $workspaceLabel = New-Object System.Windows.Forms.Label
    $workspaceLabel.Text = "User Workspace Directory:"
    $workspaceLabel.Location = New-Object System.Drawing.Point(20, 120)
    $workspaceLabel.Size = New-Object System.Drawing.Size(200, 20)
    $optionsPage.Controls.Add($workspaceLabel)

    $workspaceBox = New-Object System.Windows.Forms.TextBox
    $workspaceBox.Location = New-Object System.Drawing.Point(20, 145)
    $workspaceBox.Size = New-Object System.Drawing.Size(450, 20)
    $workspaceBox.Text = Join-Path $steamCmdBox.Text "user_workspace"
    $workspaceBox.ReadOnly = $true
    $optionsPage.Controls.Add($workspaceBox)

    $workspaceBrowse = New-Object System.Windows.Forms.Button
    $workspaceBrowse.Text = "Browse..."
    $workspaceBrowse.Location = New-Object System.Drawing.Point(480, 145)
    $workspaceBrowse.Size = New-Object System.Drawing.Size(80, 23)
    $optionsPage.Controls.Add($workspaceBrowse)

    # Custom workspace checkbox
    $customWorkspaceCheckbox = New-Object System.Windows.Forms.CheckBox
    $customWorkspaceCheckbox.Text = "Use custom workspace directory"
    $customWorkspaceCheckbox.Location = New-Object System.Drawing.Point(20, 175)
    $customWorkspaceCheckbox.Size = New-Object System.Drawing.Size(250, 20)
    $optionsPage.Controls.Add($customWorkspaceCheckbox)

    # Service installation
    $serviceCheckbox = New-Object System.Windows.Forms.CheckBox
    $serviceCheckbox.Text = "Install as Windows Service (recommended - starts automatically with Windows)"
    $serviceCheckbox.Location = New-Object System.Drawing.Point(20, 210)
    $serviceCheckbox.Size = New-Object System.Drawing.Size(500, 20)
    $optionsPage.Controls.Add($serviceCheckbox)

    # Host type group
    $hostGroupBox = New-Object System.Windows.Forms.GroupBox
    $hostGroupBox.Text = "Cluster Configuration"
    $hostGroupBox.Location = New-Object System.Drawing.Point(20, 240)
    $hostGroupBox.Size = New-Object System.Drawing.Size(540, 100)
    $optionsPage.Controls.Add($hostGroupBox)

    $hostRadio = New-Object System.Windows.Forms.RadioButton
    $hostRadio.Text = "Host (Master) - This will be the main server"
    $hostRadio.Location = New-Object System.Drawing.Point(15, 25)
    $hostRadio.Size = New-Object System.Drawing.Size(300, 20)
    $hostRadio.Checked = $true
    $hostGroupBox.Controls.Add($hostRadio)

    $subhostRadio = New-Object System.Windows.Forms.RadioButton
    $subhostRadio.Text = "Subhost (Agent) - This will connect to a master server"
    $subhostRadio.Location = New-Object System.Drawing.Point(15, 50)
    $subhostRadio.Size = New-Object System.Drawing.Size(350, 20)
    $hostGroupBox.Controls.Add($subhostRadio)

    $hostAddrLabel = New-Object System.Windows.Forms.Label
    $hostAddrLabel.Text = "Master Host Address:"
    $hostAddrLabel.Location = New-Object System.Drawing.Point(350, 50)
    $hostAddrLabel.Size = New-Object System.Drawing.Size(120, 20)
    $hostAddrLabel.Visible = $false
    $hostGroupBox.Controls.Add($hostAddrLabel)

    $hostAddrBox = New-Object System.Windows.Forms.TextBox
    $hostAddrBox.Location = New-Object System.Drawing.Point(350, 70)
    $hostAddrBox.Size = New-Object System.Drawing.Size(150, 20)
    $hostAddrBox.Visible = $false
    $hostGroupBox.Controls.Add($hostAddrBox)

    $pages += $optionsPage

    # Page 3: Database Configuration
    $dbPage = New-Object System.Windows.Forms.Panel
    $dbPage.Location = New-Object System.Drawing.Point(20, 20)
    $dbPage.Size = New-Object System.Drawing.Size(610, 340)
    $dbPage.Visible = $false
    $contentPanel.Controls.Add($dbPage)

    $dbTitle = New-Object System.Windows.Forms.Label
    $dbTitle.Text = "Database Configuration"
    $dbTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $dbTitle.Location = New-Object System.Drawing.Point(20, 20)
    $dbTitle.Size = New-Object System.Drawing.Size(300, 25)
    $dbPage.Controls.Add($dbTitle)

    $dbDesc = New-Object System.Windows.Forms.Label
    $dbDesc.Text = "Select the database type for storing user accounts and server configurations."
    $dbDesc.Location = New-Object System.Drawing.Point(20, 50)
    $dbDesc.Size = New-Object System.Drawing.Size(500, 20)
    $dbPage.Controls.Add($dbDesc)

    $sqlTypeLabel = New-Object System.Windows.Forms.Label
    $sqlTypeLabel.Text = "Database Type:"
    $sqlTypeLabel.Location = New-Object System.Drawing.Point(20, 90)
    $sqlTypeLabel.Size = New-Object System.Drawing.Size(100, 20)
    $dbPage.Controls.Add($sqlTypeLabel)

    $sqlTypeCombo = New-Object System.Windows.Forms.ComboBox
    $sqlTypeCombo.Location = New-Object System.Drawing.Point(130, 90)
    $sqlTypeCombo.Size = New-Object System.Drawing.Size(300, 20)
    $sqlTypeCombo.DropDownStyle = 'DropDownList'
    $dbPage.Controls.Add($sqlTypeCombo)

    # Populate SQL types
    $detected = Get-InstalledSQLServers
    foreach ($item in $detected) {
        $sqlTypeCombo.Items.Add($item.Display)
    }
    if ($sqlTypeCombo.Items.Count -gt 0) {
        $sqlTypeCombo.SelectedIndex = 0
    }

    $sqlLocationLabel = New-Object System.Windows.Forms.Label
    $sqlLocationLabel.Text = "Connection String:"
    $sqlLocationLabel.Location = New-Object System.Drawing.Point(20, 130)
    $sqlLocationLabel.Size = New-Object System.Drawing.Size(120, 20)
    $dbPage.Controls.Add($sqlLocationLabel)

    $sqlLocationBox = New-Object System.Windows.Forms.TextBox
    $sqlLocationBox.Location = New-Object System.Drawing.Point(20, 155)
    $sqlLocationBox.Size = New-Object System.Drawing.Size(540, 20)
    if ($detected.Count -gt 0) {
        $sqlLocationBox.Text = if ($detected[0].Type -eq "SQLite") { "(no connection string required)" } else { $detected[0].Location }
        $sqlLocationBox.ReadOnly = ($detected[0].Type -eq "SQLite")
    }
    $dbPage.Controls.Add($sqlLocationBox)

    $sqlNote = New-Object System.Windows.Forms.Label
    $sqlNote.Text = "Note: SQLite is recommended for most installations as it requires no additional setup."
    $sqlNote.Font = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Italic)
    $sqlNote.Location = New-Object System.Drawing.Point(20, 185)
    $sqlNote.Size = New-Object System.Drawing.Size(500, 30)
    $dbPage.Controls.Add($sqlNote)

    $pages += $dbPage

    # Page 4: Installation Progress
    $installPage = New-Object System.Windows.Forms.Panel
    $installPage.Location = New-Object System.Drawing.Point(20, 20)
    $installPage.Size = New-Object System.Drawing.Size(610, 340)
    $installPage.Visible = $false
    $contentPanel.Controls.Add($installPage)

    $installTitle = New-Object System.Windows.Forms.Label
    $installTitle.Text = "Installing Server Manager"
    $installTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $installTitle.Location = New-Object System.Drawing.Point(20, 20)
    $installTitle.Size = New-Object System.Drawing.Size(300, 25)
    $installPage.Controls.Add($installTitle)

    $installDesc = New-Object System.Windows.Forms.Label
    $installDesc.Text = "Please wait while Server Manager is being installed..."
    $installDesc.Location = New-Object System.Drawing.Point(20, 50)
    $installDesc.Size = New-Object System.Drawing.Size(400, 20)
    $installPage.Controls.Add($installDesc)

    $installProgressBar = New-Object System.Windows.Forms.ProgressBar
    $installProgressBar.Location = New-Object System.Drawing.Point(20, 100)
    $installProgressBar.Size = New-Object System.Drawing.Size(570, 25)
    $installProgressBar.Style = 'Continuous'
    $installPage.Controls.Add($installProgressBar)

    $installStatusLabel = New-Object System.Windows.Forms.Label
    $installStatusLabel.Text = "Preparing installation..."
    $installStatusLabel.Location = New-Object System.Drawing.Point(20, 140)
    $installStatusLabel.Size = New-Object System.Drawing.Size(570, 20)
    $installPage.Controls.Add($installStatusLabel)

    $pages += $installPage

    # Page 5: Completion
    $completePage = New-Object System.Windows.Forms.Panel
    $completePage.Location = New-Object System.Drawing.Point(20, 20)
    $completePage.Size = New-Object System.Drawing.Size(610, 340)
    $completePage.Visible = $false
    $contentPanel.Controls.Add($completePage)

    $completeTitle = New-Object System.Windows.Forms.Label
    $completeTitle.Text = "Installation Complete"
    $completeTitle.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
    $completeTitle.Location = New-Object System.Drawing.Point(20, 20)
    $completeTitle.Size = New-Object System.Drawing.Size(400, 30)
    $completePage.Controls.Add($completeTitle)

    $completeText = New-Object System.Windows.Forms.Label
    $completeText.Text = @"
Server Manager has been successfully installed on your computer.

You can now:
Access the web interface at http://localhost:8080
Log in with username: admin, password: admin
Start managing your game servers

Click Finish to complete the setup.
"@
    $completeText.Location = New-Object System.Drawing.Point(20, 70)
    $completeText.Size = New-Object System.Drawing.Size(550, 150)
    $completePage.Controls.Add($completeText)

    $pages += $completePage

    # Event handlers
    $steamCmdBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select SteamCMD installation directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $steamCmdBox.Text = $dialog.SelectedPath
            # Update workspace path if not using custom
            if (-not $customWorkspaceCheckbox.Checked) {
                $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
            }
        }
    })

    $workspaceBrowse.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select user workspace parent directory"
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $workspaceBox.Text = Join-Path $dialog.SelectedPath "user_workspace"
        }
    })

    $customWorkspaceCheckbox.Add_CheckedChanged({
        if ($customWorkspaceCheckbox.Checked) {
            $workspaceBox.ReadOnly = $false
            $workspaceBrowse.Enabled = $true
            $workspaceBox.Text = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "user_workspace"
        } else {
            $workspaceBox.ReadOnly = $true
            $workspaceBrowse.Enabled = $false
            $workspaceBox.Text = Join-Path $steamCmdBox.Text "user_workspace"
        }
    })

    $subhostRadio.Add_CheckedChanged({
        $hostAddrLabel.Visible = $subhostRadio.Checked
        $hostAddrBox.Visible = $subhostRadio.Checked
    })

    $sqlTypeCombo.Add_SelectedIndexChanged({
        if ($sqlTypeCombo.SelectedIndex -ge 0) {
            $selectedItem = $detected[$sqlTypeCombo.SelectedIndex]
            if ($selectedItem.Type -eq "SQLite") {
                $sqlLocationBox.Text = "(no connection string required)"
                $sqlLocationBox.ReadOnly = $true
            } else {
                $sqlLocationBox.Text = $selectedItem.Location
                $sqlLocationBox.ReadOnly = $false
            }
        }
    })

    function Show-Page($index) {
        for ($i = 0; $i -lt $pages.Count; $i++) {
            $pages[$i].Visible = ($i -eq $index)
        }
        
        # Update header subtitle based on current page
        switch ($index) {
            0 { $headerSubtitle.Text = "Welcome to the Server Manager Setup Wizard" }
            1 { $headerSubtitle.Text = "Choose installation options and directories" }
            2 { $headerSubtitle.Text = "Configure the database for user accounts" }
            3 { $headerSubtitle.Text = "Installing Server Manager components..." }
            4 { $headerSubtitle.Text = "Setup completed successfully" }
        }
        
        # Update button states
        $backButton.Enabled = ($index -gt 0 -and $index -ne 3)
        $nextButton.Enabled = ($index -ne 3)  # Enable for all pages except installation progress
        $cancelButton.Enabled = ($index -ne 3 -and $index -ne 4)
        
        if ($index -eq 2) {
            $nextButton.Text = "Install"
            $nextButton.Enabled = $true  # Explicitly enable Install button
        } elseif ($index -eq 4) {
            $nextButton.Text = "Finish"
            $nextButton.Enabled = $true
        } else {
            $nextButton.Text = "Next >"
        }
        
        $script:currentPageIndex = $index
    }

    $nextButton.Add_Click({
        switch ($script:currentPageIndex) {
            0 { Show-Page 1 }
            1 { Show-Page 2 }
            2 { 
                # Start installation
                Show-Page 3
                $cancelButton.Enabled = $false
                $backButton.Enabled = $false
                $nextButton.Enabled = $false
                
                # Collect settings and start installation
                $settings = @{
                    SteamCMDPath = $steamCmdBox.Text
                    UserWorkspacePath = $workspaceBox.Text
                    InstallService = $serviceCheckbox.Checked
                    HostType = if ($hostRadio.Checked) { "Host" } else { "Subhost" }
                    HostAddress = if ($subhostRadio.Checked) { $hostAddrBox.Text } else { $null }
                    SQLType = if ($sqlTypeCombo.SelectedIndex -ge 0) { $detected[$sqlTypeCombo.SelectedIndex].Type } else { "SQLite" }
                    SQLLocation = if ($sqlTypeCombo.SelectedIndex -ge 0 -and $detected[$sqlTypeCombo.SelectedIndex].Type -eq "SQLite") { "" } else { $sqlLocationBox.Text }
                    SQLVersion = if ($sqlTypeCombo.SelectedIndex -ge 0) { $detected[$sqlTypeCombo.SelectedIndex].Version } else { "3" }
                }
                
                Start-Installation -Settings $settings -ProgressBar $installProgressBar -StatusLabel $installStatusLabel -Form $form -OnComplete {
                    Show-Page 4
                }
            }
            4 { 
                $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
                $form.Close()
            }
        }
    })

    $backButton.Add_Click({
        if ($script:currentPageIndex -gt 0) {
            Show-Page ($script:currentPageIndex - 1)
        }
    })

    $cancelButton.Add_Click({
        $form.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $form.Close()
    })

    # Initialize first page
    Show-Page 0

    return $form.ShowDialog()
}

function Start-Installation {
    param(
        [hashtable]$Settings,
        [System.Windows.Forms.ProgressBar]$ProgressBar,
        [System.Windows.Forms.Label]$StatusLabel,
        [System.Windows.Forms.Form]$Form,
        [scriptblock]$OnComplete
    )

    try {
        $totalSteps = 12
        $currentStep = 0

        function Update-Progress([string]$Message) {
            $script:currentStep++
            $StatusLabel.Text = $Message
            $ProgressBar.Value = [math]::Min(100, ($script:currentStep / $totalSteps) * 100)
            $Form.Refresh()
            Write-Log $Message
            Start-Sleep -Milliseconds 200  # Brief pause to show progress
        }

        function Show-StepError([string]$StepName, [string]$ErrorMessage) {
            Write-Log "[ERROR] $StepName failed: $ErrorMessage"
            $result = [System.Windows.Forms.MessageBox]::Show(
                "$StepName failed with the following error:`n`n$ErrorMessage`n`nWould you like to continue with the installation? (Some features may not work properly)",
                "Installation Step Failed",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )
            return $result -eq [System.Windows.Forms.DialogResult]::Yes
        }

        Update-Progress "Checking prerequisites..."
        try {
            Test-AdminPrivileges
        } catch {
            if (-not (Show-StepError "Admin Privilege Check" $_.Exception.Message)) {
                throw "Installation cancelled by user after admin privilege check failed"
            }
        }

        Update-Progress "Checking Python 3.10+ installation..."
        try {
            if (-not (Test-Python310)) {
                Update-Progress "Installing Python 3.10..."
                Install-Python310
                if (-not (Test-Python310)) {
                    throw "Python 3.10 (64-bit) installation verification failed"
                }
            }
        } catch {
            if (-not (Show-StepError "Python Installation" "Failed to install or verify Python 3.10 (64-bit): $($_.Exception.Message)")) {
                throw "Installation cancelled by user after Python installation failed"
            }
        }

        Update-Progress "Creating directories..."
        try {
            New-Servermanager -dir $Settings.SteamCMDPath
            $ServerManagerDir = Join-Path $Settings.SteamCMDPath "Servermanager"
            New-Item -ItemType Directory -Force -Path $ServerManagerDir | Out-Null
            
            if (-not (Test-Path $Settings.UserWorkspacePath)) {
                New-Item -ItemType Directory -Force -Path $Settings.UserWorkspacePath | Out-Null
            }
        } catch {
            if (-not (Show-StepError "Directory Creation" "Failed to create installation directories: $($_.Exception.Message)")) {
                throw "Installation cancelled by user after directory creation failed"
            }
        }

        Update-Progress "Setting up logging..."
        try {
            $global:logFilePath = Join-Path $ServerManagerDir "Install-Log.txt"
        } catch {
            Write-Log "Warning: Failed to set up logging path: $($_.Exception.Message)"
        }

        Update-Progress "Creating registry entries..."
        try {
            $registryValues = @{
                'CurrentVersion' = $CurrentVersion
                'SteamCMDPath' = $Settings.SteamCMDPath
                'Servermanagerdir' = $ServerManagerDir
                'UserWorkspace' = $Settings.UserWorkspacePath
                'InstallDate' = (Get-Date).ToString('o')
                'LastUpdate' = (Get-Date).ToString('o')
                'WebPort' = '8080'
                'ModulePath' = "$ServerManagerDir\Modules"
                'LogPath' = "$ServerManagerDir\logs"
                'HostType' = $Settings.HostType
            }
            if ($Settings.HostType -eq "Subhost" -and $Settings.HostAddress) {
                $registryValues['HostAddress'] = $Settings.HostAddress
            }

            New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
            New-Item -Path $registryPath -Force | Out-Null
            foreach ($key in $registryValues.Keys) {
                Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
            }
        } catch {
            if (-not (Show-StepError "Registry Configuration" "Failed to create registry entries: $($_.Exception.Message)")) {
                throw "Installation cancelled by user after registry configuration failed"
            }
        }

        Update-Progress "Installing Git..."
        try {
            Install-Git
        } catch {
            if (-not (Show-StepError "Git Installation" "Failed to install Git: $($_.Exception.Message)`n`nThis may prevent downloading the latest Server Manager files.")) {
                throw "Installation cancelled by user after Git installation failed"
            }
        }

        Update-Progress "Downloading Server Manager files..."
        try {
            # Add a bit more detail to show progress
            $StatusLabel.Text = "Downloading Server Manager files (this may take a moment)..."
            $Form.Refresh()
            
            Initialize-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir -StatusLabel $StatusLabel -Form $Form
            
        } catch {
            $errorMsg = $_.Exception.Message
            if ($errorMsg -match "timeout|timed out") {
                $errorMsg = "Download operation timed out. This could be due to:`n• Slow internet connection`n• Repository server issues`n• Firewall blocking the connection`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "fatal: could not read Username" -or $errorMsg -match "Authentication failed" -or $errorMsg -match "repository not found") {
                $errorMsg = "Repository access denied. This may be because:`n• The repository is private and requires authentication`n• The repository URL is incorrect`n• Network connectivity issues`n`nAttempted fallback download from website but that also failed.`n`nOriginal error: $errorMsg"
            } elseif ($errorMsg -match "Both Git clone and website download failed") {
                $errorMsg = "Failed to download Server Manager files from both Git repository and website backup.`n`nThis could be due to:`n• Network connectivity issues`n• Repository access restrictions`n• Website availability problems`n• Firewall blocking connections`n`nOriginal error: $errorMsg"
            }
            if (-not (Show-StepError "Repository Download" $errorMsg)) {
                throw "Installation cancelled by user after repository download failed"
            }
        }

        Update-Progress "Installing Python requirements..."
        try {
            $requirementsPath = Join-Path $ServerManagerDir "requirements.txt"
            if (Test-Path $requirementsPath) {
                if (-not (Install-PythonRequirements -RequirementsPath $requirementsPath)) {
                    throw "Failed to install required Python packages"
                }
            } else {
                Write-Log "Warning: requirements.txt not found, skipping Python package installation"
            }
        } catch {
            if (-not (Show-StepError "Python Requirements" "Failed to install Python requirements: $($_.Exception.Message)`n`nSome Python modules may not be available.")) {
                throw "Installation cancelled by user after Python requirements installation failed"
            }
        }

        Update-Progress "Installing SteamCMD..."
        try {
            $steamCmdExe = Join-Path $Settings.SteamCMDPath "steamcmd.exe"
            if (-Not (Test-Path $steamCmdExe)) {
                $steamCmdZip = Join-Path $Settings.SteamCMDPath "steamcmd.zip"
                Write-Log "Downloading SteamCMD from $steamCmdUrl"
                Invoke-WebRequest -Uri $steamCmdUrl -OutFile $steamCmdZip -TimeoutSec 30
                Expand-Archive -Path $steamCmdZip -DestinationPath $Settings.SteamCMDPath -Force
                Remove-Item -Path $steamCmdZip -Force
            }
        } catch {
            if (-not (Show-StepError "SteamCMD Installation" "Failed to download or extract SteamCMD: $($_.Exception.Message)`n`nYou may need to install SteamCMD manually.")) {
                throw "Installation cancelled by user after SteamCMD installation failed"
            }
        }

        Update-Progress "Updating SteamCMD..."
        try {
            $steamCmdExe = Join-Path $Settings.SteamCMDPath "steamcmd.exe"
            if (Test-Path $steamCmdExe) {
                Update-SteamCmd -steamCmdPath $steamCmdExe
            }
            New-AppIDFile -serverManagerDir $ServerManagerDir
        } catch {
            Write-Log "Warning: SteamCMD update failed: $($_.Exception.Message)"
        }

        Update-Progress "Setting up database..."
        try {
            $DataFolder = Join-Path $ServerManagerDir "data"
            if (-not (Test-Path $DataFolder)) {
                New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
            }
            $SQLDatabasePath = Initialize-SQLDatabase -SQLType $Settings.SQLType -SQLVersion $Settings.SQLVersion -SQLLocation $Settings.SQLLocation -DataFolder $DataFolder
        } catch {
            if (-not (Show-StepError "Database Setup" "Failed to initialize database: $($_.Exception.Message)`n`nUser authentication may not work properly.")) {
                throw "Installation cancelled by user after database setup failed"
            }
        }

        Update-Progress "Creating configuration files..."
        try {
            $sqlOptions = @{
                SQLType = $Settings.SQLType
                SQLVersion = $Settings.SQLVersion
                SQLLocation = $Settings.SQLLocation
            }
            $hostTypeOptions = @{
                HostType = $Settings.HostType
                HostAddress = $Settings.HostAddress
            }
            if (-not (New-EnvironmentFile -ServerManagerDir $ServerManagerDir -SQLOptions $sqlOptions -SQLDatabasePath $SQLDatabasePath -HostTypeOptions $hostTypeOptions)) {
                throw "Failed to create environment configuration file"
            }
        } catch {
            if (-not (Show-StepError "Configuration Files" "Failed to create configuration files: $($_.Exception.Message)`n`nYou may need to configure the application manually.")) {
                throw "Installation cancelled by user after configuration file creation failed"
            }
        }

        Update-Progress "Setting up authentication..."
        try {
            Set-InitialAuthConfig -ServerManagerDir $ServerManagerDir
        } catch {
            Write-Log "Warning: Authentication setup failed: $($_.Exception.Message)"
        }

        if ($Settings.InstallService) {
            Update-Progress "Installing Windows Service..."
            try {
                Write-Log "Installing Server Manager as Windows Service..."
                
                # Path to the service wrapper script
                $serviceWrapperPath = Join-Path $ServerManagerDir "Scripts\service_wrapper.py"
                
                # Check if service wrapper exists
                if (-not (Test-Path $serviceWrapperPath)) {
                    throw "Service wrapper script not found at: $serviceWrapperPath"
                }
                
                # Install pywin32 if not already installed
                Write-Log "Ensuring pywin32 is installed for service functionality..."
                & $PythonPath -m pip install pywin32 2>&1 | Out-Null
                
                # Install the service
                Write-Log "Installing Windows service..."
                $installResult = & $PythonPath $serviceWrapperPath install 2>&1
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "Service installed successfully"
                    
                    # Start the service
                    Write-Log "Starting Server Manager service..."
                    $startResult = & $PythonPath $serviceWrapperPath start 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Log "Service started successfully"
                        
                        # Set the service to automatically start with Windows
                        try {
                            Set-Service -Name "ServerManagerService" -StartupType Automatic
                            Write-Log "Service configured to start automatically with Windows"
                        } catch {
                            Write-Log "Warning: Could not set service startup type: $($_.Exception.Message)"
                        }
                    } else {
                        Write-Log "Warning: Service installed but failed to start: $startResult"
                    }
                } else {
                    throw "Service installation failed: $installResult"
                }
                
            } catch {
                Write-Log "Warning: Windows Service installation failed: $($_.Exception.Message)"
                Write-Log "Server Manager can still be started manually using Start-ServerManager.pyw"
            }
        }

        Update-Progress "Finalizing installation..."
        $ProgressBar.Value = 100
        
        Write-LogToFile -logFilePath $global:logFilePath
        
        # Call completion callback
        if ($OnComplete) {
            & $OnComplete
        }
    }
    catch {
        Write-Log "[ERROR] Installation failed: $($_.Exception.Message)"
        Write-LogToFile -logFilePath $global:logFilePath
        
        # Re-enable buttons for user to potentially retry or cancel
        $cancelButton.Enabled = $true
        $backButton.Enabled = $true
        
        [System.Windows.Forms.MessageBox]::Show(
            "Installation failed: $($_.Exception.Message)`n`nPlease check the installation log for more details. You can try going back and changing settings, or cancel the installation.",
            "Installation Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
        
        # Don't automatically close, let user decide
    }
}

function New-AppIDFile {
    param ([string]$serverManagerDir)
    $appIDFile = Join-Path $serverManagerDir "AppID.txt"
    if (-Not (Test-Path $appIDFile)) {
        New-Item -Path $appIDFile -ItemType File
        Write-Log "Created AppID.txt file."
    } else {
        Write-Log "AppID.txt file already exists."
    }
}

function Test-Python310 {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $ver = & python -c "import sys; print(sys.version_info.major, sys.version_info.minor, sys.maxsize > 2**32)"
        $parts = $ver -split " "
        if ($parts.Length -eq 3) {
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            $is64 = $parts[2] -eq "True"
            if ($major -eq 3 -and $minor -ge 10 -and $is64) {
                return $true
            }
        }
    }
    return $false
}

function Install-Python310 {
    Write-Log "Python 3.10 (64-bit) not found. Downloading and installing Python 3.10 (64-bit)..."
    $pythonInstallerUrl = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri $pythonInstallerUrl -OutFile $installerPath
    Write-Log "Running Python installer..."
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    Remove-Item $installerPath -Force
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

function Install-PythonRequirements {
    param([string]$RequirementsPath)
    Write-Log "Installing Python requirements using pip..." -ForegroundColor Cyan
    if (-not (Test-Path $RequirementsPath)) {
        Write-Log "Python requirements.txt not found at: $RequirementsPath" -ForegroundColor Yellow
        return $false
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Log "Python not found in PATH after install. Please restart your shell and try again." -ForegroundColor Red
        return $false
    }
    $pipInstall = & python -m pip install --upgrade pip
    $pipReq = & python -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to install Python requirements." -ForegroundColor Red
        return $false
    }
    Write-Log "Python requirements installed successfully." -ForegroundColor Green
    return $true
}

function New-Salt {
    param([int]$Length = 32)
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes)
    return ([BitConverter]::ToString($bytes) -replace '-', '').Substring(0, $Length)
}

function Protect-ConfigFile {
    param([Parameter(Mandatory=$true)][string]$FilePath)
    if (-not (Test-Path $FilePath)) {
        Write-Log "File not found: $FilePath" -ForegroundColor Yellow
        return $false
    }
    try {
        $acl = Get-Acl $FilePath
        $acl.SetAccessRuleProtection($true, $false)

        foreach ($rule in $acl.Access) {
            $acl.RemoveAccessRule($rule)
        }

        $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "FullControl", "Allow"
        )
        $acl.AddAccessRule($systemRule)

        $adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "Administrators", "FullControl", "Allow"
        )
        $acl.AddAccessRule($adminRule)

        Set-Acl -Path $FilePath -AclObject $acl
        Write-Log "Protected config file: $FilePath" -ForegroundColor Green
        return $true
    } catch {
        Write-Log "Failed to protect config file: $FilePath - $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Set-InitialAuthConfig {
    param([string]$ServerManagerDir)
    
    Write-Log "Starting authentication configuration setup"
    
    try {
        # First try to create a simple admin user using direct database operations
        $DataFolder = Join-Path $ServerManagerDir "data"
        $dbFile = Join-Path $DataFolder "users.db"
        
        if (Test-Path $dbFile) {
            Write-Log "Creating default admin user directly in database"
            
            # Use Python to create admin user
            $initScript = @"
import sqlite3
import hashlib
import secrets

def create_admin_user():
    try:
        conn = sqlite3.connect(r'$dbFile')
        cursor = conn.cursor()
        
        # Check if admin user already exists
        cursor.execute('SELECT id FROM users WHERE username = ?', ('admin',))
        if cursor.fetchone():
            print('Admin user already exists')
            return True
        
        # Create admin user with default password 'admin'
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(('admin' + salt).encode()).hexdigest()
        
        cursor.execute('''
            INSERT INTO users (username, password, email, is_admin, is_active)
            VALUES (?, ?, ?, ?, ?)
        ''', ('admin', password_hash + ':' + salt, 'admin@localhost', 1, 1))
        
        conn.commit()
        conn.close()
        print('SUCCESS: Admin user created')
        return True
        
    except Exception as e:
        print(f'ERROR: {e}')
        return False

create_admin_user()
"@
            
            $tempPyFile = [System.IO.Path]::GetTempFileName() + ".py"
            Set-Content -Path $tempPyFile -Value $initScript
            
            try {
                $result = & python $tempPyFile 2>&1
                Write-Log "Authentication initialization result: $result"
                
                if ($result -match "SUCCESS" -or $result -match "already exists") {
                    Write-Log "Authentication system initialized successfully"
                } else {
                    Write-Log "Warning: Authentication initialization may have failed: $result"
                }
            } finally {
                Remove-Item $tempPyFile -Force -ErrorAction SilentlyContinue
            }
        } else {
            Write-Log "Database file not found, authentication setup will be handled by application startup"
        }
        
        return $true
    }
    catch {
        Write-Log "Error during authentication setup: $($_.Exception.Message)"
        return $false
    }
    finally {
        Write-Log "Authentication configuration setup completed"
    }
}

# MAIN SCRIPT FLOW
try {
    # Check admin privileges first, before showing any UI
    Test-AdminPrivileges

    # Check for existing installation and prompt for reinstall
    if (Test-ExistingInstallation -RegPath $registryPath) {
        if (-not (Prompt-Reinstall)) {
            Write-Log "Installation cancelled by user." -ForegroundColor Yellow
            exit 0
        }
        else {
            Write-Log "Proceeding with reinstall. Existing settings will be overwritten." -ForegroundColor Yellow
        }
    }

    # Show the unified installer wizard
    $result = Show-InstallerWizard
    
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Log "Installation cancelled by user." -ForegroundColor Yellow
        exit 0
    }
}
catch {
    Write-Log "[ERROR] Installation failed: $($_.Exception.Message)"
    if (Test-Path (Split-Path $global:logFilePath -Parent)) {
        Write-LogToFile -logFilePath $global:logFilePath
    }
    [System.Windows.Forms.MessageBox]::Show(
        "Installation failed: $($_.Exception.Message)",
        "Installation Error",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}

exit 0