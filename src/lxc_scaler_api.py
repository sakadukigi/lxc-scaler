#!/usr/bin/env python3
"""Config API for LXC Scaler - HTTPS on port 8087.

Serves GET/POST /config, reusing the Proxmox SSL cert so the web-UI panel can
read and write /opt/lxc-scaler/config.json. Python stdlib only.
"""
import http.server
import json
import os
import ssl
import urllib.request

CONFIG_FILE = "/opt/lxc-scaler/config.json"
DATA_FILE = "/usr/share/pve-manager/js/lxcscaler-data.json"
CERT_FILE = "/etc/pve/local/pve-ssl.pem"
KEY_FILE = "/etc/pve/local/pve-ssl.key"
PORT = 8087
NODENAME = os.uname().nodename
PEER_TIMEOUT = 3

DEFAULT_CONFIG = {
    "defaults": {
        "mem_min_mb": 128,
        "mem_max_mb": 16384,
        "cpu_min": 1,
        "cpu_max": 16,
        "cooldown_sec": 300,
        "mem_low": 0.50,
        "mem_high": 0.90,
        "cpu_low": 0.10,
        "cpu_high": 0.90
    },
    "containers": {},
    "peers": []
}

# Peers use self-signed PVE certs; verify off for LAN peer-to-peer fetch.
_SSL_NOVERIFY = ssl.create_default_context()
_SSL_NOVERIFY.check_hostname = False
_SSL_NOVERIFY.verify_mode = ssl.CERT_NONE


def load_peers():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return [str(p).strip() for p in cfg.get("peers", []) if str(p).strip()]
    except Exception:
        return []


def fetch_peer(host):
    url = f"https://{host}:{PORT}/data"
    try:
        with urllib.request.urlopen(url, timeout=PEER_TIMEOUT, context=_SSL_NOVERIFY) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _send_json(self, code, text):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(text.encode())

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == "/config":
            try:
                with open(CONFIG_FILE) as f:
                    data = f.read()
            except FileNotFoundError:
                data = json.dumps(DEFAULT_CONFIG, indent=2)
            self._send_json(200, data)
        elif path == "/data":
            # Local UI data ({host, containers}); consumed by peers' /peers-data.
            try:
                with open(DATA_FILE) as f:
                    data = f.read()
            except FileNotFoundError:
                data = json.dumps({"host": NODENAME, "containers": {}})
            self._send_json(200, data)
        elif path == "/peers-data":
            # Server-side proxy: fetch each configured peer's /data (verify off).
            out = {p: fetch_peer(p) for p in load_peers()}
            self._send_json(200, json.dumps(out))
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        if self.path.split('?')[0] != "/config":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            cfg = json.loads(body)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())


def main():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    server = http.server.HTTPServer(("", PORT), Handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"LXC Scaler config API: https://0.0.0.0:{PORT}/config", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
