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

    try {
        Write-Host 'Starting process'

        # Only remove the SteamCMD directory if the user confirmed
        if (`$env:UNINSTALL_STEAMCMD -eq 'True') {
            Remove-Directory -dir '$($SteamCMDPath)'
        }

        # Remove the Servermanager directory
        Remove-Directory -dir '$($SteamCMDPath)\Servermanager'

        # Step 3: Remove 'servermanager' registry key
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries\servermanager'

        # Step 4: Remove the parent key 'SkywereIndustries' if it exists and is empty
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries'

        Write-Host 'Process complete.'
    } catch {
        Write-Host 'Error during process: $($_.Exception.Message)'
        exit
    }
"@

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