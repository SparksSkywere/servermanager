# Remove any private module references at the start
$registryPath = "HKLM:\Software\SkywereIndustries\servermanager"

# Direct module imports - no folder structure
$requiredModules = @(
    "Security.psm1",
    "Network.psm1"
)

# Import modules directly from Modules directory
foreach ($module in $requiredModules) {
    $modulePath = Join-Path $PSScriptRoot $module
    if (Test-Path $modulePath) {
        Import-Module $modulePath -Force
    }
}

$serverManagerDir = (Get-ItemProperty -Path $registryPath).servermanagerdir

function Test-Credentials {
    param(
        [string]$Username,
        [string]$Password,
        [string]$AuthType
    )

    switch ($AuthType) {
        "LDAP" {
            return Test-LDAPCredentials -Username $Username -Password $Password
        }
        "Local" {
            return Test-LocalCredentials -Username $Username -Password $Password
        }
        "File" {
            return Test-FileCredentials -Username $Username -Password $Password
        }
        default {
            throw "Unsupported authentication type: $AuthType"
        }
    }
}

function Test-LDAPCredentials {
    param($Username, $Password)
    try {
        $config = Get-AuthConfig
        if (!$config.LDAP.Enabled) { return $false }

        $ldapPath = "LDAP://" + $config.LDAP.Server
        $userEntry = New-Object System.DirectoryServices.DirectoryEntry(
            $ldapPath, 
            "$Username@$($config.LDAP.Domain)", 
            $Password
        )
        return $userEntry.name -ne $null
    }
    catch {
        Write-Error "LDAP authentication error: $($_.Exception.Message)"
        return $false
    }
}

function Test-LocalCredentials {
    param($Username, $Password)
    try {
        $config = Get-AuthConfig
        if (!$config.Local.Enabled) { return $false }

        $securePassword = ConvertTo-SecureString $Password -AsPlainText -Force
        $credential = New-Object System.Management.Automation.PSCredential($Username, $securePassword)
        
        # Try to validate against local Windows accounts
        $result = Start-Process cmd.exe -Credential $credential -ArgumentList "/c echo test" -WindowStyle Hidden -Wait -PassThru
        return $result.ExitCode -eq 0
    }
    catch {
        Write-Error "Local authentication error: $($_.Exception.Message)"
        return $false
    }
}

function Test-FileCredentials {
    param($Username, $Password)
    try {
        $config = Get-AuthConfig
        if (!$config.File.Enabled) { return $false }

        $usersFile = $config.File.Path
        if (!(Test-Path $usersFile)) { return $false }

        $users = Import-Clixml -Path $usersFile
        $user = $users | Where-Object { $_.Username -eq $Username }
        
        if (!$user) { return $false }

        $hashedPassword = Get-HashString $Password
        return $user.PasswordHash -eq $hashedPassword
    }
    catch {
        Write-Error "File authentication error: $($_.Exception.Message)"
        return $false
    }
}

function Get-HashString {
    param([string]$InputString)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($InputString)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return [Convert]::ToBase64String($hash)
}

function Get-AuthConfig {
    $configPath = Join-Path $serverManagerDir "config\auth.xml"
    if (Test-Path $configPath) {
        return Import-Clixml -Path $configPath
    }
    throw "Authentication configuration not found"
}

# Remove any private folder references if they exist
# ...existing code...

Export-ModuleMember -Function *
