#!/usr/bin/env python3
"""LXC Auto-Scaler for Proxmox VE.

Watches every running LXC container every 60s and adjusts its memory/cores
allocation based on live CPU and memory usage, via `pvesh`. History and scale
events are written to a JSON file consumed by the Proxmox web-UI panel.
No external dependencies (Python stdlib only).
"""
import collections
import json
import logging
import logging.handlers
import os
import subprocess
import time

CONFIG_FILE = "/opt/lxc-scaler/config.json"
DATA_FILE = "/usr/share/pve-manager/js/lxcscaler-data.json"
MAX_HISTORY = 1440  # 24h at 60s intervals
INTERVAL = 60
NODENAME = os.uname().nodename

DEFAULT_CONFIG = {
    "mem_min_mb": 128,
    "mem_max_mb": 16384,
    "cpu_min": 1,
    "cpu_max": 16,
    "cooldown_sec": 300,
    "mem_low": 0.50,
    "mem_high": 0.90,
    "cpu_low": 0.10,
    "cpu_high": 0.90,
}

log = logging.getLogger("lxc-scaler")
log.setLevel(logging.INFO)
try:
    sh = logging.handlers.SysLogHandler(address="/dev/log")
    sh.ident = "lxc-scaler: "
    log.addHandler(sh)
except Exception:
    pass
log.addHandler(logging.StreamHandler())


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"defaults": DEFAULT_CONFIG.copy(), "containers": {}}
    try:
        with open(CONFIG_FILE) as f:
            raw = json.load(f)
        d = DEFAULT_CONFIG.copy()
        d.update(raw.get("defaults", {}))
        raw["defaults"] = d
        if "containers" not in raw:
            raw["containers"] = {}
        return raw
    except Exception as e:
        log.warning(f"Config load error: {e}, using defaults")
        return {"defaults": DEFAULT_CONFIG.copy(), "containers": {}}


def get_ct_config(cfg, vmid_s):
    c = cfg["defaults"].copy()
    c.update(cfg.get("containers", {}).get(vmid_s, {}))
    return c


def read_cgroup_cpu_usec(vmid):
    path = f"/sys/fs/cgroup/lxc/{vmid}/cpu.stat"
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def pvesh(path):
    r = subprocess.run(
        ["pvesh", "get", path, "--output-format", "json"],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return json.loads(r.stdout)


def pvesh_set(path, **kwargs):
    cmd = ["pvesh", "set", path]
    for k, v in kwargs.items():
        cmd += ["-" + k, str(v)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())


def process(vmid, status, cdata, cfg):
    ts = int(time.time())
    name = status.get("name", str(vmid))
    vmid_s = str(vmid)
    c = get_ct_config(cfg, vmid_s)

    if vmid_s not in cdata:
        cdata[vmid_s] = {
            "name": name,
            "history": collections.deque(maxlen=MAX_HISTORY),
            "events": collections.deque(maxlen=200),
            "last_scale": {},
        }

    d = cdata[vmid_s]
    d["name"] = name

    mem_used = status["mem"]
    mem_max = status["maxmem"]
    cpu_cores = int(status.get("cpus", 1))

    # Compute CPU fraction from cgroup cpu.stat delta (status["cpu"] is always 0 in PVE9)
    cpu_usec_now = read_cgroup_cpu_usec(vmid)
    cpu_frac = 0.0
    if cpu_usec_now is not None:
        last_usec = d.get("_cpu_usec", 0)
        last_ts = d.get("_cpu_ts", ts)
        dt = ts - last_ts
        if dt > 0 and last_usec > 0:
            cpu_frac = (cpu_usec_now - last_usec) / (dt * 1_000_000 * cpu_cores)
            cpu_frac = max(0.0, min(1.0, cpu_frac))
        d["_cpu_usec"] = cpu_usec_now
        d["_cpu_ts"] = ts

    mem_pct = mem_used / mem_max if mem_max else 0
    mem_mb = mem_max // (1024 * 1024)
    mem_used_mb = mem_used // (1024 * 1024)
    cpu_used = round(cpu_frac * cpu_cores, 3)

    d["history"].append({
        "t": ts,
        "mem_mb": mem_mb,
        "mem_used_mb": mem_used_mb,
        "cpu": cpu_cores,
        "cpu_used": cpu_used,
    })

    log.info(f"CT{vmid}({name}) cpu_frac={cpu_frac:.3f} cpu_cores={cpu_cores} mem_pct={mem_pct:.3f}")

    last_scale = d.get("last_scale", {})

    # Memory scaling — scale-up: no cooldown; scale-down: cooldown applies
    mem_down_ok = (ts - last_scale.get("memory", 0)) >= c["cooldown_sec"]
    if mem_pct > c["mem_high"]:
        new_mb = min(c["mem_max_mb"], mem_mb * 2)
        if new_mb != mem_mb:
            try:
                pvesh_set(f"/nodes/localhost/lxc/{vmid}/config", memory=new_mb)
                last_scale["memory"] = ts
                log.info(f"CT{vmid}({name}) mem {mem_mb}MB->{new_mb}MB (usage {mem_pct:.1%})")
                d["events"].appendleft({"t": ts, "resource": "memory", "old": mem_mb, "new_val": new_mb, "dir": 1,
                                        "reason": f"avg>{c['mem_high']:.0%} ({mem_pct:.1%})"})
            except Exception as e:
                log.error(f"CT{vmid} mem up failed: {e}")
    elif mem_pct < c["mem_low"] and mem_down_ok:
        new_mb = max(c["mem_min_mb"], mem_mb // 2)
        if new_mb != mem_mb:
            try:
                pvesh_set(f"/nodes/localhost/lxc/{vmid}/config", memory=new_mb)
                last_scale["memory"] = ts
                log.info(f"CT{vmid}({name}) mem {mem_mb}MB->{new_mb}MB (usage {mem_pct:.1%})")
                d["events"].appendleft({"t": ts, "resource": "memory", "old": mem_mb, "new_val": new_mb, "dir": -1,
                                        "reason": f"avg<{c['mem_low']:.0%} ({mem_pct:.1%})"})
            except Exception as e:
                log.error(f"CT{vmid} mem down failed: {e}")

    # CPU scaling — scale-up: no cooldown; scale-down: cooldown applies
    cpu_down_ok = (ts - last_scale.get("cpu", 0)) >= c["cooldown_sec"]
    if d.get("_cpu_usec"):  # skip first loop (no delta yet)
        if cpu_frac > c["cpu_high"] and cpu_cores < c["cpu_max"]:
            new_cores = min(c["cpu_max"], cpu_cores + 1)
            try:
                pvesh_set(f"/nodes/localhost/lxc/{vmid}/config", cores=new_cores)
                last_scale["cpu"] = ts
                log.info(f"CT{vmid}({name}) cpu {cpu_cores}->{new_cores} (usage {cpu_frac:.1%})")
                d["events"].appendleft({"t": ts, "resource": "cpu", "old": cpu_cores, "new_val": new_cores, "dir": 1,
                                        "reason": f"usage {cpu_frac:.1%} > {c['cpu_high']:.0%}"})
            except Exception as e:
                log.error(f"CT{vmid} cpu up failed: {e}")
        elif cpu_frac < c["cpu_low"] and cpu_cores > c["cpu_min"] and cpu_down_ok:
            new_cores = max(c["cpu_min"], cpu_cores - 1)
            try:
                pvesh_set(f"/nodes/localhost/lxc/{vmid}/config", cores=new_cores)
                last_scale["cpu"] = ts
                log.info(f"CT{vmid}({name}) cpu {cpu_cores}->{new_cores} (usage {cpu_frac:.1%})")
                d["events"].appendleft({"t": ts, "resource": "cpu", "old": cpu_cores, "new_val": new_cores, "dir": -1,
                                        "reason": f"usage {cpu_frac:.1%} < {c['cpu_low']:.0%}"})
            except Exception as e:
                log.error(f"CT{vmid} cpu down failed: {e}")

    d["last_scale"] = last_scale


def write_ui_data(cdata):
    containers = {}
    for vmid_s, d in cdata.items():
        containers[vmid_s] = {
            "name": d["name"],
            "history": list(d["history"]),
            "events": list(d["events"]),
        }
    ui = {"host": NODENAME, "containers": containers}
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ui, f)
    os.replace(tmp, DATA_FILE)


def main():
    log.info("LXC Scaler started")
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    cdata = {}

    while True:
        cfg = load_config()
        try:
            containers = pvesh("/nodes/localhost/lxc")
            for ct in containers:
                if ct.get("status") != "running":
                    continue
                vmid = ct["vmid"]
                try:
                    status = pvesh(f"/nodes/localhost/lxc/{vmid}/status/current")
                    process(vmid, status, cdata, cfg)
                except Exception as e:
                    log.error(f"CT{vmid} error: {e}")
            write_ui_data(cdata)
        except Exception as e:
            log.error(f"Loop error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
