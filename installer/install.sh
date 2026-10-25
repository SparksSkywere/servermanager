#!/usr/bin/env bash
# Server Manager — Linux bootstrap installer (same role as install.ps1 / Setup.exe on Windows).
# Clones from Git (or uses a local publish folder), publishes linux-x64, installs under /opt/servermanager.
set -euo pipefail

ACTION="${1:-install}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/servermanager}"
REPO_URL="${REPO_URL:-}"
REPO_BRANCH="${REPO_BRANCH:-main}"
PAYLOAD_DIR="${PAYLOAD_DIR:-}"
WEB_PORT="${WEB_PORT:-18080}"
RUNTIME_PORT="${RUNTIME_PORT:-18091}"
CLUSTER_PORT="${CLUSTER_PORT:-15001}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() { echo "==> $*"; }
ok() { echo "    $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "Missing required tool: $1"; }

resolve_repo_url() {
  if [[ -n "$REPO_URL" ]]; then
    echo "$REPO_URL"
    return
  fi
  if git -C "$SCRIPT_DIR" rev-parse --show-toplevel >/dev/null 2>&1; then
    git -C "$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)" remote get-url origin 2>/dev/null || true
  fi
}

resolve_payload() {
  if [[ -n "$PAYLOAD_DIR" && -x "$PAYLOAD_DIR/ServerManager" ]]; then
    echo "$PAYLOAD_DIR"
    return
  fi
  for c in \
    "$SCRIPT_DIR/payload" \
    "$SCRIPT_DIR/artifacts/publish/linux-x64" \
    "$SCRIPT_DIR/../artifacts/publish/linux-x64"
  do
    if [[ -x "$c/ServerManager" ]]; then
      echo "$c"
      return
    fi
  done

  local url
  url="$(resolve_repo_url)"
  [[ -n "$url" ]] || die "No payload and no REPO_URL. Export REPO_URL=https://github.com/ORG/servermanager.git"

  need git
  need dotnet
  local work
  work="$(mktemp -d /tmp/servermanager-src-XXXXXX)"
  info "Cloning $url ($REPO_BRANCH) -> $work"
  git clone --depth 1 --branch "$REPO_BRANCH" "$url" "$work"
  info "Publishing linux-x64..."
  (
    cd "$work"
    mkdir -p artifacts/publish/linux-x64
    for proj in \
      src/ServerManager.HostRuntime/ServerManager.HostRuntime.csproj \
      src/ServerManager.Web/ServerManager.Web.csproj \
      src/ServerManager.AppHost/ServerManager.AppHost.csproj
    do
      dotnet publish "$proj" -c Release -r linux-x64 --self-contained true \
        -o artifacts/publish/linux-x64 --verbosity minimal
    done
    if [[ -d www ]]; then
      mkdir -p artifacts/publish/linux-x64/www
      cp -a www/. artifacts/publish/linux-x64/www/
    fi
  )
  echo "$work/artifacts/publish/linux-x64"
}

ensure_dirs() {
  local root="$1"
  mkdir -p "$root"/{logs/components,temp,db,ssl,www,config,icons}
}

write_config() {
  local runtime="$1"
  cat > "$runtime/config/appsettings.json" <<EOF
{
  "ServerManager": {
    "RootPath": "$runtime",
    "WebPort": $WEB_PORT,
    "HostRuntimePort": $RUNTIME_PORT,
    "ClusterPort": $CLUSTER_PORT
  }
}
EOF
}

install_unit() {
  local app="$1"
  local runtime="$2"
  cat > /etc/systemd/system/servermanager.service <<EOF
[Unit]
Description=Server Manager
After=network.target

[Service]
Type=simple
WorkingDirectory=$app
Environment=ServerManager__RootPath=$runtime
ExecStart=$app/ServerManager
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable servermanager.service
  systemctl restart servermanager.service
  ok "systemd unit servermanager.service enabled"
}

do_install() {
  [[ "$(id -u)" -eq 0 ]] || die "Run as root (sudo)"
  need rsync
  local src
  src="$(resolve_payload)"
  info "Payload: $src"
  info "Install: $INSTALL_ROOT"
  local runtime="$INSTALL_ROOT/runtime"
  mkdir -p "$INSTALL_ROOT"
  ensure_dirs "$runtime"
  rsync -a --delete --exclude runtime "$src/" "$INSTALL_ROOT/"
  if [[ -d "$INSTALL_ROOT/www" ]]; then
    rsync -a "$INSTALL_ROOT/www/" "$runtime/www/"
  fi
  write_config "$runtime"
  chmod +x "$INSTALL_ROOT/ServerManager" "$INSTALL_ROOT/ServerManager.HostRuntime" "$INSTALL_ROOT/ServerManager.Web" 2>/dev/null || true
  install_unit "$INSTALL_ROOT" "$runtime"
  ok "Install complete. SQLite DBs: $runtime/db"
  ok "Web port: $WEB_PORT  (default login admin / admin)"
}

do_uninstall() {
  [[ "$(id -u)" -eq 0 ]] || die "Run as root (sudo)"
  systemctl stop servermanager.service 2>/dev/null || true
  systemctl disable servermanager.service 2>/dev/null || true
  rm -f /etc/systemd/system/servermanager.service
  systemctl daemon-reload
  ok "Service removed. Leaving $INSTALL_ROOT (contains runtime/db) — delete manually if desired."
}

case "$ACTION" in
  install) do_install ;;
  uninstall) do_uninstall ;;
  *) die "Usage: $0 [install|uninstall]" ;;
esac
