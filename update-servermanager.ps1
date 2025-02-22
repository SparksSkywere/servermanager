# Function to update (pull) or clone Git repository
function Update-GitRepo {
    param (
        [string]$repoUrl,
        [string]$destination
    )
    
    Write-Host "Updating Git repository at $destination"
    try {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            if (Test-Path -Path (Join-Path $destination ".git")) {
                Write-Host "Existing Git repository found."
                Set-Location -Path $destination
                
                # Fetch updates
                Write-Host "Fetching updates..."
                git fetch origin
                
                # Get current branch name
                $currentBranch = git rev-parse --abbrev-ref HEAD
                
                # Reset to origin
                Write-Host "Resetting to latest version..."
                git reset --hard "origin/$currentBranch"
                
                Set-Location -Path $PSScriptRoot
                Write-Host "Git repository updated successfully."
            } else {
                Write-Host "No Git repository found. Please run the installer first."
                exit 1
            }
        } else {
            Write-Host "Git is not installed or not found in the PATH."
            exit 1
        }
    } catch {
        Write-Host "Failed to update Git repository: $($_.Exception.Message)"
        throw
    }
}

# Main update script
try {
    # Get installation directory from registry
    $registryPath = "HKLM:\Software\SkywereIndustries\Servermanager"
    if (-not (Test-Path $registryPath)) {
        throw "Server Manager is not installed. Please run the installer first."
    }

    $serverManagerDir = Get-ItemProperty -Path $registryPath -Name "Servermanagerdir" -ErrorAction Stop | Select-Object -ExpandProperty Servermanagerdir
    $gitRepoUrl = "https://github.com/SparksSkywere/servermanager.git"

    # Update repository
    Update-GitRepo -repoUrl $gitRepoUrl -destination $serverManagerDir

    # Update last update time in registry
    Set-ItemProperty -Path $registryPath -Name "LastUpdate" -Value (Get-Date).ToString('o')

    Write-Host "Update completed successfully." -ForegroundColor Green
}
catch {
    Write-Host "Update failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
