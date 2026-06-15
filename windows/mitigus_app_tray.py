#!/usr/bin/env python3
"""
Versão SEM console (segundo plano): nenhuma janela preta. Roda com um ícone na
bandeja do sistema (perto do relógio) — clique direito -> "Abrir painel" / "Sair".
Gera o "Mitigus XIV (sem console).exe".

O proxy roda numa thread; a thread principal segura o ícone da bandeja. Como não
há console, tudo que apareceria na tela é gravado só no mitigus.log (ao lado do
programa). Erros aparecem numa caixinha do Windows.
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


def _msgbox(text: str, title: str = "Mitigus XIV") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def _icon_image():
    from PIL import Image

    from mitigus.paths import resource_dir

    return Image.open(os.path.join(resource_dir(), "mitigus.ico"))


def _open(url: str) -> None:
    import run_proxy

    if not run_proxy.open_app_window(url):
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass


def main() -> int:
    from mitigus.net.adapters import enable_routing, is_admin

    if not is_admin():
        _msgbox("Preciso de Administrador.\nAbra de novo e aceite o aviso do Windows (UAC).")
        return 2
    enable_routing()

    import run_proxy

    ready: queue.Queue = queue.Queue()

    def proxy_thread():
        try:
            run_proxy._run_full(
                ps5_ip=None, pc_ip=None, port=0, mitigate=True, exe=None,
                extra_delay=0.075, opcodes_json=None, panel=True,
                panel_host="0.0.0.0", panel_port=8080, open_mode="none",
                on_ready=lambda url, hub, refresh=None: ready.put(url),
            )
        except Exception:
            import traceback

            traceback.print_exc()
        ready.put(None)  # se chegou aqui sem URL, foi falha

    threading.Thread(target=proxy_thread, daemon=True).start()

    try:
        url = ready.get(timeout=45)
    except queue.Empty:
        url = None
    if not url:
        _msgbox("Não consegui iniciar.\nVeja o arquivo mitigus.log (ao lado do programa).")
        return 1

    _open(url)  # abre o painel uma vez

    import pystray

    menu = pystray.Menu(
        pystray.MenuItem("Abrir painel", lambda icon, item: _open(url), default=True),
        pystray.MenuItem("Sair", lambda icon, item: (icon.stop(), os._exit(0))),
    )
    pystray.Icon("MitigusXIV", _icon_image(), "Mitigus XIV", menu).run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main() or 0)
    except SystemExit:
        raise
    except Exception:
        _msgbox("Erro inesperado.\nVeja o arquivo mitigus.log.")
        raise SystemExit(1)
