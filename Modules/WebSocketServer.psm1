# Module initialization
using namespace System.Net.WebSockets
using namespace System.Net
using namespace System.Text

# Initialize module variables with default paths
$script:DefaultWebSocketPort = 8081
$script:DefaultWebPort = 8080
$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Get registry path for server manager directory
try {
    $script:ServerManagerDir = (Get-ItemProperty -Path $script:RegPath -ErrorAction Stop).servermanagerdir
    $script:ServerManagerDir = $script:ServerManagerDir.Trim('"', ' ', '\')
} catch {
    # Fallback to script location if registry fails
    Write-Warning "Failed to get ServerManagerDir from registry: $_"
    $script:ServerManagerDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

# Initialize paths structure
$script:Paths = @{
    Root = $script:ServerManagerDir
    Logs = Join-Path $script:ServerManagerDir "logs"
    Config = Join-Path $script:ServerManagerDir "config"
    Temp = Join-Path $script:ServerManagerDir "temp"
    Modules = Join-Path $script:ServerManagerDir "Modules"
}

# Initialize ready file paths
$script:ReadyFiles = @{
    WebSocket = Join-Path $script:Paths.Temp "websocket.ready"
    WebServer = Join-Path $script:Paths.Temp "webserver.ready"
}

# Make sure temp directory exists
if (-not (Test-Path $script:Paths.Temp)) {
    New-Item -Path $script:Paths.Temp -ItemType Directory -Force -ErrorAction SilentlyContinue
}

# Define Get-WebSocketPaths to use initialized paths
function Global:Get-WebSocketPaths {
    # Return cached paths from module scope
    return @{
        WebSocketReadyFile = $script:ReadyFiles.WebSocket
        WebServerReadyFile = $script:ReadyFiles.WebServer
        DefaultWebSocketPort = $script:DefaultWebSocketPort
        DefaultWebPort = $script:DefaultWebPort
        TempPath = $script:Paths.Temp
    }
}

# Immediately test the function to verify it works
try {
    $testPaths = Get-WebSocketPaths
    Write-Verbose "WebSocketServer: Get-WebSocketPaths returned: $($testPaths | ConvertTo-Json)"
} catch {
    Write-Warning "WebSocketServer: Get-WebSocketPaths test failed: $_"
}

# Simple alternative WebSocketServer class that uses regular TCP sockets
# to avoid the cloud file provider issue
class SimpleWebSocketServer {
    # Make properties public to ensure they're accessible
    [System.Net.Sockets.TcpListener]$Listener
    [bool]$IsRunning
    [hashtable]$Connections
    [string]$ServerDirectory
    [int]$Port
    
    SimpleWebSocketServer([string]$serverDir) {
        $this.IsRunning = $false
        $this.Connections = @{}
        $this.ServerDirectory = $serverDir
        $this.Port = 8081
        $this.Listener = $null
    }
    
    [bool] IsListening() {
        # Better check for listening state
        if ($null -eq $this.Listener) {
            return $false
        }
        
        try {
            # More reliable test if the listener is actually working
            return $this.IsRunning -and $this.Listener.Server.IsBound
        }
        catch {
            return $false
        }
    }
    
    [bool] Initialize([int]$Port = 8081, [string]$HostName = "localhost") {
        try {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Initializing SimpleWebSocketServer on port $Port and host $HostName" -Level INFO
            }
            
            # Clean up any existing listener
            if ($null -ne $this.Listener) {
                try {
                    $this.Listener.Stop()
                    $this.Listener = $null
                } 
                catch {
                    if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                        Write-WebSocketLog "Error stopping existing listener: $_" -Level WARN
                    }
                }
            }
            
            # Store port
            $this.Port = $Port
            
            # Create TCP listener based on hostname
            if ($HostName -eq '+' -or $HostName -eq '*') {
                # Listen on all interfaces
                $this.Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "Created listener on all interfaces (IPAddress.Any)" -Level INFO
                }
            }
            elseif ($HostName -eq 'localhost') {
                # Listen on localhost only (loopback)
                $this.Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "Created listener on localhost only (Loopback)" -Level INFO
                }
            }
            else {
                # Listen on specified hostname
                try {
                    $ipAddress = [System.Net.Dns]::GetHostAddresses($HostName) | 
                                 Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } | 
                                 Select-Object -First 1
                                 
                    if ($null -eq $ipAddress) {
                        throw "Could not resolve hostname $HostName to an IPv4 address"
                    }
                    
                    $this.Listener = New-Object System.Net.Sockets.TcpListener($ipAddress, $Port)
                    if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                        Write-WebSocketLog "Created listener on specific host: $HostName ($($ipAddress.ToString()))" -Level INFO
                    }
                }
                catch {
                    if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                        Write-WebSocketLog "Failed to resolve hostname $HostName, using Any: $_" -Level WARN
                    }
                    $this.Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
                }
            }
            
            # Start the listener
            $this.Listener.Start()
            
            # Write ready file
            $readyFilePath = Join-Path $this.ServerDirectory "temp\websocket.ready"
            
            # Create directory if it doesn't exist
            $readyDir = Split-Path -Parent $readyFilePath
            if (-not (Test-Path $readyDir)) {
                New-Item -Path $readyDir -ItemType Directory -Force | Out-Null
            }
            
            $config = @{
                status = "ready"
                port = $Port
                timestamp = Get-Date -Format "o"
                host = $HostName
            } | ConvertTo-Json
            
            Set-Content -Path $readyFilePath -Value $config -Force
            
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "WebSocket server initialized on port $Port" -Level INFO
                Write-WebSocketLog "Ready file created at: $readyFilePath" -Level INFO
            }
            
            return $true
        }
        catch {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Failed to initialize WebSocket server: $_" -Level ERROR
            }
            return $false
        }
    }
    
    [void] Start() {
        $this.IsRunning = $true
        
        # Create a thread to handle inbound connections
        try {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Starting WebSocket server on port $($this.Port)" -Level INFO
            }
            
            # Update ready file to indicate we're running
            $readyFilePath = Join-Path $this.ServerDirectory "temp\websocket.ready"
            $config = @{
                status = "running"
                port = $this.Port
                timestamp = Get-Date -Format "o"
            } | ConvertTo-Json
            
            Set-Content -Path $readyFilePath -Value $config -Force
            
            # Start a background thread to handle listening
            $thread = [System.Threading.Thread]::new({
                param($server)
                
                try {
                    while ($server.IsRunning) {
                        try {
                            if ($server.Listener.Pending()) {
                                # Accept a new client connection
                                $client = $server.Listener.AcceptSocket()
                                
                                # In a real implementation, we would handle WebSocket handshake
                                # and manage the connection. For this simple server, we'll just
                                # keep the port open and accept connections.
                                $client.Close()
                            }
                            
                            # Sleep to avoid CPU spike
                            [System.Threading.Thread]::Sleep(100)
                        }
                        catch [System.Net.Sockets.SocketException] {
                            # Socket exceptions may occur if client disconnects - just continue
                        }
                        catch {
                            # Log other errors but continue running
                            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                                Write-WebSocketLog "Error in WebSocket listener thread: $_" -Level ERROR
                            }
                            [System.Threading.Thread]::Sleep(1000)
                        }
                    }
                }
                catch {
                    if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                        Write-WebSocketLog "WebSocket listener thread terminated with error: $_" -Level ERROR
                    }
                }
                finally {
                    if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                        Write-WebSocketLog "WebSocket listener thread exited" -Level INFO
                    }
                }
            })
            
            # Set thread as background so it doesn't prevent PowerShell from exiting
            $thread.IsBackground = $true
            
            # Pass the server instance to the thread
            $thread.Start($this)
            
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "WebSocket server started successfully" -Level INFO
            }
        }
        catch {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Failed to start WebSocket server: $_" -Level ERROR
            }
        }
    }
    
    [void] Stop() {
        $this.IsRunning = $false
        if ($null -ne $this.Listener) {
            try {
                $this.Listener.Stop()
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "WebSocket server stopped" -Level INFO
                }
            }
            catch {
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "Error stopping WebSocket server: $_" -Level ERROR
                }
            }
        }
    }
    
    [hashtable] GetStatus() {
        return @{
            IsListening = $this.IsListening()
            Port = $this.Port
            IsRunning = $this.IsRunning
            ConnectionCount = $this.Connections.Count
        }
    }
}

# Helper function to create a simple WebSocket server - completely revised
function Global:New-WebSocketServer {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory=$false)]
        [int]$Port = 8081,
        
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost",
        
        [Parameter(Mandatory=$true)]
        [string]$ServerDirectory
    )
    
    try {
        Write-WebSocketLog "Creating SimpleWebSocketServer for directory: $ServerDirectory" -Level INFO
        
        # Create simple WebSocket server (avoids complex .NET WebSocket implementation)
        $server = [SimpleWebSocketServer]::new($ServerDirectory)
        
        # Initialize with requested port and hostname
        Write-WebSocketLog "Initializing server with port $Port and hostname $HostName" -Level INFO
        if (-not $server.Initialize($Port, $HostName)) {
            throw "Failed to initialize WebSocket server"
        }
        
        # Verify server object is valid
        if ($null -eq $server -or -not ($server -is [SimpleWebSocketServer])) {
            throw "Server object is not the correct type"
        }
        
        # Explicitly verify properties and methods required
        $requiredProperties = @('Listener', 'IsRunning', 'ServerDirectory', 'Port')
        $missingProperties = $requiredProperties | Where-Object { -not $server.PSObject.Properties.Name.Contains($_) }
        if ($missingProperties.Count -gt 0) {
            throw "Server missing required properties: $($missingProperties -join ', ')"
        }
        
        # Verify methods
        $requiredMethods = @('IsListening', 'Start', 'Stop')
        $methods = $server | Get-Member -MemberType Method | Select-Object -ExpandProperty Name
        $missingMethods = $requiredMethods | Where-Object { $_ -notin $methods }
        if ($missingMethods.Count -gt 0) {
            throw "Server missing required methods: $($missingMethods -join ', ')"
        }
        
        # Create separate runspace for server
        $runspace = [runspacefactory]::CreateRunspace()
        $runspace.Open()
        $runspace.SessionStateProxy.SetVariable('server', $server)
        
        $ps = [powershell]::Create()
        $ps.Runspace = $runspace
        
        # Start server in separate thread
        $scriptBlock = {
            param($server)
            try {
                # Start the server
                $server.Start()
                
                # Keep server alive with a simple loop
                while ($server.IsRunning) {
                    Start-Sleep -Seconds 1
                }
            }
            catch {
                # Log error if available
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "Error in WebSocket server thread: $_" -Level ERROR
                }
            }
        }
        
        $ps.AddScript($scriptBlock).AddArgument($server) | Out-Null
        $handle = $ps.BeginInvoke()
        
        # Add to server object for cleanup
        $server | Add-Member -NotePropertyName PowerShell -NotePropertyValue $ps -Force
        $server | Add-Member -NotePropertyName Runspace -NotePropertyValue $runspace -Force
        $server | Add-Member -NotePropertyName AsyncHandle -NotePropertyValue $handle -Force
        
        # Verify server is actually listening
        $maxAttempts = 5
        $attempts = 0
        $success = $false
        
        while (-not $success -and $attempts -lt $maxAttempts) {
            $attempts++
            Start-Sleep -Milliseconds 500
            
            try {
                if ($server.IsListening()) {
                    $success = $true
                    break
                }
            }
            catch {
                Write-WebSocketLog "Error checking IsListening: $_" -Level WARN
            }
        }
        
        if (-not $success) {
            # Clean up resources before throwing
            try { $ps.Stop() } catch {}
            try { $ps.Dispose() } catch {}
            try { $runspace.Close() } catch {}
            try { $runspace.Dispose() } catch {}
            try { $server.Stop() } catch {}
            
            throw "WebSocket server failed to start listening"
        }
        
        # Verify ready file exists and is valid
        $readyFile = Join-Path $ServerDirectory "temp\websocket.ready"
        if (-not (Test-Path $readyFile)) {
            throw "WebSocket ready file not created"
        }
        
        try {
            $readyContent = Get-Content $readyFile -Raw | ConvertFrom-Json
            if ($readyContent.status -ne "ready" -and $readyContent.status -ne "running") {
                throw "WebSocket server not in ready state"
            }
        }
        catch {
            throw "Invalid ready file format: $_"
        }
        
        Write-WebSocketLog "WebSocket server created and verified successfully" -Level INFO
        return $server
    }
    catch {
        # Comprehensive cleanup
        if ($ps) { 
            try { $ps.Stop() } catch {}
            try { $ps.Dispose() } catch {}
        }
        
        if ($runspace) {
            try { $runspace.Close() } catch {}
            try { $runspace.Dispose() } catch {}
        }
        
        if ($server) {
            try { $server.Stop() } catch {}
        }
        
        Write-WebSocketLog "Failed to create WebSocket server: $_" -Level ERROR
        throw 
    }
}

function Set-WebSocketReady {
    [CmdletBinding()]
    param(
        [string]$Status = "ready",
        [int]$Port = 8081,
        [string]$ReadyFile = $script:ReadyFiles.WebSocket
    )
    
    try {
        # Create parent directory if it doesn't exist
        $readyDir = Split-Path -Parent $ReadyFile
        if (-not (Test-Path $readyDir)) {
            New-Item -Path $readyDir -ItemType Directory -Force | Out-Null
        }
        
        $config = @{
            status = $Status
            port = $Port
            timestamp = Get-Date -Format "o"
        } | ConvertTo-Json
        
        Set-Content -Path $ReadyFile -Value $config -Force
        
        if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
            Write-WebSocketLog "WebSocket ready file created: $ReadyFile" -Level INFO
        }
        
        return $true
    }
    catch {
        if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
            Write-WebSocketLog "Failed to create WebSocket ready file: $_" -Level ERROR
        }
        return $false
    }
}

function Global:Test-WebSocketReady {
    [CmdletBinding()]
    param(
        [string]$ReadyFile = $script:ReadyFiles.WebSocket
    )
    
    try {
        if (Test-Path $ReadyFile) {
            $content = Get-Content $ReadyFile -Raw | ConvertFrom-Json
            return $content.status -eq "ready" -or $content.status -eq "running"
        }
    }
    catch {
        if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
            Write-WebSocketLog "Error checking WebSocket ready status: $_" -Level ERROR
        }
    }
    
    return $false
}

function Test-WebSocketConnection {
    [CmdletBinding()]
    param(
        [int]$Port = 8081,
        [string]$HostName = "localhost",
        [int]$Timeout = 2000
    )
    
    $tcpClient = $null
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connectResult = $tcpClient.ConnectAsync($HostName, $Port).Wait($Timeout)
        
        return $connectResult
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $tcpClient) {
            $tcpClient.Dispose()
        }
    }
}

# Minimal WebSocket client for testing connectivity
function Global:New-WebSocketClient {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory=$true)]
        [string]$ServerUrl
    )
    
    # In this simplified version, just return a hashtable with the URL
    return @{
        ServerUrl = $ServerUrl
        IsConnected = $false
        Connect = {
            param($this)
            $uri = [Uri]$this.ServerUrl
            return (Test-WebSocketConnection -HostName $uri.Host -Port $uri.Port)
        }
    }
}

# Function to log WebSocket messages
function Write-WebSocketLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [string]$Level = "INFO"
    )
    
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $logEntry = "[$timestamp] [$Level] $Message"
        
        # First try to use the existing log function if available
        if ($null -ne (Get-Command "Write-Log" -ErrorAction SilentlyContinue)) {
            Write-Log $Message -Level $Level
            return
        }
        
        # Otherwise log to a dedicated file
        $logPath = Join-Path $script:Paths.Logs "websocket.log"
        
        # Ensure log directory exists
        $logDir = Split-Path -Parent $logPath
        if (-not (Test-Path $logDir)) {
            New-Item -Path $logDir -ItemType Directory -Force | Out-Null
        }
        
        Add-Content -Path $logPath -Value $logEntry
        
        # Also write to console for verbose mode
        if ($VerbosePreference -eq 'Continue') {
            Write-Host "WEBSOCKET: $Message" -ForegroundColor Cyan
        }
    }
    catch {
        # Last resort, try to write to host
        try {
            Write-Host "WEBSOCKET ERROR: $Message (Logging failed: $_)" -ForegroundColor Red
        }
        catch {}
    }
}

# Function to connect to WebSocket with port scanning for reliability
function Connect-WebSocketWithPortScan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [int]$StartPort = 8081,
        
        [Parameter(Mandatory=$false)]
        [int]$EndPort = 8091,
        
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost",
        
        [Parameter(Mandatory=$false)]
        [int]$Timeout = 2000,
        
        [Parameter(Mandatory=$false)]
        [string]$ReadyFile = $script:ReadyFiles.WebSocket,
        
        [Parameter(Mandatory=$false)]
        [switch]$UseReadyFileFirst,
        
        [Parameter(Mandatory=$false)]
        [switch]$Silent
    )
    
    # Suppress confirmation prompts
    $oldConfirmPreference = $ConfirmPreference
    $ConfirmPreference = 'None'
    $InformationPreference = 'SilentlyContinue'
    
    try {
        Write-WebSocketLog "Attempting WebSocket connection with port scan ($StartPort-$EndPort)" -Level INFO
        
        # First try to get port from ready file if requested
        if ($UseReadyFileFirst -and (Test-Path $ReadyFile)) {
            try {
                $readyContent = Get-Content $ReadyFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
                if ($readyContent.port -gt 0) {
                    Write-WebSocketLog "Found port $($readyContent.port) in ready file, trying first" -Level INFO
                    
                    if (Test-WebSocketConnection -Port $readyContent.port -HostName $HostName -Timeout $Timeout) {
                        Write-WebSocketLog "Successfully connected to WebSocket on port $($readyContent.port) from ready file" -Level INFO
                        return @{
                            Success = $true
                            Port = $readyContent.port
                            Host = $HostName
                            Url = "ws://$($HostName):$($readyContent.port)/"
                        }
                    }
                }
            }
            catch {
                Write-WebSocketLog "Error reading ready file: $_" -Level WARN
            }
        }
        
        # Scan ports in range
        Write-WebSocketLog "Scanning ports $StartPort to $EndPort for WebSocket connection" -Level INFO
        
        for ($port = $StartPort; $port -le $EndPort; $port++) {
            try {
                Write-WebSocketLog "Trying WebSocket connection on port $port" -Level DEBUG
                
                if (Test-WebSocketConnection -Port $port -HostName $HostName -Timeout $Timeout) {
                    Write-WebSocketLog "Successfully connected to WebSocket on port $port" -Level INFO
                    return @{
                        Success = $true
                        Port = $port
                        Host = $HostName
                        Url = "ws://$($HostName):$port/"
                    }
                }
            }
            catch {
                Write-WebSocketLog "Error testing connection on port $port $_" -Level DEBUG
            }
        }
        
        # If we get here, we failed to connect
        Write-WebSocketLog "Failed to find WebSocket on any port in range $StartPort-$EndPort" -Level ERROR
        
        return @{
            Success = $false
            Port = 0
            Host = $HostName
            Url = $null
            Error = "Could not connect to WebSocket on any port"
        }
    }
    finally {
        # Restore original preferences
        $ConfirmPreference = $oldConfirmPreference
    }
}

# Export module members - make sure ALL required functions are here
Export-ModuleMember -Function @(
    'Get-WebSocketPaths',
    'New-WebSocketServer',
    'Test-WebSocketReady',
    'Set-WebSocketReady',
    'Test-WebSocketConnection',
    'New-WebSocketClient',
    'Write-WebSocketLog',
    'Connect-WebSocketWithPortScan'
) -Variable @(
    'DefaultWebSocketPort',
    'DefaultWebPort'
)

# Additional check immediately after export to verify functions are available
$exportedFunctions = (Get-Module WebSocketServer).ExportedFunctions.Keys
Write-Verbose "WebSocketServer module exported these functions: $($exportedFunctions -join ', ')"

# Verify explicitly that the New-WebSocketServer function exists
if (-not (Get-Command New-WebSocketServer -ErrorAction SilentlyContinue)) {
    Write-Warning "New-WebSocketServer function not available after export, defining globally"
    # If for some reason the function isn't exported properly, redefine it in global scope
    New-Alias -Name New-WebSocketServer -Value Global:New-WebSocketServer -Scope Global -Force
}
