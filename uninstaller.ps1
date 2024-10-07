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

# MAIN UNINSTALLATION PROCESS
# Step 1: Fetch the installation directory from 'servermanager' subkey
if (Test-Path -Path $serverManagerRegistryPath) {
    try {
        $installDir = (Get-ItemProperty -Path $serverManagerRegistryPath).InstallDir
        
        if (-not $installDir) {
            throw "InstallDir property is missing."
        }

        Write-Host "Installation directory found: $installDir"
    } catch {
        Write-Host "Failed to retrieve InstallDir property from the registry: $($_.Exception.Message)"
        exit
    }
} else {
    Write-Host "Registry path does not exist: $serverManagerRegistryPath"
    exit
}

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
        Write-Host 'Starting uninstallation process'
        
        # Step 2: Remove the installation directory and any related files
        Remove-Directory -dir '$($installDir)'

        # Step 3: Remove 'servermanager' registry key
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries\servermanager'

        # Step 4: Remove the parent key 'SkywereIndustries' if it exists and is empty
        Remove-RegistryKey -regPath 'HKLM:\Software\SkywereIndustries'

        Write-Host 'Uninstallation complete.'
    } catch {
        Write-Host 'Error during uninstallation: $($_.Exception.Message)'
        exit
    }
"@

# Run all admin tasks in one elevation request
Start-ElevatedProcess -scriptBlock $scriptBlock

# End of uninstaller
Write-Host "Uninstallation process finished."
