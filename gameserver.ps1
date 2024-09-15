Clear-Host
$host.UI.RawUI.WindowTitle = "*** Server Watchdog"

# Define the name of this server
$ServerName = "***"

# Path to the PIDs file
$pidFilePath = "C:\PIDS.txt"

# Define the arguments for the process
$arguments = 
'
ENTER YOUR ARGUEMENTS HERE
'

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

    try {
        # Start the server and capture its PID with arguments
        $process = Start-Process "***" -ArgumentList $arguments -PassThru -ErrorAction Stop
        if ($null -eq $process) {
            throw "Failed to start the process."
        }

        # Lock the file during the write operation
        $pidEntry = "$($process.Id) - $ServerName"
        $fileStream = [System.IO.File]::Open($pidFilePath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $writer = New-Object System.IO.StreamWriter($fileStream)
        $writer.WriteLine($pidEntry)
        $writer.Flush()
        $writer.Close()
        $fileStream.Close()

        Write-Output "PID $($process.Id) recorded for $ServerName."

    } catch {
        Write-Output "Error starting process or writing PID: $_"
        Start-Sleep -Seconds 5
        continue
    }

    # Wait for the server process to exit (crash or shutdown)
    $process | Wait-Process

    Write-Output "$ServerName server crashed or shutdown at: $(Get-Date)"

    # Remove the PID from the file after the server stops
    try {
        $pids = Get-Content -Path $pidFilePath | Where-Object { $_ -notmatch "$($process.Id) - $ServerName" }
        Set-Content -Path $pidFilePath -Value $pids
    } catch {
        Write-Output "Error removing PID from the file: $_"
    }
}
