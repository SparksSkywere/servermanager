Add-Type -AssemblyName System.Windows.Forms

$serverManagerPath = Join-Path $PSScriptRoot "..\Modules\ServerManager.psm1"
Import-Module $serverManagerPath -Force

# Function to remove a game server
function Remove-GameServer {
    # Prompt user for server details
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Remove Game Server"
    $form.Width = 400
    $form.Height = 200
    $form.StartPosition = "CenterScreen"

    $nameLabel = New-Object System.Windows.Forms.Label
    $nameLabel.Text = "Server Name:"
    $nameLabel.Location = New-Object System.Drawing.Point(10, 20)
    $form.Controls.Add($nameLabel)

    $nameTextBox = New-Object System.Windows.Forms.TextBox
    $nameTextBox.Location = New-Object System.Drawing.Point(120, 20)
    $form.Controls.Add($nameTextBox)

    $destroyButton = New-Object System.Windows.Forms.Button
    $destroyButton.Text = "Remove"
    $destroyButton.Location = New-Object System.Drawing.Point(120, 60)
    $destroyButton.Add_Click({
        $serverName = $nameTextBox.Text

        if (-not [string]::IsNullOrEmpty($serverName)) {
            # Call the relevant script or function to remove a game server
            .\stop-all-servers.ps1 -ServerName $serverName
            [System.Windows.Forms.MessageBox]::Show("Game server removed successfully.", "Success")
            $form.Close()
        } else {
            [System.Windows.Forms.MessageBox]::Show("Please enter the server name.", "Error")
        }
    })
    $form.Controls.Add($destroyButton)

    $form.ShowDialog()
}

# Function to remove a server instance
function Remove-ServerInstance {
    param (
        [string]$ServerName
    )
    Logging "Removing server instance: $ServerName..."
    # ...existing code...
}

# Function to connect to the PID console
function Connect-PIDConsole {
    param (
        [int]$ProcessId
    )
    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $process | Out-Host
    } catch {
        Write-Host "Failed to connect to process (PID: $ProcessId): $_" -ForegroundColor Red
    }
}

Remove-GameServer
