# API Server for Server Manager
param(
    [int]$Port = 8080,
    [string]$TempPath,
    [int]$WebSocketPort = 8081,
    [switch]$NoRedirect
)

# Error handling
$ErrorActionPreference = 'Stop'
$VerbosePreference = 'SilentlyContinue'

# Get base paths from registry
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
if (-not (Test-Path $registryPath)) {
    Write-Error "Registry path not found: $registryPath"
    exit 1
}

try {
    $serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
} catch {
    Write-Error "Failed to get server manager directory from registry: $_"
    exit 1
}

# Define paths structure
$script:Paths = @{
    Root = $serverManagerDir
    Logs = Join-Path $serverManagerDir "logs"
    Config = Join-Path $serverManagerDir "config"
    Scripts = Join-Path $serverManagerDir "Scripts"
    Modules = Join-Path $serverManagerDir "Modules"
}

if ($TempPath) {
    $script:Paths.Temp = $TempPath
} else {
    $script:Paths.Temp = Join-Path $serverManagerDir "temp"
}

# Ensure directories exist
foreach ($path in $script:Paths.Values) {
    if (-not (Test-Path $path)) {
        New-Item -Path $path -ItemType Directory -Force | Out-Null
    }
}

# Initialize logging
$script:LogFile = Join-Path $script:Paths.Logs "api-server.log"

# Enhanced logging with timestamp and proper level info
function Write-ApiLog {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [ValidateSet("INFO", "WARN", "ERROR", "DEBUG")]
        [string]$Level = "INFO"
    )
    
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $logEntry = "[$timestamp] [$Level] $Message"
        
        # Write to log file
        Add-Content -Path $script:LogFile -Value $logEntry -ErrorAction SilentlyContinue
        
        # Console output for interactive debugging
        $foregroundColor = switch ($Level) {
            "INFO" { "White" }
            "WARN" { "Yellow" }
            "ERROR" { "Red" }
            "DEBUG" { "Cyan" }
            default { "White" }
        }
        
        if ($VerbosePreference -eq 'Continue' -or $Level -eq "ERROR") {
            Write-Host $logEntry -ForegroundColor $foregroundColor
        }
    }
    catch {
        # Last resort error output
        Write-Host "Log error: $Message" -ForegroundColor Red
    }
}

# Import required modules
try {
    Write-ApiLog "Importing required modules..." -Level INFO
    
    # Import core modules
    $moduleImportResults = @()
    
    foreach ($module in @("Common", "Network", "ServerOperations", "Authentication")) {
        $modulePath = Join-Path $script:Paths.Modules "$module.psm1"
        
        if (Test-Path $modulePath) {
            try {
                Import-Module $modulePath -Force -ErrorAction Stop
                $moduleImportResults += "Success: $module"
                Write-ApiLog "Imported module: $module" -Level DEBUG
            }
            catch {
                $moduleImportResults += "Failed: $module - $($_.Exception.Message)"
                Write-ApiLog "Failed to import module $module : $($_.Exception.Message)" -Level ERROR
            }
        }
        else {
            $moduleImportResults += "Not found: $module"
            Write-ApiLog "Module not found: $module at $modulePath" -Level WARN
        }
    }
    
    Write-ApiLog "Module import completed: $($moduleImportResults -join ', ')" -Level DEBUG
}
catch {
    Write-ApiLog "Fatal error importing modules: $_" -Level ERROR
    exit 1
}

# Initialize authentication
$script:AuthConfig = @{
    RequireAuth = $true
    SessionTimeoutMinutes = 60
    Sessions = @{}
}

# Initialize performance metrics
$script:Metrics = @{
    RequestCount = 0
    RequestsPerSecond = 0
    AverageResponseTime = 0
    LastCalculationTime = [DateTime]::Now
    ResponseTimes = New-Object System.Collections.ArrayList
    Errors = 0
    SuccessRate = 100.0
}

# Start performance monitoring
Start-Job -ScriptBlock {
    param($LogFile)
    $ErrorActionPreference = 'Continue'
    
    try {
        function Write-PerfApiLog {
            param($Message, $Level)
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "$timestamp [$Level] [PerfMon] $Message" | Add-Content -Path $LogFile -ErrorAction SilentlyContinue
        }
        
        Write-PerfApiLog "Performance monitor started" "INFO"
        
        while ($true) {
            Start-Sleep -Seconds 60
            
            try {
                # Collect system metrics
                $cpuLoad = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
                $memoryAvailable = (Get-Counter '\Memory\Available MBytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
                $diskTime = (Get-Counter '\PhysicalDisk(_Total)\% Disk Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
                
                Write-PerfApiLog "System Metrics - CPU: $($cpuLoad)%, Memory Available: $($memoryAvailable) MB, Disk Time: $($diskTime)%" "INFO"
            }
            catch {
                Write-PerfApiLog "Error collecting performance metrics: $_" "ERROR"
            }
        }
    }
    catch {
        "$(Get-Date) [ERROR] Performance monitor failed: $_" | Add-Content -Path $LogFile -ErrorAction SilentlyContinue
    }
} -ArgumentList $script:LogFile | Out-Null

# Create HTTP Server and Configure URL Prefix
$prefixes = @(
    "http://localhost:$Port/",
    "http://+:$Port/" # Requires admin rights
)

# Create server object with simple API versioning support
$script:Server = New-Object -TypeName System.Net.HttpListener
$script:CurrentVersion = "1.0"
$serverStarted = $false

try {
    Write-ApiLog "Starting HTTP server on port $Port..." -Level INFO
    
    # Try to add URL prefixes with fallbacks
    $prefixAdded = $false
    foreach ($prefix in $prefixes) {
        try {
            $script:Server.Prefixes.Add($prefix)
            $prefixAdded = $true
            Write-ApiLog "Added URL prefix: $prefix" -Level INFO
            break
        }
        catch {
            Write-ApiLog "Failed to add URL prefix $prefix : $($_.Exception.Message)" -Level WARN
        }
    }
    
    if (-not $prefixAdded) {
        throw "Failed to add any URL prefix"
    }
    
    # Start the server
    $script:Server.Start()
    $serverStarted = $true
    Write-ApiLog "HTTP server started successfully on port $Port" -Level INFO
    
    # Write ready file for server discovery
    $readyFilePath = Join-Path $script:Paths.Temp "webserver.ready"
    $readyContent = @{
        status = "ready"
        port = $Port
        timestamp = Get-Date -Format "o"
    } | ConvertTo-Json
    
    Set-Content -Path $readyFilePath -Value $readyContent -Force
    Write-ApiLog "Ready file created at: $readyFilePath" -Level INFO
    
    # Load API routes
    Write-ApiLog "Loading API routes..." -Level INFO
    $routes = @()
    
    # Define built-in routes
    $routes += @{
        Method = 'GET'
        Path = '/health'
        Handler = {
            param($Request)
            @{ 
                status = "ok"
                version = $script:CurrentVersion
                timestamp = Get-Date -Format "o"
                uptime = [math]::Round(([DateTime]::Now - [System.Diagnostics.Process]::GetCurrentProcess().StartTime).TotalMinutes, 2)
            }
        }
    }
    
    # Version route for API version information
    $routes += @{
        Method = 'GET'
        Path = '/api/version'
        Handler = {
            param($Request)
            @{ 
                version = $script:CurrentVersion
                server = "Server Manager API"
                release_date = "2023-04-01"
            }
        }
    }
    
    # Metrics route for API statistics
    $routes += @{
        Method = 'GET'
        Path = '/api/metrics'
        Handler = {
            param($Request)
            
            # Update metrics
            $now = [DateTime]::Now
            $timeDiff = ($now - $script:Metrics.LastCalculationTime).TotalSeconds
            
            if ($timeDiff -gt 0) {
                $script:Metrics.RequestsPerSecond = [math]::Round($script:Metrics.RequestCount / $timeDiff, 2)
            }
            
            # Calculate average response time
            if ($script:Metrics.ResponseTimes.Count -gt 0) {
                $script:Metrics.AverageResponseTime = [math]::Round(($script:Metrics.ResponseTimes | Measure-Object -Average).Average, 2)
            }
            
            # Calculate success rate
            if ($script:Metrics.RequestCount -gt 0) {
                $successCount = $script:Metrics.RequestCount - $script:Metrics.Errors
                $script:Metrics.SuccessRate = [math]::Round(($successCount / $script:Metrics.RequestCount) * 100, 2)
            }
            
            # Reset metrics for next interval
            $script:Metrics.LastCalculationTime = $now
            $script:Metrics.RequestCount = 0
            $script:Metrics.ResponseTimes.Clear()
            $script:Metrics.Errors = 0
            
            return $script:Metrics
        }
    }
    
    # Load additional API routes from api-routes.ps1
    $routesScript = Join-Path $script:Paths.Scripts "api-routes.ps1"
    if (Test-Path $routesScript) {
        try {
            Write-ApiLog "Loading routes from: $routesScript" -Level INFO
            . $routesScript
            Write-ApiLog "Added $($routes.Count) routes from api-routes.ps1" -Level INFO
        }
        catch {
            Write-ApiLog "Failed to load routes from api-routes.ps1: $_" -Level ERROR
        }
    }
    
    # Default route for static content serving from www folder
    $wwwPath = Join-Path $script:Paths.Root "www"
    if (Test-Path $wwwPath) {
        Write-ApiLog "Static content folder found: $wwwPath" -Level INFO
    }
    
    # Process incoming requests
    Write-ApiLog "Ready to process requests" -Level INFO
    
    while ($script:Server.IsListening) {
        try {
            # Get the request context
            $context = $script:Server.GetContext()
            
            # Measure response time
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            
            # Increment request counter
            $script:Metrics.RequestCount++
            
            # Get request and response objects
            $request = $context.Request
            $response = $context.Response
            
            # Get request details
            $method = $request.HttpMethod
            $rawUrl = $request.RawUrl
            $path = ($rawUrl -split "\?")[0]
            
            # Log the request
            Write-ApiLog "Request: $method $rawUrl" -Level DEBUG
            
            # Process the request
            try {
                $handled = $false
                $statusCode = 200
                $contentType = "application/json"
                $allowCORS = $true
                
                # Check for API route match
                $route = $routes | Where-Object { $_.Method -eq $method -and $path -match "^$($_.Path)$" }
                
                if ($route) {
                    # API route matched
                    Write-ApiLog "Route matched: $($route.Path)" -Level DEBUG
                    
                    # Get route parameters from regex match
                    $routeParams = @{}
                    if ($path -match $route.Path) {
                        $matches.Keys | Where-Object { $_ -ne 0 } | ForEach-Object {
                            $routeParams[$_] = $matches[$_]
                        }
                    }
                    
                    # Parse request body for POST/PUT
                    $bodyData = $null
                    if ($method -in @('POST', 'PUT', 'PATCH')) {
                        try {
                            if ($request.ContentLength64 -gt 0) {
                                $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
                                $bodyContent = $reader.ReadToEnd()
                                
                                if ($request.ContentType -match "application/json") {
                                    $bodyData = $bodyContent | ConvertFrom-Json
                                }
                                else {
                                    # Try to parse as form data
                                    $bodyData = @{}
                                    $bodyContent -split "&" | ForEach-Object {
                                        $parts = $_ -split "="
                                        if ($parts.Count -eq 2) {
                                            $bodyData[$parts[0]] = [System.Web.HttpUtility]::UrlDecode($parts[1])
                                        }
                                    }
                                }
                            }
                        }
                        catch {
                            Write-ApiLog "Error parsing request body: $_" -Level ERROR
                        }
                    }
                    
                    # Invoke the route handler
                    $routeContext = @{
                        Parameters = $routeParams
                        QueryString = @{}
                        Body = $bodyData
                        RawRequest = $request
                    }
                    
                    # Parse query string
                    foreach ($key in $request.QueryString.AllKeys) {
                        if ($null -ne $key) {
                            $routeContext.QueryString[$key] = $request.QueryString[$key]
                        }
                    }
                    
                    # Execute route handler
                    $result = Invoke-Command -ScriptBlock $route.Handler -ArgumentList $routeContext
                    
                    if ($result -ne $null) {
                        # Convert result to JSON
                        $responseJson = $result | ConvertTo-Json -Depth 10
                        $responseBytes = [System.Text.Encoding]::UTF8.GetBytes($responseJson)
                        
                        # Send the response
                        $response.ContentType = $contentType
                        $response.ContentLength64 = $responseBytes.Length
                        $response.OutputStream.Write($responseBytes, 0, $responseBytes.Length)
                        
                        $handled = $true
                    }
                }
                
                # If not handled yet, check for static content
                if (-not $handled -and $method -eq "GET") {
                    # Handle root URL
                    if ($path -eq "/" -and -not $NoRedirect) {
                        $path = "/dashboard.html"
                    }
                    
                    # Clean up the path
                    $path = $path.TrimStart("/")
                    
                    # Handle static content
                    $filePath = Join-Path $wwwPath $path
                    
                    if (Test-Path $filePath -PathType Leaf) {
                        # Determine content type
                        $contentType = switch ([System.IO.Path]::GetExtension($filePath)) {
                            ".html" { "text/html; charset=utf-8" }
                            ".htm"  { "text/html; charset=utf-8" }
                            ".js"   { "application/javascript; charset=utf-8" }
                            ".css"  { "text/css; charset=utf-8" }
                            ".png"  { "image/png" }
                            ".jpg"  { "image/jpeg" }
                            ".jpeg" { "image/jpeg" }
                            ".gif"  { "image/gif" }
                            ".svg"  { "image/svg+xml" }
                            ".json" { "application/json; charset=utf-8" }
                            ".txt"  { "text/plain; charset=utf-8" }
                            default { "application/octet-stream" }
                        }
                        
                        # Send the file content
                        $fileBytes = [System.IO.File]::ReadAllBytes($filePath)
                        $response.ContentType = $contentType
                        $response.ContentLength64 = $fileBytes.Length
                        $response.OutputStream.Write($fileBytes, 0, $fileBytes.Length)
                        
                        $handled = $true
                        Write-ApiLog "Served static file: $filePath" -Level DEBUG
                    }
                }
                
                # Handle 404 Not Found
                if (-not $handled) {
                    $statusCode = 404
                    $responseJson = @{ error = "Not Found"; path = $path; method = $method } | ConvertTo-Json
                    $responseBytes = [System.Text.Encoding]::UTF8.GetBytes($responseJson)
                    
                    $response.StatusCode = $statusCode
                    $response.ContentType = "application/json"
                    $response.ContentLength64 = $responseBytes.Length
                    $response.OutputStream.Write($responseBytes, 0, $responseBytes.Length)
                    
                    Write-ApiLog "404 Not Found: $method $path" -Level WARN
                }
                
                # Add CORS headers if needed
                if ($allowCORS) {
                    $response.Headers.Add("Access-Control-Allow-Origin", "*")
                    $response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                    $response.Headers.Add("Access-Control-Allow-Headers", "Content-Type, Authorization")
                }
                
                # Add server header
                $response.Headers.Add("Server", "ServerManager/$($script:CurrentVersion)")
                
                # Complete response
                $response.Close()
                
                # Record response time
                $stopwatch.Stop()
                $responseTime = $stopwatch.ElapsedMilliseconds
                $null = $script:Metrics.ResponseTimes.Add($responseTime)
                
                Write-ApiLog "Response: $statusCode (${responseTime}ms)" -Level DEBUG
            }
            catch {
                # Handle exception
                $script:Metrics.Errors++
                
                $errorMessage = "Request processing error: $_"
                Write-ApiLog $errorMessage -Level ERROR
                Write-ApiLog $_.ScriptStackTrace -Level ERROR
                
                # Try to send error response
                try {
                    $statusCode = 500
                    $responseJson = @{ 
                        error = "Internal Server Error"
                        message = $_.Exception.Message
                    } | ConvertTo-Json
                    
                    $responseBytes = [System.Text.Encoding]::UTF8.GetBytes($responseJson)
                    
                    $response.StatusCode = $statusCode
                    $response.ContentType = "application/json"
                    $response.ContentLength64 = $responseBytes.Length
                    $response.OutputStream.Write($responseBytes, 0, $responseBytes.Length)
                    
                    # Complete response
                    $response.Close()
                }
                catch {
                    Write-ApiLog "Failed to send error response: $_" -Level ERROR
                }
            }
        }
        catch [System.Net.HttpListenerException] {
            # Listener was closed/stopped
            if ($_.Exception.ErrorCode -eq 995) { # Error code for operation aborted
                Write-ApiLog "HTTP Listener stopped" -Level INFO
                break
            }
            else {
                Write-ApiLog "HTTP Listener error: $($_)" -Level ERROR
            }
        }
        catch {
            # Other error
            Write-ApiLog "Critical error: $($_)" -Level ERROR
            Write-ApiLog $_.ScriptStackTrace -Level ERROR
        }
    }
}
catch {
    Write-ApiLog "Fatal error: $_" -Level ERROR
    Write-ApiLog $_.ScriptStackTrace -Level ERROR
}
finally {
    # Clean up
    if ($serverStarted) {
        try {
            $script:Server.Stop()
            $script:Server.Close()
            Write-ApiLog "HTTP server stopped" -Level INFO
        }
        catch {
            Write-ApiLog "Error stopping server: $_" -Level ERROR
        }
    }
    
    # Clean up ready file
    $readyFilePath = Join-Path $script:Paths.Temp "webserver.ready"
    if (Test-Path $readyFilePath) {
        try {
            Remove-Item -Path $readyFilePath -Force
            Write-ApiLog "Ready file removed" -Level INFO
        }
        catch {
            Write-ApiLog "Error removing ready file: $_" -Level ERROR
        }
    }
}

using module "..\Modules\WebSocketServer.psm1"

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

# Add logging setup
$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $logDir "api-server.log"

function Write-ApiLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )
    try {
        if ($Level -eq "ERROR" -or $Level -eq "DEBUG") {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "$timestamp [$Level] - $Message" | Add-Content -Path $logFile -ErrorAction Stop
        }
    }
    catch {
        # If logging fails, try Windows Event Log
        try {
            Write-EventLog -LogName Application -Source "ServerManager" -EventId 1001 -EntryType Error -Message "Failed to write to log file: $Message"
        }
        catch { }
    }
}

# Add port verification before starting WebSocket server
$wsPort = 8081
$portInUse = Get-NetTCPConnection -LocalPort $wsPort -ErrorAction SilentlyContinue
if ($portInUse) {
    throw "WebSocket port $wsPort is already in use by process: $((Get-Process -Id $portInUse.OwningProcess).ProcessName)"
}

$webSocketServer = [WebSocketServer]::new($wsPort)
$connectedClients = @()

function Broadcast-ServerUpdate {
    param($UpdateData)
    
    $jsonData = $UpdateData | ConvertTo-Json
    foreach ($client in $connectedClients) {
        try {
            $client.SendMessage($jsonData)
        } catch {
            Write-Host "Failed to send to client: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# Event handlers for WebSocket
$webSocketServer.OnClientConnect = {
    param($Client)
    $connectedClients += $Client
    Write-ApiLog "Client connected: $($Client.Id)" -Level DEBUG
}

$webSocketServer.OnClientDisconnect = {
    param($Client)
    $connectedClients = $connectedClients | Where-Object { $_ -ne $Client }
    Write-ApiLog "Client disconnected: $($Client.Id)" -Level DEBUG
}

# Add error handling and logging
try {
    $webSocketServer.Start()
    Write-ApiLog "WebSocket server started successfully on port $wsPort" -Level DEBUG
}
catch {
    Write-ApiLog "Failed to start WebSocket server: $($_.Exception.Message)" -Level ERROR
    throw
}
