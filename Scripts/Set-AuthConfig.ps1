$ErrorActionPreference = 'Stop'

# Get registry paths
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

# Config file path
$configPath = Join-Path $serverManagerDir "config\auth.xml"

# Create config directory if it doesn't exist
$configDir = Split-Path $configPath -Parent
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir | Out-Null
}

Write-Host "Authentication Configuration Setup" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

# LDAP Configuration
$ldapEnabled = Read-Host "Enable LDAP authentication? (y/n)"
$ldapConfig = @{
    Enabled = $ldapEnabled -eq 'y'
    Server = ""
    Domain = ""
}

if ($ldapEnabled -eq 'y') {
    $ldapConfig.Server = Read-Host "Enter LDAP server (e.g., dc01.domain.com)"
    $ldapConfig.Domain = Read-Host "Enter LDAP domain (e.g., domain.com)"
}

# Local Windows Authentication
$localEnabled = Read-Host "Enable Local Windows authentication? (y/n)"
$localConfig = @{
    Enabled = $localEnabled -eq 'y'
}

# File-based Authentication
$fileEnabled = Read-Host "Enable File-based authentication? (y/n)"
$fileConfig = @{
    Enabled = $fileEnabled -eq 'y'
    Path = Join-Path $serverManagerDir "config\users.xml"
}

if ($fileEnabled -eq 'y') {
    # Create initial users file if it doesn't exist
    $usersFile = $fileConfig.Path
    if (!(Test-Path $usersFile)) {
        $admin = Read-Host "Enter admin username"
        $adminPass = Read-Host "Enter admin password" -AsSecureString
        $adminPassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPass)
        )
        
        $users = @(
            @{
                Username = $admin
                PasswordHash = Get-HashString $adminPassPlain
                IsAdmin = $true
            }
        )
        $users | Export-Clixml -Path $usersFile
    }
}

# Create final config
$config = @{
    LDAP = $ldapConfig
    Local = $localConfig
    File = $fileConfig
}

# Export configuration
$config | Export-Clixml -Path $configPath

Write-Host "Authentication configuration saved successfully" -ForegroundColor Green
