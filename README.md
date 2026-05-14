# Production Note: This is in active development so all is subject to change! Linux development is a side project, Windows is first.

# Server Manager

A server management platform for Steam dedicated servers, Minecraft servers, and other game/application servers. Provides a desktop GUI and web-based dashboard for managing servers locally or across a network.

**Version:** 1.4.1 | **Developer:** Sparks Skywere

---

## System Requirements

| | Minimum | Recommended |
|---|---|---|
| **OS** | Windows 10 / Server 2016 | Windows 11 / Server 2022 |
| **Python** | 3.8+ | 3.11+ |
| **RAM** | 4 GB | 8 GB+ |
| **Disk** | 500 MB (application only) | 10 GB+ (with game servers) |

**Linux:** Experimental support — Debian-based distributions recommended. See [Getting Started](https://github.com/SparksSkywere/servermanager/wiki/Getting-Started) for details.

---

## Quick Start

### Windows Installation

1. Open PowerShell **as Administrator**
2. Run the installer:
   ```powershell
   .\install.ps1
   ```
3. The GUI wizard will guide you through:
   - Python & Git detection/installation
   - SteamCMD setup
   - Database initialisation
   - **HTTPS/HTTP selection** — HTTPS is recommended; a self-signed certificate is generated automatically
   - Cluster configuration (Host or Subhost)
   - Admin account creation

See [Getting Started](https://github.com/SparksSkywere/servermanager/wiki/Getting-Started) for the full walkthrough.

### Linux Installation

```bash
chmod +x install.sh
./install.sh
```

The interactive installer handles Python, Git, dependencies, databases, SSL certificate generation, firewall rules, and systemd service setup.

See [Getting Started](https://github.com/SparksSkywere/servermanager/wiki/Getting-Started) for details.

### Manual Installation

```bash
git clone https://github.com/SparksSkywere/servermanager.git
cd servermanager
pip install -r requirements.txt
```

After manual installation you will need to create registry keys (Windows), initialise databases, and create an admin user. See [Getting Started](https://github.com/SparksSkywere/servermanager/wiki/Getting-Started).

---

## Usage

- **Desktop Mode:** Run `Start-ServerManager.pyw` — right-click the system tray icon and select "Open Server Dashboard"
- **Web Interface:** Access at `https://localhost:443` (HTTPS) or `http://localhost:8080` (HTTP), depending on your installation choice. From another machine use your server's IP address.
- **Service Mode:** Install as a Windows service via `.\install.ps1 -ServiceAction Install`. See [Getting Started](https://github.com/SparksSkywere/servermanager/wiki/Getting-Started).

**Default credentials:** `admin` / `admin` — change these immediately after first login.

-> **Note:** If using HTTPS with a self-signed certificate, your browser will show a security warning. This is expected — see [Security and Clustering](https://github.com/SparksSkywere/servermanager/wiki/Security-and-Clustering).

---

## Ports & Firewall

The installer configures firewall rules automatically. Key ports:

| Port | Protocol | Purpose |
|---|---|---|
| 8080 | TCP | Web interface (HTTP) |
| 443 | TCP | Web interface (HTTPS) |
| 8081 | TCP | HTTP → HTTPS redirect |
| 5001 | TCP | Cluster API |
| 7777–7800 | TCP/UDP | Game servers |
| 27015–27030 | UDP | Steam query protocol |

See [Troubleshooting and Reference](https://github.com/SparksSkywere/servermanager/wiki/Troubleshooting-and-Reference) for the full firewall rule reference.

---

## Uninstallation

- **Windows:** Run `.\uninstaller.ps1` as Administrator
- **Linux:** Run `./uninstaller.sh`

Full uninstall. See [Troubleshooting and Reference](https://github.com/SparksSkywere/servermanager/wiki/Troubleshooting-and-Reference).

---

## Notes

VSCode Github AI has been used in the making of this product

No .ENV file is used for Windows as you should be setting it all up with the registry (I will be making one for Linux at somepoint so this is just stand-in text.)

---

## Full Documentation

See the [GitHub Wiki](https://github.com/SparksSkywere/servermanager/wiki).