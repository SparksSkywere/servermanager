# Minecraft server management
import os
import sys
import json
import urllib.request
import subprocess
import re
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path, setup_module_logging
setup_module_path()

logger: logging.Logger = setup_module_logging("Minecraft")

# Common Java installation base directories on Windows used by find_java_installations() to discover available JDK/JRE installs
WINDOWS_JAVA_SEARCH_PATHS = [
    r"C:\Program Files\Java",
    r"C:\Program Files (x86)\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Eclipse Foundation",
    r"C:\Program Files\Amazon Corretto",
    r"C:\Program Files\Microsoft",
    r"C:\Program Files\Zulu",
]

def get_java_version(java_path="java"):
    # Get Java version from executable
    try:
        logger.debug(f"[SUBPROCESS_TRACE] get_java_version: {java_path}")
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = subprocess.CREATE_NO_WINDOW
            logger.debug(f"[SUBPROCESS_TRACE] CREATE_NO_WINDOW: {creationflags}")

        logger.debug("[SUBPROCESS_TRACE] Running java -version")
        result = subprocess.run([java_path, '-version'], capture_output=True, text=True, timeout=10,
                               startupinfo=startupinfo, creationflags=creationflags)
        logger.debug(f"[SUBPROCESS_TRACE] returncode: {result.returncode}")
        version_output = result.stderr

        # Parse version-handles "1.8.0_271" and "21.0.1" formats
        version_match = re.search(r'version "([^"]+)"', version_output)
        if version_match:
            version_str = version_match.group(1)

            if version_str.startswith('1.'):
                major_version = int(version_str.split('.')[1])
            else:
                major_version = int(version_str.split('.')[0])

            return major_version, version_str

    except Exception as e:
        logger.debug(f"Java version check failed: {java_path} - {str(e)}")

    return None, None

def detect_java_installations():
    # Find all Java installations on system and returns list of {"path", "version", "major"} dicts
    java_installations = []

    # Check default Java in PATH
    major, version = get_java_version("java")
    if major is not None:
        java_installations.append({
            "path": "java",
            "version": version,
            "major": major,
            "display_name": f"System Default (Java {major})"
        })

    # Scan common Java installation paths on Windows
    if os.name == 'nt':
        for base_path in WINDOWS_JAVA_SEARCH_PATHS:
            if os.path.exists(base_path):
                try:
                    for item in os.listdir(base_path):
                        java_dir = os.path.join(base_path, item)
                        if os.path.isdir(java_dir):
                            # Look for java.exe in bin directory
                            java_exe = os.path.join(java_dir, "bin", "java.exe")
                            if os.path.exists(java_exe):
                                major, version = get_java_version(java_exe)
                                if major is not None:
                                    # Create a descriptive display name
                                    if "jdk" in item.lower():
                                        display_name = f"JDK {major} ({item})"
                                    elif "jre" in item.lower():
                                        display_name = f"JRE {major} ({item})"
                                    else:
                                        display_name = f"Java {major} ({item})"

                                    java_installations.append({
                                        "path": java_exe,
                                        "version": version,
                                        "major": major,
                                        "display_name": display_name
                                    })
                except Exception as e:
                    logger.debug(f"Error scanning {base_path}: {str(e)}")

    # Remove duplicates based on version and path
    unique_installations = []
    seen_versions = set()
    for installation in java_installations:
        key = (installation["major"], installation["path"])
        if key not in seen_versions:
            seen_versions.add(key)
            unique_installations.append(installation)

    # Sort by major version (newest first)
    unique_installations.sort(key=lambda x: x["major"], reverse=True)

    return unique_installations

def get_recommended_java_for_minecraft(version_id):
    # Get the recommended Java installation for a specific Minecraft version
    required_java = get_minecraft_java_requirement(version_id)
    available_javas = detect_java_installations()

    # Find the best match - prefer the lowest version that meets requirements
    suitable_javas = [j for j in available_javas if j["major"] >= required_java]

    if suitable_javas:
        # Sort by major version (lowest suitable version first)
        suitable_javas.sort(key=lambda x: x["major"])
        return suitable_javas[0]

    return None

def get_minecraft_java_requirement(version_id):
    # Get the minimum Java version required for a Minecraft version
    try:
        # Parse version to determine Java requirements
        if version_id.startswith('1.'):
            version_parts = version_id.split('.')
            if len(version_parts) >= 2:
                major = int(version_parts[1])
                if major <= 16:
                    # MC 1.16 and earlier: Java 8+
                    return 8
                elif major == 17:
                    # MC 1.17: Java 16+
                    return 16
                elif major <= 20:
                    # MC 1.18-1.20: Java 17+
                    return 17
                else:
                    # MC 1.21+: Java 21+
                    return 21

        # Snapshots (like 25w16a) are typically for the next major version and most recent snapshots require Java 21+
        if 'w' in version_id:  # Weekly snapshots
            return 21

        # Default to Java 21 for unknown versions (future-proofing)
        return 21

    except Exception:
        # Default to Java 17 if we can't parse the version
        return 17

def check_java_compatibility(version_id, java_path="java"):
    # Check if a Java installation is compatible with a Minecraft version
    java_major, java_full = get_java_version(java_path)
    required_java = get_minecraft_java_requirement(version_id)

    if java_major is None:
        return False, None, required_java, f"Java is not installed or not accessible at {java_path}"

    is_compatible = java_major >= required_java

    if is_compatible:
        message = f"Java {java_full} at {java_path} is compatible with Minecraft {version_id}"
    else:
        message = f"Java {java_full} at {java_path} is incompatible with Minecraft {version_id}. Requires Java {required_java} or later."

    return is_compatible, java_major, required_java, message

def fetch_minecraft_versions():
    # Fetch available Minecraft server versions from Mojang's manifest
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
    # Get the download URL for the server jar for a given version
    try:
        # First check if the version exists in the list
        version_info = None
        for v in versions_list:
            if v["id"] == version_id:
                version_info = v
                break

        if not version_info:
            logger.error(f"Version {version_id} not found in available versions")
            return None

        # Fetch the version-specific manifest
        with urllib.request.urlopen(version_info["url"], timeout=10) as resp:
            version_data = json.load(resp)

        # Check if server download is available
        downloads = version_data.get("downloads", {})
        server_download = downloads.get("server")
        if not server_download:
            logger.error(f"Server download not available for version {version_id}")
            return None

        return server_download["url"]
    except Exception as e:
        logger.error(f"Failed to get server jar URL for {version_id}: {str(e)}")
        return None

def fetch_fabric_installer_url(mc_version):
    # Fetch Fabric installer URL for a given Minecraft version
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
    # Fetch Forge installer URL for a given Minecraft version
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
    # Fetch NeoForge installer URL for a given Minecraft version
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
    # Class to manage Minecraft server operations and installations

    def __init__(self, server_manager_dir, config=None):
        # Initialise the Minecraft server manager
        self.server_manager_dir = server_manager_dir
        self.config = config or {}

    def create_launch_script(self, install_dir, jar_file, memory_mb=1024, additional_args="", java_path="java"):
        # Create a platform-specific launch script for the Minecraft server
        import os

        # Windows
        if os.name == 'nt':
            script_path = os.path.join(install_dir, "start_server.bat")
            with open(script_path, "w", encoding='utf-8') as f:
                f.write("@echo off\n")
                f.write("echo Starting Minecraft Server...\n")
                f.write(f'"{java_path}" -Xmx{memory_mb}M -Xms{memory_mb}M -jar "{jar_file}" nogui {additional_args}\n')
                f.write("echo Server stopped.\n")
                f.write("pause\n")
        # Unix/Linux
        else:
            script_path = os.path.join(install_dir, "start_server.sh")
            with open(script_path, "w", encoding='utf-8') as f:
                f.write("#!/bin/bash\n")
                f.write("echo \"Starting Minecraft Server...\"\n")
                f.write(f'"{java_path}" -Xmx{memory_mb}M -Xms{memory_mb}M -jar "{jar_file}" nogui {additional_args}\n')
                f.write("echo \"Server stopped.\"\n")
            os.chmod(script_path, 0o755)

        logger.info(f"Created launch script at: {script_path}")
        return script_path

    def detect_server_executable(self, install_dir):
        # Detect the server executable in an installation directory
        import os

        if not os.path.exists(install_dir):
            return None, None

        # Look for JAR files first (preferred)
        jar_candidates = []
        script_candidates = []

        for file in os.listdir(install_dir):
            file_lower = file.lower()

            # JAR files
            if file_lower.endswith('.jar'):
                if any(keyword in file_lower for keyword in [
                    'server', 'minecraft', 'forge', 'fabric', 'spigot', 'paper', 'bukkit', 'neoforge'
                ]):
                    jar_candidates.append(file)

            # Script files
            elif file_lower.endswith(('.bat', '.cmd')) and os.name == 'nt':
                if any(keyword in file_lower for keyword in [
                    'run', 'start', 'server', 'launch'
                ]):
                    script_candidates.append(file)

            elif file_lower.endswith('.sh') and os.name != 'nt':
                if any(keyword in file_lower for keyword in [
                    'run', 'start', 'server', 'launch'
                ]):
                    script_candidates.append(file)

        # Prioritize JAR files over scripts
        if jar_candidates:
            # Sort by preference
            jar_candidates.sort(key=lambda x: (
                0 if 'server' in x.lower() else
                1 if any(mod in x.lower() for mod in ['forge', 'fabric', 'neoforge']) else
                2 if any(impl in x.lower() for impl in ['spigot', 'paper', 'bukkit']) else
                3
            ))
            return 'jar', os.path.join(install_dir, jar_candidates[0])

        elif script_candidates:
            return 'script', os.path.join(install_dir, script_candidates[0])

        return None, None