import json
import os
import urllib.request
import logging

# Get logger for this module
logger = logging.getLogger(__name__)


def fetch_minecraft_versions():
    """Fetch available Minecraft server versions from Mojang's manifest."""
    try:
        manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        with urllib.request.urlopen(manifest_url, timeout=10) as resp:
            manifest = json.load(resp)
        versions = []
        for v in manifest["versions"]:
            if v["type"] in ("release", "snapshot"):
                versions.append({
                    "id": v["id"],
                    "type": v["type"],
                    "url": v["url"]
                })
        return versions
    except Exception as e:
        logger.error(f"Failed to fetch Minecraft versions: {str(e)}")
        return []


def get_minecraft_server_jar_url(version_id, versions_list):
    """Get the download URL for the server jar for a given version."""
    try:
        for v in versions_list:
            if v["id"] == version_id:
                with urllib.request.urlopen(v["url"], timeout=10) as resp:
                    version_data = json.load(resp)
                return version_data["downloads"]["server"]["url"]
    except Exception as e:
        logger.error(f"Failed to get server jar URL for {version_id}: {str(e)}")
    return None


def fetch_fabric_installer_url(mc_version):
    """Fetch Fabric installer URL for a given Minecraft version."""
    try:
        meta_url = "https://meta.fabricmc.net/v2/versions/installer"
        with urllib.request.urlopen(meta_url, timeout=10) as resp:
            installers = json.load(resp)
        if installers:
            return installers[0]["url"]
    except Exception as e:
        logger.error(f"Failed to fetch Fabric installer: {str(e)}")
    return None


def fetch_forge_installer_url(mc_version):
    """Fetch Forge installer URL for a given Minecraft version."""
    try:
        meta_url = f"https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
        with urllib.request.urlopen(meta_url, timeout=10) as resp:
            promotions = json.load(resp)
        key = f"{mc_version}-recommended"
        if key in promotions["promos"]:
            forge_version = promotions["promos"][key]
            url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
            return url
    except Exception as e:
        logger.error(f"Failed to fetch Forge installer: {str(e)}")
    return None


def fetch_neoforge_installer_url(mc_version):
    """Fetch NeoForge installer URL for a given Minecraft version."""
    try:
        meta_url = f"https://api.neoforged.net/v1/projects/neoforge/versions?game_versions={mc_version}"
        with urllib.request.urlopen(meta_url, timeout=10) as resp:
            versions = json.load(resp)
        if versions:
            # Pick latest version for this MC version
            version = versions[0]
            url = version.get("installer_url")
            if url:
                return url
    except Exception as e:
        logger.error(f"Failed to fetch NeoForge installer: {str(e)}")
    return None


class MinecraftServerManager:
    """Class to manage Minecraft server operations and installations."""
    
    def __init__(self, server_manager_dir, config=None):
        """Initialize the Minecraft server manager.
        
        Args:
            server_manager_dir (str): Base directory for server manager
            config (dict): Configuration dictionary
        """
        self.server_manager_dir = server_manager_dir
        self.config = config or {}
    
    def get_minecraft_install_path(self, server_name):
        """Get the installation path for a Minecraft server.
        
        Args:
            server_name (str): Name of the server
            
        Returns:
            str: Full path to the server installation directory
        """
        minecraft_path = self.config.get("defaults", {}).get("minecraftServersPath", "minecraft_servers")
        return os.path.join(self.server_manager_dir, minecraft_path, server_name)
    
    def create_eula_file(self, install_dir):
        """Create EULA acceptance file for Minecraft server.
        
        Args:
            install_dir (str): Directory where the server is installed
        """
        import os
        eula_path = os.path.join(install_dir, "eula.txt")
        with open(eula_path, "w") as f:
            f.write("eula=true\n")
        logger.info(f"Created EULA file at: {eula_path}")
    
    def download_server_jar(self, version_id, versions_list, install_dir, jar_name=None):
        """Download Minecraft server jar file.
        
        Args:
            version_id (str): Minecraft version ID
            versions_list (list): List of available versions
            install_dir (str): Directory to download the jar to
            jar_name (str): Optional custom jar filename
            
        Returns:
            str: Path to the downloaded jar file
        """
        import os
        
        jar_url = get_minecraft_server_jar_url(version_id, versions_list)
        if not jar_url:
            raise Exception(f"Could not get download URL for Minecraft {version_id}")
        
        jar_filename = jar_name or f"minecraft_server.{version_id}.jar"
        jar_path = os.path.join(install_dir, jar_filename)
        
        logger.info(f"Downloading Minecraft server {version_id} to {jar_path}")
        urllib.request.urlretrieve(jar_url, jar_path)
        logger.info("Download complete.")
        
        return jar_path
