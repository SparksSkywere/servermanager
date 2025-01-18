# Add these routes to your existing API routes

$routes += @{
    Method = 'GET'
    Path = '/api/stats'
    Handler = {
        param($Request)
        $stats = @{
            totalServers = 0
            runningServers = 0
            cpuUsage = 0
            memoryUsage = 0
            timestamp = [DateTime]::Now.ToString('o')
        }

        # Get system stats
        try {
            $processor = Get-WmiObject Win32_Processor
            $memory = Get-WmiObject Win32_OperatingSystem
            
            $stats.cpuUsage = ($processor | Measure-Object -Property LoadPercentage -Average).Average
            $stats.memoryUsage = [math]::Round(((($memory.TotalVisibleMemorySize - $memory.FreePhysicalMemory) * 100) / $memory.TotalVisibleMemorySize), 2)

            # Get server counts from your server management system
            $servers = Get-Content "$PSScriptRoot\..\data\servers.json" -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($servers) {
                $stats.totalServers = $servers.Count
                $stats.runningServers = ($servers | Where-Object { $_.status -eq 'Running' }).Count
            }

            Send-JsonResponse $stats
        }
        catch {
            Send-JsonResponse @{
                error = "Failed to get system stats: $_"
            } -StatusCode 500
        }
    }
}

$routes += @{
    Method = 'GET'
    Path = '/api/servers'
    Handler = {
        param($Request)
        try {
            $serversFile = "$PSScriptRoot\..\data\servers.json"
            if (Test-Path $serversFile) {
                $servers = Get-Content $serversFile -Raw | ConvertFrom-Json
            }
            else {
                $servers = @()
            }
            Send-JsonResponse $servers
        }
        catch {
            Send-JsonResponse @{
                error = "Failed to get servers: $_"
            } -StatusCode 500
        }
    }
}

$routes += @{
    Method = 'POST'
    Path = '/api/servers'
    Handler = {
        param($Request)
        try {
            $serverData = $Request.Body | ConvertFrom-Json
            
            # Validate required fields
            if (-not $serverData.name -or -not $serverData.type -or -not $serverData.path) {
                Send-JsonResponse @{
                    error = "Missing required fields"
                } -StatusCode 400
                return
            }

            $serversFile = "$PSScriptRoot\..\data\servers.json"
            $servers = @()
            
            if (Test-Path $serversFile) {
                $servers = Get-Content $serversFile -Raw | ConvertFrom-Json
            }

            # Add new server
            $newServer = @{
                name = $serverData.name
                type = $serverData.type
                path = $serverData.path
                status = "Stopped"
                cpuUsage = 0
                memoryUsage = 0
                uptime = 0
            }

            $servers += $newServer
            $servers | ConvertTo-Json | Set-Content $serversFile

            Send-JsonResponse $newServer
        }
        catch {
            Send-JsonResponse @{
                error = "Failed to create server: $_"
            } -StatusCode 500
        }
    }
}

# Add server control endpoints
$routes += @{
    Method = 'POST'
    Path = '/api/servers/{name}/{action}'
    Handler = {
        param($Request)
        try {
            $serverName = $Request.PathParameters['name']
            $action = $Request.PathParameters['action']
            
            $serversFile = "$PSScriptRoot\..\data\servers.json"
            $servers = Get-Content $serversFile -Raw | ConvertFrom-Json

            $server = $servers | Where-Object { $_.name -eq $serverName }
            if (-not $server) {
                Send-JsonResponse @{
                    error = "Server not found: $serverName"
                } -StatusCode 404
                return
            }

            switch ($action) {
                'start' {
                    $server.status = 'Running'
                }
                'stop' {
                    $server.status = 'Stopped'
                }
                'restart' {
                    $server.status = 'Running'
                }
                default {
                    Send-JsonResponse @{
                        error = "Invalid action: $action"
                    } -StatusCode 400
                    return
                }
            }

            $servers | ConvertTo-Json | Set-Content $serversFile

            Send-JsonResponse @{
                status = "success"
                message = "Server $serverName $action successful"
            }
        }
        catch {
            Send-JsonResponse @{
                error = "Failed to $action server: $_"
            } -StatusCode 500
        }
    }
}
