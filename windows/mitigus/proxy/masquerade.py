"""
NAT / masquerade em userland (WinDivert) — o equivalente Windows do
`iptables MASQUERADE` do XivMitm.

Problema que resolve: com o gateway do PS5/aparelho apontando pro PC, o PC
encaminha o tráfego, mas o roteador (de provedor) frequentemente NÃO roteia esse
tráfego "de passagem" (origem = aparelho). A solução é mascarar: reescrever a
ORIGEM do tráfego do aparelho pro IP do PC (e a porta pra uma porta alocada),
guardar o mapeamento, e desfazer no retorno. Assim o roteador só vê o PC.

PRÉ-REQUISITO (confirmado em hardware): o IP forwarding do Windows precisa estar
ativo (IPEnableRouter=1 + RemoteAccess) E o PC precisa ter sido REINICIADO depois
de ligar isso — o IPEnableRouter só vale após reboot. Com forwarding ativo, o
tráfego do aparelho (gateway = PC) que o Windows encaminha aparece na camada
NETWORK_FORWARD (~3000 pacotes/20s medidos com o celular). Falta só o NAT.

Arquitetura (padrão de dois handles do basil00, issue #39):
  SAÍDA  (NETWORK_FORWARD): aparelho -> internet, sendo encaminhado pelo PC.
         src (aparelho) -> (IP do PC, porta alocada 20000-29999). PAT.
         Reinjeta no forward -> o SO roteia pro gateway real; como a origem virou o
         IP do PC, o roteador devolve normalmente (era isso que faltava).
  VOLTA  (NETWORK, inbound): internet -> (IP do PC : porta alocada). Como o SNAT pôs
         origem = PC, a resposta volta endereçada ao PC = tráfego LOCAL (cai na
         NETWORK, não na FORWARD). Desfaz: dst -> (aparelho, porta original),
         reinjeta OUTBOUND pro aparelho na LAN.

A faixa 20000-29999 é escolhida de propósito ABAIXO da faixa efêmera do Windows
(49152+), pra o loop de volta não encostar no tráfego do próprio PC.

   STATUS: validar EM HARDWARE (use run_share.py com o celular). A captura na
   FORWARD já foi confirmada por `run_share.py --diag`. Falta confirmar o NAT
   ponta-a-ponta (internet no aparelho). Não trata ICMP (ping); cobre TCP e UDP.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Tuple

import pydivert
from pydivert import Direction, Layer


class NatTable:
    """Conntrack + alocação de porta (PAT) do masquerade. Thread-safe e testável."""

    def __init__(self, pool: Tuple[int, int] = (20000, 29999), ttl: float = 120.0,
                 clock: Callable[[], float] = time.monotonic):
        self._lo, self._hi = pool
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._fwd = {}   # (proto,dev_ip,dev_port,dst_ip,dst_port) -> [alloc, dev_ip, dev_port, last_seen]
        self._rev = {}   # (proto,alloc,dst_ip,dst_port) -> fkey
        self._used = {}  # (proto,alloc) -> fkey
        self._cursor = self._lo

    def _alloc_port(self, proto: str) -> Optional[int]:
        n = self._hi - self._lo + 1
        for _ in range(n):
            p = self._cursor
            self._cursor = self._lo if self._cursor >= self._hi else self._cursor + 1
            if (proto, p) not in self._used:
                return p
        return None

    def snat(self, proto, dev_ip, dev_port, dst_ip, dst_port) -> Optional[int]:
        fkey = (proto, dev_ip, dev_port, dst_ip, dst_port)
        with self._lock:
            e = self._fwd.get(fkey)
            if e is not None:
                e[3] = self._clock()
                return e[0]
            alloc = self._alloc_port(proto)
            if alloc is None:
                return None
            self._fwd[fkey] = [alloc, dev_ip, dev_port, self._clock()]
            self._used[(proto, alloc)] = fkey
            self._rev[(proto, alloc, dst_ip, dst_port)] = fkey
            return alloc

    def dnat(self, proto, alloc, internet_ip, internet_port) -> Optional[Tuple[str, int]]:
        with self._lock:
            fkey = self._rev.get((proto, alloc, internet_ip, internet_port))
            if fkey is None:
                return None
            e = self._fwd.get(fkey)
            if e is None:
                return None
            e[3] = self._clock()
            return (e[1], e[2])

    def gc(self) -> int:
        now = self._clock()
        with self._lock:
            dead = [k for k, e in self._fwd.items() if now - e[3] > self._ttl]
            for fkey in dead:
                e = self._fwd.pop(fkey)
                proto, _, _, dst_ip, dst_port = fkey
                self._used.pop((proto, e[0]), None)
                self._rev.pop((proto, e[0], dst_ip, dst_port), None)
            return len(dead)

    def __len__(self):
        with self._lock:
            return len(self._fwd)


def _lan_range(pc_ip: str) -> Tuple[str, str]:
    """Faixa /24 da LAN a partir do IP do PC (ex.: 192.168.0.198 -> .0 .. .255)."""
    p = pc_ip.split(".")
    return ".".join(p[:3] + ["0"]), ".".join(p[:3] + ["255"])


class Masquerade:
    def __init__(self, pc_ip: str, pool: Tuple[int, int] = (20000, 29999),
                 on_log: Optional[Callable[[str], None]] = None, priority: int = 0,
                 qos=None):
        self.pc_ip = pc_ip
        self.pool = pool
        # controlador anti-bufferbloat opcional (BufferbloatController). Só atua no
        # tráfego de FUNDO (o jogo nem passa por aqui — vai pro DivertNat). off=None.
        self.qos = qos
        # Prioridade do handle de SAÍDA (forward). Fica ABAIXO do DivertNat (jogo), pra
        # o tráfego do FFXIV ser desviado pro proxy ANTES de cair no NAT geral.
        self.priority = priority
        self.nat = NatTable(pool=pool)
        self._log = on_log or (lambda s: None)
        self._stop = threading.Event()
        self._lan_prefix = ".".join(pc_ip.split(".")[:3]) + "."
        self._out_handle = None
        self._in_handle = None
        self._threads = []
        self.out_packets = 0
        self.in_matched = 0

    def start(self):
        lo, hi = self.pool
        lan_lo, lan_hi = _lan_range(self.pc_ip)
        self._lan_prefix = ".".join(self.pc_ip.split(".")[:3]) + "."
        # SAÍDA (camada FORWARD): o tráfego do aparelho que o Windows ENCAMINHA aparece
        # aqui (confirmado em hardware: ~3000 pacotes/20s do celular nesta camada). É o
        # padrão de dois handles do basil00 (#39): FORWARD pra interceptar a saída,
        # NETWORK pra tratar o retorno local. O recorte "destino FORA da LAN" (= internet)
        # é feito em Python no _out_loop (o WinDivert recusa 'not (...)' -> WinError 87).
        out_filter = (f"(tcp or udp) and "
                      f"ip.SrcAddr >= {lan_lo} and ip.SrcAddr <= {lan_hi} and ip.SrcAddr != {self.pc_ip}")
        # VOLTA (camada NETWORK, inbound): respostas da internet pro PC nas portas que
        # alocamos (PAT). Como o SNAT pôs origem = IP do PC, a resposta volta endereçada
        # ao PC (= tráfego local), então cai na NETWORK, não na FORWARD.
        in_filter = (f"inbound and (tcp or udp) and ip.DstAddr == {self.pc_ip} and "
                     f"((tcp.DstPort >= {lo} and tcp.DstPort <= {hi}) or "
                     f"(udp.DstPort >= {lo} and udp.DstPort <= {hi}))")

        # Abre os DOIS handles em SEQUÊNCIA (na thread principal) para não correr no
        # driver: o 1º instala/sobe o WinDivert; o 2º anexa (driver já no ar). Evita o
        # erro 1058 que matava o loop de volta.
        self._out_handle = pydivert.WinDivert(out_filter, layer=Layer.NETWORK_FORWARD,
                                              priority=self.priority)
        self._out_handle.open()
        self._log(f"SNAT ativo (forward, prio={self.priority}): só LAN {lan_lo}/24 -> internet")
        self._in_handle = pydivert.WinDivert(in_filter, layer=Layer.NETWORK)
        self._in_handle.open()
        self._log(f"DNAT ativo (network): portas {lo}-{hi}")

        self._threads = [
            threading.Thread(target=self._guard(self._out_loop), name="mitigus-snat", daemon=True),
            threading.Thread(target=self._guard(self._in_loop), name="mitigus-dnat", daemon=True),
            threading.Thread(target=self._guard(self._gc_loop), name="mitigus-gc", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()
        for h in (self._out_handle, self._in_handle):
            try:
                if h is not None:
                    h.close()
            except Exception:
                pass

    def _guard(self, fn):
        def wrapped():
            try:
                fn()
            except Exception as exc:
                if not self._stop.is_set():
                    self._log(f"loop caiu: {exc!r}")
        return wrapped

    # SAÍDA: aparelho -> internet, na camada FORWARD (pacote sendo encaminhado pelo PC).
    # Mascara a origem pro IP do PC e reinjeta no forward: o SO roteia pro gateway real,
    # e como agora a origem é o PC, o roteador devolve normalmente.
    def _out_loop(self):
        for packet in self._out_handle:
            if self._stop.is_set():
                break
            # Só mascara o que vai pra INTERNET. Tráfego interno da LAN volta intacto.
            if packet.dst_addr.startswith(self._lan_prefix):
                self._out_handle.send(packet)
                continue
            # QoS anti-bufferbloat: sob ping alto, derruba pacote GRANDE de fundo
            # (TCP recua e o buffer esvazia). O jogo não passa aqui, então é poupado.
            if self.qos is not None and self.qos.should_drop(len(packet.payload or b"")):
                continue
            proto = "tcp" if packet.tcp is not None else "udp"
            alloc = self.nat.snat(proto, packet.src_addr, packet.src_port,
                                  packet.dst_addr, packet.dst_port)
            if alloc is None:
                continue  # pool cheio: descarta este pacote
            if self.out_packets == 0:
                self._log(f"primeiro fluxo: {packet.src_addr}:{packet.src_port} "
                          f"-> {packet.dst_addr}:{packet.dst_port} (como {self.pc_ip}:{alloc})")
            self.out_packets += 1
            packet.src_addr = self.pc_ip
            packet.src_port = alloc
            self._out_handle.send(packet)  # send() recalcula os checksums

    # Expira fluxos ociosos (libera portas do pool). Sem isto a tabela só cresce.
    def _gc_loop(self):
        while not self._stop.wait(30.0):
            freed = self.nat.gc()
            if freed:
                self._log(f"gc: {freed} fluxo(s) expirado(s)")

    # VOLTA: internet -> PC:porta_alocada (network inbound). Desfaz e manda pro aparelho.
    def _in_loop(self):
        for packet in self._in_handle:
            if self._stop.is_set():
                break
            proto = "tcp" if packet.tcp is not None else "udp"
            dev = self.nat.dnat(proto, packet.dst_port, packet.src_addr, packet.src_port)
            if dev is None:
                self._in_handle.send(packet)  # não é nosso -> volta pro stack do PC
                continue
            self.in_matched += 1
            packet.dst_addr = dev[0]
            packet.dst_port = dev[1]
            packet.direction = Direction.OUTBOUND  # sai pro aparelho na LAN
            self._in_handle.send(packet)
