"""
Fase 0 — sniffer somente-leitura do tráfego do FFXIV.

Abre o WinDivert em modo SNIFF (cópia, não desvia — o tráfego original segue
intacto), reagrupa os bytes TCP por fluxo, detecta o magic FF14ARR e relata o
que está vendo: tipo de conexão, contagem de mensagens, compressão e, quando o
bundle é decodificável (none/zlib), os opcodes IPC. Bundles Oodle são contados,
mas a decodificação fica para a Fase 3.

Nada é modificado aqui. O objetivo é provar a fundação: "conseguimos enxergar o
FF14ARR vindo do PS5 (ou do cliente no PC)".
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Dict, Optional

import pydivert
from pydivert import Flag, Layer

from ..protocol.bundle import BundleStream, decode_body, iter_messages, read_opcode
from ..net.ports import FFXIV_PORT_RANGES, PortRanges, build_filter, port_in_ranges

_COMP_NAME = {0: "none", 1: "zlib", 2: "oodle"}
_CONN_NAME = {1: "zone", 2: "chat"}


class Sniffer:
    def __init__(
        self,
        host: Optional[str] = None,
        layer: str = "forward",
        ranges: PortRanges = FFXIV_PORT_RANGES,
        summary_every: float = 2.0,
    ) -> None:
        self.host = host
        self.layer_name = layer
        self.ranges = ranges
        self.filter = build_filter(host, ranges)
        self._wd_layer = Layer.NETWORK_FORWARD if layer == "forward" else Layer.NETWORK
        self._streams: Dict[tuple, BundleStream] = {}
        self._flows: set = set()
        self._summary_every = summary_every
        self._last_summary = 0.0
        self._announced = False
        # estatísticas
        self.packets = 0
        self.bundles = 0
        self.comp: Counter = Counter()
        self.conn: Counter = Counter()
        self.opcodes: Counter = Counter()

    def run(self) -> None:
        with pydivert.WinDivert(self.filter, layer=self._wd_layer, flags=Flag.SNIFF) as w:
            self._print_header()
            for packet in w:
                self._handle(packet)

    # ----------------------------------------------------------- internos ---
    def _handle(self, packet) -> None:
        self.packets += 1
        if packet.tcp is None:
            return
        payload = packet.payload
        if not payload:
            return

        key = (packet.src_addr, packet.src_port, packet.dst_addr, packet.dst_port)
        flow = self._flow_label(packet)
        if flow not in self._flows:
            self._flows.add(flow)
            print(f"  [fluxo] {flow}")

        stream = self._streams.get(key)
        if stream is None:
            stream = BundleStream()
            self._streams[key] = stream
        stream.feed(payload)

        for header, body in stream:
            self._on_bundle(header, body)

        self._maybe_summary()

    def _on_bundle(self, header, body: bytes) -> None:
        self.bundles += 1
        self.comp[int(header.compression)] += 1
        self.conn[int(header.conn_type)] += 1

        if not self._announced:
            self._announced = True
            print()
            print("  ===================================================")
            print("   FF14ARR detectado — captura do FFXIV funcionando!")
            print(
                f"   conn={_CONN_NAME.get(header.conn_type, header.conn_type)}"
                f"  msgs={header.message_count}"
                f"  compression={_COMP_NAME.get(header.compression, header.compression)}"
                f"  len={header.length}"
            )
            print("  ===================================================")
            print()

        decoded = decode_body(header, body)
        if decoded is None:
            return  # Oodle/indecodificável — contado; opcodes ficam para a Fase 3
        for msg, mpayload in iter_messages(header, decoded):
            op = read_opcode(msg, mpayload)
            if op is not None:
                self.opcodes[op] += 1

    def _flow_label(self, packet) -> str:
        # coloca o lado servidor (porta do FFXIV) à direita
        if port_in_ranges(packet.dst_port, self.ranges):
            return f"{packet.src_addr}:{packet.src_port} -> {packet.dst_addr}:{packet.dst_port}"
        return f"{packet.dst_addr}:{packet.dst_port} <- {packet.src_addr}:{packet.src_port}"

    def _maybe_summary(self) -> None:
        now = time.monotonic()
        if now - self._last_summary < self._summary_every:
            return
        self._last_summary = now
        print("  " + self.summary_line())

    def summary_line(self) -> str:
        comp = " ".join(f"{_COMP_NAME.get(k, k)}={v}" for k, v in sorted(self.comp.items()))
        conn = " ".join(f"{_CONN_NAME.get(k, k)}={v}" for k, v in sorted(self.conn.items()))
        return (
            f"pkts={self.packets} bundles={self.bundles} | "
            f"conn[{conn}] comp[{comp}] | flows={len(self._flows)} "
            f"opcodes_seen={len(self.opcodes)}"
        )

    def print_report(self) -> None:
        print()
        print("  ===== resumo da sessão =====")
        print("  " + self.summary_line())
        if self.opcodes:
            print("  opcodes mais vistos (apenas bundles none/zlib decodificáveis):")
            for op, c in self.opcodes.most_common(15):
                print(f"    0x{op:04x}  x{c}")
        if self.comp.get(2):
            print(
                f"  obs: {self.comp[2]} bundles Oodle não decodificados — esperado; "
                "a decodificação Oodle entra na Fase 3."
            )
        if self.bundles == 0:
            print("  nenhum bundle visto. Cheque: Admin, gateway do PS5 = este PC,")
            print("  enable-routing.ps1 rodado, e tráfego de jogo ativo (entre numa zona).")
        print("  ============================")

    def _print_header(self) -> None:
        print(f"  layer   : {self.layer_name}")
        print(f"  filter  : {self.filter}")
        if self.host:
            print(f"  host    : {self.host}")
        print("  status  : aguardando tráfego do FFXIV...  (Ctrl+C para encerrar)")
        print()
