# Define the registry paths
$serverManagerRegistryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$rootRegistryPath = "HKLM:\Software\SkywereIndustries"
$rootRegistryPath | Out-Null

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

# Function to delete a directory if it exists
function Remove-Directory {
    param (
        [string]$dir
    )
    if (Test-Path -Path $dir) {
        try {
            Remove-Item -Recurse -Force -Path $dir
        } catch {
            Write-Host "Failed to remove directory: $($_.Exception.Message)"
            throw
        }
    } else {
        Write-Host "Directory does not exist: $dir"
    }
}

# Function to show dialog box for user confirmation
function Get-UserConfirmation {
    Add-Type -AssemblyName PresentationFramework
    $result = [System.Windows.MessageBox]::Show("Do you want to uninstall SteamCMD?", "Uninstall SteamCMD", 'YesNo', 'Question')
    return ($result -eq 'Yes')
}

# Function to connect to the PID console
function Connect-PIDConsole {
    param (
        [int]$ProcessId
    )
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $process | Out-Host
    } catch {
        Write-Host "Failed to connect to process (PID: $ProcessId): $_" -ForegroundColor Red
    }
}

# Function to remove a server instance
function Remove-ServerInstance {
    param (
        [string]$ServerName
    )
    Logging "Removing server instance: $ServerName..."
    # ...existing code...
}

# Function to remove module installations
function Remove-ModuleInstallations {
    Write-Host "Removing installed PowerShell modules..."
    try {
        # Remove SecretManagement module if it was installed by our installer
        if (Get-Module -ListAvailable -Name "Microsoft.PowerShell.SecretManagement") {
            Uninstall-Module -Name "Microsoft.PowerShell.SecretManagement" -AllVersions -Force
        }
        
        # Clean up local modules directory
        $localModulePath = Join-Path $SteamCMDPath "Servermanager\Modules"
        if (Test-Path $localModulePath) {
            Remove-Item -Path $localModulePath -Recurse -Force
        }
    } catch {
        Write-Host "Error removing modules: $($_.Exception.Message)"
    }
}

# Function to remove encryption key
function Remove-EncryptionKey {
    $encryptionKeyPath = "C:\ProgramData\ServerManager"
    $keyFile = Join-Path $encryptionKeyPath "encryption.key"
    
    try {
        if (Test-Path $keyFile) {
            # Securely delete the encryption key file
            $bytes = New-Object byte[] (Get-Item $keyFile).Length
            $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
            $rng.GetBytes($bytes)
            Set-Content -Path $keyFile -Value $bytes -Encoding Byte -Force
            Remove-Item -Path $keyFile -Force
        }
        
        if (Test-Path $encryptionKeyPath) {
            Remove-Item -Path $encryptionKeyPath -Force -Recurse
        }
        
        Write-Host "Encryption key cleanup completed successfully."
    }
    catch {
        Write-Host "Error during encryption key cleanup: $($_.Exception.Message)"
    }
}

# Add service cleanup function
function Remove-ServerManagerService {
    Write-Host "Checking for Server Manager service..." -ForegroundColor Cyan
    try {
        $service = Get-Service -Name "ServerManagerService" -ErrorAction SilentlyContinue
        if ($service) {
            Write-Host "Found Server Manager service, stopping and removing..." -ForegroundColor Yellow
            Stop-Service -Name "ServerManagerService" -Force
            $null = sc.exe delete "ServerManagerService"
            Write-Host "Service removed successfully" -ForegroundColor Green
        }
    } catch {
        Write-Host "Error removing service: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Add firewall rules cleanup
function Remove-FirewallRules {
    Write-Host "Cleaning up firewall rules..." -ForegroundColor Cyan
    $rules = @(
        "ServerManager_HTTP_8080",
        "ServerManager_WebSocket_8081",
        "ServerManager_*"  # Catch-all for any other rules we might have created
    )

    foreach ($rule in $rules) {
        Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | 
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    }
}

# Add scheduled tasks cleanup
function Remove-ScheduledTasks {
    Write-Host "Cleaning up scheduled tasks..." -ForegroundColor Cyan
    $tasks = @(
        "\ServerManager\*"
    )

    foreach ($task in $tasks) {
        Get-ScheduledTask -TaskPath $task -ErrorAction SilentlyContinue |
        Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
    }
}

# Add function to clean up program data
function Remove-ProgramData {
    Write-Host "Cleaning up program data..." -ForegroundColor Cyan
    $paths = @(
        "C:\ProgramData\ServerManager",
        "$env:LOCALAPPDATA\ServerManager",
        "$env:APPDATA\ServerManager"
    )

    foreach ($path in $paths) {
        if (Test-Path $path) {
            Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# Add function to clean up temp files
function Remove-TempFiles {
    Write-Host "Cleaning up temporary files..." -ForegroundColor Cyan
    $tempFiles = @(
        "$env:TEMP\websocket_ready.flag",
        "$env:TEMP\webserver_ready.flag",
        "$env:TEMP\servermanager_*.pid",
        "$env:TEMP\servermanager_*.log"
    )

    foreach ($file in $tempFiles) {
        Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
    }
}

# Add port cleanup
function Remove-PortReservations {
    Write-Host "Cleaning up port reservations..." -ForegroundColor Cyan
    $ports = @(8080, 8081)
    
    foreach ($port in $ports) {
        # Remove URL ACL
        $null = netsh http delete urlacl url=http://+:$port/
        
        # Force kill any processes using these ports
        Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | 
        ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

# MAIN UNINSTALLATION PROCESS
# Step 1: Fetch the installation directory from 'servermanager' subkey
if (Test-Path -Path $serverManagerRegistryPath) {
    try {
        $SteamCMDPath = (Get-ItemProperty -Path $serverManagerRegistryPath).SteamCMDPath
        
        if (-not $SteamCMDPath) {
            throw "SteamCMDPath property is missing."
        }

        Write-Host "Installation directory found: $SteamCMDPath"
    } catch {
        Write-Host "Failed to retrieve SteamCMDPath property from the registry: $($_.Exception.Message)"
        exit
    }
} else {
    Write-Host "Registry path does not exist: $serverManagerRegistryPath"
    exit
}

# Ask if user wants to uninstall SteamCMD
$uninstallSteamCMD = Get-UserConfirmation

# Combine all admin-required tasks into a single elevated process
$scriptBlock = @"
    # Define the function to remove registry keys inside elevated context
    function Remove-RegistryKey {
        param ([string]`$regPath)
        try {
            if (Test-Path -Path `$regPath) {
                Remove-Item -Path `$regPath -Recurse -Force
            } else {
                Write-Host "Registry key not found: `$regPath"
            }
        } catch {
            Write-Host "Failed to remove registry key: `$($_.Exception.Message)"
            throw
        }
    }

    # Define function to delete directories inside elevated context
    function Remove-Directory {
        param ([string]`$dir)
        if (Test-Path -Path `$dir) {
            try {
                Remove-Item -Recurse -Force -Path `$dir
            } catch {
                Write-Host "Failed to remove directory: `$($_.Exception.Message)"
                throw
            }
        } else {
            Write-Host "Directory does not exist: `$dir"
        }
    }

    # Define function to remove encryption key inside elevated context
    function Remove-EncryptionKey {
        `$encryptionKeyPath = "C:\ProgramData\ServerManager"
        `$keyFile = Join-Path `$encryptionKeyPath "encryption.key"
        
        try {
            if (Test-Path `$keyFile) {
                # Securely delete the encryption key file
                `$bytes = New-Object byte[] (Get-Item `$keyFile).Length
                `$rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
                `$rng.GetBytes(`$bytes)
                Set-Content -Path `$keyFile -Value `$bytes -Encoding Byte -Force
                Remove-Item -Path `$keyFile -Force
            }
            
            if (Test-Path `$encryptionKeyPath) {
                Remove-Item -Path `$encryptionKeyPath -Force -Recurse
            }
            
            Write-Host "Encryption key cleanup completed successfully."
        }
        catch {
            Write-Host "Error during encryption key cleanup: `$($_.Exception.Message)"
        }
    }

    # Add service cleanup function
    function Remove-ServerManagerService {
        Write-Host "Checking for Server Manager service..." -ForegroundColor Cyan
        try {
            `$service = Get-Service -Name "ServerManagerService" -ErrorAction SilentlyContinue
            if (`$service) {
                Write-Host "Found Server Manager service, stopping and removing..." -ForegroundColor Yellow
                Stop-Service -Name "ServerManagerService" -Force
                `$null = sc.exe delete "ServerManagerService"
                Write-Host "Service removed successfully" -ForegroundColor Green
            }
        } catch {
            Write-Host "Error removing service: `$($_.Exception.Message)" -ForegroundColor Red
        }
    }

    # Add firewall rules cleanup
    function Remove-FirewallRules {
        Write-Host "Cleaning up firewall rules..." -ForegroundColor Cyan
        `$rules = @(
            "ServerManager_HTTP_8080",
            "ServerManager_WebSocket_8081",
            "ServerManager_*"  # Catch-all for any other rules we might have created
        )

        foreach (`$rule in `$rules) {
            Get-NetFirewallRule -DisplayName `$rule -ErrorAction SilentlyContinue | 
            Remove-NetFirewallRule -ErrorAction SilentlyContinue
        }
    }

    # Add scheduled tasks cleanup
    function Remove-ScheduledTasks {
        Write-Host "Cleaning up scheduled tasks..." -ForegroundColor Cyan
        `$tasks = @(
            "\ServerManager\*"
        )

        foreach (`$task in `$tasks) {
            Get-ScheduledTask -TaskPath `$task -ErrorAction SilentlyContinue |
            Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
        }
    }

    # Add function to clean up program data
    function Remove-ProgramData {
        Write-Host "Cleaning up program data..." -ForegroundColor Cyan
        `$paths = @(
            "C:\ProgramData\ServerManager",
            "`$env:LOCALAPPDATA\ServerManager",
            "`$env:APPDATA\ServerManager"
        )

        foreach (`$path in `$paths) {
            if (Test-Path `$path) {
                Remove-Item -Path `$path -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # Add function to clean up temp files
    function Remove-TempFiles {
        Write-Host "Cleaning up temporary files..." -ForegroundColor Cyan
        `$tempFiles = @(
            "`$env:TEMP\websocket_ready.flag",
            "`$env:TEMP\webserver_ready.flag",
            "`$env:TEMP\servermanager_*.pid",
            "`$env:TEMP\servermanager_*.log"
        )

        foreach (`$file in `$tempFiles) {
            Remove-Item -Path `$file -Force -ErrorAction SilentlyContinue
        }
    }

    # Add port cleanup
    function Remove-PortReservations {
        Write-Host "Cleaning up port reservations..." -ForegroundColor Cyan
        `$ports = @(8080, 8081)
        
        foreach (`$port in `$ports) {
            # Remove URL ACL
            `$null = netsh http delete urlacl url=http://+:`$port/
            
            # Force kill any processes using these ports
            Get-NetTCPConnection -LocalPort `$port -ErrorAction SilentlyContinue | 
            ForEach-Object {
                Stop-Process -Id `$.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }

    try {
        Write-Host 'Starting uninstallation process' -ForegroundColor Cyan

        # Stop and remove service first
        Remove-ServerManagerService

        # Kill any running processes
        Write-Host "Stopping any running Server Manager processes..." -ForegroundColor Cyan
        Get-Process -Name "powershell" | 
            Where-Object { `$.CommandLine -like "*servermanager*" } |
            Stop-Process -Force -ErrorAction SilentlyContinue

        # Remove service and scheduled tasks
        Remove-ServerManagerService
        Remove-ScheduledTasks

        # Clean up firewall rules
        Remove-FirewallRules

        # Remove encryption key and program data
        Remove-EncryptionKey
        Remove-ProgramData

        # Clean up ports and temp files
        Remove-PortReservations
        Remove-TempFiles

        # Only remove the SteamCMD directory if the user confirmed
        if (`$env:UNINSTALL_STEAMCMD -eq 'True') {
            Remove-Directory -dir '$($SteamCMDPath)'
        } else {
            # Remove only Server Manager components
            `$itemsToRemove = @(
                (Join-Path '$($SteamCMDPath)' "Servermanager")
            )

            foreach (`$item in `$itemsToRemove) {
                Remove-Directory -dir `$item
            }
        }

        # Remove registry keys
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries\servermanager'
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries'

        Write-Host "`nUninstallation completed successfully!" -ForegroundColor Green
        Write-Host "All Server Manager components have been removed." -ForegroundColor Green
        
        if (`$env:UNINSTALL_STEAMCMD -ne 'True') {
            Write-Host "SteamCMD has been preserved at: $($SteamCMDPath)" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "Error during uninstallation: `$(`$_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
"@

# Remove installed modules before elevation
Remove-ModuleInstallations

# Set environment variable for use in the elevated script
if ($uninstallSteamCMD) {
    $env:UNINSTALL_STEAMCMD = 'True'
} else {
    $env:UNINSTALL_STEAMCMD = 'False'
    Write-Host "SteamCMD uninstallation skipped."
}

# Run all admin tasks in one elevation request
Start-ElevatedProcess -scriptBlock $scriptBlock

# End of uninstaller
Write-Host "Process finished."