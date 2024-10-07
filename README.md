# Video Game Updater - Server Manager
Powershell based video game server update manager (mostly for games)

# Installation
1. I have packed a helpful installer along to easily setup the locations (run "install.ps1" with powershell), If you move steamCMD re-run the install.ps1 and tell it where the new directory is as it will update all the registry keys.
2. Upon installation all the git cloned files will be copied to "servermanager" which is meant for copying

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
3. While editing, you can put in the arguements, an example:
   ```
   $arguments = 
    -console
    -game garrysmod
    -secure
    -ip **
    -port 27023
    +clientport 27003
    +map **
    +maxplayers 50
    +gamemode **
    +r_hunkalloclightmaps 0
    -high
    -nod3d9ex
    -r_emulate_gl
    -novid
    -tickrate 33
    +gmod_mcore_test 1
   ```
4. Start the server with running the "startserver.bat" file
5. To stop all servers for shutdown just right click and run the ps1 file named "stop-all-servers.ps1"

# Uninstallation
1. There is also an uninstaller.ps1 file in there and this is used to completely uninstall everything, registry keys and clear the steamcmd directory, if you wish to stop using my program but wish to keep the downloaded games, move the steamcmd folder and run the uninstaller