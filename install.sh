#!/bin/bash
# LXC Scaler — one-command installer for Proxmox VE.
#
#   Install:    bash -c "$(curl -fsSL https://raw.githubusercontent.com/sakadukigi/lxc-scaler/main/install.sh)"
#   Uninstall:  bash -c "$(curl -fsSL https://raw.githubusercontent.com/sakadukigi/lxc-scaler/main/install.sh)" -- --uninstall
#
# Idempotent and non-interactive. Re-running upgrades an existing install and
# preserves /opt/lxc-scaler/config.json. No external dependencies.
set -euo pipefail

REPO_TARBALL="https://github.com/sakadukigi/lxc-scaler/archive/refs/heads/main.tar.gz"

OPT_DIR="/opt/lxc-scaler"
PVE_JS_DIR="/usr/share/pve-manager/js"
JS_DST="$PVE_JS_DIR/lxc-scaler.js"
DATA_FILE="$PVE_JS_DIR/lxcscaler-data.json"
TPL="/usr/share/pve-manager/index.html.tpl"
APT_HOOK="/etc/apt/apt.conf.d/99-lxc-scaler"
SERVICES=(lxc-scaler lxc-scaler-api)

CLEANUP_DIR=""
cleanup() { [ -n "${CLEANUP_DIR:-}" ] && rm -rf "$CLEANUP_DIR"; return 0; }
trap cleanup EXIT

say()  { echo -e "\033[1;36m[lxc-scaler]\033[0m $*"; }
err()  { echo -e "\033[1;31m[lxc-scaler]\033[0m $*" >&2; }
die()  { err "$*"; exit 1; }

require_root() { [ "$(id -u)" -eq 0 ] || die "Must run as root."; }
require_pve()  { command -v pvesh >/dev/null 2>&1 || die "pvesh not found — this is not a Proxmox VE host."; }

stop_services() {
    for s in "${SERVICES[@]}"; do
        systemctl disable --now "$s.service" >/dev/null 2>&1 || true
    done
}

remove_units() {
    for s in "${SERVICES[@]}"; do rm -f "/etc/systemd/system/$s.service"; done
    systemctl daemon-reload >/dev/null 2>&1 || true
}

remove_injection() {
    # Drop any injected <script> line for our panel (any ?ver=) — idempotent.
    [ -f "$TPL" ] && sed -i '\#/pve2/js/lxc-scaler\.js#d' "$TPL" || true
}

# ---------------------------------------------------------------- uninstall
do_uninstall() {
    require_root
    say "Uninstalling LXC Scaler..."
    stop_services
    remove_units
    remove_injection
    rm -f "$JS_DST" "$DATA_FILE" "$APT_HOOK"
    rm -rf "$OPT_DIR"
    say "Uninstalled. (LXC container allocations are left as-is.)"
}

# ---------------------------------------------------------------- source
resolve_source() {
    local script_dir=""
    if [ -n "${BASH_SOURCE:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    fi
    if [ -n "$script_dir" ] && [ -d "$script_dir/src" ]; then
        SRC_ROOT="$script_dir"
        say "Installing from local checkout: $SRC_ROOT"
    else
        command -v curl >/dev/null 2>&1 || die "curl is required to fetch the package."
        command -v tar  >/dev/null 2>&1 || die "tar is required to unpack the package."
        CLEANUP_DIR="$(mktemp -d)"
        say "Downloading package..."
        curl -fsSL "$REPO_TARBALL" | tar xz -C "$CLEANUP_DIR"
        SRC_ROOT="$(find "$CLEANUP_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)"
        [ -n "$SRC_ROOT" ] && [ -d "$SRC_ROOT/src" ] || die "Downloaded package looks malformed."
    fi
}

# ---------------------------------------------------------------- install
seed_config() {
    [ -f "$OPT_DIR/config.json" ] && { say "Keeping existing config.json"; return; }
    cat > "$OPT_DIR/config.json" <<'JSON'
{
  "defaults": {
    "mem_min_mb": 128,
    "mem_max_mb": 16384,
    "cpu_min": 1,
    "cpu_max": 16,
    "cooldown_sec": 300,
    "mem_low": 0.5,
    "mem_high": 0.9,
    "cpu_low": 0.1,
    "cpu_high": 0.9
  },
  "containers": {}
}
JSON
    say "Wrote default config.json"
}

write_apt_hook() {
    cat > "$APT_HOOK" <<'HOOK'
// LXC Scaler: re-inject the web-UI panel after pve-manager upgrades
// overwrite /usr/share/pve-manager/index.html.tpl.
DPkg::Post-Invoke { "if [ -x /opt/lxc-scaler/reinject-ui.sh ]; then /opt/lxc-scaler/reinject-ui.sh >/dev/null 2>&1 || true; fi"; };
HOOK
}

do_install() {
    require_root
    require_pve
    resolve_source

    say "Stopping any existing services..."
    stop_services

    say "Installing daemon + API to $OPT_DIR"
    mkdir -p "$OPT_DIR"
    install -m 0755 "$SRC_ROOT/src/lxc_scaler.py"     "$OPT_DIR/lxc_scaler.py"
    install -m 0755 "$SRC_ROOT/src/lxc_scaler_api.py" "$OPT_DIR/lxc_scaler_api.py"
    install -m 0755 "$SRC_ROOT/tools/reinject-ui.sh"  "$OPT_DIR/reinject-ui.sh"
    seed_config

    say "Installing web-UI panel"
    mkdir -p "$PVE_JS_DIR"
    install -m 0644 "$SRC_ROOT/src/lxc-scaler.js" "$JS_DST"
    remove_injection
    bash "$OPT_DIR/reinject-ui.sh"
    write_apt_hook

    say "Installing systemd services"
    install -m 0644 "$SRC_ROOT/systemd/lxc-scaler.service"     /etc/systemd/system/lxc-scaler.service
    install -m 0644 "$SRC_ROOT/systemd/lxc-scaler-api.service" /etc/systemd/system/lxc-scaler-api.service
    systemctl daemon-reload
    systemctl enable "${SERVICES[@]/%/.service}" >/dev/null 2>&1 || true
    systemctl restart lxc-scaler.service lxc-scaler-api.service

    say "Done."
    echo
    say "Web UI:   Datacenter -> 'LXC Scaler' tab (reload the Proxmox UI; Shift+Reload to bust cache)"
    say "Config:   https://<host>:8087/config  (accept the self-signed cert once)"
    say "Status:   systemctl status lxc-scaler lxc-scaler-api"
    say "Uninstall: bash $0 --uninstall"
}

# ---------------------------------------------------------------- entry
case "${1:-install}" in
    --uninstall|uninstall) do_uninstall ;;
    install|"")            do_install ;;
    *) die "Unknown argument: $1 (use --uninstall or no argument to install)" ;;
esac
