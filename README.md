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
4. Right click the PS1 file and "run in powershell"
5. To stop all servers for shutdown just right click and run the ps1 file named "end_all.ps1"