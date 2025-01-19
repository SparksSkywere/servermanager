# Hide console window
Add-Type -Name Window -Namespace Console -MemberDefinition '
[DllImport("Kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
'
$consolePtr = [Console.Window]::GetConsoleWindow()
[void][Console.Window]::ShowWindow($consolePtr, 0)

$host.UI.RawUI.WindowStyle = 'Hidden'

# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "Modules\ServerManager.psm1"
Import-Module $serverManagerPath -Force

# Define the registry path where the Server Manager settings are stored
$registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"

# Function to retrieve registry value
function Get-RegistryValue {
    param (
        [string]$keyPath,
        [string]$propertyName
    )
    try {
        $value = Get-ItemProperty -Path $keyPath -Name $propertyName -ErrorAction Stop
        return $value.$propertyName
    } catch {
        Write-Host "Failed to retrieve registry value: $($_.Exception.Message)"
        exit 1
    }
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

# Function to stop all server instances
function Stop-AllServerInstances {
    Logging "Stopping all server instances..."
    # Retrieve Server Manager directory path from registry
    $ServerManagerDir = Get-RegistryValue -keyPath $registryPath -propertyName "Servermanagerdir"

    # Define the path to the PID file using the registry-based directory
    $pidFilePath = Join-Path $ServerManagerDir "PIDS.txt"

    # Check if the PID file exists
    if (Test-Path -Path $pidFilePath) {
        # Read all the PIDs from the file
        $pidEntries = Get-Content -Path $pidFilePath

        # Loop through each entry in the file
        foreach ($pidEntry in $pidEntries) {
            # Attempt to extract the PID (assumes PID is the first value in each line)
            $processId = [int]($pidEntry -split ' - ')[0]

            # Attempt to stop the process
            try {
                Stop-Process -Id $processId -Force
                Write-Host "Successfully stopped process (PID: $processId)."
            } catch {
                Write-Host "Failed to stop process (PID: $processId): $_" -ForegroundColor Red
            }
        }

        # Clear the contents of the PID file after processing
        Clear-Content -Path $pidFilePath
        Write-Host "All processes stopped and PID file cleared."
    } else {
        Write-Host "PID file not found at $pidFilePath."
    }
}

function Stop-AllServers {
    param(
        [string]$ServerName = ""
    )

    try {
        # Validate registry path
        if (-not (Test-Path $registryPath)) {
            throw "Server manager registry path not found"
        }

        $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
        if (-not $serverManagerDir) {
            throw "Server manager directory not found in registry"
        }

        $pidFile = Join-Path $serverManagerDir "PIDS.txt"

        if (Test-Path $pidFile) {
            $servers = Get-Content $pidFile

            foreach ($server in $servers) {
                $serverInfo = $server -split ' - '
                if ($serverInfo.Count -ge 2) {
                    $processId = $serverInfo[0]
                    $name = $serverInfo[1]

                    # If ServerName is specified, only stop that server
                    if ($ServerName -and $name -ne $ServerName) {
                        continue
                    }

                    Write-Host "Stopping server: $name (PID: $processId)"
                    try {
                        Stop-Process -Id $processId -Force
                        Write-Host "Server stopped successfully: $name"
                    }
                    catch {
                        Write-Host "Failed to stop server $name : $_"
                    }
                }
            }

            # Clear or update PID file
            if ($ServerName) {
                $remainingServers = $servers | Where-Object { $_ -notlike "* - $ServerName" }
                Set-Content -Path $pidFile -Value $remainingServers
            }
            else {
                Clear-Content -Path $pidFile
            }
        }
        else {
            Write-Host "No PID file found. No servers to stop."
        }
    } catch {
        Write-Error "Failed to stop servers: $_"
        return $false
    }
}

# Execute with error handling
try {
    Stop-AllServers @args
} catch {
    Write-Error "Critical error: $_"
    exit 1
}
