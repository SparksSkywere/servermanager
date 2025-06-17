# --- Hide console and relaunch as WinForms GUI if needed ---
Add-Type -AssemblyName System.Windows.Forms

# --- Logging functions must be defined before any usage ---
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

# --- Main installer script ---

# Define global variables first
$global:logMemory = @()
$global:logFilePath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "Install-Log.txt"
$CurrentVersion = "0.3"
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

# Add after global variable definitions
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
                    # Only include real SQL instance names, skip PS* properties
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

function Suggest-SQLDownload {
    param([string]$Type)
    if ($Type -eq "MSSQL") {
        $url = "https://aka.ms/ssms"
        $msg = "Microsoft SQL Server Express was not found. Download and install from: $url"
    } elseif ($Type -eq "MySQL") {
        $url = "https://dev.mysql.com/downloads/installer/"
        $msg = "MySQL Server was not found. Download and install from: $url"
    } elseif ($Type -eq "MariaDB") {
        $url = "https://mariadb.org/download/"
        $msg = "MariaDB Server was not found. Download and install from: $url"
    } else {
        return
    }
    [System.Windows.Forms.MessageBox]::Show($msg, "$Type Not Found", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
}

function Get-SQLSetupOptions {
    $detected = Get-InstalledSQLServers

    # Convert hashtables to PSCustomObject for Select-Object compatibility
    $detectedObjs = @()
    foreach ($item in $detected) {
        $detectedObjs += [PSCustomObject]$item
    }

    # Handle empty detection
    if (-not $detectedObjs -or $detectedObjs.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show(
            "No supported SQL servers detected. Please install SQLite, MSSQL, MySQL, or MariaDB and restart the installer.",
            "No SQL Servers Found",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
        return $null
    }

    $types = $detectedObjs | Select-Object -ExpandProperty Type -Unique
    $typeDisplay = $detectedObjs | Select-Object -ExpandProperty Display

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "SQL Database Setup"
    $form.Size = New-Object System.Drawing.Size(420,260)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $typeLabel = New-Object System.Windows.Forms.Label
    $typeLabel.Text = "SQL Type:"
    $typeLabel.Location = New-Object System.Drawing.Point(20,20)
    $typeLabel.Size = New-Object System.Drawing.Size(80,20)
    $form.Controls.Add($typeLabel)

    $typeCombo = New-Object System.Windows.Forms.ComboBox
    $typeCombo.Location = New-Object System.Drawing.Point(110,20)
    $typeCombo.Size = New-Object System.Drawing.Size(260,20)
    $typeCombo.DropDownStyle = 'DropDownList'
    if ($typeDisplay) {
        $typeCombo.Items.AddRange($typeDisplay)
        $typeCombo.SelectedIndex = 0
    }
    $form.Controls.Add($typeCombo)

    $versionLabel = New-Object System.Windows.Forms.Label
    $versionLabel.Text = "SQL Version:"
    $versionLabel.Location = New-Object System.Drawing.Point(20,60)
    $versionLabel.Size = New-Object System.Drawing.Size(80,20)
    $form.Controls.Add($versionLabel)

    $versionBox = New-Object System.Windows.Forms.TextBox
    $versionBox.Location = New-Object System.Drawing.Point(110,60)
    $versionBox.Size = New-Object System.Drawing.Size(260,20)
    $versionBox.Text = $detectedObjs[0].Version
    $form.Controls.Add($versionBox)

    $locationLabel = New-Object System.Windows.Forms.Label
    $locationLabel.Text = "SQL Location/Connection:"
    $locationLabel.Location = New-Object System.Drawing.Point(20,100)
    $locationLabel.Size = New-Object System.Drawing.Size(150,20)
    $form.Controls.Add($locationLabel)

    $locationBox = New-Object System.Windows.Forms.TextBox
    $locationBox.Location = New-Object System.Drawing.Point(20,120)
    $locationBox.Size = New-Object System.Drawing.Size(350,20)
    $locationBox.Text = $detectedObjs[0].Location
    $form.Controls.Add($locationBox)

    $infoLabel = New-Object System.Windows.Forms.Label
    $infoLabel.Text = "If your preferred SQL server is not listed, please install it and restart the installer."
    $infoLabel.Location = New-Object System.Drawing.Point(20,150)
    $infoLabel.Size = New-Object System.Drawing.Size(370,30)
    $form.Controls.Add($infoLabel)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = "Continue"
    $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $okButton.Location = New-Object System.Drawing.Point(150,190)
    $form.Controls.Add($okButton)
    $form.AcceptButton = $okButton

    $typeCombo.Add_SelectedIndexChanged({
        $sel = $typeCombo.SelectedIndex
        $versionBox.Text = $detectedObjs[$sel].Version
        $locationBox.Text = $detectedObjs[$sel].Location
    })

    $result = $form.ShowDialog()
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        $sel = $typeCombo.SelectedIndex
        $chosenType = $detectedObjs[$sel].Type
        # If not SQLite and not found, suggest download
        if ($chosenType -ne "SQLite" -and -not ($types -contains $chosenType)) {
            Suggest-SQLDownload -Type $chosenType
            return $null
        }
        return @{
            SQLType = $chosenType
            SQLVersion = $versionBox.Text
            SQLLocation = $locationBox.Text
        }
    } else {
        return $null
    }
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
            # Use Python to create the DB and table for cross-platform compatibility
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
        } else {
            # Always ensure schema is up-to-date (add columns if missing)
            $pythonScript = @"
import sqlite3
import sys
dbfile = sys.argv[1]
conn = sqlite3.connect(dbfile)
c = conn.cursor()
# Add columns if they do not exist
def add_column(col, typ):
    try:
        c.execute(f'ALTER TABLE users ADD COLUMN {col} {typ}')
    except Exception as e:
        if 'duplicate column name' not in str(e):
            print(e)
for col, typ in [('two_factor_enabled', 'INTEGER DEFAULT 0'), ('two_factor_secret', 'TEXT')]:
    add_column(col, typ)
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
    elseif ($SQLType -match "^(MSSQL|SQLEXPRESS|MSSQLEXPRESS|SQLSERVER|^SQL.*$)") {
        # For MSSQL, attempt to create the database and table if they do not exist
        $dbName = "ServerManager"
        $instanceName = $SQLLocation -replace '^[.\\]+', ''
        $sqlcmd = "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe"
        if (-not (Test-Path $sqlcmd)) {
            $sqlcmd = Get-Command sqlcmd.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
        }
        if ($sqlcmd) {
            $queries = @(
                @{ server = "localhost\$instanceName"; desc = "localhost\$instanceName" },
                @{ server = "$env:COMPUTERNAME\$instanceName"; desc = "$env:COMPUTERNAME\$instanceName" },
                @{ server = ".\$instanceName"; desc = ".\$instanceName" },
                @{ server = $instanceName; desc = $instanceName }
            )
            $success = $false
            $query = "IF DB_ID(N'$dbName') IS NULL CREATE DATABASE [$dbName];"
            foreach ($q in $queries) {
                try {
                    & $sqlcmd -S $q.server -Q $query 2>$null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Log "Ensured SQL Server database '$dbName' exists on instance $($q.desc)"
                        $success = $true
                        # Now ensure the users table exists and is up-to-date
                        $tableQuery = @"
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
BEGIN
    CREATE TABLE users (
        id INT IDENTITY(1,1) PRIMARY KEY,
        username NVARCHAR(64) UNIQUE NOT NULL,
        password NVARCHAR(256) NOT NULL,
        email NVARCHAR(128) UNIQUE,
        is_admin BIT DEFAULT 0,
        is_active BIT DEFAULT 1,
        two_factor_enabled BIT DEFAULT 0,
        two_factor_secret NVARCHAR(64) NULL
    )
END
ELSE
BEGIN
    IF NOT EXISTS (SELECT * FROM sys.columns WHERE Name = N'two_factor_enabled' AND Object_ID = Object_ID(N'users'))
        ALTER TABLE users ADD two_factor_enabled BIT DEFAULT 0;
    IF NOT EXISTS (SELECT * FROM sys.columns WHERE Name = N'two_factor_secret' AND Object_ID = Object_ID(N'users'))
        ALTER TABLE users ADD two_factor_secret NVARCHAR(64) NULL;
END
"@
                        $tableTemp = [System.IO.Path]::GetTempFileName() + ".sql"
                        Set-Content -Path $tableTemp -Value $tableQuery
                        & $sqlcmd -S $q.server -d $dbName -i $tableTemp 2>$null
                        Remove-Item $tableTemp -Force
                        break
                    }
                } catch {}
            }
            if (-not $success) {
                Write-Log "Could not create or verify SQL Server database '$dbName' on any tested instance. Please ensure permissions and connectivity." -ForegroundColor Yellow
                Write-Log "TIP: Make sure the SQL Server instance is running, TCP/IP is enabled, and your user has permission to create databases."
                Write-Log "You can also try running this installer as an administrator, or manually create the database named '$dbName' in SQL Server Management Studio."
            }
        } else {
            Write-Log "sqlcmd.exe not found. Please ensure SQL Server command line tools are installed." -ForegroundColor Yellow
        }
        return $SQLLocation
    }
    elseif ($SQLType -eq "MySQL" -or $SQLType -eq "MariaDB") {
        # For MySQL/MariaDB, attempt to create the database and table if they do not exist
        $dbName = "servermanager"
        $dbHost = $SQLLocation
        $pythonScript = @"
import sys
import pymysql
try:
    conn = pymysql.connect(host='$dbHost', user='root', password='', charset='utf8mb4')
    cur = conn.cursor()
    cur.execute('CREATE DATABASE IF NOT EXISTS $dbName')
    conn.select_db('$dbName')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) UNIQUE NOT NULL,
            password VARCHAR(256) NOT NULL,
            email VARCHAR(128) UNIQUE,
            is_admin BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            two_factor_enabled BOOLEAN DEFAULT 0,
            two_factor_secret VARCHAR(64)
        )
    ''')
    # Add columns if missing
    try:
        cur.execute('ALTER TABLE users ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 0')
    except Exception as e:
        if 'Duplicate column name' not in str(e): print(e)
    try:
        cur.execute('ALTER TABLE users ADD COLUMN two_factor_secret VARCHAR(64)')
    except Exception as e:
        if 'Duplicate column name' not in str(e): print(e)
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print('MySQL/MariaDB database creation failed:', e)
    sys.exit(1)
"@
        $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
        Set-Content -Path $tempPy -Value $pythonScript
        python $tempPy
        Remove-Item $tempPy -Force
        return $SQLLocation
    }
    else {
        throw "Unsupported SQL type: $SQLType"
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

# Function to check and install Git if missing
function Install-Git {
    if (-Not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Log "Git is not installed. Installing Git..."
        try {
            # Use a more reliable Git download URL
            $installerUrl = "https://api.github.com/repos/git-for-windows/git/releases/latest"
            $latestRelease = Invoke-RestMethod -Uri $installerUrl
            $installerUrl = ($latestRelease.assets | Where-Object { $_.name -like "*64-bit.exe" }).browser_download_url
            $installerPath = Join-Path $env:TEMP "git-installer.exe"

            Write-Log "Downloading Git installer..."
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Log "Running Git installer..."
            Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART" -Wait

            # Verify installation
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

# Function to open folder selection dialog (non-admin)
function Select-FolderDialog {
    [System.Windows.Forms.FolderBrowserDialog]$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select the directory where SteamCMD should be installed"
    $dialog.ShowNewFolderButton = $true
    [void]$dialog.ShowDialog()
    if ($null -eq $dialog.SelectedPath) {
        Write-Log "No directory selected, exiting..."
        exit
    }
    return $dialog.SelectedPath
}

# Function to update and run SteamCMD (non-admin)
function Update-SteamCmd {
    param (
        [string]$steamCmdPath
    )
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

# Replace the Update-GitRepo function with a simpler initial clone function
function Initialize-GitRepo {
    param (
        [string]$repoUrl,
        [string]$destination
    )
    
    Write-Log "Initializing Git repository at $destination"
    try {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            if (Test-Path $destination) {
                Write-Log "Removing existing directory..."
                Remove-Item -Path $destination -Recurse -Force
            }
            
            Write-Log "Cloning repository..."
            git clone $repoUrl $destination
            Write-Log "Git repository successfully cloned."
        } else {
            Write-Log "Git is not installed or not found in the PATH."
            exit
        }
    } catch {
        Write-Log "Failed to clone Git repository: $($_.Exception.Message)"
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
        Write-Log "Created AppID.txt file."
    } else {
        Write-Log "AppID.txt file already exists."
    }
}

# Modify Install-RequiredModules function to match actual repository structure
function Install-RequiredModules {
    param([string]$ServerManagerDir)
    
    Write-Log "Installing required PowerShell modules..." -ForegroundColor Cyan
    
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
            "Security"
            "Logging"
        )

        $successCount = 0
        foreach ($moduleName in $installModules) {
            $modulePath = Join-Path $modulesPath "$moduleName.psm1"
            if (Test-Path $modulePath) {
                try {
                    Write-Log "Importing installation module: $moduleName"
                    Import-Module -Name $modulePath -Force -Global -ErrorAction Stop
                    $successCount++
                } catch {
                    Write-Log "Error importing module $moduleName : $($_.Exception.Message)" -ForegroundColor Red
                    Write-Log "Full Error: $($_)" -ForegroundColor Red
                }
            } else {
                Write-Log "Critical module not found: $modulePath" -ForegroundColor Red
                return $false
            }
        }

        # Verify core modules were loaded
        if ($successCount -ne $installModules.Count) {
            Write-Log "Not all required installation modules were loaded." -ForegroundColor Red
            return $false
        }

        Write-Log "Successfully loaded installation modules." -ForegroundColor Green
        return $true
    }
    catch {
        Write-Log "Module installation error: $($_.Exception.Message)" -ForegroundColor Red
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
        
        Write-Log "Encryption key setup completed successfully" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Log "Failed to initialize encryption key: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Modify Set-InitialAuthConfig function
function Set-InitialAuthConfig {
    param([string]$ServerManagerDir)
    
    Write-Log "Starting authentication configuration setup"
    
    try {
        # Import the authentication module to create the default admin user
        $authModulePath = Join-Path $ServerManagerDir "Modules\authentication.py"
        
        if (Test-Path $authModulePath) {
            Write-Log "Initializing authentication system with default admin user"
            
            # Use Python to initialize the authentication system
            $initScript = @"
import sys
import os
sys.path.insert(0, r'$ServerManagerDir')

try:
    from Modules.authentication import initialize_default_admin, create_user
    
    # Initialize default admin
    result = initialize_default_admin()
    if result:
        print("SUCCESS: Default admin user initialized")
    else:
        print("ERROR: Failed to initialize default admin user")
        # Try to create manually as fallback
        try:
            result = create_user("admin", "admin", True)
            if result:
                print("SUCCESS: Fallback admin user created")
            else:
                print("ERROR: Failed to create fallback admin user")
        except Exception as e:
            print(f"ERROR: Exception during fallback creation: {e}")
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    print(f"TRACEBACK: {traceback.format_exc()}")
"@
            
            $tempPyFile = [System.IO.Path]::GetTempFileName() + ".py"
            Set-Content -Path $tempPyFile -Value $initScript
            
            try {
                $result = & python $tempPyFile 2>&1
                Write-Log "Authentication initialization result: $result"
                
                if ($result -match "SUCCESS") {
                    Write-Log "Authentication system initialized successfully"
                } else {
                    Write-Log "Warning: Authentication initialization may have failed: $result" -Level WARNING
                }
            } finally {
                Remove-Item $tempPyFile -Force -ErrorAction SilentlyContinue
            }
        } else {
            Write-Log "Authentication module not found at: $authModulePath" -Level WARNING
        }
        
        return $true
    }
    catch {
        Write-Log "Error during authentication setup: $($_.Exception.Message)" -Level ERROR
        return $false
    }
    finally {
        Write-Log "Authentication configuration setup completed"
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
        Write-Log "Registry access test failed: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

# Add function to ensure admin elevation
function Test-AdminPrivileges {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Log "Requesting administrative privileges..." -ForegroundColor Yellow
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

# Add after global variable definitions
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
    # Refresh environment variables for current session
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

# Add after global variable definitions (before any usage of New-Salt)
function New-Salt {
    param([int]$Length = 32)
    # Generate a cryptographically secure random salt as a hex string
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes)
    return ([BitConverter]::ToString($bytes) -replace '-', '').Substring(0, $Length)
}

function Get-SecureHash {
    param(
        [Parameter(Mandatory=$true)]
        [System.Security.SecureString]$SecurePassword,
        [Parameter(Mandatory=$true)]
        [string]$Salt
    )
    # Convert SecureString to plain text
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    try {
        $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($plain + $Salt)
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $hash = $sha256.ComputeHash($bytes)
        return [Convert]::ToBase64String($hash)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

# Protect-ConfigFile function to set secure NTFS permissions on a file
function Protect-ConfigFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$FilePath
    )
    if (-not (Test-Path $FilePath)) {
        Write-Log "File not found: $FilePath" -ForegroundColor Yellow
        return $false
    }
    try {
        $acl = Get-Acl $FilePath
        $acl.SetAccessRuleProtection($true, $false) # Disable inheritance

        # Remove all existing access rules
        foreach ($rule in $acl.Access) {
            $acl.RemoveAccessRule($rule)
        }

        # Grant SYSTEM full control
        $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "FullControl", "Allow"
        )
        $acl.AddAccessRule($systemRule)

        # Grant Administrators full control
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

# --- Host/Subhost selection ---
function Get-HostTypeOptions {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Cluster Role Selection"
    $form.Size = New-Object System.Drawing.Size(400,180)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Select the role for this machine in the cluster:"
    $label.Location = New-Object System.Drawing.Point(20,20)
    $label.Size = New-Object System.Drawing.Size(350,20)
    $form.Controls.Add($label)

    $hostRadio = New-Object System.Windows.Forms.RadioButton
    $hostRadio.Text = "Host (Master)"
    $hostRadio.Location = New-Object System.Drawing.Point(40,50)
    $hostRadio.Size = New-Object System.Drawing.Size(150,20)
    $hostRadio.Checked = $true
    $form.Controls.Add($hostRadio)

    $subhostRadio = New-Object System.Windows.Forms.RadioButton
    $subhostRadio.Text = "Subhost (Slave/Agent)"
    $subhostRadio.Location = New-Object System.Drawing.Point(200,50)
    $subhostRadio.Size = New-Object System.Drawing.Size(150,20)
    $form.Controls.Add($subhostRadio)

    $hostAddrLabel = New-Object System.Windows.Forms.Label
    $hostAddrLabel.Text = "Host Address (for Subhost):"
    $hostAddrLabel.Location = New-Object System.Drawing.Point(40,80)
    $hostAddrLabel.Size = New-Object System.Drawing.Size(180,20)
    $hostAddrLabel.Visible = $false
    $form.Controls.Add($hostAddrLabel)

    $hostAddrBox = New-Object System.Windows.Forms.TextBox
    $hostAddrBox.Location = New-Object System.Drawing.Point(220,80)
    $hostAddrBox.Size = New-Object System.Drawing.Size(140,20)
    $hostAddrBox.Visible = $false
    $form.Controls.Add($hostAddrBox)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = "Continue"
    $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $okButton.Location = New-Object System.Drawing.Point(150,80)
    $form.Controls.Add($okButton)
    $form.AcceptButton = $okButton

    $subhostRadio.Add_CheckedChanged({
        if ($subhostRadio.Checked) {
            $hostAddrLabel.Visible = $true
            $hostAddrBox.Visible = $true
        } else {
            $hostAddrLabel.Visible = $false
            $hostAddrBox.Visible = $false
        }
    })

    $result = $form.ShowDialog()
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        $role = if ($hostRadio.Checked) { "Host" } else { "Subhost" }
        $hostAddr = if ($subhostRadio.Checked) { $hostAddrBox.Text } else { $null }
        return @{ HostType = $role; HostAddress = $hostAddr }
    } else {
        return $null
    }
}

# MAIN SCRIPT FLOW
try {
    Test-AdminPrivileges

    # --- Host/Subhost selection ---
    $hostTypeOptions = Get-HostTypeOptions
    if (-not $hostTypeOptions) {
        Write-Log "Installation cancelled by user." -ForegroundColor Yellow
        exit 0
    }

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

    # Check for Python 3.10+ 64-bit and install if missing
    if (-not (Test-Python310)) {
        Install-Python310
        if (-not (Test-Python310)) {
            Write-Log "Python 3.10 (64-bit) installation failed or not detected in PATH." -ForegroundColor Red
            exit 1
        }
    }

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
        'HostType' = $hostTypeOptions.HostType
    }
    if ($hostTypeOptions.HostType -eq "Subhost" -and $hostTypeOptions.HostAddress) {
        $registryValues['HostAddress'] = $hostTypeOptions.HostAddress
    }

    New-Item -Path "HKLM:\Software\SkywereIndustries" -Force | Out-Null
    New-Item -Path $registryPath -Force | Out-Null
    foreach ($key in $registryValues.Keys) {
        Set-ItemProperty -Path $registryPath -Name $key -Value $registryValues[$key] -Force
    }

    # Git operations first to get repository content
    Install-Git
    Initialize-GitRepo -repoUrl $gitRepoUrl -destination $ServerManagerDir

    # Now that we have the repository, install Python requirements using pip
    $requirementsPath = Join-Path $ServerManagerDir "requirements.txt"
    if (-not (Install-PythonRequirements -RequirementsPath $requirementsPath)) {
        throw "Failed to install required Python packages"
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

    # Prompt for SQL setup options
    $sqlOptions = Get-SQLSetupOptions
    if (-not $sqlOptions) {
        throw "SQL setup cancelled"
    }

    # Create data folder if not exists
    $DataFolder = Join-Path $ServerManagerDir "data"
    if (-not (Test-Path $DataFolder)) {
        New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
    }

    # Initialize SQL database and get DB path/location
    $SQLDatabasePath = Initialize-SQLDatabase -SQLType $sqlOptions.SQLType -SQLVersion $sqlOptions.SQLVersion -SQLLocation $sqlOptions.SQLLocation -DataFolder $DataFolder

    # --- Ensure SQL registry keys are always created/updated ---
    # For SQLLocation: 
    #   - SQLite: store the absolute path to the DB file (in data folder)
    #   - MSSQL: store the full instance path (not abbreviated .\Instance, but the actual installation path if possible)
    #   - MySQL/MariaDB: store the host/address only
    $regSQLLocation = ""
    $regSQLDatabasePath = ""

    if ($sqlOptions.SQLType -eq "SQLite") {
        $regSQLLocation = $SQLDatabasePath  # Absolute path to SQLite DB file
        $regSQLDatabasePath = $SQLDatabasePath
    } elseif ($sqlOptions.SQLType -match "^(MSSQL|SQLEXPRESS|MSSQLEXPRESS|SQLSERVER|^SQL.*$)") {
        # Try to resolve the full installation path for the SQL instance
        $instanceName = $sqlOptions.SQLLocation -replace '^[.\\]+', ''
        $mssqlRoot = ""
        $mssqlRegPaths = @(
            "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL"
        )
        foreach ($regPath in $mssqlRegPaths) {
            if (Test-Path $regPath) {
                $props = Get-ItemProperty -Path $regPath
                if ($props.PSObject.Properties.Name -contains $instanceName) {
                    $instanceId = $props.$instanceName
                    $setupRegPath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\Setup"
                    if (Test-Path $setupRegPath) {
                        $setupProps = Get-ItemProperty -Path $setupRegPath
                        if ($setupProps.PSObject.Properties.Name -contains "SQLPath") {
                            $mssqlRoot = $setupProps.SQLPath
                        } elseif ($setupProps.PSObject.Properties.Name -contains "SQLDataRoot") {
                            $mssqlRoot = $setupProps.SQLDataRoot
                        }
                    }
                }
            }
        }
        if ($mssqlRoot) {
            $regSQLLocation = $mssqlRoot
        } else {
            # Fallback to instance name if path not found
            $regSQLLocation = $instanceName
        }
        $regSQLDatabasePath = Join-Path $DataFolder "ServerManager.mdf"
    } elseif ($sqlOptions.SQLType -eq "MySQL" -or $sqlOptions.SQLType -eq "MariaDB") {
        $regSQLLocation = $sqlOptions.SQLLocation
        $regSQLDatabasePath = Join-Path $DataFolder "servermanager"
    } else {
        $regSQLLocation = $sqlOptions.SQLLocation
        $regSQLDatabasePath = $SQLDatabasePath
    }

    Set-ItemProperty -Path $registryPath -Name 'SQLType' -Value $sqlOptions.SQLType -Force
    Set-ItemProperty -Path $registryPath -Name 'SQLVersion' -Value $sqlOptions.SQLVersion -Force
    Set-ItemProperty -Path $registryPath -Name 'SQLLocation' -Value $regSQLLocation -Force
    Set-ItemProperty -Path $registryPath -Name 'SQLDatabasePath' -Value $regSQLDatabasePath -Force

    # --- Test SQL connection after setup ---
    $sqlTestResult = $false
    if ($sqlOptions.SQLType -eq "SQLite") {
        # For SQLite, check if file exists and can be opened
        if (Test-Path $SQLDatabasePath) {
            try {
                $testPy = @"
import sqlite3
import sys
try:
    conn = sqlite3.connect(sys.argv[1])
    conn.execute('SELECT 1')
    conn.close()
    sys.exit(0)
except Exception as e:
    print(str(e))
    sys.exit(1)
"@
                $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
                Set-Content -Path $tempPy -Value $testPy
                python $tempPy $SQLDatabasePath
                $sqlTestResult = ($LASTEXITCODE -eq 0)
                Remove-Item $tempPy -Force
            } catch {
                $sqlTestResult = $false
            }
        }
    } else {
        # For other SQL types, just check that location is not empty (real connection test should be in Python app)
        if ($SQLDatabasePath) {
            $sqlTestResult = $true
        }
    }
    if (-not $sqlTestResult) {
        [System.Windows.Forms.MessageBox]::Show(
            "SQL database connection test failed. Please check your SQL configuration.",
            "SQL Connection Test Failed",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        )
        throw "SQL connection test failed"
    }

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
    Write-Log "[ERROR] Installation failed: $($_.Exception.Message)"
    if (Test-Path (Split-Path $global:logFilePath -Parent)) {
        Write-LogToFile -logFilePath $global:logFilePath
    }
    exit 1
}

# --- Store SQL admin credentials in registry (encrypted) ---
# Only do this if using a SQL server that requires credentials (not SQLite)
if ($sqlOptions.SQLType -ne "SQLite") {
    # Use the admin username/password created earlier
    $adminUser = $adminUser  # from Set-InitialAuthConfig
    $adminPassPlain = $passPlain  # from Set-InitialAuthConfig

    # Read Fernet key from encryption.key
    $encryptionKeyPath = "C:\ProgramData\ServerManager\encryption.key"
    $fernetKey = [System.IO.File]::ReadAllBytes($encryptionKeyPath)
    # Fernet key must be base64 string (44 chars)
    if ($fernetKey.Length -eq 32) {
        $fernetKey = [System.Convert]::ToBase64String($fernetKey)
    } else {
        $fernetKey = [System.Text.Encoding]::UTF8.GetString($fernetKey)
    }

    # Encrypt using Python Fernet (call python inline)
    function Encrypt-Fernet([string]$plaintext, [string]$key) {
        $py = @"
import sys, base64
from cryptography.fernet import Fernet
key = sys.argv[1].encode()
f = Fernet(key)
token = f.encrypt(sys.argv[2].encode())
print(base64.b64encode(token).decode())
"@
        $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
        Set-Content -Path $tempPy -Value $py
        $enc = python $tempPy $key $plaintext
        Remove-Item $tempPy -Force
        return $enc
    }

    $encUser = Encrypt-Fernet $adminUser $fernetKey
    $encPass = Encrypt-Fernet $adminPassPlain $fernetKey

    Set-ItemProperty -Path $registryPath -Name 'SQLUser' -Value $encUser -Force
    Set-ItemProperty -Path $registryPath -Name 'SQLPassword' -Value $encPass -Force
}

exit 0