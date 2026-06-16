#!/usr/bin/env python3
"""
Mitigus XIV — modo CAPTURA (variante DPS meter; branch dps-meter).

Roda o MESMO proxy/relay de produção (PS5 -> PC -> servidor), com a mitigação
de weave ligada, mas ADICIONALMENTE grava os segmentos IPC pós-Oodle num
arquivo .jsonl para desofuscação/análise offline (alimenta research/deob).

Por que reusar o proxy de produção e não um sniff passivo:
  - O relay termina o TCP desde o SYN, então o estado do Oodle (stateful por
    canal) fica sincronizado do início — captura confiável. Um sniff iniciado
    no meio do fluxo dessincroniza o Oodle.
  - O console continua jogando normalmente; a captura é read-only sobre o
    conteúdo (os bytes seguem intactos pro PS5).

NÃO altera o app de produção (main): a captura é uma costura opcional
(default-off) no Mitigator; aqui só a ligamos.

Uso (Administrador, igual ao modo real do Mitigus):
    python run_capture.py                 # grava capture-AAAAMMDD-HHMMSS.jsonl
    python run_capture.py --out luta.jsonl
    python run_capture.py --no-panel      # sem painel web

Pré-requisitos (mesmos da mitigação): roteamento habilitado + ffxiv_dx11.exe
em vendor\\ (para o Oodle). Pare o Mitigus de produção antes (um relay por vez).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_proxy
from mitigus.paths import app_dir


def main() -> int:
    p = argparse.ArgumentParser(description="Mitigus XIV — modo captura (DPS)")
    p.add_argument("--out", help="arquivo .jsonl (padrão: capture-<data>.jsonl ao lado do app)")
    p.add_argument("--ps5-ip", help="(opcional) filtra só este IP; padrão: capta o console automaticamente")
    p.add_argument("--pc-ip", help="IP do PC na rede do console (auto se omitido)")
    p.add_argument("--port", type=int, default=0, help="porta do proxy (0 = efêmera)")
    p.add_argument("--exe", help="ffxiv_dx11.exe (necessário p/ o Oodle no Dawntrail)")
    p.add_argument("--extra-delay", type=float, default=0.075, help="margem de segurança do weave (s)")
    p.add_argument("--opcodes-json", help="arquivo único de opcodes (senão baixa/usa cache)")
    p.add_argument("--no-panel", action="store_true", help="não subir o painel web")
    p.add_argument("--panel-port", type=int, default=8080, help="porta do painel (padrão 8080)")
    args = p.parse_args()

    out = args.out or os.path.join(
        app_dir(), f"capture-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    print("=== Mitigus XIV — modo CAPTURA (variante DPS) ===")
    print(f"  dump: {out}")
    print("  Jogue uma luta normal no console; Ctrl+C encerra e fecha o arquivo.")

    return run_proxy._run_full(
        ps5_ip=args.ps5_ip,
        pc_ip=args.pc_ip,
        port=args.port,
        mitigate=True,                 # captura precisa do factory/Oodle
        exe=args.exe,
        extra_delay=args.extra_delay,
        opcodes_json=args.opcodes_json,
        panel=not args.no_panel,
        panel_host="0.0.0.0",
        panel_port=args.panel_port,
        open_mode="none",
        prompt_reboot=True,
        capture_path=out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
