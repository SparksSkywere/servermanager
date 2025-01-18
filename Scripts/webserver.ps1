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
        $null = netsh http add url=http://+:8080/ user=Everyone
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
        
        if (Test-Path $flagFile) {
            Remove-Item $flagFile -Force
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
catch {
    Write-ServerLog "Fatal error: $($_.Exception.Message)" -Level "ERROR"
    Write-ServerLog $_.ScriptStackTrace -Level "ERROR"
    exit 1
}
