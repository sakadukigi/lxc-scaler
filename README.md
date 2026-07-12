# LXC Scaler

Auto-scaler for **Proxmox VE** LXC containers. A lightweight daemon watches every
running container every 60 seconds and adjusts its **memory** and **CPU cores**
allocation to match live usage — no OS/app changes, just `pvesh` config edits.
Ships with a panel embedded in the Proxmox web UI. **Python stdlib only, no external dependencies.**

## Install (one command)

Run on any Proxmox VE host as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/sakadukigi/lxc-scaler/main/install.sh)"
```

Then reload the Proxmox web UI and open **Datacenter → "LXC Scaler"**.
(First time, click the config-API link in the panel to accept the self-signed cert.)

## What it does

- Enumerates running LXC containers via `pvesh get /nodes/localhost/lxc`.
- **Memory**: usage above `mem_high` (default 90%) → allocation doubled (up to `mem_max_mb`);
  below `mem_low` (default 50%) → halved (down to `mem_min_mb`).
- **CPU**: usage above `cpu_high` (default 90%) → cores +1 (up to `cpu_max`);
  below `cpu_low` (default 10%) → cores −1 (down to `cpu_min`).
  CPU usage is measured from cgroup v2 `cpu.stat` (PVE 9 reports `status.cpu` as 0).
- **Scale-up is immediate; scale-down waits `cooldown_sec`** (default 300s) to avoid flapping.
- Per-container overrides via the `containers` map in the config.
- History (up to 24h) and scale events render as charts/grids in the web-UI panel.

## Configuration

Edit thresholds/limits in the web-UI panel (**Save** writes via the config API on port 8087),
or edit `/opt/lxc-scaler/config.json` directly and the daemon picks it up on the next loop.

```json
{
  "defaults": {
    "mem_min_mb": 128, "mem_max_mb": 16384,
    "cpu_min": 1, "cpu_max": 16,
    "cooldown_sec": 300,
    "mem_low": 0.5, "mem_high": 0.9,
    "cpu_low": 0.1, "cpu_high": 0.9
  },
  "containers": { "100": { "mem_max_mb": 4096, "cpu_max": 4 } }
}
```

## Components

| Path | Role |
|------|------|
| `/opt/lxc-scaler/lxc_scaler.py`      | Scaler daemon (`lxc-scaler.service`) |
| `/opt/lxc-scaler/lxc_scaler_api.py`  | HTTPS config API on :8087 (`lxc-scaler-api.service`) |
| `/opt/lxc-scaler/config.json`        | Thresholds and per-container overrides |
| `/usr/share/pve-manager/js/lxc-scaler.js` | Web-UI panel (ExtJS) |
| `/etc/apt/apt.conf.d/99-lxc-scaler`  | Re-injects the panel after `pve-manager` upgrades |

The panel is injected into `index.html.tpl`. Because a `pve-manager` upgrade rewrites
that file, an APT post-invoke hook re-runs `reinject-ui.sh` automatically after upgrades,
so the panel survives updates.

## Uninstall

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/sakadukigi/lxc-scaler/main/install.sh)" -- --uninstall
```

Removes the services, code, UI panel, injection, and APT hook. Container allocations are left as-is.

## Requirements

Proxmox VE 8/9 (tested on 9.1), Python 3, `pvesh`. Nothing else.
