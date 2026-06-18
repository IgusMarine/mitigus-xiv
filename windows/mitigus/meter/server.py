"""
Servidor HTTP da UI do DPS meter (variante DPS / branch dps-meter).

Serve a página Neon Bars + a API JSON do tracker. Separado do PanelServer de
produção de propósito (a variante DPS é um app à parte). ThreadingHTTPServer
numa thread daemon, como o painel.

Rotas:
  GET  /              -> meter.html
  GET  /api/dps       -> snapshot do DpsTracker (JSON)
  GET  /fonts/<woff2> -> fontes Chakra Petch (reusa as do painel)
  POST /api/reset     -> zera o encounter
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..paths import resource_dir

_HTML = os.path.join(resource_dir(), "mitigus", "meter", "meter.html")
_FONTS = os.path.join(resource_dir(), "mitigus", "panel", "fonts")


class MeterServer:
    def __init__(self, tracker, host: str = "0.0.0.0", port: int = 8088):
        self.tracker = tracker
        self.host = host
        self.port = port
        self._httpd = None

    def start(self) -> int:
        tracker = self.tracker

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, body: bytes):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

            def _file(self, path, ctype):
                try:
                    with open(path, "rb") as fh:
                        self._send(200, ctype, fh.read())
                except Exception:
                    self._send(404, "text/plain; charset=utf-8", b"nao encontrado")

            def do_GET(self):
                if self.path.startswith("/api/dps"):
                    body = json.dumps(tracker.snapshot()).encode("utf-8")
                    self._send(200, "application/json", body)
                elif self.path == "/" or self.path.startswith("/index") or self.path.startswith("/?"):
                    self._file(_HTML, "text/html; charset=utf-8")
                elif self.path.startswith("/fonts/"):
                    name = os.path.basename(self.path.split("?")[0])
                    if name.endswith(".woff2"):
                        self._file(os.path.join(_FONTS, name), "font/woff2")
                    else:
                        self._send(404, "text/plain", b"nf")
                else:
                    self._send(404, "text/plain", b"nf")

            def do_POST(self):
                if self.path.startswith("/api/reset"):
                    tracker.reset()
                    self._send(200, "application/json", b'{"ok":true}')
                else:
                    self._send(404, "text/plain", b"nf")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True,
                         name="mitigus-meter").start()
        return self.port

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
