#!/usr/bin/env python3
"""
Mitigus XIV — Fase 5: painel web (demo, sem Admin/PS5).

Sobe o painel com um gerador de telemetria sintético, para você ver a UI ao vivo
(liga/desliga + cortes de lock) no navegador ou no celular. O painel "de verdade"
é o run_proxy.py --mitigate --panel.

    python run_panel.py
    python run_panel.py --port 9000
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mitigus.net.adapters import primary_ipv4
from mitigus.panel.hub import ControlHub
from mitigus.panel.server import PanelServer


def _feeder(hub: ControlHub, stop: threading.Event) -> None:
    hub.add_log("demo: gerando telemetria sintética")
    hub.note_flow()
    original = 600
    while not stop.is_set():
        rtt = random.randint(70, 240)
        reduced = max(0, original - max(0, rtt - 75)) if hub.is_enabled() else original
        hub.record_effect(original, reduced, rtt)
        # WAN sintético: a perna de rede é ~85% do ping sentido, com piso estável e
        # uma retransmissão eventual (pra ver o HUD reagir).
        wan = rtt * 0.85
        hub.record_net(wan, wan * 0.82, random.choice([0, 0, 0, 0, 0, 1]))
        hub.add_log(f"S2C_ActionEffect wait={original}ms->{reduced}ms rtt={rtt}ms")
        stop.wait(1.4)


def main() -> int:
    p = argparse.ArgumentParser(description="Mitigus XIV — painel (demo)")
    p.add_argument("--host", default="0.0.0.0", help="host do painel (padrão: LAN)")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    hub = ControlHub()
    ip = primary_ipv4() or "127.0.0.1"
    hub.set_info(
        mode="demo", pc_ip=ip, admin=True, routing=True, oodle_loaded=True,
        opcodes_count=1, opcodes_date="10/06/2026", opcodes_matched=True, mitigate=True,
        server_ip="204.2.29.6", server_region="NA", server_label="América do Norte",
        game_active=1,
        log_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitigus.log"),
    )

    def fake_update():
        d = time.strftime("%d/%m/%Y")
        hub.set_info(opcodes_date=d)
        hub.add_log("opcodes atualizados (demo)")
        return {"ok": True, "count": 1, "date": d}

    server = PanelServer(hub, host=args.host, port=args.port, on_update_opcodes=fake_update)
    port = server.start()

    print("=== Mitigus XIV — painel (demo) ===")
    print(f"  abra:  http://{ip}:{port}   (ou http://127.0.0.1:{port})")
    print("  toque no botão para ligar/desligar; os cortes mudam ao vivo. Ctrl+C encerra.")
    try:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass

    stop = threading.Event()
    threading.Thread(target=_feeder, args=(hub, stop), daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
