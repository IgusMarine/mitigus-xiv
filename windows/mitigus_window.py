#!/usr/bin/env python3
"""
"Mitigus XIV (app).exe" — janela DEFINITIVA, sem a barra do Windows.

Renderiza o painel cristal (o index.html bonito) numa janela FRAMELESS pelo motor
WebView2 (Chromium do Edge) via pywebview. A barra de título é nossa: marca +
abas (Painel/Configuração) + botões minimizar/maximizar/fechar. Fechar NÃO encerra
— manda pra BANDEJA (ícone perto do relógio); "Sair" encerra de vez.

O servidor HTTP continua igual (0.0.0.0:8080), então o painel também abre no
celular (lá, sem a barra própria — detectado pelo ?app=1 que só a janela usa).

    python mitigus_window.py                 # modo real (proxy + janela), pede Admin
    python mitigus_window.py --test-url URL  # só a janela apontando pra URL (sem Admin)
"""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from mitigus import i18n  # noqa: E402  (depende do sys.path acima)

_window = None
_tray = None
_is_max = False
_quitting = False


def _msgbox(text: str, title: str = "Mitigus XIV", flags: int = 0x10) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        pass


def _icon_image():
    from PIL import Image

    from mitigus.paths import resource_dir
    try:
        return Image.open(os.path.join(resource_dir(), "mitigus.ico"))
    except Exception:
        return Image.new("RGB", (16, 16), (11, 22, 32))


def _app_url(url: str) -> str:
    """Acrescenta ?app=1 (faz o HTML mostrar a barra de título própria)."""
    base = (url or "http://127.0.0.1:8080").rstrip("/")
    return base + "/?app=1"


class _Api:
    """Exposto como window.pywebview.api.* no JS (botões da barra)."""

    def minimize(self):
        if _window:
            _window.minimize()

    def toggle_maximize(self):
        global _is_max
        if not _window:
            return
        if _is_max:
            _window.restore()
            _is_max = False
        else:
            _window.maximize()
            _is_max = True

    def hide_to_tray(self):
        if _window:
            threading.Thread(target=_window.hide, daemon=True).start()


def _on_closing():
    # Alt+F4 / fechar do SO -> some pra bandeja (a menos que seja "Sair").
    if _quitting:
        return True
    if _window:
        threading.Thread(target=_window.hide, daemon=True).start()
    return False


def _on_maximized():
    global _is_max
    _is_max = True


def _on_restored():
    global _is_max
    _is_max = False


def _run_tray():
    global _tray
    import pystray

    def _show(icon=None, item=None):
        if _window:
            _window.show()

    def _quit(icon=None, item=None):
        global _quitting
        _quitting = True
        try:
            if _tray:
                _tray.stop()
        finally:
            if _window:
                _window.destroy()

    # texto via callable: pystray reavalia quando o menu abre, então segue o idioma
    # atual (o painel manda /api/lang e o i18n troca em tempo real).
    menu = pystray.Menu(
        pystray.MenuItem(lambda item: i18n.t("tray.open"), _show, default=True),
        pystray.MenuItem(lambda item: i18n.t("tray.quit"), _quit),
    )
    _tray = pystray.Icon("MitigusXIV", _icon_image(), "Mitigus XIV", menu)
    _tray.run()


def run_window(url: str) -> int:
    """Abre a janela frameless apontando pra URL e roda a bandeja. Bloqueia."""
    global _window
    import webview

    _window = webview.create_window(
        "Mitigus XIV", url=_app_url(url), js_api=_Api(),
        width=580, height=760, min_size=(560, 600),
        frameless=True, easy_drag=False,
        background_color="#0b1620", resizable=True,
    )
    for name, fn in (("closing", _on_closing), ("maximized", _on_maximized),
                     ("restored", _on_restored)):
        ev = getattr(_window.events, name, None)
        if ev is not None:
            ev += fn
    webview.start(func=_run_tray, debug=False)
    return 0


def main() -> int:
    # idioma salvo (ou o do Windows no 1º uso) — pra bandeja/diálogos saírem certos
    # antes do painel abrir e mandar /api/lang.
    i18n.load_lang()

    # Modo de teste: só a janela, sem Admin/proxy (pra ver a UI contra o run_panel).
    if "--test-url" in sys.argv:
        i = sys.argv.index("--test-url")
        url = sys.argv[i + 1] if i + 1 < len(sys.argv) else "http://127.0.0.1:8080"
        return run_window(url)

    from mitigus.net.adapters import (
        ask_yes_no, enable_routing, is_admin, mark_reboot_dismissed,
        reboot_should_prompt, reboot_windows)

    if not is_admin():
        _msgbox(i18n.t("dlg.need_admin"))
        return 2

    enable_routing()
    if reboot_should_prompt():
        mark_reboot_dismissed()
        if ask_yes_no(i18n.t("dlg.reboot_title"), i18n.t("dlg.reboot_text")):
            reboot_windows(20)
            return 0

    import run_proxy

    ready: queue.Queue = queue.Queue()

    def proxy_thread():
        try:
            run_proxy._run_full(
                ps5_ip=None, pc_ip=None, port=0, mitigate=True, exe=None,
                extra_delay=0.075, opcodes_json=None, panel=True,
                panel_host="0.0.0.0", panel_port=8080, open_mode="none",
                prompt_reboot=False,
                on_ready=lambda url, hub, refresh=None: ready.put((url, hub, refresh)),
            )
        except Exception:
            import traceback
            traceback.print_exc()
        ready.put((None, None, None))

    threading.Thread(target=proxy_thread, daemon=True).start()
    try:
        url, hub, _refresh = ready.get(timeout=90)
    except queue.Empty:
        url, hub, _refresh = None, None, None
    if hub is None or not url:
        _msgbox(i18n.t("dlg.cant_start"))
        return 1

    return run_window(url)


if __name__ == "__main__":
    try:
        raise SystemExit(main() or 0)
    except SystemExit:
        raise
    except Exception:
        _msgbox(i18n.t("dlg.unexpected"))
        raise SystemExit(1)
