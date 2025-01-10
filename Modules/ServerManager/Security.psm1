using namespace System.Security.Cryptography
using namespace System.Text

function New-Salt {
    $salt = New-Object byte[] 32
    $rng = [RNGCryptoServiceProvider]::new()
    $rng.GetBytes($salt)
    return [Convert]::ToBase64String($salt)
}

function Get-SecureHash {
    param(
        [SecureString]$SecurePassword,
        [string]$Salt
    )
    
    try {
        # Convert SecureString to byte array
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
        $passBytes = [byte[]][char[]][Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        
        # Combine password with salt
        $saltBytes = [Convert]::FromBase64String($Salt)
        $combined = $passBytes + $saltBytes
        
        # Use SHA512 for better security
        $hash = [SHA512]::Create().ComputeHash($combined)
        
        # Clean up sensitive data
        [Array]::Clear($passBytes, 0, $passBytes.Length)
        [Array]::Clear($combined, 0, $combined.Length)
        
        return [Convert]::ToBase64String($hash)
    }
    finally {
        if ($hash) { [Array]::Clear($hash, 0, $hash.Length) }
    }
}

function Protect-ConfigFile {
    param([string]$FilePath)
    
    try {
        # Create a unique encryption key for this machine
        $key = [Byte[]]::new(32)
        $rng = [RNGCryptoServiceProvider]::new()
        $rng.GetBytes($key)
        
        # Store the key in Windows Credential Manager
        $keyBase64 = [Convert]::ToBase64String($key)
        $cred = New-Object PSCredential "ServerManagerEncryption", ($keyBase64 | ConvertTo-SecureString -AsPlainText -Force)
        [System.Management.Automation.PSCredential]::new("ServerManagerEncryption", $cred.Password) | 
            Export-Clixml -Path (Join-Path $env:ProgramData "ServerManager\encryption.key")
            
        # Set strong file permissions
        $acl = Get-Acl $FilePath
        $acl.SetAccessRuleProtection($true, $false)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "FullControl", "Allow")
        $acl.AddAccessRule($rule)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $env:USERNAME, "FullControl", "Allow")
        $acl.AddAccessRule($rule)
        Set-Acl $FilePath $acl
        
    }
    finally {
        if ($key) { [Array]::Clear($key, 0, $key.Length) }
    }
}

Export-ModuleMember -Function New-Salt, Get-SecureHash, Protect-ConfigFile
