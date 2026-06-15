#!/usr/bin/env python3
"""
Entry do app empacotado (o .exe). Comportamento "tudo ligado":
pede Administrador (via manifesto UAC no .exe), liga o roteamento e sobe o proxy
com mitigação + painel. O ffxiv_dx11.exe do jogo NÃO vem no pacote — é achado na
sua instalação/trial, ou colado em vendor\\ (ao lado do .exe).

Dois "visuais" do painel (mesma engine, mudam só onde abrem):
  - browser : abre no seu navegador padrão (uma aba).        -> "Mitigus XIV.exe"
  - window  : abre numa janela do app (Edge --app, sem abas). -> "Mitigus XIV (janela).exe"

    --selfcheck   apenas confere que o bundle tem o WinDivert e o index.html (sem Admin).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _selfcheck() -> int:
    import pydivert

    from mitigus.panel import server as panel_server

    base = os.path.dirname(pydivert.__file__)
    dll = os.path.join(base, "windivert_dll", "WinDivert64.dll")
    sysfile = os.path.join(base, "windivert_dll", "WinDivert64.sys")
    index = os.path.join(os.path.dirname(panel_server.__file__), "index.html")

    print("=== Mitigus XIV — selfcheck do pacote ===")
    print(f"  WinDivert64.dll : {os.path.isfile(dll)}")
    print(f"  WinDivert64.sys : {os.path.isfile(sysfile)}")
    print(f"  index.html      : {os.path.isfile(index)}")
    ok = os.path.isfile(dll) and os.path.isfile(sysfile) and os.path.isfile(index)
    print("  resultado       :", "OK" if ok else "FALTANDO ARQUIVOS")
    return 0 if ok else 1


def _run(open_mode: str) -> int:
    from mitigus.net.adapters import enable_routing, is_admin

    print("============================================")
    print("            M I T I G U S   X I V")
    print("============================================")
    if not is_admin():
        print("\n! Preciso de Administrador. Feche e abra de novo (deve aparecer o aviso do UAC).")
        return 2

    print("Ligando o roteamento (PC como gateway do PS5)...")
    enable_routing()
    print("Abrindo o painel...\n")

    import run_proxy

    return run_proxy._run_full(
        ps5_ip=None, pc_ip=None, port=0, mitigate=True, exe=None,
        extra_delay=0.075, opcodes_json=None, panel=True,
        panel_host="0.0.0.0", panel_port=8080, open_mode=open_mode,
    )


def run_entry(open_mode: str = "browser") -> int:
    if "--selfcheck" in sys.argv:
        return _selfcheck()
    rc = 0
    try:
        rc = _run(open_mode)
    except KeyboardInterrupt:
        rc = 0
    except Exception:
        import traceback

        traceback.print_exc()
        rc = 1
    if rc:
        try:
            input("\nPressione Enter para sair...")
        except EOFError:
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(run_entry("browser") or 0)
