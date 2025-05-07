# Server Manager Debug Module
# Contains centralized debugging functions for troubleshooting application issues

# Define registry path 
$script:RegPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Get application paths
function Get-ServerManagerPaths {
    [CmdletBinding()]
    param()
    
    $paths = @{}
    
    try {
        # Get base directory from registry
        if (Test-Path $script:RegPath) {
            $serverManagerDir = (Get-ItemProperty -Path $script:RegPath -ErrorAction Stop).servermanagerdir
            $serverManagerDir = $serverManagerDir.Trim('"', ' ', '\')
            
            $paths = @{
                Root = $serverManagerDir
                Logs = Join-Path $serverManagerDir "logs"
                Config = Join-Path $serverManagerDir "config"
                Temp = Join-Path $serverManagerDir "temp"
                Scripts = Join-Path $serverManagerDir "Scripts"
                Modules = Join-Path $serverManagerDir "Modules"
                Debug = Join-Path $serverManagerDir "Scripts\Debug"
                ReadyFiles = @{
                    WebSocket = Join-Path (Join-Path $serverManagerDir "temp") "websocket.ready"
                    WebServer = Join-Path (Join-Path $serverManagerDir "temp") "webserver.ready"
                }
            }
        }
        else {
            # Fallback to script-relative paths
            $basePath = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
            
            $paths = @{
                Root = $basePath
                Logs = Join-Path $basePath "logs"
                Config = Join-Path $basePath "config"
                Temp = Join-Path $basePath "temp"
                Scripts = Join-Path $basePath "Scripts"
                Modules = Join-Path $basePath "Modules"
                Debug = Join-Path $basePath "Scripts\Debug"
                ReadyFiles = @{
                    WebSocket = Join-Path (Join-Path $basePath "temp") "websocket.ready"
                    WebServer = Join-Path (Join-Path $basePath "temp") "webserver.ready"
                }
            }
        }
    }
    catch {
        Write-Error "Failed to get Server Manager paths: $_"
    }
    
    return $paths
}

# Check if a port is open
function Test-PortOpen {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][int]$Port,
        [string]$ComputerName = "localhost",
        [int]$TimeoutMilliseconds = 1000
    )
    
    try {
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connection = $tcpClient.BeginConnect($ComputerName, $Port, $null, $null)
        $success = $connection.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)
        
        if ($success) {
            if ($tcpClient.Connected) {
                $tcpClient.Close()
                return $true
            }
        }
        
        if ($tcpClient.Connected) { $tcpClient.Close() }
        return $false
    }
    catch {
        return $false
    }
}

# Get WebSocket port from ready file with fallback options
function Get-WebSocketPort {
    [CmdletBinding()]
    param(
        [string]$ReadyFilePath,
        [int]$DefaultPort = 8081,
        [int]$FallbackPort = 8080
    )
    
    try {
        # If no path provided, try to determine it
        if ([string]::IsNullOrWhiteSpace($ReadyFilePath)) {
            $paths = Get-ServerManagerPaths
            $ReadyFilePath = $paths.ReadyFiles.WebSocket
        }
        
        if (-not (Test-Path $ReadyFilePath)) {
            Write-Verbose "WebSocket ready file not found at: $ReadyFilePath"
            
            # Test default port
            if (Test-PortOpen -Port $DefaultPort) {
                return $DefaultPort
            }
            
            # Try fallback port
            if (Test-PortOpen -Port $FallbackPort) {
                return $FallbackPort
            }
            
            # Return default port if no ports are open
            return $DefaultPort
        }
        
        # Read ready file
        $readyContent = Get-Content -Path $ReadyFilePath -Raw | ConvertFrom-Json
        $configuredPort = if ($readyContent.port) { $readyContent.port } else { $DefaultPort }
        
        # Test if configured port is open
        if (Test-PortOpen -Port $configuredPort) {
            return $configuredPort
        }
        
        # Try fallback port
        if (Test-PortOpen -Port $FallbackPort) {
            return $FallbackPort
        }
        
        # Return configured port even if it's not open
        return $configuredPort
    }
    catch {
        Write-Error "Error determining WebSocket port: $($_.Exception.Message)"
        return $DefaultPort
    }
}

# Connect to WebSocket server
function Connect-WebSocket {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [int]$Port,
        
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost",
        
        [Parameter(Mandatory=$false)]
        [int]$TimeoutSeconds = 5
    )
    
    try {
        # If no port specified, try to get it
        if ($Port -eq 0) {
            $Port = Get-WebSocketPort
        }
        
        # Create WebSocket client
        $client = New-Object System.Net.WebSockets.ClientWebSocket
        $uri = New-Object System.Uri("ws://$HostName`:$Port/ws")
        
        # Set up timeout
        $cts = New-Object System.Threading.CancellationTokenSource
        $cts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
        $token = $cts.Token
        
        # Connect
        $connectTask = $client.ConnectAsync($uri, $token)
        
        # Wait for connection
        $null = $connectTask.GetAwaiter().GetResult()
        
        # Return client if successfully connected
        if ($client.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            return $client
        }
        else {
            $client.Dispose()
            return $null
        }
    }
    catch {
        if ($client) {
            $client.Dispose()
        }
        
        Write-Error "WebSocket connection error: $($_.Exception.Message)"
        return $null
    }
}

# Send WebSocket message
function Send-WebSocketMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        $WebSocketClient,
        
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [int]$TimeoutSeconds = 5
    )
    
    try {
        # Check client state
        if ($WebSocketClient.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
            throw "WebSocket is not connected"
        }
        
        # Encode message
        $buffer = [System.Text.Encoding]::UTF8.GetBytes($Message)
        $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
        
        # Set up timeout
        $cts = New-Object System.Threading.CancellationTokenSource
        $cts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
        $token = $cts.Token
        
        # Send message
        $sendTask = $WebSocketClient.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $token)
        $null = $sendTask.GetAwaiter().GetResult()
        
        return $true
    }
    catch {
        Write-Error "WebSocket send error: $($_.Exception.Message)"
        return $false
    }
}

# Receive WebSocket message
function Receive-WebSocketMessage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        $WebSocketClient,
        
        [Parameter(Mandatory=$false)]
        [int]$TimeoutSeconds = 10,
        
        [Parameter(Mandatory=$false)]
        [int]$BufferSize = 8192
    )
    
    try {
        # Check client state
        if ($WebSocketClient.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
            throw "WebSocket is not connected"
        }
        
        # Set up buffer
        $buffer = New-Object byte[] $BufferSize
        $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
        
        # Set up timeout
        $cts = New-Object System.Threading.CancellationTokenSource
        $cts.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
        $token = $cts.Token
        
        # Receive message
        $receiveTask = $WebSocketClient.ReceiveAsync($segment, $token)
        $result = $receiveTask.GetAwaiter().GetResult()
        
        if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
            return $null
        }
        
        # Convert message to string
        $message = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
        
        return $message
    }
    catch {
        Write-Error "WebSocket receive error: $($_.Exception.Message)"
        return $null
    }
}

# Create WebSocket ready file
function New-WebSocketReadyFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [int]$Port = 8081,
        
        [Parameter(Mandatory=$false)]
        [string]$HostName = "localhost",
        
        [Parameter(Mandatory=$false)]
        [string]$ReadyFilePath
    )
    
    try {
        # If no path provided, try to determine it
        if ([string]::IsNullOrWhiteSpace($ReadyFilePath)) {
            $paths = Get-ServerManagerPaths
            $ReadyFilePath = $paths.ReadyFiles.WebSocket
        }
        
        # Ensure directory exists
        $directory = Split-Path -Parent $ReadyFilePath
        if (-not (Test-Path $directory)) {
            New-Item -Path $directory -ItemType Directory -Force | Out-Null
        }
        
        # Create ready file content
        $content = @{
            status = "ready"
            port = $Port
            host = $HostName
            timestamp = Get-Date -Format "o"
        }
        
        # Write to file
        $content | ConvertTo-Json | Set-Content -Path $ReadyFilePath -Force
        
        return $true
    }
    catch {
        Write-Error "Failed to create WebSocket ready file: $($_.Exception.Message)"
        return $false
    }
}

# Get system information
function Get-SystemDiagnostics {
    [CmdletBinding()]
    param()
    
    $systemInfo = @{}
    
    try {
        # Get basic system info
        $computerSystem = Get-WmiObject -Class Win32_ComputerSystem -ErrorAction Stop
        $os = Get-WmiObject -Class Win32_OperatingSystem -ErrorAction Stop
        $processor = Get-WmiObject -Class Win32_Processor -ErrorAction Stop
        
        # Calculate memory
        $totalMemoryGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        $freeMemoryGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        $usedMemoryGB = [math]::Round($totalMemoryGB - $freeMemoryGB, 1)
        $memoryPercent = [math]::Round(($usedMemoryGB / $totalMemoryGB) * 100, 0)
        
        # Get disk info
        $drives = Get-WmiObject -Class Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 }
        $totalSizeGB = [math]::Round(($drives | Measure-Object -Property Size -Sum).Sum / 1GB, 0)
        $freeSpaceGB = [math]::Round(($drives | Measure-Object -Property FreeSpace -Sum).Sum / 1GB, 0)
        $usedSpaceGB = $totalSizeGB - $freeSpaceGB
        $diskPercent = [math]::Round(($usedSpaceGB / $totalSizeGB) * 100, 0)
        
        # Get GPU info
        $gpus = Get-WmiObject -Class Win32_VideoController -ErrorAction SilentlyContinue
        $gpuInfo = if ($gpus) {
            $gpus | ForEach-Object {
                @{
                    Name = $_.Name
                    DriverVersion = $_.DriverVersion
                    Memory = if ($_.AdapterRAM) { [math]::Round($_.AdapterRAM / 1MB, 0) } else { 0 }
                }
            }
        } else {
            @{}
        }
        
        # System uptime
        $uptime = (Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime)
        if ($uptime.Days -gt 0) {
            $uptimeString = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
        }
        elseif ($uptime.Hours -gt 0) {
            $uptimeString = "$($uptime.Hours)h $($uptime.Minutes)m"
        }
        else {
            $uptimeString = "$($uptime.Minutes)m"
        }
        
        # Compile all information
        $systemInfo = @{
            ComputerName = $computerSystem.Name
            Model = $computerSystem.Model
            Manufacturer = $computerSystem.Manufacturer
            OS = @{
                Name = $os.Caption
                Version = $os.Version
                Build = $os.BuildNumber
                Architecture = $os.OSArchitecture
            }
            CPU = @{
                Name = $processor.Name
                Cores = $processor.NumberOfCores
                LogicalProcessors = $processor.NumberOfLogicalProcessors
                MaxClockSpeed = $processor.MaxClockSpeed
            }
            Memory = @{
                TotalGB = $totalMemoryGB
                UsedGB = $usedMemoryGB
                FreeGB = $freeMemoryGB
                UsedPercent = $memoryPercent
            }
            Storage = @{
                TotalGB = $totalSizeGB
                UsedGB = $usedSpaceGB
                FreeGB = $freeSpaceGB
                UsedPercent = $diskPercent
            }
            GPU = $gpuInfo
            Uptime = $uptimeString
        }
    }
    catch {
        Write-Error "Error getting system diagnostics: $($_.Exception.Message)"
    }
    
    return $systemInfo
}

# Get WebSocket diagnostics
function Get-WebSocketDiagnostics {
    [CmdletBinding()]
    param()
    
    $diagnosticInfo = @{
        ReadyFile = @{}
        Ports = @{}
        Paths = @{}
        Connection = @{}
        TestResults = @{}
    }
    
    try {
        # Check WebSocket ready file
        $paths = Get-ServerManagerPaths
        $readyFilePath = $paths.ReadyFiles.WebSocket
        
        if (Test-Path $readyFilePath) {
            $diagnosticInfo.ReadyFile.Exists = $true
            
            try {
                $readyContent = Get-Content $readyFilePath -Raw | ConvertFrom-Json
                $diagnosticInfo.ReadyFile.Content = $readyContent
                $diagnosticInfo.ReadyFile.Port = $readyContent.port
            }
            catch {
                $diagnosticInfo.ReadyFile.Error = $_.Exception.Message
            }
        }
        else {
            $diagnosticInfo.ReadyFile.Exists = $false
        }
        
        # Test common WebSocket ports
        $ports = @(8081, 8080, 3000, 9000)
        
        foreach ($port in $ports) {
            $diagnosticInfo.Ports[$port] = Test-PortOpen -Port $port
        }
        
        # Check paths
        foreach ($key in $paths.Keys) {
            if ($key -eq "ReadyFiles") { continue }
            
            $diagnosticInfo.Paths[$key] = @{
                Path = $paths[$key]
                Exists = Test-Path $paths[$key]
            }
        }
        
        # Try to connect to WebSocket
        $port = Get-WebSocketPort -ReadyFilePath $readyFilePath
        try {
            $client = Connect-WebSocket -Port $port
            
            if ($client -and $client.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                $diagnosticInfo.Connection.Connected = $true
                $diagnosticInfo.Connection.Port = $port
                
                # Send test message
                $pingMessage = '{"Type":"Ping","Timestamp":"' + (Get-Date -Format o) + '"}'
                $sendResult = Send-WebSocketMessage -WebSocketClient $client -Message $pingMessage
                $diagnosticInfo.TestResults.SendSuccess = $sendResult
                
                if ($sendResult) {
                    # Try to receive a response
                    $response = Receive-WebSocketMessage -WebSocketClient $client -TimeoutSeconds 2
                    $diagnosticInfo.TestResults.Response = $response
                    $diagnosticInfo.TestResults.ReceiveSuccess = $null -ne $response
                }
                
                # Close the connection
                try {
                    $closeTask = $client.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "Test complete", [System.Threading.CancellationToken]::None)
                    $null = $closeTask.GetAwaiter().GetResult()
                }
                finally {
                    $client.Dispose()
                }
            }
            else {
                $diagnosticInfo.Connection.Connected = $false
                $diagnosticInfo.Connection.Port = $port
                
                if ($client) { 
                    $diagnosticInfo.Connection.State = $client.State
                    $client.Dispose() 
                }
            }
        }
        catch {
            $diagnosticInfo.Connection.Connected = $false
            $diagnosticInfo.Connection.Error = $_.Exception.Message
        }
    }
    catch {
        $diagnosticInfo.Error = $_.Exception.Message
    }
    
    return $diagnosticInfo
}

# Export module members
Export-ModuleMember -Function Get-ServerManagerPaths
Export-ModuleMember -Function Test-PortOpen
Export-ModuleMember -Function Get-WebSocketPort
Export-ModuleMember -Function Connect-WebSocket
Export-ModuleMember -Function Send-WebSocketMessage
Export-ModuleMember -Function Receive-WebSocketMessage
Export-ModuleMember -Function New-WebSocketReadyFile
Export-ModuleMember -Function Get-SystemDiagnostics
Export-ModuleMember -Function Get-WebSocketDiagnostics
