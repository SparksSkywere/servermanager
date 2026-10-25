<#
.SYNOPSIS
  Migrate legacy Server Manager databases/settings into a Server Manager runtime root.

.DESCRIPTION
  Thin wrapper around ServerManager.Migrator. No install paths are hard-coded.
  Pass -SourceRoot / -DestRoot, or let the script discover them from registry / nearby folders.

.PARAMETER SourceRoot
  Legacy install root that contains db\ (and optionally ssl\).

.PARAMETER DestRoot
  Target runtime root that will receive db\ and ssl\.

.PARAMETER PathRemapFile
  Optional JSON mapping old *install folder* path prefixes to new ones (see path-remap.example.json).
  This is NOT server configuration — servers are stored in SQLite only.

.PARAMETER SkipJsonServers
  Do not import leftover legacy servers\*.json into SQLite (default is to import them into SQL).

.PARAMETER DryRun
  Report only; do not write.

.PARAMETER Gui
  Open the WinForms migration UI instead of running from the command line.

.EXAMPLE
  .\Migrate-ServerManager.ps1 -Gui

.EXAMPLE
  .\Migrate-ServerManager.ps1 -SourceRoot '<legacy-install-root>' -DestRoot '<runtime-root>'

.EXAMPLE
  .\Migrate-ServerManager.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$DestRoot,
    [string]$PathRemapFile,
    [switch]$DryRun,
    [switch]$ClearDestDb,
    [switch]$SkipUsers,
    [switch]$SkipServers,
    [switch]$SkipJsonServers,
    [switch]$SkipCluster,
    [switch]$SkipCatalogs,
    [switch]$NoCopySsl,
    [switch]$Gui,
    [string]$MigratorExe
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-MigratorGuiExe {
    $candidates = @(
        (Join-Path $ScriptDir 'dist\ServerManager.Migrator.Gui.exe'),
        (Join-Path $ScriptDir 'ServerManager.Migrator.Gui\bin\Release\net8.0-windows\ServerManager.Migrator.Gui.exe'),
        (Join-Path $ScriptDir 'ServerManager.Migrator.Gui\bin\Debug\net8.0-windows\ServerManager.Migrator.Gui.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return (Resolve-Path $c).Path }
    }
    $proj = Join-Path $ScriptDir 'ServerManager.Migrator.Gui\ServerManager.Migrator.Gui.csproj'
    if (-not (Test-Path $proj)) { throw "GUI project not found at $proj" }
    Write-Host "Building migration GUI..."
    $dist = Join-Path $ScriptDir 'dist'
    New-Item -ItemType Directory -Force -Path $dist | Out-Null
    # Ensure CLI migrator exists beside GUI
    $cliProj = Join-Path $ScriptDir 'ServerManager.Migrator\ServerManager.Migrator.csproj'
    if (Test-Path $cliProj) {
        dotnet publish $cliProj -c Release -o $dist --nologo
        if ($LASTEXITCODE -ne 0) { throw "Failed to publish ServerManager.Migrator" }
    }
    dotnet publish $proj -c Release -o $dist --nologo
    if ($LASTEXITCODE -ne 0) { throw "Failed to publish ServerManager.Migrator.Gui" }
    $built = Join-Path $dist 'ServerManager.Migrator.Gui.exe'
    if (-not (Test-Path $built)) { throw "GUI exe not found after publish: $built" }
    return (Resolve-Path $built).Path
}

if ($Gui -or ($PSBoundParameters.Count -eq 0 -and -not $SourceRoot -and -not $DestRoot -and [Environment]::UserInteractive)) {
    # Default to GUI when invoked with no migration args (double-click / bare run)
    if ($Gui -or (-not $SourceRoot -and -not $DestRoot -and -not $DryRun -and -not $ClearDestDb -and -not $MigratorExe)) {
        $guiExe = Resolve-MigratorGuiExe
        Write-Host "Launching GUI: $guiExe"
        Start-Process -FilePath $guiExe
        exit 0
    }
}
function Get-RegistryInstallPath {
    $paths = @(
        'HKLM:\Software\SkywereIndustries\Servermanager',
        'HKCU:\Software\SkywereIndustries\Servermanager'
    )
    foreach ($p in $paths) {
        if (Test-Path $p) {
            $v = (Get-ItemProperty -Path $p -ErrorAction SilentlyContinue).InstallPath
            if ($v -and (Test-Path $v)) { return $v }
            $v = (Get-ItemProperty -Path $p -ErrorAction SilentlyContinue).RootPath
            if ($v -and (Test-Path $v)) { return $v }
        }
    }
    return $null
}

function Resolve-SourceRoot([string]$explicit) {
    if ($explicit) { return (Resolve-Path $explicit).Path }
    $candidates = @()
    $reg = Get-RegistryInstallPath
    if ($reg) { $candidates += $reg }
    # Common relative guesses from this toolkit folder (never machine-specific drive letters)
    $repoRuntime = Join-Path (Split-Path $ScriptDir -Parent) 'runtime'
    if (Test-Path (Join-Path $repoRuntime 'db')) { $candidates += (Split-Path $repoRuntime -Parent) }
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c 'db')) { return (Resolve-Path $c).Path }
    }
    throw "Could not resolve SourceRoot. Pass -SourceRoot pointing at the legacy install (folder that contains db\)."
}

function Resolve-DestRoot([string]$explicit) {
    if ($explicit) {
        $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($explicit)
        if (-not (Test-Path $full)) { New-Item -ItemType Directory -Path $full -Force | Out-Null }
        return (Resolve-Path $full).Path
    }
    $repoRuntime = Join-Path (Split-Path $ScriptDir -Parent) 'runtime'
    if (Test-Path $repoRuntime) { return (Resolve-Path $repoRuntime).Path }
    $reg = Get-RegistryInstallPath
    if ($reg) {
        $rt = Join-Path $reg 'runtime'
        if (Test-Path $rt) { return (Resolve-Path $rt).Path }
        return (Resolve-Path $reg).Path
    }
    throw "Could not resolve DestRoot. Pass -DestRoot pointing at the target runtime folder (will contain db\)."
}

function Resolve-MigratorExe([string]$explicit) {
    if ($explicit -and (Test-Path $explicit)) { return (Resolve-Path $explicit).Path }
    $candidates = @(
        (Join-Path $ScriptDir 'dist\ServerManager.Migrator.exe'),
        (Join-Path $ScriptDir 'ServerManager.Migrator\bin\Release\net8.0\ServerManager.Migrator.exe'),
        (Join-Path $ScriptDir 'ServerManager.Migrator\bin\Debug\net8.0\ServerManager.Migrator.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return (Resolve-Path $c).Path }
    }

    # Build on demand
    $proj = Join-Path $ScriptDir 'ServerManager.Migrator\ServerManager.Migrator.csproj'
    if (-not (Test-Path $proj)) { throw "Migrator project not found at $proj" }
    Write-Host "Building migrator..."
    dotnet publish $proj -c Release -o (Join-Path $ScriptDir 'dist') --nologo
    $built = Join-Path $ScriptDir 'dist\ServerManager.Migrator.exe'
    if (-not (Test-Path $built)) { throw "Build succeeded but exe not found: $built" }
    return (Resolve-Path $built).Path
}

$src = Resolve-SourceRoot $SourceRoot
$dst = Resolve-DestRoot $DestRoot
$exe = Resolve-MigratorExe $MigratorExe

$args = @(
    '--source', $src,
    '--dest', $dst
)
if ($DryRun) { $args += '--dry-run' }
if ($ClearDestDb) { $args += '--clear-dest-db' }
if ($SkipUsers) { $args += '--skip-users' }
if ($SkipServers) { $args += '--skip-servers' }
if ($SkipJsonServers) { $args += '--skip-json-servers' }
if ($SkipCluster) { $args += '--skip-cluster' }
if ($SkipCatalogs) { $args += '--skip-catalogs' }
if ($NoCopySsl) { $args += '--copy-ssl', 'false' }
if ($PathRemapFile) {
    if (-not (Test-Path $PathRemapFile)) { throw "Path remap file not found: $PathRemapFile" }
    $args += '--path-remap', (Resolve-Path $PathRemapFile).Path
}

Write-Host "Migrator : $exe"
& $exe @args
exit $LASTEXITCODE
