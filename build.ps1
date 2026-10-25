#Requires -Version 5.1
<#
.SYNOPSIS
  Build Server Manager end-to-end: solution, publish, and shippable dist\.

.DESCRIPTION
  Always:
    - Builds the solution
    - Publishes self-contained win-x64 apps to artifacts\publish\win-x64
    - Stages installer payload and compiles ServerManager-Setup.exe
    - Refreshes dist\ with Setup.exe + install.ps1 + install.sh + README.txt

.EXAMPLE
  .\build.ps1
  .\build.ps1 -Clean -Version 1.0.1
  .\build.ps1 -Test
  .\build.ps1 -Run
#>
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$Version = "1.0.0",
    [switch]$Clean,
    [switch]$Test,
    [switch]$Run
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Artifacts = Join-Path $Root "artifacts"
$PublishDir = Join-Path $Artifacts "publish\$Runtime"
$PayloadDir = Join-Path $Artifacts "payload"
$DistDir = Join-Path $Root "dist"
$RuntimeRoot = Join-Path $Root "runtime"
$IconSrc = Join-Path $Root "icons\servermanager.ico"
$Iss = Join-Path $Root "installer\inno\ServerManager.iss"

function Invoke-DotNet([string[]]$DotNetArgs) {
    & dotnet @DotNetArgs
    if ($LASTEXITCODE -ne 0) { throw "dotnet $($DotNetArgs -join ' ') failed ($LASTEXITCODE)" }
}

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-RuntimeTree {
    foreach ($d in @("logs\components", "temp", "db", "ssl", "www", "config", "icons", "seed\db")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeRoot $d) | Out-Null
    }
    $wwwSrc = Join-Path $Root "www"
    if (Test-Path $wwwSrc) {
        Copy-Item -Path (Join-Path $wwwSrc "*") -Destination (Join-Path $RuntimeRoot "www") -Recurse -Force
    }
    if (Test-Path $IconSrc) {
        Copy-Item $IconSrc (Join-Path $RuntimeRoot "icons\servermanager.ico") -Force
    }

    # Ship Steam / Minecraft / Modded catalog DBs with the product.
    # Prefer existing runtime\db copies; else import from legacy Python Host if present.
    $catalogNames = @("steam_ID.db", "minecraft_ID.db", "minecraft_modded_ID.db")
    $legacyDb = "D:\SteamCMD\Servermanager2\db"
    $seedDb = Join-Path $RuntimeRoot "seed\db"
    $runtimeDb = Join-Path $RuntimeRoot "db"
    New-Item -ItemType Directory -Force -Path $seedDb | Out-Null
    foreach ($name in $catalogNames) {
        $destRuntime = Join-Path $runtimeDb $name
        $destSeed = Join-Path $seedDb $name
        $src = $null
        foreach ($candidate in @(
                (Join-Path $runtimeDb $name),
                (Join-Path $seedDb $name),
                (Join-Path $legacyDb $name)
            )) {
            if ((Test-Path $candidate) -and ((Get-Item $candidate).Length -gt 64000)) {
                $src = $candidate
                break
            }
        }
        if (-not $src) { continue }
        if (-not (Test-Path $destRuntime) -or ((Get-Item $destRuntime).Length -lt 64000)) {
            Copy-Item $src $destRuntime -Force
            Write-Host "    Catalog DB -> runtime\db\$name" -ForegroundColor DarkGray
        }
        Copy-Item $src $destSeed -Force
    }
}

function Get-IsccPath {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        (Join-Path $Root "tools\InnoSetup\ISCC.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

function Install-InnoSetup {
    $local = Join-Path $Root "tools\InnoSetup"
    $iscc = Join-Path $local "ISCC.exe"
    if (Test-Path $iscc) { return $iscc }

    Write-Step "Inno Setup not found - downloading quiet installer into tools"
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools") | Out-Null
    $setup = Join-Path $Root "tools\innosetup-installer.exe"
    $urls = @(
        "https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe",
        "https://jrsoftware.org/download.php/is.exe"
    )
    $downloaded = $false
    foreach ($url in $urls) {
        try {
            Write-Host "    $url"
            Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing -MaximumRedirection 5
            $len = (Get-Item $setup).Length
            $fs = [System.IO.File]::OpenRead($setup)
            try {
                $b0 = $fs.ReadByte(); $b1 = $fs.ReadByte()
            } finally { $fs.Dispose() }
            if ($len -gt 1MB -and $b0 -eq 0x4D -and $b1 -eq 0x5A) { $downloaded = $true; break }
        } catch {
            Write-Host "    download failed: $_" -ForegroundColor Yellow
        }
    }
    if (-not $downloaded) {
        throw "Could not download Inno Setup. Install it manually from https://jrsoftware.org/isinfo.php then re-run .\build.ps1"
    }

    Write-Step "Installing Inno Setup locally -> $local"
    $p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$local`"" -Wait -PassThru
    if ($p.ExitCode -ne 0 -and -not (Test-Path $iscc)) {
        throw "Inno Setup install failed (exit $($p.ExitCode)). Install from https://jrsoftware.org/isinfo.php"
    }
    if (-not (Test-Path $iscc)) {
        $found = Get-IsccPath
        if ($found) { return $found }
        throw "ISCC.exe not found after Inno install"
    }
    return $iscc
}

# --- main ---
Write-Step "Server Manager full build ($Configuration / $Runtime / v$Version)"

if ($Clean) {
    Write-Step "Clean"
    Invoke-DotNet @("clean", "ServerManager.sln", "-c", $Configuration, "--verbosity", "minimal")
    foreach ($d in @($Artifacts, $DistDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
}

Ensure-RuntimeTree

Write-Step "Build solution"
Invoke-DotNet @("build", "ServerManager.sln", "-c", $Configuration, "--verbosity", "minimal")

if ($Test) {
    Write-Step "Tests"
    Invoke-DotNet @("test", "ServerManager.sln", "-c", $Configuration, "--no-build", "--verbosity", "minimal")
}

Write-Step "Publish -> $PublishDir  (self-contained, non-single-file)"
if (Test-Path $PublishDir) { Remove-Item -Recurse -Force $PublishDir }
New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null

# IncludeNativeLibrariesForSelfExtract keeps SQLite natives reliable.
# Non-single-file publish is required so e_sqlite3.dll ships beside the exe.
$selfArgs = @(
    "--self-contained", "true",
    "-p:PublishSingleFile=false",
    "-p:IncludeNativeLibrariesForSelfExtract=true"
)

$projects = @(
    "src\ServerManager.HostRuntime\ServerManager.HostRuntime.csproj",
    "src\ServerManager.Web\ServerManager.Web.csproj",
    "src\ServerManager.Tray\ServerManager.Tray.csproj",
    "src\ServerManager.HostUI\ServerManager.HostUI.csproj",
    "src\ServerManager.AppHost\ServerManager.AppHost.csproj"
)

foreach ($proj in $projects) {
    Write-Host "    $proj"
    $publishArgs = @(
        "publish", $proj,
        "-c", $Configuration,
        "-r", $Runtime,
        "-o", $PublishDir,
        "--verbosity", "minimal"
    ) + $selfArgs
    Invoke-DotNet $publishArgs
}

# www + icon into publish
$publishWww = Join-Path $PublishDir "www"
New-Item -ItemType Directory -Force -Path $publishWww | Out-Null
if (Test-Path (Join-Path $Root "www")) {
    Copy-Item -Path (Join-Path $Root "www\*") -Destination $publishWww -Recurse -Force
}
if (Test-Path $IconSrc) {
    New-Item -ItemType Directory -Force -Path (Join-Path $PublishDir "icons") | Out-Null
    Copy-Item $IconSrc (Join-Path $PublishDir "icons\servermanager.ico") -Force
    Copy-Item $IconSrc (Join-Path $PublishDir "servermanager.ico") -Force
}

# Catalog SQLite DBs ship beside the app (seed) and under runtime\db for RootPath installs
$catalogNames = @("steam_ID.db", "minecraft_ID.db", "minecraft_modded_ID.db")
$publishSeedDb = Join-Path $PublishDir "seed\db"
$publishRuntimeDb = Join-Path $PublishDir "runtime\db"
New-Item -ItemType Directory -Force -Path $publishSeedDb, $publishRuntimeDb | Out-Null
foreach ($name in $catalogNames) {
    $src = $null
    foreach ($candidate in @(
            (Join-Path $RuntimeRoot "seed\db\$name"),
            (Join-Path $RuntimeRoot "db\$name"),
            "D:\SteamCMD\Servermanager2\db\$name"
        )) {
        if ((Test-Path $candidate) -and ((Get-Item $candidate).Length -gt 64000)) { $src = $candidate; break }
    }
    if (-not $src) { Write-Host "    WARN: missing catalog $name" -ForegroundColor Yellow; continue }
    Copy-Item $src (Join-Path $publishSeedDb $name) -Force
    Copy-Item $src (Join-Path $publishRuntimeDb $name) -Force
    Write-Host "    Packaged catalog $name" -ForegroundColor DarkGray
}

# Strip symbols from publish
Get-ChildItem $PublishDir -Filter "*.pdb" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force

# .NET culture satellites cannot live under Lang\ — ship English only and keep Lang\ for custom packs
$satelliteCultures = @("cs", "de", "es", "fr", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "zh-Hans", "zh-Hant")
foreach ($c in $satelliteCultures) {
    $p = Join-Path $PublishDir $c
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
$langOut = Join-Path $PublishDir "Lang"
New-Item -ItemType Directory -Force -Path $langOut | Out-Null
if (Test-Path (Join-Path $Root "Lang")) {
    Copy-Item -Path (Join-Path $Root "Lang\*") -Destination $langOut -Recurse -Force
}

# Dev launcher
$cmdPath = Join-Path $Root "Start-ServerManager.cmd"
@"
@echo off
setlocal
set "ROOT=%~dp0"
set "ServerManager__RootPath=%ROOT%runtime"
cd /d "%ROOT%"
if exist "%ROOT%artifacts\publish\$Runtime\ServerManager.exe" (
  start "" "%ROOT%artifacts\publish\$Runtime\ServerManager.exe"
) else (
  echo ServerManager.exe not found. Run build.ps1 first.
  exit /b 1
)
"@ | Set-Content -Path $cmdPath -Encoding ASCII

Write-Host ""
Write-Host "Publish OK: $PublishDir" -ForegroundColor Green
Get-ChildItem $PublishDir -Filter "ServerManager*.exe" | ForEach-Object {
    $kb = [math]::Round($_.Length / 1KB)
    Write-Host ("    {0}  ({1} KB)" -f $_.Name, $kb)
}

if ($Runtime -ne "win-x64") { throw "Installer packaging currently supports win-x64 only (got $Runtime)" }
if (-not (Test-Path $Iss)) { throw "Missing Inno script: $Iss" }
if (-not (Test-Path $IconSrc)) { throw "Missing icon: $IconSrc" }

Write-Step "Stage installer payload -> $PayloadDir"
if (Test-Path $PayloadDir) { Remove-Item -Recurse -Force $PayloadDir }
New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null
Copy-Item -Path (Join-Path $PublishDir "*") -Destination $PayloadDir -Recurse -Force

@"
@echo off
setlocal
set "ROOT=%~dp0"
set "ServerManager__RootPath=%ROOT%runtime"
cd /d "%ROOT%"
start "" "%ROOT%ServerManager.exe"
"@ | Set-Content -Path (Join-Path $PayloadDir "Start-ServerManager.cmd") -Encoding ASCII

$iscc = Get-IsccPath
if (-not $iscc) { $iscc = Install-InnoSetup }

Write-Step "Compile Setup.exe with $iscc"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
Get-ChildItem $DistDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

$payloadArg = ($PayloadDir -replace '\\', '/')
$outputArg = ($DistDir -replace '\\', '/')
& $iscc "/DMyAppVersion=$Version" "/DPayloadDir=$payloadArg" "/DOutputDir=$outputArg" $Iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }

Copy-Item (Join-Path $Root "installer\install.ps1") (Join-Path $DistDir "install.ps1") -Force
Copy-Item (Join-Path $Root "installer\install.sh") (Join-Path $DistDir "install.sh") -Force

@"
Server Manager — distribution package
=====================================

Windows (recommended):
  Run ServerManager-Setup.exe as Administrator.

Windows (script / automation):
  PowerShell (admin):
    .\install.ps1
    .\install.ps1 -AsService -StartAfterInstall
    .\install.ps1 -RepoUrl https://github.com/ORG/servermanager.git

Linux:
  sudo REPO_URL=https://github.com/ORG/servermanager.git bash install.sh

Notes:
  - Server configs are stored in SQLite under runtime\db\ (not JSON files).
  - Catalog DBs (steam_ID.db, minecraft_ID.db, minecraft_modded_ID.db) ship in runtime\db and seed\db.
  - Default login: admin / admin
  - Default ports: Web 18080; HostRuntime 18091; Cluster 15001
  - Version: $Version
"@ | Set-Content -Path (Join-Path $DistDir "README.txt") -Encoding UTF8

Write-Host ""
Write-Host "Full build complete. dist\ ready to ship:" -ForegroundColor Green
Get-ChildItem $DistDir | ForEach-Object {
    $kb = if ($_.PSIsContainer) { "dir" } else { "{0} KB" -f [math]::Round($_.Length / 1KB) }
    Write-Host ("    {0}  ({1})" -f $_.Name, $kb)
}

if ($Run) {
    Write-Step "Starting ServerManager.exe"
    $exe = Join-Path $PublishDir "ServerManager.exe"
    if (-not (Test-Path $exe)) { throw "Missing $exe" }
    $env:ServerManager__RootPath = $RuntimeRoot
    Start-Process -FilePath $exe -WorkingDirectory $PublishDir
}
