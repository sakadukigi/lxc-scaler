#!/usr/bin/env python3
"""Config API for LXC Scaler - HTTPS on port 8087.

Serves GET/POST /config, reusing the Proxmox SSL cert so the web-UI panel can
read and write /opt/lxc-scaler/config.json. Python stdlib only.
"""
import http.server
import json
import os
import ssl

CONFIG_FILE = "/opt/lxc-scaler/config.json"
CERT_FILE = "/etc/pve/local/pve-ssl.pem"
KEY_FILE = "/etc/pve/local/pve-ssl.key"
PORT = 8087

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
    "containers": {}
}


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

    def do_GET(self):
        if self.path.split('?')[0] != "/config":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            with open(CONFIG_FILE) as f:
                data = f.read()
        except FileNotFoundError:
            data = json.dumps(DEFAULT_CONFIG, indent=2)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(data.encode())

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
