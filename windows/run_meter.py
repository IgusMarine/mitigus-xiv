#!/usr/bin/env python3
"""
Mitigus XIV — DPS METER ao vivo (variante DPS; branch dps-meter).

Roda o MESMO proxy/relay de produção (console -> PC -> servidor) e, em vez de
gravar em arquivo, desofusca os ActionEffect EM TEMPO REAL e serve um painel de
DPS (Neon Bars) que você abre no navegador/celular.

Pipeline: relay (Oodle) -> sink MeterFeed (deob + parse de combate) -> DpsTracker
-> MeterServer (HTTP) -> UI. NÃO altera o app de produção (main); a captura é a
mesma costura opcional do Mitigator.

Uso (Administrador; ffxiv_dx11.exe em vendor\\ p/ o Oodle):
    python run_meter.py
    python run_meter.py --meter-port 8088 --version 2026.06.10.0000.0000
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_proxy
from mitigus.deob.constants import LATEST
from mitigus.meter.live import MeterFeed
from mitigus.meter.server import MeterServer
from mitigus.meter.tracker import DpsTracker
from mitigus.net.adapters import open_firewall_port, primary_ipv4


def main() -> int:
    p = argparse.ArgumentParser(description="Mitigus XIV — DPS meter ao vivo")
    p.add_argument("--ps5-ip", help="(opcional) filtra só este IP; padrão: auto")
    p.add_argument("--pc-ip", help="IP do PC na rede do console (auto se omitido)")
    p.add_argument("--port", type=int, default=0, help="porta do proxy (0 = efêmera)")
    p.add_argument("--exe", help="ffxiv_dx11.exe (necessário p/ o Oodle)")
    p.add_argument("--extra-delay", type=float, default=0.075, help="margem do weave (s)")
    p.add_argument("--opcodes-json", help="arquivo único de opcodes (senão baixa/cache)")
    p.add_argument("--meter-port", type=int, default=8088, help="porta do painel de DPS")
    p.add_argument("--version", default=LATEST, help="versão do jogo p/ o deob")
    args = p.parse_args()

    tracker = DpsTracker()
    feed = MeterFeed(tracker, version=args.version)
    meter = MeterServer(tracker, port=args.meter_port)
    mport = meter.start()
    if open_firewall_port(mport):
        print(f"  firewall: porta {mport} liberada na rede local")
    pc = args.pc_ip or primary_ipv4() or "127.0.0.1"
    print("=== Mitigus XIV — DPS METER ao vivo ===")
    print(f"  painel de DPS: http://127.0.0.1:{mport}   (neste PC)")
    print(f"                 http://{pc}:{mport}   (no celular, mesma rede)")
    print("  Entre em combate; o DPS aparece no painel. Ctrl+C encerra.\n")

    try:
        return run_proxy._run_full(
            ps5_ip=args.ps5_ip,
            pc_ip=args.pc_ip,
            port=args.port,
            mitigate=True,                 # precisa do factory/Oodle
            exe=args.exe,
            extra_delay=args.extra_delay,
            opcodes_json=args.opcodes_json,
            panel=False,                   # UI é a do meter, não o painel de latência
            panel_host="0.0.0.0",
            panel_port=0,
            open_mode="none",
            prompt_reboot=True,
            capture_sink=feed,
        )
    finally:
        meter.stop()


if __name__ == "__main__":
    raise SystemExit(main())
