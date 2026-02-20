#!/usr/bin/env python3
# Java config utility for Minecraft
import os
import sys
import argparse

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Modules.common import setup_module_path
setup_module_path()

from Modules.minecraft import (
    detect_java_installations,
    get_recommended_java_for_minecraft,
    check_java_compatibility,
    get_minecraft_java_requirement
)


def list_java_installations():
    # List detected Java installs
    print("Detected Java Installations:")
    print("=" * 50)
    
    installations = detect_java_installations()
    
    if not installations:
        print("No Java installations found.")
        return
    
    for i, java in enumerate(installations, 1):
        print(f"{i}. {java['display_name']}")
        print(f"   Path: {java['path']}")
        print(f"   Version: {java['version']}")
        print()


def list_servers():
    # List configured servers from database
    try:
        from Modules.Database.server_configs_database import ServerConfigManager
        manager = ServerConfigManager()
        all_servers = manager.get_all_servers()
        
        servers = []
        for config in all_servers:
            try:
                if config.get("Type") == "Minecraft":
                    servers.append(config)
            except Exception as e:
                print(f"Error processing server config: {e}")
        
        return servers
    except Exception as e:
        print(f"Server list error: {e}")
        return []


def check_server_java_compatibility(server_config):
    # Check Java compatibility for a server
    server_name = server_config.get("Name", "Unknown")
    version = server_config.get("Version", "Unknown")
    java_path = server_config.get("JavaPath", "java")
    
    print(f"\nServer: {server_name}")
    print(f"Minecraft Version: {version}")
    print(f"Current Java: {java_path}")
    
    if version != "Unknown":
        required_java = get_minecraft_java_requirement(version)
        print(f"Required Java: {required_java}+")
        
        is_compatible, java_version, _, message = check_java_compatibility(version, java_path)
        print(f"Compatibility: {'✓ Compatible' if is_compatible else '✗ Incompatible'}")
        
        if not is_compatible:
            # Suggest a better Java
            recommended = get_recommended_java_for_minecraft(version)
            if recommended:
                print(f"Recommended: {recommended['display_name']} at {recommended['path']}")
            else:
                print("No suitable Java installation found.")
    
    print("-" * 50)


def configure_server_java(server_name, java_path=None):
    # Configure Java for a specific server using database
    try:
        from Modules.Database.server_configs_database import ServerConfigManager
        manager = ServerConfigManager()
        
        config = manager.get_server(server_name)
        if not config:
            print(f"Server configuration not found: {server_name}")
            return False
        
        if config.get("Type") != "Minecraft":
            print(f"Server '{server_name}' is not a Minecraft server.")
            return False
        
        # If no Java path specified, suggest one
        if not java_path:
            version = config.get("Version")
            if version:
                recommended = get_recommended_java_for_minecraft(version)
                if recommended:
                    java_path = recommended['path']
                    print(f"Auto-selected: {recommended['display_name']}")
                else:
                    print("No suitable Java installation found.")
                    return False
            else:
                print("Cannot determine Minecraft version for auto-selection.")
                return False
        
        # Update configuration
        config["JavaPath"] = java_path
        config["LastUpdate"] = "2025-07-28T01:30:00"
        
        # Save configuration to database
        manager.update_server(server_name, config)
        
        print(f"Updated '{server_name}' to use Java at: {java_path}")
        
        # Update launch script
        from Modules.minecraft import MinecraftServerManager
        mc_manager = MinecraftServerManager("", {})
        
        install_dir = config.get("InstallDir", "")
        if install_dir and os.path.exists(install_dir):
            executable_path = config.get("ExecutablePath", "")
            jar_file = os.path.basename(executable_path) if executable_path else "server.jar"
            
            script_path = mc_manager.create_launch_script(install_dir, jar_file, 1024, "", java_path)
            print(f"Updated launch script: {script_path}")
        
        return True
        
    except Exception as e:
        print(f"Error configuring server: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Java Configuration Utility for Server Manager")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List Java installations
    subparsers.add_parser('list-java', help='List detected Java installations')
    
    # List servers
    subparsers.add_parser('list-servers', help='List all Minecraft servers')
    
    # Check compatibility
    check_parser = subparsers.add_parser('check', help='Check Java compatibility for servers')
    check_parser.add_argument('--server', help='Specific server to check (optional)')
    
    # Configure server
    config_parser = subparsers.add_parser('configure', help='Configure Java for a server')
    config_parser.add_argument('server', help='Server name to configure')
    config_parser.add_argument('--java-path', help='Specific Java path (optional, will auto-select if not provided)')
    
    args = parser.parse_args()
    
    if args.command == 'list-java':
        list_java_installations()
    
    elif args.command == 'list-servers':
        servers = list_servers()
        if servers:
            print("Minecraft Servers:")
            print("=" * 50)
            for server in servers:
                name = server.get("Name", "Unknown")
                version = server.get("Version", "Unknown")
                java_path = server.get("JavaPath", "java (default)")
                print(f"• {name} (v{version}) - Java: {java_path}")
        else:
            print("No Minecraft servers found.")
    
    elif args.command == 'check':
        servers = list_servers()
        if args.server:
            # Check specific server
            server = next((s for s in servers if s.get("Name") == args.server), None)
            if server:
                check_server_java_compatibility(server)
            else:
                print(f"Server '{args.server}' not found.")
        else:
            # Check all servers
            if servers:
                print("Java Compatibility Check:")
                print("=" * 50)
                for server in servers:
                    check_server_java_compatibility(server)
            else:
                print("No Minecraft servers found.")
    
    elif args.command == 'configure':
        success = configure_server_java(args.server, args.java_path)
        if success:
            print("Configuration updated successfully!")
        else:
            print("Failed to update configuration.")
    
    else:
        parser.print_help()


class JavaConfigurator:
    # Java Configuration class for server management dashboard
    
    @staticmethod
    def detect_java_installations():
        # Detect all available Java installations on the system
        return detect_java_installations()


if __name__ == "__main__":
    main()
