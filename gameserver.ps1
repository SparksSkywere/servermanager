Clear-Host
$host.UI.RawUI.WindowTitle = "*** Server Watchdog"

# Define the name of this server
$ServerName = "***"

# Path to the PIDs file
$pidFilePath = "C:\PIDS.txt"

while ($true) {
    # Check if the stop file exists and read its content
    $stopFilePath = "C:\stop.txt"
    if (Test-Path -Path $stopFilePath) {
        $stopFileContent = Get-Content -Path $stopFilePath
        if ($stopFileContent -eq $ServerName) {
            Write-Output "$ServerName update in progress. Waiting for the update to finish at: $(Get-Date)"
            Start-Sleep -Seconds 5
            continue
        }
    }

    Write-Output "$ServerName server starting at: $(Get-Date)"

    # Start the server and capture its PID
    $process = Start-Process "***" -PassThru

    # Write the PID and server name to the PIDS.txt file
    "$($process.Id) - $ServerName" | Out-File -Append -FilePath $pidFilePath

    # Wait for the server process to exit (crash or shutdown)
    $process | Wait-Process

    Write-Output "$ServerName server crashed or shutdown at: $(Get-Date)"

    # Optionally remove the PID from the file after the server stops
    (Get-Content -Path $pidFilePath) | Where-Object { $_ -notmatch "$($process.Id) - $ServerName" } | Set-Content -Path $pidFilePath
}
