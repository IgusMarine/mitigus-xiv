"""
Servidor HTTP do painel (Fase 5).

Serve o index.html e uma API JSON mínima, num ThreadingHTTPServer numa thread
daemon (o proxy roda no loop asyncio da thread principal; só compartilham o
ControlHub, que é thread-safe). Sem dependências externas — stdlib pura.

    GET  /              -> painel (index.html)
    GET  /api/status    -> estado + telemetria
    GET  /api/logs      -> linhas recentes
    POST /api/toggle    -> inverte liga/desliga
    POST /api/enable?on=1|0 -> define liga/desliga
"""
from __future__ import annotations

import http.server
import json
import os
import re
import threading
import urllib.parse

from .hub import ControlHub

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX_PATH = os.path.join(_HERE, "index.html")
_FONTS_DIR = os.path.join(_HERE, "fonts")
_FONT_NAME_RE = re.compile(r"[A-Za-z0-9._-]+\.woff2")


class PanelServer:
    def __init__(self, hub: ControlHub, host: str = "0.0.0.0", port: int = 8080, on_update_opcodes=None, tracker=None):
        self.hub = hub
        self.host = host
        self.port = port
        self.on_update_opcodes = on_update_opcodes  # callable() -> dict, opcional
        self.tracker = tracker                      # DpsTracker, opcional
        self._httpd = None
        self._thread = None

    def start(self) -> int:
        hub = self.hub
        on_update = self.on_update_opcodes
        tracker = self.tracker
        # UI atualizavel sem rebuild: usa o index.html baixado pelo canal de update
        # (%LOCALAPPDATA%\Mitigus\ui\) se existir; senao, o embutido.
        idx = _INDEX_PATH
        la = os.environ.get("LOCALAPPDATA")
        if la:
            ov = os.path.join(la, "Mitigus", "ui", "index.html")
            if os.path.exists(ov):
                idx = ov
        with open(idx, "rb") as fp:
            index_html = fp.read()

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # silencia o log padrão
                pass

            def _send(self, body: bytes, content_type: str, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, obj, code: int = 200):
                self._send(json.dumps(obj).encode("utf-8"), "application/json", code)

            def _send_font(self, path):
                name = os.path.basename(path)
                if not _FONT_NAME_RE.fullmatch(name):
                    self._json({"error": "not found"}, 404)
                    return
                fp = os.path.join(_FONTS_DIR, name)
                if not os.path.isfile(fp):
                    self._json({"error": "not found"}, 404)
                    return
                with open(fp, "rb") as fh:
                    body = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path in ("/", "/index.html"):
                    self._send(index_html, "text/html; charset=utf-8")
                elif path.startswith("/fonts/") and path.endswith(".woff2"):
                    self._send_font(path)
                elif path == "/api/status":
                    self._json(hub.status())
                elif path == "/api/logs":
                    self._json({"lines": hub.logs()})
                elif path == "/api/dps":
                    if tracker is not None:
                        self._json(tracker.snapshot())
                    else:
                        self._json({"error": "dps meter disabled"}, 404)
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/api/toggle":
                    self._json({"enabled": hub.toggle()})
                elif parsed.path == "/api/reset":
                    if tracker is not None:
                        tracker.reset()
                        self._json({"ok": True})
                    else:
                        self._json({"error": "dps meter disabled"}, 404)
                elif parsed.path == "/api/enable":
                    qs = urllib.parse.parse_qs(parsed.query)
                    on = qs.get("on", ["1"])[0].lower() not in ("0", "false", "off")
                    self._json({"enabled": hub.set_enabled(on)})
                elif parsed.path == "/api/config":
                    qs = urllib.parse.parse_qs(parsed.query)
                    ed_ms = qs.get("extra_delay_ms", [None])[0]
                    qos_q = qs.get("qos", [None])[0]
                    qos = None if qos_q is None else qos_q.lower() not in ("0", "false", "off")
                    try:
                        ed = (float(ed_ms) / 1000.0) if ed_ms else None
                    except ValueError:
                        self._json({"error": "extra_delay_ms inválido"}, 400)
                        return
                    cfg = hub.set_config(extra_delay=ed, qos=qos)
                    self._json({"extra_delay_ms": int(round(cfg["extra_delay"] * 1000)),
                                "qos": bool(cfg["qos"])})
                elif parsed.path == "/api/reboot":
                    from ..net.adapters import reboot_windows
                    from ..i18n import t
                    ok = reboot_windows(20)
                    hub.add_log(t("log.reboot_req"))
                    self._json({"ok": ok, "delay": 20})
                elif parsed.path == "/api/route":
                    qs = urllib.parse.parse_qs(parsed.query)
                    mode = qs.get("mode", [None])[0]
                    host = qs.get("host", [None])[0]
                    port = qs.get("port", [None])[0]
                    self._json(hub.set_route(mode=mode, host=host, port=port))
                elif parsed.path == "/api/lang":
                    # idioma (EN/PT/ES). O painel é a fonte da verdade: detecta e
                    # manda; aqui persistimos pra bandeja/diálogos/logs do Python.
                    from ..i18n import save_lang
                    qs = urllib.parse.parse_qs(parsed.query)
                    lang = qs.get("lang", [None])[0]
                    self._json({"lang": save_lang(lang)})
                elif parsed.path == "/api/opcodes/update":
                    if on_update is None:
                        self._json({"ok": False, "error": "indisponível neste modo"})
                    else:
                        try:
                            self._json(on_update() or {"ok": True})
                        except Exception as e:
                            self._json({"ok": False, "error": str(e)})
                else:
                    self._json({"error": "not found"}, 404)

        self._httpd = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="mitigus-panel", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
