"""
Cola WinDivert: NAT em userland que coloca o proxy no caminho do PS5.

   STATUS: precisa de validação EM HARDWARE (PS5 + PC com Admin). O núcleo
   (conntrack + relay) é testado em loopback; esta camada faz a injeção de
   pacotes e os detalhes finos (ifidx da injeção inbound, ICMP redirects) só
   dá para afinar com tráfego real. Está estruturada e documentada para iterar.

Faz NAT bidirecional para fingir, dos dois lados, que ninguém está no meio:

  DNAT (forward layer):  PS5 -> servidor:porta_ffxiv
        reescreve dst -> (PC, proxy_port) e injeta INBOUND no stack local,
        para o relay (ouvindo em proxy_port) aceitar. No SYN, grava no
        conntrack (PS5) -> (servidor) para o relay saber o destino real.

  SNAT (network layer, outbound):  PC:proxy_port -> PS5
        reescreve src -> (servidor, porta_ffxiv), para o PS5 ver as respostas
        como se viessem do servidor.

A conexão upstream do relay (PC -> servidor real) NÃO é tocada: ela é local
(network layer) com src_port efêmero, fora dos dois filtros acima.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

import pydivert
from pydivert import Direction, Layer

from .conntrack import ConnTrack
from ..net.ports import FFXIV_PORT_RANGES, PortRanges


@dataclass
class ProxyConfig:
    pc_ip: str
    proxy_port: int
    ps5_ip: Optional[str] = None  # None = captura qualquer dispositivo roteado (o PS5)
    ranges: PortRanges = field(default=FFXIV_PORT_RANGES)


def _dst_port_expr(ranges: PortRanges) -> str:
    return " or ".join(
        f"(tcp.DstPort >= {lo} and tcp.DstPort <= {hi})" for lo, hi in ranges
    )


class DivertNat:
    def __init__(self, cfg: ProxyConfig, conntrack: ConnTrack, priority: int = 1000) -> None:
        self.cfg = cfg
        self._ct = conntrack
        # Prioridade ALTA no handle forward do jogo: o FFXIV é desviado pro proxy ANTES
        # de o Masquerade (NAT geral, prioridade menor) tocar no pacote. Assim os dois
        # convivem na mesma camada FORWARD sem brigar (padrão multi-handle do basil00).
        self._priority = priority
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._handles: list = []
        self.on_log = lambda msg: print(f"  [nat] {msg}")

    # ------------------------------------------------------------- controle ---
    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._guard(self._dnat_loop), name="mitigus-dnat", daemon=True),
            threading.Thread(target=self._guard(self._snat_loop), name="mitigus-snat", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for h in self._handles:
            try:
                h.close()
            except Exception:
                pass

    def _guard(self, fn):
        def wrapped():
            try:
                fn()
            except Exception as exc:  # mantém o outro loop vivo; reporta
                if not self._stop.is_set():
                    self.on_log(f"loop falhou: {exc!r}")
        return wrapped

    # ---------------------------------------------------------------- DNAT ---
    def _dnat_filter(self) -> str:
        src = f"ip.SrcAddr == {self.cfg.ps5_ip} and " if self.cfg.ps5_ip else ""
        return f"tcp and {src}({_dst_port_expr(self.cfg.ranges)})"

    def _dnat_loop(self) -> None:
        with pydivert.WinDivert(self._dnat_filter(), layer=Layer.NETWORK_FORWARD,
                                priority=self._priority) as w:
            self._handles.append(w)
            inject = pydivert.WinDivert("false", layer=Layer.NETWORK)
            inject.open()
            self._handles.append(inject)
            self.on_log(f"DNAT ativo (forward, prio={self._priority}): {self._dnat_filter()}")
            for packet in w:
                if self._stop.is_set():
                    break
                self._dnat_one(packet, inject)

    def _dnat_one(self, packet, inject) -> None:
        tcp = packet.tcp
        if tcp is None:
            return
        if tcp.syn and not tcp.ack:
            self._ct.remember(packet.src_addr, packet.src_port, packet.dst_addr, packet.dst_port)
            self.on_log(
                f"novo fluxo {packet.src_addr}:{packet.src_port} -> "
                f"{packet.dst_addr}:{packet.dst_port}"
            )
        packet.dst_addr = self.cfg.pc_ip
        packet.dst_port = self.cfg.proxy_port
        packet.direction = Direction.INBOUND
        inject.send(packet)

    # ---------------------------------------------------------------- SNAT ---
    def _snat_filter(self) -> str:
        dst = f" and ip.DstAddr == {self.cfg.ps5_ip}" if self.cfg.ps5_ip else ""
        return f"outbound and tcp and tcp.SrcPort == {self.cfg.proxy_port}{dst}"

    def _snat_loop(self) -> None:
        with pydivert.WinDivert(self._snat_filter(), layer=Layer.NETWORK) as w:
            self._handles.append(w)
            self.on_log(f"SNAT ativo (network): {self._snat_filter()}")
            for packet in w:
                if self._stop.is_set():
                    break
                self._snat_one(packet, w)

    def _snat_one(self, packet, w) -> None:
        server = self._ct.lookup(packet.dst_addr, packet.dst_port)
        if server is not None:
            packet.src_addr = server[0]
            packet.src_port = server[1]
        w.send(packet)
