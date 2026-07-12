#!/bin/bash
# Idempotently inject the LXC Scaler UI panel <script> into the Proxmox web UI.
# Safe to run repeatedly. Re-run automatically after pve-manager upgrades via the
# APT hook at /etc/apt/apt.conf.d/99-lxc-scaler, because a pve-manager upgrade
# overwrites index.html.tpl and drops our injection.
set -euo pipefail

TPL="/usr/share/pve-manager/index.html.tpl"
JS="/usr/share/pve-manager/js/lxc-scaler.js"
MARKER='src="/pve2/js/lxc-scaler.js'
LINE='    <script type="text/javascript" src="/pve2/js/lxc-scaler.js?ver=2"></script>'

# Nothing to inject into if the template or the panel JS is missing.
[ -f "$TPL" ] || { echo "reinject-ui: $TPL not found, skipping"; exit 0; }
[ -f "$JS" ]  || { echo "reinject-ui: $JS not found, skipping"; exit 0; }

# Already injected? Idempotent no-op.
if grep -qF "$MARKER" "$TPL"; then
    exit 0
fi

# Insert our script tag just before </head> (fall back to </body> or EOF-append).
if grep -q '</head>' "$TPL"; then
    sed -i "s#</head>#${LINE}\n</head>#" "$TPL"
elif grep -q '</body>' "$TPL"; then
    sed -i "s#</body>#${LINE}\n</body>#" "$TPL"
else
    printf '%s\n' "$LINE" >> "$TPL"
fi

echo "reinject-ui: injected LXC Scaler UI into $TPL"
