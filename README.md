# Video Game Updater - Server Manager
Powershell based video game server update manager (mostly for games)

# How to use
1. When using this program what you will need to do is either run the exe (no admin needed) | If this doesn't load type in "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned" into powershell with admin rights and press Y
2. Edit the file "auto-app-update.ps1" and add all what is required down at the part where you need to input game information
    ```
    EXAMPLE WITHOUT DIR: @{ Name = "Project Zomboid"; AppID = "108600" },
    ```
    
    ```
    EXAMPLE WITH DIR @{ Name = "Team Fortress 2"; AppID = "232250"; InstallDir = 
    "D:\SteamCMD\steamapps\common\TeamFortress2_DedicatedServer" }
    ```
3. Right click the PS1 file and "run in powershell"