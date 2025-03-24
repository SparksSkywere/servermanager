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
        # Simple implementation that just returns the status
        return $this.IsRunning -and $null -ne $this.Listener
    }
    
    [bool] Initialize([int]$Port = 8081, [string]$HostName = "localhost") {
        try {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Initializing SimpleWebSocketServer on port $Port" -Level INFO
            }
            
            # Clean up any existing listener
            if ($null -ne $this.Listener) {
                try { $this.Listener.Stop() } catch {}
                $this.Listener = $null
            }
            
            # Store port
            $this.Port = $Port
            
            # Create TCP listener based on hostname
            if ($HostName -eq '+' -or $HostName -eq '*') {
                $this.Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
            }
            elseif ($HostName -eq 'localhost') {
                $this.Listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
            }
            else {
                # Try to parse IP address
                try {
                    $ipAddress = [System.Net.IPAddress]::Parse($HostName)
                    $this.Listener = New-Object System.Net.Sockets.TcpListener($ipAddress, $Port)
                }
                catch {
                    # Default to Any address
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
            } | ConvertTo-Json
            
            Set-Content -Path $readyFilePath -Value $config -Force
            
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "SimpleWebSocketServer initialized successfully on port $Port" -Level INFO
            }
            
            return $true
        }
        catch {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Failed to initialize SimpleWebSocketServer: $_" -Level ERROR
            }
            return $false
        }
    }
    
    [void] Start() {
        $this.IsRunning = $true
        
        # Keep the server alive - we're not actually processing WebSocket messages
        # in this simplified version, just making the ports available
        try {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "SimpleWebSocketServer started on port $($this.Port)" -Level INFO
            }
            
            # Update ready file to indicate we're running
            $readyFilePath = Join-Path $this.ServerDirectory "temp\websocket.ready"
            $config = @{
                status = "running"
                port = $this.Port
                timestamp = Get-Date -Format "o"
            } | ConvertTo-Json
            
            Set-Content -Path $readyFilePath -Value $config -Force
        }
        catch {
            if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                Write-WebSocketLog "Error in SimpleWebSocketServer: $_" -Level ERROR
            }
            $this.IsRunning = $false
        }
    }
    
    [void] Stop() {
        $this.IsRunning = $false
        if ($null -ne $this.Listener) {
            try { 
                $this.Listener.Stop() 
                if ($null -ne (Get-Command "Write-WebSocketLog" -ErrorAction SilentlyContinue)) {
                    Write-WebSocketLog "SimpleWebSocketServer stopped" -Level INFO
                }
            } 
            catch {}
        }
    }
    
    [hashtable] GetStatus() {
        return @{
            IsRunning = $this.IsRunning
            Port = $this.Port
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

# Export module members - make sure ALL required functions are here
Export-ModuleMember -Function @(
    'Get-WebSocketPaths',
    'New-WebSocketServer',
    'Test-WebSocketReady',
    'Set-WebSocketReady',
    'Test-WebSocketConnection',
    'New-WebSocketClient',
    'Write-WebSocketLog'
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
