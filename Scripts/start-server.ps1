# Add module import at the start
$serverManagerPath = Join-Path $PSScriptRoot "Modules\ServerManager.psm1"
Import-Module $serverManagerPath -Force

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

function Start-GameServer {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServerName
    )

    # Get registry path
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $configPath = Join-Path $serverManagerDir "servers\$ServerName.json"

    if (Test-Path $configPath) {
        $config = Get-Content $configPath | ConvertFrom-Json
        
        # Start the server process
        try {
            $process = Start-Process -FilePath "$($config.InstallDir)\$($config.ExecutablePath)" `
                                   -ArgumentList $config.StartupArgs `
                                   -WorkingDirectory $config.InstallDir `
                                   -WindowStyle Hidden `
                                   -RedirectStandardOutput (Join-Path $logDir "$ServerName.log") `
                                   -RedirectStandardError (Join-Path $logDir "$ServerName.error.log") `
                                   -PassThru

            # Log the PID
            $pidFile = Join-Path $serverManagerDir "PIDS.txt"
            Add-Content -Path $pidFile -Value "$($process.Id) - $ServerName"
            
            Write-Host "Server started successfully: $ServerName (PID: $($process.Id))"
        }
        catch {
            Write-Host "Failed to start server $ServerName : $_"
        }
    }
    else {
        Write-Host "Server configuration not found: $ServerName"
    }
}

# Execute the function if ServerName is provided
if ($args.Count -gt 0) {
    Start-GameServer -ServerName $args[0]
}
else {
    Write-Host "Please provide a server name."
}
