#!/usr/bin/env python3
"""
Mitigus XIV — valida o codec Oodle contra o seu ffxiv_dx11.exe (Fase 3).

Carrega o PE, faz o sigscan das funções Oodle e roda um round-trip
encode/decode (TCP e UDP). Se passar, a base da decodificação Oodle está pronta
para a Fase 4 (mitigação).

    python run_oodle_test.py --exe C:\\caminho\\ffxiv_dx11.exe

Sem --exe, procura em vendor\\ffxiv_dx11.exe e no diretório atual.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_exe(explicit: str | None) -> str | None:
    from mitigus.oodle.locate import find_ffxiv_dx11

    return find_ffxiv_dx11(explicit, base_dir=HERE)


def main() -> int:
    p = argparse.ArgumentParser(description="Valida o Oodle contra o ffxiv_dx11.exe")
    p.add_argument("--exe", help="caminho do ffxiv_dx11.exe (x64)")
    args = p.parse_args()

    if sys.maxsize <= 2**32:
        print("! Use Python 64-bit (x64). O ffxiv_dx11.exe é x64.")
        return 2

    exe = _find_exe(args.exe)
    if not exe:
        print("! ffxiv_dx11.exe não encontrado.")
        print("  Passe --exe <caminho>, ou copie-o para vendor\\ffxiv_dx11.exe.")
        print("  (instale o trial gratuito do FFXIV num PC Windows; o arquivo fica na pasta game\\)")
        return 2

    print(f"=== Mitigus XIV — teste do Oodle ===")
    print(f"  exe: {exe}")
    from mitigus.oodle.oodle import OodleHelper, selftest

    try:
        helper = OodleHelper.from_exe(exe)
    except Exception as e:
        print(f"! Falha ao carregar/sigscan o Oodle: {e}")
        print("  Pode ser um exe de versão muito diferente (padrões de sigscan mudaram).")
        return 1

    print("  módulo Oodle carregado. Rodando round-trip...")
    try:
        ok = selftest(helper)
    except Exception as e:
        print(f"! Erro no round-trip: {e}")
        return 1

    if ok:
        print("  OK — encode/decode Oodle (TCP e UDP) bateram. Fase 3 validada. ✅")
        return 0
    print("  FALHOU — o round-trip não bateu.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
