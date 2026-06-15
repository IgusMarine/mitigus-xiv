"""
Portas do FFXIV e construção do filtro do WinDivert.

Os ranges são as portas TCP exigidas pela Square Enix (as portas de ESCUTA do
servidor) — o servidor de zona/chat fica dentro delas. A linguagem de filtro do
WinDivert não tem notação CIDR nem range de porta, então expandimos em
comparações `>=`/`<=` explícitas.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

PortRanges = Tuple[Tuple[int, int], ...]

FFXIV_PORT_RANGES: PortRanges = (
    (54992, 54994),
    (55006, 55007),
    (55021, 55040),
)


def port_in_ranges(port: int, ranges: Iterable[Tuple[int, int]] = FFXIV_PORT_RANGES) -> bool:
    return any(lo <= port <= hi for lo, hi in ranges)


def format_ranges(ranges: Iterable[Tuple[int, int]] = FFXIV_PORT_RANGES) -> str:
    return ", ".join(f"{lo}-{hi}" if lo != hi else str(lo) for lo, hi in ranges)


def build_filter(host: Optional[str] = None, ranges: PortRanges = FFXIV_PORT_RANGES) -> str:
    terms = []
    for lo, hi in ranges:
        terms.append(f"(tcp.SrcPort >= {lo} and tcp.SrcPort <= {hi})")
        terms.append(f"(tcp.DstPort >= {lo} and tcp.DstPort <= {hi})")
    expr = "tcp and (" + " or ".join(terms) + ")"
    if host:
        expr += f" and (ip.SrcAddr == {host} or ip.DstAddr == {host})"
    return expr
