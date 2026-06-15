#!/usr/bin/env python3
"""
Mitigus XIV — Fase 0: spike de captura (somente leitura / SNIFF).

Confirma que conseguimos ENXERGAR o tráfego do FFXIV (o magic FF14ARR) passando
pelo PC. Não modifica nada — só observa. É a fundação antes do proxy (Fase 1).

Dois modos:
  1) Validar o parser com o FFXIV rodando NESTE PC (mais confiável):
        python run_sniff.py --layer network
  2) Enxergar o PS5 roteado por este PC:
        (rode setup\\enable-routing.ps1 como Admin e aponte o gateway do PS5)
        python run_sniff.py --host <IP_DO_PS5>

Requer Administrador (o WinDivert carrega um driver de kernel).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mitigus.net.adapters import is_admin, primary_ipv4
from mitigus.net.ports import FFXIV_PORT_RANGES, format_ranges


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mitigus XIV — Fase 0 sniffer (FFXIV / FF14ARR)"
    )
    p.add_argument("--host", help="IP do PS5 (ou do cliente) para filtrar só esse host")
    p.add_argument(
        "--layer",
        choices=("forward", "network"),
        default="forward",
        help="forward = tráfego roteado do PS5 (padrão); network = cliente neste PC",
    )
    p.add_argument(
        "--list-ports", action="store_true", help="mostra os ranges de porta e sai"
    )
    args = p.parse_args()

    if args.list_ports:
        print("ranges de porta do FFXIV (TCP):", format_ranges(FFXIV_PORT_RANGES))
        return 0

    print("=== Mitigus XIV — Fase 0 (captura) ===")

    if not is_admin():
        print("! Precisa rodar como Administrador (o WinDivert carrega um driver de kernel).")
        print("  Abra um PowerShell/Prompt COMO ADMINISTRADOR e rode de novo.")
        return 2

    if args.layer == "forward" and not args.host:
        ip = primary_ipv4()
        print("  modo: PS5 via forward.")
        if ip:
            print(f"  dica: gateway do PS5 = {ip}, e rode setup\\enable-routing.ps1 antes.")
        print("  (use --host <IP_DO_PS5> para filtrar só o PS5)")

    try:
        from mitigus.capture.sniffer import Sniffer
    except ImportError as e:
        print(f"! Falta dependência: {e}")
        print("  Rode:  pip install -r requirements.txt")
        return 3

    sniffer = Sniffer(host=args.host, layer=args.layer)
    try:
        sniffer.run()
    except KeyboardInterrupt:
        pass
    except PermissionError:
        print("! Permissão negada ao abrir o WinDivert. Rode como Administrador.")
        return 2
    except OSError as e:
        print(f"! Erro ao abrir o WinDivert: {e}")
        print("  Cheque: Administrador, antivírus, e se outra instância já usa o driver.")
        return 4
    finally:
        try:
            sniffer.print_report()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
