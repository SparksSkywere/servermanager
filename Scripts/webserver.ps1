$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

try {
    # Basic initialization
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    
    # Import required module
    $modulesPath = Join-Path $serverManagerDir "Modules"
    Import-Module (Join-Path $modulesPath "WebSocketServer.psm1") -Force -ErrorAction Stop
    
    # Get paths from module
    $paths = Get-WebSocketPaths
    if (-not $paths) {
        throw "Failed to get WebSocket paths"
    }
    
    Write-Host "Starting web server..."
    
    # Create HTTP listener
    $http = [System.Net.HttpListener]::new()
    $http.Prefixes.Add("http://+:8080/")
    $http.Start()
    
    # Signal HTTP server is ready
    "ready" | Out-File -FilePath $paths.WebServerReadyFile -Force
    Write-Host "HTTP server ready"
    
    # Create WebSocket server
    $wsServer = New-WebSocketServer -Port 8081
    if (-not $wsServer) {
        throw "Failed to create WebSocket server"
    }
    
    $wsServer.Start()
    Write-Host "WebSocket server started"
    
    # Keep the servers running
    while ($http.IsListening -and $wsServer.GetStatus().IsRunning) {
        Start-Sleep -Seconds 1
    }
}
catch {
    Write-Error "Server error: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($http) {
        $http.Stop()
        $http.Close()
    }
    if ($wsServer) {
        $wsServer.Stop()
    }
}
