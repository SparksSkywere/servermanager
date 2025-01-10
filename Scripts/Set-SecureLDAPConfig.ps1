$ErrorActionPreference = 'Stop'

# Get registry path
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"
$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

# Config file path
$configPath = Join-Path $serverManagerDir "config\ldap.xml"

# Create config directory if it doesn't exist
$configDir = Split-Path $configPath -Parent
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir | Out-Null
}

# Prompt for LDAP configuration
$ldapServer = Read-Host "Enter LDAP server (e.g., dc01.domain.com)"
$ldapDomain = Read-Host "Enter LDAP domain (e.g., domain.com)"
$servicePrincipal = Read-Host "Enter service account username"
$servicePassword = Read-Host "Enter service account password" -AsSecureString

# Create credential object and convert to encrypted string
$credential = New-Object System.Management.Automation.PSCredential($servicePrincipal, $servicePassword)
$encryptedPassword = $credential.Password | ConvertFrom-SecureString

# Create configuration object
$config = @{
    LDAPServer = $ldapServer
    Domain = $ldapDomain
    ServicePrincipal = $servicePrincipal
    EncryptedPassword = $encryptedPassword
}

# Export to encrypted XML
$config | Export-Clixml -Path $configPath

Write-Host "LDAP configuration has been securely saved to $configPath" -ForegroundColor Green
