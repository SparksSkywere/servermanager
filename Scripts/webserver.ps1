$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

try {
    # Get registry and paths
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
    
    # Setup logging
    $logsDir = Join-Path $serverManagerDir "logs"
    if (-not (Test-Path $logsDir)) {
        New-Item -Path $logsDir -ItemType Directory -Force | Out-Null
    }
    
    $logPath = Join-Path $logsDir "webserver.log"
    
    function Write-ServerLog {
        param([string]$Message, [string]$Level = "INFO")
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$timestamp [$Level] - $Message" | Add-Content -Path $logPath
        Write-Host "[$Level] $Message"
    }
    
    Write-ServerLog "Starting web server..."

    # Ensure URL reservation exists
    try {
        $null = netsh http show urlacl url=http://+:8080/
    }
    catch {
        Write-ServerLog "Adding URL reservation..." -Level "WARN"
        $null = netsh http add urlacl url=http://+:8080/ user=Everyone
    }
    
    # Set up HTTP listener with more permissive binding
    $http = [System.Net.HttpListener]::new()
    $http.Prefixes.Add("http://+:8080/")
    
    try {
        Write-ServerLog "Starting HTTP listener..."
        $http.Start()
        
        # Signal that we're ready
        $flagFile = Join-Path $env:TEMP "webserver_ready.flag"
        "ready" | Out-File -FilePath $flagFile -Force
        Write-ServerLog "Server is ready!"
        
        # Set up cancellation token
        $exitEvent = [System.Threading.EventWaitHandle]::new($false, [System.Threading.EventResetMode]::ManualReset)
        
        # Register handler for Ctrl+C with explicit method signature
        [Console]::TreatControlCAsInput = $true
        $action = [Action]{
            while ($true) {
                if ([Console]::KeyAvailable) {
                    $key = [Console]::ReadKey($true)
                    if ($key.Key -eq "C" -and $key.Modifiers -eq "Control") {
                        $exitEvent.Set()
                        break
                    }
                }
                Start-Sleep -Milliseconds 100
            }
        }
        $null = [System.Threading.Tasks.Task]::Factory.StartNew($action)
        
        # Main request handling loop
        while (-not $exitEvent.WaitOne(100)) {
            if ($http.IsListening) {
                try {
                    # Get context with timeout
                    $getContextTask = $http.GetContextAsync()
                    $completed = $getContextTask.Wait(1000)
                    
                    if ($completed) {
                        $context = $getContextTask.Result
                        
                        # Handle request
                        $response = $context.Response
                        $content = "Server Manager API Running"
                        $buffer = [System.Text.Encoding]::UTF8.GetBytes($content)
                        
                        $response.ContentLength64 = $buffer.Length
                        $response.ContentType = "text/plain"
                        $response.StatusCode = 200
                        
                        $response.OutputStream.Write($buffer, 0, $buffer.Length)
                        $response.Close()
                        
                        Write-ServerLog "Handled request: $($context.Request.Url.LocalPath)"
                    }
                }
                catch [System.ObjectDisposedException] {
                    break
                }
                catch {
                    if ($http.IsListening) {
                        Write-ServerLog "Request error: $($_.Exception.Message)" -Level "ERROR"
                    }
                }
            }
            else {
                Write-ServerLog "HTTP listener stopped unexpectedly" -Level "ERROR"
                break
            }
        }
    }
    finally {
        Write-ServerLog "Shutting down server..." -Level "INFO"
        if ($http -ne $null) {
            if ($http.IsListening) {
                $http.Stop()
            }
            $http.Close()
            $http.Dispose()
        }
        if (Test-Path $flagFile) {
            Remove-Item $flagFile -Force
        }
        # Remove URL reservation on exit
        try {
            $null = netsh http delete urlacl url=http://+:8080/
        }
        catch {
            Write-ServerLog "Failed to remove URL reservation: $($_.Exception.Message)" -Level "WARN"
        }
    }
}
catch {
    Write-ServerLog "Fatal error: $($_.Exception.Message)" -Level "ERROR"
    Write-ServerLog $_.ScriptStackTrace -Level "ERROR"
    exit 1
}
