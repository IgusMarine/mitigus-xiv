#!/usr/bin/env python3
"""
Baixa/atualiza as definições de opcode do FFXIV (definitions.json), cross-platform.
Substitui o antigo scripts/update-opcodes.sh (que era shell/Linux).

Rode após cada patch do jogo:
    python update_opcodes.py
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mitigus.protocol.opcodes import default_cache_path, load_definitions


def main() -> int:
    p = argparse.ArgumentParser(description="Atualiza definitions.json (fonte XivAlexander)")
    p.add_argument("--out", default=default_cache_path(), help="caminho do cache de saída")
    args = p.parse_args()

    print("Baixando definições de opcode da fonte XivAlexander...")
    try:
        defs = load_definitions(cache_path=args.out, force_update=True)
    except Exception as e:
        print(f"! Falha ao baixar: {e}")
        return 1

    print(f"OK — {len(defs)} definição(ões) salvas em {args.out}")
    for d in defs:
        print(
            f"  - {d.Name}: ActionEffect01=0x{d.S2C_ActionEffect01:04x} "
            f"ActionRequest=0x{d.C2S_ActionRequest:04x} oodleTcp={d.Common_UseOodleTcp}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
