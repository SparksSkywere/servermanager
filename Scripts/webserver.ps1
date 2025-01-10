$ErrorActionPreference = 'Stop'

# Import required modules
$modulePath = if ([System.IO.Path]::IsPathRooted($PSScriptRoot)) {
    Join-Path $PSScriptRoot "..\Modules\ServerManager"
} else {
    $rootDir = Split-Path (Split-Path $PSScriptRoot)
    Join-Path $rootDir "Modules\ServerManager"
}
Import-Module $modulePath -Force

# Add at the start after imports
$logPath = Join-Path $serverManagerDir "logs\webserver.log"
$authLogPath = Join-Path $serverManagerDir "logs\auth.log"

function Write-AuthLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Add-Content -Path $authLogPath
}

function Write-ServerLog {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp [$Level] - $Message" | Add-Content -Path $logPath
}

# Get registry paths
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

$authConfigPath = Join-Path $serverManagerDir "config\auth.xml"
if (-not (Test-Path $authConfigPath)) {
    throw "Authentication configuration not found. Please run Set-AuthConfig.ps1 first."
}

Write-Host "Setting up HTTP listener..." -ForegroundColor Cyan
$http = [System.Net.HttpListener]::new()
$http.Prefixes.Add("http://localhost:8080/")

# Add MIME type mapping
$mimeTypes = @{
    ".html" = "text/html"
    ".css"  = "text/css"
    ".js"   = "application/javascript"
    ".json" = "application/json"
    ".png"  = "image/png"
    ".jpg"  = "image/jpeg"
    ".gif"  = "image/gif"
    ".svg"  = "image/svg+xml"
    ".psm1" = "text/plain"
    ".ps1"  = "text/plain"
    ".txt"  = "text/plain"
}

function Get-MimeType($FilePath) {
    $extension = [System.IO.Path]::GetExtension($FilePath)
    $mimeType = $mimeTypes[$extension.ToLower()]
    if ($mimeType) {
        return $mimeType
    }
    return "application/octet-stream"
}

function Test-LDAPCredentials {
    param($Username, $Password)
    try {
        $ldapPath = "LDAP://" + $ldapConfig.LDAPServer
        
        # First validate using service account
        $servicePassword = $ldapConfig.EncryptedPassword | ConvertTo-SecureString
        $serviceCred = New-Object System.Management.Automation.PSCredential($ldapConfig.ServicePrincipal, $servicePassword)
        $serviceEntry = New-Object System.DirectoryServices.DirectoryEntry($ldapPath, $serviceCred.UserName, $serviceCred.GetNetworkCredential().Password)
        
        if ($serviceEntry.name -eq $null) {
            throw "Service account authentication failed"
        }

        # Then validate user credentials
        $userEntry = New-Object System.DirectoryServices.DirectoryEntry($ldapPath, "$Username@$($ldapConfig.Domain)", $Password)
        return $userEntry.name -ne $null
    }
    catch {
        Write-Host "LDAP authentication error: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Test-FileBasedCredentials {
    param(
        [string]$Username,
        [SecureString]$Password
    )
    try {
        $usersFile = Join-Path $serverManagerDir "config\users.xml"
        
        if (-not (Test-Path $usersFile)) {
            Write-ServerLog "Users file not found: $usersFile" -Level "ERROR"
            throw "Authentication database not found"
        }

        $users = Import-Clixml -Path $usersFile
        $user = $users | Where-Object { $_.Username -eq $Username }

        if (-not $user) {
            Write-AuthLog "Failed login attempt - User not found: $Username"
            Start-Sleep -Seconds 2  # Prevent timing attacks
            return $false
        }

        # Import security module
        Import-Module (Join-Path $serverManagerDir "Modules\ServerManager\Security.psm1") -Force
        
        # Verify password using stored salt
        $hash = Get-SecureHash -SecurePassword $Password -Salt $user.Salt
        $authenticated = $user.PasswordHash -eq $hash

        if ($authenticated) {
            Write-AuthLog "Successful login: $Username"
        } else {
            Write-AuthLog "Failed login attempt - Invalid password: $Username"
            Start-Sleep -Seconds 2  # Prevent timing attacks
        }

        return $authenticated
    }
    catch {
        Write-ServerLog "Authentication error: $($_.Exception.Message)" -Level "ERROR"
        throw "Authentication service error"
    }
}

function Test-Credentials {
    param(
        [string]$Username,
        [string]$Password,
        [string]$AuthType
    )
    
    Write-Host "Testing credentials for user '$Username' using auth type '$AuthType'" -ForegroundColor Cyan
    
    try {
        # Convert plain password to SecureString
        $securePassword = ConvertTo-SecureString $Password -AsPlainText -Force
        
        switch ($AuthType) {
            "Local" {
                $credential = New-Object System.Management.Automation.PSCredential($Username, $securePassword)
                # Test local credentials
                $result = Start-Process -FilePath "cmd.exe" -ArgumentList "/c echo Test" -Credential $credential -WindowStyle Hidden
                Write-Host "Local authentication result: $result" -ForegroundColor Yellow
                return $true
            }
            "LDAP" {
                return Test-LDAPCredentials -Username $Username -Password $Password
            }
            "File" {
                return Test-FileBasedCredentials -Username $Username -Password $securePassword
            }
            default {
                Write-Host "Unsupported authentication type: $AuthType" -ForegroundColor Red
                return $false
            }
        }
    }
    catch {
        Write-Host "Authentication error: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    finally {
        if ($securePassword) { $securePassword.Dispose() }
    }
}

function Get-RequestBody($Request) {
    try {
        $length = [int]$Request.ContentLength64
        $buffer = [byte[]]::new($length)
        [void]$Request.InputStream.Read($buffer, 0, $length)
        $body = [System.Text.Encoding]::UTF8.GetString($buffer)
        $jsonBody = $body | ConvertFrom-Json

        # Convert password to SecureString immediately
        if ($jsonBody.password) {
            $jsonBody.password = ConvertTo-SecureString $jsonBody.password -AsPlainText -Force
        }

        return $jsonBody
    }
    catch {
        Write-ServerLog "Error processing request body: $($_.Exception.Message)" -Level "ERROR"
        throw
    }
}

function Get-EnabledAuthMethods {
    try {
        Write-Host "Loading auth config..." -ForegroundColor Cyan
        $config = Get-AuthConfig
        Write-Host "Raw auth config: $($config | ConvertTo-Json)" -ForegroundColor Yellow
        
        $methods = @()
        
        # Always include Local Windows auth as fallback
        $methods += @{
            type = "Local"
            name = "Local Windows"
            isDefault = $true
        }
        
        Write-Host "Final auth methods: $($methods | ConvertTo-Json)" -ForegroundColor Green
        return $methods
    }
    catch {
        Write-Host "Error in Get-EnabledAuthMethods: $($_.Exception.Message)" -ForegroundColor Red
        # Return default Local auth even on error
        return @(@{
            type = "Local"
            name = "Local Windows"
            isDefault = $true
        })
    }
}

try {
    # Before starting HTTP listener, verify port
    $portInUse = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
    if ($portInUse) {
        throw "Port 8080 is already in use by process: $((Get-Process -Id $portInUse.OwningProcess).ProcessName)"
    }

    Write-Host "Starting HTTP listener..." -ForegroundColor Cyan
    $http.Start()
    Write-Host "HTTP listener started successfully" -ForegroundColor Green
    
    while ($http.IsListening) {
        $context = $http.GetContext()
        $request = $context.Request
        $response = $context.Response
        
        # Set CORS headers
        $response.Headers.Add("Access-Control-Allow-Origin", "*")
        $response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        $response.Headers.Add("Access-Control-Allow-Headers", "Content-Type")

        if ($request.HttpMethod -eq "OPTIONS") {
            $response.StatusCode = 200
            $response.Close()
            continue
        }

        # Handle authentication
        if ($request.Url.LocalPath -eq "/api/auth/methods") {
            try {
                Write-Host "Auth methods request received" -ForegroundColor Cyan
                $methods = Get-EnabledAuthMethods
                $jsonResponse = $methods | ConvertTo-Json -Depth 10
                Write-Host "Sending response: $jsonResponse" -ForegroundColor Green
                $buffer = [System.Text.Encoding]::UTF8.GetBytes($jsonResponse)
                $response.ContentType = "application/json"
                $response.StatusCode = 200
                $response.ContentLength64 = $buffer.Length
                $response.OutputStream.Write($buffer, 0, $buffer.Length)
            }
            catch {
                Write-Host "Error serving auth methods: $($_.Exception.Message)" -ForegroundColor Red
                $response.StatusCode = 500
                $errorResponse = @{
                    error = "Failed to get authentication methods"
                    details = $_.Exception.Message
                } | ConvertTo-Json
                $buffer = [System.Text.Encoding]::UTF8.GetBytes($errorResponse)
                $response.ContentType = "application/json"
                $response.ContentLength64 = $buffer.Length
                $response.OutputStream.Write($buffer, 0, $buffer.Length)
            }
        }
        elseif ($request.Url.LocalPath -eq "/api/auth") {
            try {
                Write-Host "Received authentication request" -ForegroundColor Cyan
                $body = Get-RequestBody $request
                Write-Host "Auth request for user: $($body.username) with type: $($body.authType)" -ForegroundColor Yellow
                
                # Convert password to string just for the test (will be converted back to SecureString inside Test-Credentials)
                $authenticated = Test-Credentials -Username $body.username `
                                       -Password ([Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($body.password))) `
                                       -AuthType $body.authType
                
                # Clear sensitive data
                if ($body.password) { $body.password.Dispose() }
                
                # Rest of the authentication handling code...
                if ($authenticated) {
                    Write-Host "Authentication successful for user: $($body.username)" -ForegroundColor Green
                    $token = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("$($body.username):$(Get-Date)"))
                    $jsonResponse = @{
                        token = $token
                        username = $body.username
                        message = "Authentication successful"
                    } | ConvertTo-Json
                    
                    $buffer = [System.Text.Encoding]::UTF8.GetBytes($jsonResponse)
                    $response.ContentType = "application/json"
                    $response.StatusCode = 200
                    $response.ContentLength64 = $buffer.Length
                    $response.OutputStream.Write($buffer, 0, $buffer.Length)
                }
                else {
                    Write-Host "Authentication failed for user: $($body.username)" -ForegroundColor Red
                    $response.StatusCode = 401
                    $errorResponse = @{
                        message = "Invalid credentials"
                    } | ConvertTo-Json
                    $buffer = [System.Text.Encoding]::UTF8.GetBytes($errorResponse)
                    $response.ContentType = "application/json"
                    $response.ContentLength64 = $buffer.Length
                    $response.OutputStream.Write($buffer, 0, $buffer.Length)
                }
            }
            catch {
                Write-Host "Error during authentication: $($_.Exception.Message)" -ForegroundColor Red
                $response.StatusCode = 500
                $errorResponse = @{
                    message = "Authentication error: $($_.Exception.Message)"
                } | ConvertTo-Json
                $buffer = [System.Text.Encoding]::UTF8.GetBytes($errorResponse)
                $response.ContentType = "application/json"
                $response.ContentLength64 = $buffer.Length
                $response.OutputStream.Write($buffer, 0, $buffer.Length)
            }
            finally {
                # Ensure cleanup of any remaining sensitive data
                if ($body -and $body.password) { $body.password.Dispose() }
            }
        }
        else {
            # Serve static files with proper MIME types
            $filePath = Join-Path $PSScriptRoot "..\www"
            $requestedPath = Join-Path $filePath $request.Url.LocalPath.TrimStart('/')
            
            if ($request.Url.LocalPath -eq "/") {
                $requestedPath = Join-Path $filePath "login.html"
            }
            
            if (Test-Path $requestedPath -PathType Leaf) {
                $mimeType = Get-MimeType $requestedPath
                $response.ContentType = $mimeType
                
                # Binary read for all file types
                $content = [System.IO.File]::ReadAllBytes($requestedPath)
                $response.ContentLength64 = $content.Length
                $response.OutputStream.Write($content, 0, $content.Length)
            }
            else {
                $response.StatusCode = 404
            }
        }
        
        $response.Close()
    }
}
catch {
    Write-Host "Error in web server: $($_.Exception.Message)" -ForegroundColor Red
    throw
}
finally {
    if ($http -and $http.IsListening) {
        $http.Stop()
        $http.Close()
    }
}
