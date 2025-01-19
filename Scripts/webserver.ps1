$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'

try {
    # Get registry and paths
    $registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
    $serverManagerDir = (Get-ItemProperty -Path $registryPath -ErrorAction Stop).servermanagerdir
    $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
    
    # Import required modules
    $modulesPath = Join-Path $serverManagerDir "Modules"
    Import-Module (Join-Path $modulesPath "WebSocketServer.psm1") -Force
    Import-Module (Join-Path $modulesPath "Network.psm1") -Force
    
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
    Write-ServerLog "Loaded required modules" -Level "INFO"

    # Initialize WebSocket server
    try {
        # First, check if port is already in use
        $testClient = New-Object System.Net.Sockets.TcpClient
        try {
            $testClient.Connect("localhost", 8081)
            throw "Port 8081 is already in use"
        }
        catch [System.Net.Sockets.SocketException] {
            # Port is available
            Write-ServerLog "Port 8081 is available" -Level "INFO"
        }
        finally {
            $testClient.Dispose()
        }

        # Create WebSocket ready flag with port info
        $wsReadyFile = Join-Path $env:TEMP "websocket_ready.flag"
        $wsConfig = @{
            status = "ready"
            port = 8081
            timestamp = Get-Date -Format "o"
        }
        $wsConfig | ConvertTo-Json | Out-File -FilePath $wsReadyFile -Force
        Write-ServerLog "WebSocket ready flag created" -Level "INFO"

        # Create TCP listener for WebSocket
        $wsListener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, 8081)
        $wsListener.Start()
        Write-ServerLog "WebSocket listener started on port 8081" -Level "INFO"

        # Create cancellation token
        $cancelSource = New-Object System.Threading.CancellationTokenSource

        # Modified WebSocket task creation
        try {
            $taskFactory = [System.Threading.Tasks.Task]::Factory
            
            # Create action with proper signature
            $action = [Action[object]] {
                param($state)
                
                try {
                    while (-not $cancelSource.Token.IsCancellationRequested) {
                        if ($wsListener.Pending()) {
                            $client = $wsListener.AcceptTcpClient()
                            Write-ServerLog "New WebSocket connection accepted" -Level "INFO"
                            
                            # Handle WebSocket upgrade
                            $stream = $client.GetStream()
                            $buffer = New-Object byte[] 8192
                            $encoding = [System.Text.Encoding]::UTF8
                            $requestBuilder = New-Object System.Text.StringBuilder
                            
                            # Read the complete HTTP request
                            do {
                                $bytesRead = $stream.Read($buffer, 0, $buffer.Length)
                                if ($bytesRead -gt 0) {
                                    $requestBuilder.Append($encoding.GetString($buffer, 0, $bytesRead)) | Out-Null
                                }
                            } while ($stream.DataAvailable)
                            
                            $request = $requestBuilder.ToString()
                            Write-ServerLog "Received WebSocket request" -Level "INFO"
                            
                            if ($request -match "Upgrade: websocket") {
                                # Extract WebSocket key
                                $key = [regex]::Match($request, "Sec-WebSocket-Key: (.+)").Groups[1].Value.Trim()
                                Write-ServerLog "WebSocket key: $key" -Level "INFO"
                                
                                if ($key) {
                                    # Calculate accept key
                                    $guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                                    $concatenated = $key + $guid
                                    $sha1 = [System.Security.Cryptography.SHA1]::Create()
                                    $hash = $sha1.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($concatenated))
                                    $base64 = [Convert]::ToBase64String($hash)
                                    
                                    # Send WebSocket upgrade response
                                    $response = "HTTP/1.1 101 Switching Protocols`r`n"
                                    $response += "Upgrade: websocket`r`n"
                                    $response += "Connection: Upgrade`r`n"
                                    $response += "Sec-WebSocket-Accept: $base64`r`n"
                                    $response += "Sec-WebSocket-Protocol: chat`r`n`r`n"
                                    
                                    $responseBytes = [System.Text.Encoding]::UTF8.GetBytes($response)
                                    $stream.Write($responseBytes, 0, $responseBytes.Length)
                                    $stream.Flush()
                                    
                                    Write-ServerLog "WebSocket upgrade completed" -Level "INFO"
                                    
                                    # Handle WebSocket communication
                                    try {
                                        while (-not $cancelSource.Token.IsCancellationRequested) {
                                            if ($stream.DataAvailable) {
                                                $header = New-Object byte[] 2
                                                $count = $stream.Read($header, 0, 2)
                                                
                                                if ($count -eq 2) {
                                                    $opcode = $header[0] -band 0x0F
                                                    $length = $header[1] -band 0x7F
                                                    
                                                    if ($opcode -eq 8) {
                                                        # Close frame received
                                                        break
                                                    }
                                                    
                                                    # Send ping response every 30 seconds
                                                    if ((Get-Date).Second % 30 -eq 0) {
                                                        $pingFrame = [byte[]]@(0x89, 0x00) # WebSocket ping frame
                                                        $stream.Write($pingFrame, 0, 2)
                                                        $stream.Flush()
                                                    }
                                                    
                                                    # Echo message back
                                                    $messageData = @{
                                                        type = "echo"
                                                        timestamp = Get-Date -Format "o"
                                                        message = "Connection active"
                                                    } | ConvertTo-Json
                                                    
                                                    $messageBytes = [System.Text.Encoding]::UTF8.GetBytes($messageData)
                                                    $stream.WriteByte(0x81) # Text frame
                                                    $stream.WriteByte($messageBytes.Length)
                                                    $stream.Write($messageBytes, 0, $messageBytes.Length)
                                                    $stream.Flush()
                                                }
                                            }
                                            Start-Sleep -Milliseconds 100
                                        }
                                    }
                                    catch {
                                        Write-ServerLog "WebSocket communication error: $($_.Exception.Message)" -Level "ERROR"
                                    }
                                }
                            }
                            
                            $client.Close()
                        }
                        Start-Sleep -Milliseconds 100
                    }
                }
                catch {
                    Write-ServerLog "WebSocket handling error: $($_.Exception.Message)" -Level "ERROR"
                }
            }

            # Start the task with proper parameters
            $task = $taskFactory.StartNew(
                $action,                  # The action to run
                $null,                    # State object (null in this case)
                $cancelSource.Token,      # Cancellation token
                [System.Threading.Tasks.TaskCreationOptions]::LongRunning,
                [System.Threading.Tasks.TaskScheduler]::Default
            )

            Write-ServerLog "WebSocket task started successfully" -Level "INFO"
        }
        catch {
            Write-ServerLog "Failed to start WebSocket task: $($_.Exception.Message)" -Level "ERROR"
            throw
        }

        # Set up HTTP listener on original port
        try {
            $null = netsh http show urlacl url=http://+:8080/
        }
        catch {
            Write-ServerLog "Adding URL reservation..." -Level "WARN"
            $null = netsh http add url=http://+:8080/ user=Everyone
        }
        
        $http = [System.Net.HttpListener]::new()
        $http.Prefixes.Add("http://+:8080/")
        
        Write-ServerLog "Starting HTTP listener..."
        $http.Start()
        
        # Signal that HTTP server is ready
        $httpReadyFile = Join-Path $env:TEMP "webserver_ready.flag"
        "ready" | Out-File -FilePath $httpReadyFile -Force
        Write-ServerLog "HTTP Server is ready!"

        # Define web root directory
        $webRoot = Join-Path $serverManagerDir "www"
        Write-ServerLog "Web root directory: $webRoot"

        # Create www directory if it doesn't exist
        if (-not (Test-Path $webRoot)) {
            New-Item -Path $webRoot -ItemType Directory -Force | Out-Null
            # Create a default index.html
            @"
<!DOCTYPE html>
<html>
<head>
    <title>Server Manager</title>
</head>
<body>
    <h1>Server Manager</h1>
    <p>Server is running!</p>
</body>
</html>
"@ | Out-File -FilePath (Join-Path $webRoot "index.html") -Encoding UTF8
        }

        # Main request handling loop
        while ($http.IsListening) {
            try {
                $context = $http.GetContext()
                $request = $context.Request
                $response = $context.Response
                
                Write-ServerLog "Received request: $($request.HttpMethod) $($request.Url.LocalPath)"

                # Handle different request types
                if ($request.Url.LocalPath -match "^/api/") {
                    $apiEndpoint = $request.Url.LocalPath
                    Write-ServerLog "API Request: $($request.HttpMethod) $apiEndpoint"
                    
                    switch -Regex ($apiEndpoint) {
                        "/api/auth/methods" {
                            $authMethods = @(
                                @{
                                    type = "Local"
                                    name = "Windows Authentication"
                                    isDefault = $true
                                }
                            )
                            $responseData = $authMethods | ConvertTo-Json
                            $response.ContentType = "application/json"
                        }
                        
                        "/api/auth" {
                            if ($request.HttpMethod -eq 'POST') {
                                Write-ServerLog "Processing authentication request"
                                $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
                                $body = $reader.ReadToEnd()
                                $credentials = $body | ConvertFrom-Json
                                
                                Write-ServerLog "Authenticating user: $($credentials.username)"
                                
                                try {
                                    # Load users file
                                    $usersFile = Join-Path $serverManagerDir "config\users.xml"
                                    if (-not (Test-Path $usersFile)) {
                                        throw "Users database not found"
                                    }
                                    
                                    $users = Import-Clixml -Path $usersFile
                                    $user = $users | Where-Object { $_.Username -eq $credentials.username }
                                    
                                    if (-not $user) {
                                        throw "User not found"
                                    }
                                    
                                    # Import security module for password verification
                                    Import-Module (Join-Path $serverManagerDir "Modules\Security.psm1") -Force
                                    
                                    # Convert password and verify
                                    $securePassword = ConvertTo-SecureString $credentials.password -AsPlainText -Force
                                    $hash = Get-SecureHash -SecurePassword $securePassword -Salt $user.Salt
                                    
                                    if ($hash -eq $user.PasswordHash) {
                                        Write-ServerLog "Authentication successful for user: $($credentials.username)"
                                        $token = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("$($credentials.username):$(Get-Date -Format 'o')"))
                                        $responseData = @{
                                            success = $true
                                            token = $token
                                            username = $credentials.username
                                            isAdmin = $user.IsAdmin
                                            redirectUrl = "/dashboard.html"
                                        } | ConvertTo-Json
                                        $response.StatusCode = 200
                                    } else {
                                        throw "Invalid password"
                                    }
                                }
                                catch {
                                    Write-ServerLog "Authentication failed for user: $($credentials.username) - $($_.Exception.Message)" -Level "ERROR"
                                    $responseData = @{
                                        success = $false
                                        error = "Invalid credentials"
                                    } | ConvertTo-Json
                                    $response.StatusCode = 401
                                }
                                finally {
                                    if ($securePassword) {
                                        $securePassword.Dispose()
                                    }
                                }
                                
                                $response.ContentType = "application/json"
                            }
                        }
                        
                        default {
                            $response.StatusCode = 404
                            $responseData = @{
                                error = "API endpoint not found"
                            } | ConvertTo-Json
                            $response.ContentType = "application/json"
                        }
                    }
                    
                    $buffer = [System.Text.Encoding]::UTF8.GetBytes($responseData)
                    $response.ContentLength64 = $buffer.Length
                    $response.OutputStream.Write($buffer, 0, $buffer.Length)
                }
                else {
                    # Serve static files
                    $localPath = $request.Url.LocalPath.TrimStart('/')
                    if ([string]::IsNullOrEmpty($localPath)) {
                        $localPath = "login.html"
                    }
                    
                    $filePath = Join-Path $webRoot $localPath
                    
                    if (Test-Path $filePath -PathType Leaf) {
                        $extension = [System.IO.Path]::GetExtension($filePath)
                        $contentType = switch ($extension) {
                            ".html" { "text/html" }
                            ".css"  { "text/css" }
                            ".js"   { "application/javascript" }
                            ".json" { "application/json" }
                            ".png"  { "image/png" }
                            ".jpg"  { "image/jpeg" }
                            default { "application/octet-stream" }
                        }
                        
                        $content = [System.IO.File]::ReadAllBytes($filePath)
                        $response.ContentType = $contentType
                        $response.ContentLength64 = $content.Length
                        $response.OutputStream.Write($content, 0, $content.Length)
                    }
                    else {
                        $response.StatusCode = 404
                        $content = "404 - File not found"
                        $buffer = [System.Text.Encoding]::UTF8.GetBytes($content)
                        $response.ContentLength64 = $buffer.Length
                        $response.OutputStream.Write($buffer, 0, $buffer.Length)
                    }
                }
                
                $response.Close()
            }
            catch {
                Write-ServerLog "Error handling request: $($_.Exception.Message)" -Level "ERROR"
            }
        }

        Write-ServerLog "Shutting down server..." -Level "INFO"
        
        # Cleanup
        if ($http -ne $null) {
            if ($http.IsListening) {
                $http.Stop()
            }
            $http.Close()
            $http.Dispose()
        }
        
        if (Test-Path $httpReadyFile) {
            Remove-Item $httpReadyFile -Force
        }
        
        Write-ServerLog "Server shutdown complete" -Level "INFO"
        exit 0  # Exit with success code
    }
    catch {
        Write-ServerLog "Fatal error: $($_.Exception.Message)" -Level "ERROR"
        Write-ServerLog $_.ScriptStackTrace -Level "ERROR"
        exit 1
    }
}
finally {
    if ($wsListener) {
        $wsListener.Stop()
    }
    if ($cancelSource) {
        $cancelSource.Cancel()
        $cancelSource.Dispose()
    }
    # Remove flag files
    if (Test-Path $wsReadyFile) {
        Remove-Item $wsReadyFile -Force
    }
    if (Test-Path $httpReadyFile) {
        Remove-Item $httpReadyFile -Force
    }
}
