#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Install Server Manager (Windows). Same outcome as ServerManager-Setup.exe.

.DESCRIPTION
  Modes:
    1) Beside a built payload / Setup.exe — copies binaries and configures the machine.
    2) From Git — clones the repo, builds, then installs (requires .NET 8 SDK + git).

  Server configs always live in SQLite under runtime\db\ (not JSON files).

.EXAMPLE
  # From a release folder that already has the published binaries:
  .\install.ps1 -PayloadDir .\payload

  # Clone from Git and install:
  .\install.ps1 -RepoUrl https://github.com/ORG/servermanager.git

  # Uninstall:
  .\install.ps1 -Action Uninstall
#>
param(
    [ValidateSet("Install", "Uninstall", "ServiceInstall", "ServiceUninstall")]
    [string]$Action = "Install",

    [string]$InstallRoot = "$env:ProgramFiles\ServerManager",
    [string]$RepoUrl = "",
    [string]$RepoBranch = "main",
    [string]$PayloadDir = "",
    [string]$SteamCmdPath = "",
    [int]$WebPort = 18080,
    [int]$HostRuntimePort = 18091,
    [int]$ClusterPort = 15001,
    [switch]$NoFirewall,
    [switch]$StartAfterInstall,
    [switch]$AsService
)

$ErrorActionPreference = "Stop"
$RegPath = "HKLM:\Software\SkywereIndustries\Servermanager"
$ServiceName = "ServerManagerService"
$ScriptDir = $PSScriptRoot

function Write-Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }

function Get-GitRepoUrl {
    if (-not [string]::IsNullOrWhiteSpace($RepoUrl)) { return $RepoUrl }
    try {
        $u = git -C $ScriptDir rev-parse --show-toplevel 2>$null
        if ($u) {
            $remote = git -C $u remote get-url origin 2>$null
            if ($remote) { return $remote.Trim() }
        }
    } catch { }
    return ""
}

function Resolve-PayloadDirectory {
    if ($PayloadDir -and (Test-Path (Join-Path $PayloadDir "ServerManager.exe"))) {
        return (Resolve-Path $PayloadDir).Path
    }

    $candidates = @(
        (Join-Path $ScriptDir "payload"),
        (Join-Path $ScriptDir "artifacts\payload"),
        (Join-Path $ScriptDir "artifacts\publish\win-x64"),
        (Join-Path $ScriptDir "..\artifacts\payload"),
        (Join-Path $ScriptDir "..\artifacts\publish\win-x64")
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "ServerManager.exe")) {
            return (Resolve-Path $c).Path
        }
    }

    # Prefer running Setup.exe if present next to this script
    $setup = Join-Path $ScriptDir "ServerManager-Setup.exe"
    if (Test-Path $setup) {
        Write-Info "Launching GUI installer: $setup"
        Start-Process -FilePath $setup -Wait
        exit $LASTEXITCODE
    }

    $url = Get-GitRepoUrl
    if ([string]::IsNullOrWhiteSpace($url)) {
        throw @"
No published payload found and no -RepoUrl supplied.

Provide one of:
  -PayloadDir <folder with ServerManager.exe>
  -RepoUrl https://github.com/ORG/servermanager.git
  Or place ServerManager-Setup.exe next to this script.
"@
    }

    Write-Info "Cloning $url ($RepoBranch)..."
    $work = Join-Path $env:TEMP ("ServerManager-src-" + [guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    git clone --depth 1 --branch $RepoBranch $url $work
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }

    Write-Info "Building release payload..."
    Push-Location $work
    try {
        & .\build.ps1 -Configuration Release
        if ($LASTEXITCODE -ne 0) { throw "build.ps1 failed" }
    } finally {
        Pop-Location
    }

    $built = Join-Path $work "artifacts\publish\win-x64"
    if (-not (Test-Path (Join-Path $built "ServerManager.exe"))) {
        throw "Build finished but ServerManager.exe missing under $built"
    }
    return $built
}

function Ensure-RuntimeDirs([string]$RuntimeRoot) {
    foreach ($d in @("logs", "logs\components", "temp", "db", "ssl", "www", "config", "icons")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeRoot $d) | Out-Null
    }
}

function Set-MachineConfig([string]$AppDir, [string]$RuntimeRoot) {
    New-Item -Path $RegPath -Force | Out-Null
    Set-ItemProperty -Path $RegPath -Name "InstallPath" -Value $AppDir
    Set-ItemProperty -Path $RegPath -Name "Servermanagerdir" -Value $RuntimeRoot
    Set-ItemProperty -Path $RegPath -Name "WebPort" -Value $WebPort -Type DWord
    Set-ItemProperty -Path $RegPath -Name "HostRuntimePort" -Value $HostRuntimePort -Type DWord
    Set-ItemProperty -Path $RegPath -Name "ClusterPort" -Value $ClusterPort -Type DWord
    Set-ItemProperty -Path $RegPath -Name "HostType" -Value "standalone"
    Set-ItemProperty -Path $RegPath -Name "ClusterEnabled" -Value "false"
    Set-ItemProperty -Path $RegPath -Name "SQLType" -Value "sqlite"
    Set-ItemProperty -Path $RegPath -Name "SteamCmdPath" -Value $SteamCmdPath

    $cfg = Join-Path $RuntimeRoot "config\appsettings.json"
    $json = @{
        ServerManager = @{
            RootPath         = $RuntimeRoot
            WebPort          = $WebPort
            HostRuntimePort  = $HostRuntimePort
            ClusterPort      = $ClusterPort
            SteamCmdPath     = $SteamCmdPath
        }
    } | ConvertTo-Json -Depth 5
    Set-Content -Path $cfg -Value $json -Encoding UTF8
}

function Set-Firewall {
    if ($NoFirewall) { return }
    foreach ($rule in @(
        @{ Name = "ServerManager-Web"; Port = $WebPort },
        @{ Name = "ServerManager-Runtime"; Port = $HostRuntimePort },
        @{ Name = "ServerManager-Cluster"; Port = $ClusterPort }
    )) {
        & netsh advfirewall firewall delete rule name="$($rule.Name)" | Out-Null
        & netsh advfirewall firewall add rule name="$($rule.Name)" dir=in action=allow protocol=TCP localport=$($rule.Port) | Out-Null
    }
    Write-Ok "Firewall rules updated"
}

function Install-WindowsService([string]$Exe) {
    $exists = $false
    & sc.exe query $ServiceName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $exists = $true }

    if ($exists) {
        Write-Info "Updating existing service $ServiceName (no delete)"
        & sc.exe stop $ServiceName 2>$null | Out-Null
        Start-Sleep -Seconds 2
        & sc.exe config $ServiceName binPath= "`"$Exe`"" start= auto DisplayName= ServerManager | Out-Null
    }
    else {
        Write-Info "Creating service $ServiceName"
        & sc.exe create $ServiceName binPath= "`"$Exe`"" start= auto DisplayName= ServerManager | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "sc create failed ($LASTEXITCODE) for $Exe" }
    }

    & sc.exe description $ServiceName "Skywere Industries Server Manager" | Out-Null
    & sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null
    New-Item -Path $RegPath -Force | Out-Null
    Set-ItemProperty -Path $RegPath -Name "InstallAsService" -Value 1 -Type DWord
    Write-Ok "Service $ServiceName ready"
}

function Register-TrayAutostart([string]$AppDir) {
    $tray = Join-Path $AppDir "ServerManager.Tray.exe"
    if (-not (Test-Path $tray)) { return }
    $runKey = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run"
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name "ServerManagerTray" -Value "`"$tray`""
    $startup = [Environment]::GetFolderPath("CommonStartup")
    if ($startup) {
        $lnkPath = Join-Path $startup "Server Manager Tray.lnk"
        $w = New-Object -ComObject WScript.Shell
        $lnk = $w.CreateShortcut($lnkPath)
        $lnk.TargetPath = $tray
        $lnk.WorkingDirectory = $AppDir
        $lnk.Save()
    }
    Write-Ok "Tray registered for user logon"
}

function Start-Tray([string]$AppDir) {
    $tray = Join-Path $AppDir "ServerManager.Tray.exe"
    if (Test-Path $tray) {
        Start-Process -FilePath $tray -WorkingDirectory $AppDir
    }
}

function Uninstall-WindowsService {
    & sc.exe stop $ServiceName 2>$null | Out-Null
    & sc.exe delete $ServiceName 2>$null | Out-Null
    Write-Ok "Service removed (if it existed)"
}

function Unregister-TrayAutostart {
    Remove-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "ServerManagerTray" -ErrorAction SilentlyContinue
    $startup = [Environment]::GetFolderPath("CommonStartup")
    if ($startup) {
        $lnkPath = Join-Path $startup "Server Manager Tray.lnk"
        if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force -ErrorAction SilentlyContinue }
    }
}

function Invoke-Install {
    $src = Resolve-PayloadDirectory
    Write-Info "Payload: $src"
    Write-Info "Install: $InstallRoot"

    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $runtime = Join-Path $InstallRoot "runtime"
    Ensure-RuntimeDirs $runtime

    Write-Info "Copying binaries..."
    # Stop service/processes so files are not locked during upgrade
    & sc.exe stop $ServiceName 2>$null | Out-Null
    Start-Sleep -Seconds 2
    foreach ($name in @("ServerManager.HostUI", "ServerManager.Tray", "ServerManager.Web", "ServerManager.HostRuntime", "ServerManager")) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    Copy-Item -Path (Join-Path $src "*") -Destination $InstallRoot -Recurse -Force

    $wwwSrc = Join-Path $InstallRoot "www"
    $wwwDst = Join-Path $runtime "www"
    if (Test-Path $wwwSrc) {
        Copy-Item -Path (Join-Path $wwwSrc "*") -Destination $wwwDst -Recurse -Force
    }

    $iconSrc = Join-Path $InstallRoot "servermanager.ico"
    if (-not (Test-Path $iconSrc)) { $iconSrc = Join-Path $InstallRoot "icons\servermanager.ico" }
    if (Test-Path $iconSrc) {
        Copy-Item $iconSrc (Join-Path $runtime "icons\servermanager.ico") -Force
        Copy-Item $iconSrc (Join-Path $InstallRoot "icons\servermanager.ico") -Force -ErrorAction SilentlyContinue
    }

    Set-MachineConfig $InstallRoot $runtime
    Set-Firewall
    Register-TrayAutostart $InstallRoot

    $exe = Join-Path $InstallRoot "ServerManager.exe"
    $wantService = $AsService.IsPresent
    if (-not $wantService) {
        try {
            $flag = (Get-ItemProperty -Path $RegPath -Name "InstallAsService" -ErrorAction SilentlyContinue).InstallAsService
            if ($flag -eq 1) { $wantService = $true }
        } catch { }
        & sc.exe query $ServiceName 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $wantService = $true }
    }

    if ($wantService) {
        Install-WindowsService $exe
        & sc.exe start $ServiceName | Out-Null
        Start-Tray $InstallRoot
    } elseif ($StartAfterInstall) {
        Start-Process -FilePath $exe -WorkingDirectory $InstallRoot
        Start-Tray $InstallRoot
    }

    Write-Ok "Install complete."
    Write-Host "    Runtime (SQLite DBs): $runtime\db"
    Write-Host "    Web port            : $WebPort"
    Write-Host "    Login               : admin / admin"
    if ($wantService) {
        Write-Host "    Tray icon           : starts at logon (and launched now). Service itself cannot show a tray icon."
    }
}

function Invoke-Uninstall {
    Write-Info "Uninstalling from $InstallRoot"
    Uninstall-WindowsService
    Unregister-TrayAutostart
    foreach ($name in @("ServerManager-Web", "ServerManager-Runtime", "ServerManager-Cluster")) {
        & netsh advfirewall firewall delete rule name="$name" 2>$null | Out-Null
    }
    if (Test-Path $RegPath) { Remove-Item -Path $RegPath -Recurse -Force }
    if (Test-Path $InstallRoot) {
        Write-Host "Leaving $InstallRoot on disk (contains runtime\db). Delete manually if desired." -ForegroundColor Yellow
    }
    Write-Ok "Uninstall registry/service/firewall done."
}

switch ($Action) {
    "Install" { Invoke-Install }
    "Uninstall" { Invoke-Uninstall }
    "ServiceInstall" {
        $exe = Join-Path $InstallRoot "ServerManager.exe"
        if (-not (Test-Path $exe)) { throw "Missing $exe — run Install first" }
        Install-WindowsService $exe
        & sc.exe start $ServiceName | Out-Null
    }
    "ServiceUninstall" { Uninstall-WindowsService }
}
