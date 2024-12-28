# Video Game Updater - Server Manager
Powershell based video game server update manager (mostly for games)

# Troubleshooting
1. If this doesn't load type in "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned" into powershell with admin rights and press Y

# Installation
1. I have packed a helpful installer along to easily setup the locations (run "install.ps1" with powershell), If you move steamCMD re-run the install.ps1 and tell it where the new directory is as it will update all the registry keys.
2. I have also packed an exe too, just download, run in any folder (DO NOT MAKE a "servermanager" folder and run from within steamCMD as it will error trying to merge)
3. Upon installation all the git cloned files will be copied to "servermanager" which is meant for copying

# How to use
1. Edit the file "auto-app-update.ps1" and add all what is required down at the part where you need to input game information
    ```
    EXAMPLE WITHOUT DIR: @{ Name = "Project Zomboid"; AppID = "108600" },
    ```

    ```
    EXAMPLE WITH DIR @{ Name = "Team Fortress 2"; AppID = "232250"; InstallDir = 
    "D:\SteamCMD\steamapps\common\TeamFortress2_DedicatedServer" }
    ```
2. While editing, you can put in the arguements, an example:
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
3. Now you have changed the server now to change the watchdog, edit the "startserver.bat" which comes with the powershell files, in the file is a PATH, do check that this has autoset and working
4. Start the server watchdog with double left clicking the "startserver.bat"
5. To stop all servers for shutdown just right click and run the ps1 file named "stop-all-servers.ps1" and run in powershell

# Uninstallation
1. There is also an uninstaller.ps1 file in there and this is used to completely uninstall everything, including registry keys and complete deletion the steamcmd directory, if you wish to stop using my program but wish to keep the downloaded servers, move the steamcmd folder and run the uninstaller.ps1 with right clicking and "run in powershell"