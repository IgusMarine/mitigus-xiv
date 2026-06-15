#!/usr/bin/env python3
"""
Versão DEFINITIVA — "Mitigus XIV (app).exe".

Mostra o PAINEL CRISTAL (o HTML bonito) numa janela de app renderizada pelo motor
do Edge (WebView2/Chromium) via modo --app — então fica idêntico ao painel web
lindo E renderiza/atualiza certinho (motor moderno, não o navegador padrão do
usuário, que foi o que falhava). Vive na BANDEJA: fechar a janela do painel NÃO
encerra; o ícone perto do relógio reabre. "Sair" encerra.

Se não houver Edge/Chrome (raro no Win10/11), cai numa janela nativa (tkinter) que
lê o motor direto — feia, porém sempre funciona. console=False (sem janela preta).
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


def _msgbox(text: str, title: str = "Mitigus XIV", flags: int = 0x10) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        pass


def _icon_image():
    from PIL import Image

    from mitigus.paths import resource_dir
    return Image.open(os.path.join(resource_dir(), "mitigus.ico"))


def main() -> int:
    from mitigus.net.adapters import (
        ask_yes_no, enable_routing, is_admin, mark_reboot_dismissed, primary_ipv4,
        reboot_should_prompt, reboot_windows)

    if not is_admin():
        _msgbox("Preciso de Administrador.\nAbra de novo e aceite o aviso do Windows (UAC).")
        return 2

    enable_routing()
    if reboot_should_prompt():
        mark_reboot_dismissed()
        if ask_yes_no(
            "Mitigus XIV — reiniciar o Windows?",
            "Para o seu PS5/PS4 conseguir conectar (aceitar o PC como gateway), o "
            "Windows precisa ter sido reiniciado UMA vez depois de ativar o "
            "compartilhamento de internet. Sem isso, o console dá erro de rede.\n\n"
            "• Se o console JÁ conecta normalmente, clique Não.\n"
            "• Se ainda não testou, ou deu erro de rede no console, clique Sim.\n\n"
            "Salve seus arquivos abertos. Reiniciar agora?",
        ):
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
        url, hub, refresh_opcodes = ready.get(timeout=90)
    except queue.Empty:
        url, hub, refresh_opcodes = None, None, None
    if hub is None:
        _msgbox("Não consegui iniciar.\n\nSe a versão ANTERIOR do Mitigus ainda estiver "
                "aberta (ícone na bandeja, perto do relógio), feche-a primeiro: clique com "
                "o botão direito nela e em 'Sair'. Depois abra este de novo.\n\n"
                "Detalhes no arquivo mitigus.log (ao lado do programa).")
        return 1

    # Tenta o painel cristal no Edge/Chrome (--app). Se abrir, vira app de bandeja.
    if run_proxy.open_app_window(url):
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem("Abrir painel", lambda i, it: run_proxy.open_app_window(url),
                                 default=True),
                pystray.MenuItem("Sair", lambda i, it: (i.stop(), os._exit(0))),
            )
            pystray.Icon("MitigusXIV", _icon_image(), "Mitigus XIV", menu).run()
            return 0
        except Exception:
            import traceback
            traceback.print_exc()
            # sem bandeja -> cai pra janela nativa abaixo

    # Sem Edge/Chrome (ou bandeja falhou): janela nativa (sempre funciona).
    pc_ip = primary_ipv4() or "127.0.0.1"
    phone_url = (url or "").replace("127.0.0.1", pc_ip)
    from mitigus.panel.native import NativePanel
    NativePanel(hub, gateway_ip=pc_ip, phone_url=phone_url,
                on_update_opcodes=refresh_opcodes,
                on_reboot=lambda: reboot_windows(20)).run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main() or 0)
    except SystemExit:
        raise
    except Exception:
        _msgbox("Erro inesperado.\nVeja o arquivo mitigus.log.")
        raise SystemExit(1)
