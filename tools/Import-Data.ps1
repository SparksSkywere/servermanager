param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [string]$DestRoot = "",
    [string]$PathRemapFile,
    [switch]$DryRun,
    [switch]$ClearDestDb,
    [switch]$RawCopy
)

<#
.SYNOPSIS
  Import legacy Server Manager data into a runtime root.

.DESCRIPTION
  By default delegates to migration\Migrate-ServerManager.ps1 (schema-aware).
  Use -RawCopy for a blind file copy of db\ and ssl\ only (no column remapping).
#>

$ErrorActionPreference = "Stop"
if (-not (Test-Path $SourceRoot)) { throw "Source not found: $SourceRoot" }

if ([string]::IsNullOrWhiteSpace($DestRoot)) {
    $repo = Split-Path $PSScriptRoot -Parent
    if (Test-Path (Join-Path $repo "ServerManager.sln")) {
        $DestRoot = Join-Path $repo "runtime"
    } else {
        $DestRoot = Join-Path (Split-Path $PSScriptRoot -Parent) "runtime"
    }
}

if ($RawCopy) {
    Write-Host "Raw-copying data from $SourceRoot to $DestRoot"
    New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "db") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot "ssl") | Out-Null

    $dbSrc = Join-Path $SourceRoot "db"
    if (Test-Path $dbSrc) {
        Copy-Item -Path (Join-Path $dbSrc "*") -Destination (Join-Path $DestRoot "db") -Force
        Write-Host "Copied databases"
    }

    $sslSrc = Join-Path $SourceRoot "ssl"
    if (Test-Path $sslSrc) {
        Copy-Item -Path (Join-Path $sslSrc "*") -Destination (Join-Path $DestRoot "ssl") -Force
        Write-Host "Copied ssl"
    }

    Write-Host "Import complete (raw copy)."
    return
}

$migrator = Join-Path (Split-Path $PSScriptRoot -Parent) "migration\Migrate-ServerManager.ps1"
if (-not (Test-Path $migrator)) {
    throw "Schema-aware migrator not found at $migrator. Use -RawCopy for blind file copy."
}

$args = @{
    SourceRoot = $SourceRoot
    DestRoot   = $DestRoot
}
if ($PathRemapFile) { $args.PathRemapFile = $PathRemapFile }
if ($DryRun) { $args.DryRun = $true }
if ($ClearDestDb) { $args.ClearDestDb = $true }

& $migrator @args
exit $LASTEXITCODE
